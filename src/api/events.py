from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Header, HTTPException, Query

from src.api.projects import require_project
from src.db import get_pool
from src.models import EventsRequest

ingest_router = APIRouter()
router = APIRouter()

DEFAULT_FUNNEL = ["visit", "signup", "activate", "pay"]


@ingest_router.post("/events", status_code=202)
async def ingest_events(body: EventsRequest, authorization: str = Header(default="")) -> dict:
    token = authorization.removeprefix("Bearer ").strip()
    if not token:
        raise HTTPException(status_code=401, detail="Missing bearer token")
    pool = await get_pool()
    project = await pool.fetchrow("SELECT id FROM projects WHERE ingest_token = $1", token)
    if project is None:
        raise HTTPException(status_code=401, detail="Invalid ingest token")
    async with pool.acquire() as conn, conn.transaction():
        await conn.executemany(
            """
            INSERT INTO events (project_id, name, user_key, ts, properties)
            VALUES ($1, $2, $3, COALESCE($4, now()), $5)
            """,
            [(project["id"], e.name, e.user_key, e.ts, e.properties) for e in body.events],
        )
    return {"accepted": len(body.events)}


async def analytics_summary(project_id: UUID, days: int) -> dict:
    project = await require_project(project_id)
    funnel_steps = (project.get("settings") or {}).get("funnel") or DEFAULT_FUNNEL
    pool = await get_pool()
    totals = await pool.fetch(
        """
        SELECT name, count(*) AS n, count(DISTINCT user_key) AS users
        FROM events
        WHERE project_id = $1 AND ts > now() - make_interval(days => $2)
        GROUP BY name ORDER BY n DESC
        """,
        project_id,
        days,
    )
    daily = await pool.fetch(
        """
        SELECT date_trunc('day', ts) AS day, name, count(*) AS n
        FROM events
        WHERE project_id = $1 AND ts > now() - make_interval(days => $2)
        GROUP BY 1, 2 ORDER BY 1
        """,
        project_id,
        days,
    )
    dau = await pool.fetch(
        """
        SELECT date_trunc('day', ts) AS day, count(DISTINCT user_key) AS users
        FROM events
        WHERE project_id = $1 AND user_key IS NOT NULL
          AND ts > now() - make_interval(days => $2)
        GROUP BY 1 ORDER BY 1
        """,
        project_id,
        days,
    )
    by_name = {r["name"]: {"count": r["n"], "users": r["users"]} for r in totals}
    funnel = []
    prev = None
    for step in funnel_steps:
        users = by_name.get(step, {}).get("users", 0)
        count = by_name.get(step, {}).get("count", 0)
        base = users or count
        rate = (base / prev * 100) if prev else None
        funnel.append({"step": step, "count": count, "users": users, "rate": rate})
        prev = base or prev
    series: dict[str, list] = {}
    for r in daily:
        series.setdefault(r["name"], []).append({"ts": r["day"].isoformat(), "value": r["n"]})
    return {
        "days": days,
        "funnel": funnel,
        "funnel_steps": funnel_steps,
        "events": [{"name": r["name"], "count": r["n"], "users": r["users"]} for r in totals],
        "series": series,
        "dau": [{"ts": r["day"].isoformat(), "value": r["users"]} for r in dau],
        "total_events": sum(r["n"] for r in totals),
    }


@router.get("")
async def analytics(project_id: UUID, days: int = Query(default=30, ge=1, le=365)) -> dict:
    return await analytics_summary(project_id, days)


@router.get("/recent")
async def recent_events(project_id: UUID, limit: int = Query(default=50, le=200)) -> list[dict]:
    await require_project(project_id)
    pool = await get_pool()
    rows = await pool.fetch(
        "SELECT * FROM events WHERE project_id = $1 ORDER BY ts DESC LIMIT $2", project_id, limit
    )
    return [
        {**dict(r), "project_id": str(r["project_id"]), "ts": r["ts"].isoformat()} for r in rows
    ]
