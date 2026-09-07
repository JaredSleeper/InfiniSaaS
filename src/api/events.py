from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Body, Header, HTTPException, Query

from src.api.projects import require_project
from src.db import get_pool
from src.integrations import posthog
from src.models import EventsRequest

ingest_router = APIRouter()
router = APIRouter()

DEFAULT_FUNNEL = ["visit", "signup", "activate", "pay"]


async def _project_for_token(authorization: str) -> UUID:
    token = authorization.removeprefix("Bearer ").strip()
    if not token:
        raise HTTPException(status_code=401, detail="Missing bearer token")
    pool = await get_pool()
    project = await pool.fetchrow("SELECT id FROM projects WHERE ingest_token = $1", token)
    if project is None:
        raise HTTPException(status_code=401, detail="Invalid ingest token")
    return project["id"]


@ingest_router.post("/events", status_code=202)
async def ingest_events(body: EventsRequest, authorization: str = Header(default="")) -> dict:
    project_id = await _project_for_token(authorization)
    pool = await get_pool()
    async with pool.acquire() as conn, conn.transaction():
        await conn.executemany(
            """
            INSERT INTO events (project_id, name, user_key, ts, properties)
            VALUES ($1, $2, $3, COALESCE($4, now()), $5)
            """,
            [(project_id, e.name, e.user_key, e.ts, e.properties) for e in body.events],
        )
    return {"accepted": len(body.events)}


@ingest_router.post("/posthog", status_code=202)
async def ingest_posthog(body: Any = Body(...), authorization: str = Header(default="")) -> dict:
    """Target for a PostHog webhook destination (default body `{event, person}`).

    Same bearer token as /events. $pageview becomes `visit`, $pathname -> properties.path,
    distinct_id -> user_key; PostHog's uuid dedupes retries and backfills.
    """
    project_id = await _project_for_token(authorization)
    raws = posthog.unwrap_payload(body)
    if len(raws) > 1000:
        raise HTTPException(status_code=413, detail="Max 1000 events per request")
    accepted, skipped = await posthog.store_events(project_id, raws)
    return {"accepted": accepted, "skipped": skipped}


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
    sources = await pool.fetch(
        """
        SELECT source, count(*) AS n, max(ts) AS last_ts FROM events
        WHERE project_id = $1 AND ts > now() - make_interval(days => $2)
        GROUP BY source ORDER BY n DESC
        """,
        project_id,
        days,
    )
    ph = await pool.fetchrow(
        "SELECT config FROM integrations WHERE provider = 'posthog' AND project_id = $1",
        project_id,
    )
    posthog_url = None
    if ph and (ph["config"] or {}).get("project_id"):
        posthog_url = posthog.project_url(ph["config"].get("host"), ph["config"]["project_id"])
    return {
        "days": days,
        "sources": [
            {"source": r["source"], "count": r["n"], "last_ts": r["last_ts"].isoformat()}
            for r in sources
        ],
        "posthog_url": posthog_url,
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
