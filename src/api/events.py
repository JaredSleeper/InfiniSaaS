from __future__ import annotations

import json
from collections import defaultdict
from typing import Any
from urllib.parse import urlparse
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


def _event_url_parts(raw: dict) -> tuple[str | None, str]:
    """Return (host, path) for a raw PostHog event, normalising www. hosts."""
    props = raw.get("properties") or {}
    if isinstance(props, str):
        try:
            props = json.loads(props)
        except ValueError:
            props = {}
    if not isinstance(props, dict):
        props = {}

    path = props.get("$pathname")
    current_url = props.get("$current_url")
    host: str | None = None

    if current_url:
        try:
            parsed = urlparse(str(current_url))
            host = (parsed.hostname or "").lower()
            path = parsed.path or "/"
        except ValueError:
            pass

    if host:
        host = host.removeprefix("www.")
    if not path:
        path = "/"
    return host, path


def _url_match_score(host: str | None, path: str, project_url: str) -> int:
    """Score how well an event matches a project's URL; 0 means no match."""
    if not project_url:
        return 0
    if "://" not in project_url:
        project_url = "https://" + project_url
    try:
        parsed = urlparse(project_url)
    except ValueError:
        return 0

    candidate_host = (parsed.hostname or "").lower().removeprefix("www.")
    if host and host != candidate_host:
        return 0

    candidate_path = (parsed.path or "/").rstrip("/")
    if path == candidate_path or path.startswith(candidate_path + "/"):
        return len(candidate_path)
    return 0


async def _posthog_routes(token_project_id: UUID) -> list[dict]:
    """Return cockpit projects sharing the same PostHog project as the token project."""
    pool = await get_pool()
    token_int = await pool.fetchrow(
        "SELECT config FROM integrations WHERE project_id = $1 AND provider = 'posthog'",
        token_project_id,
    )
    if token_int is None:
        return []
    ph_project_id = (token_int.get("config") or {}).get("project_id")
    if not ph_project_id:
        return []
    rows = await pool.fetch(
        """
        SELECT p.id, p.url, p.slug
        FROM integrations i
        JOIN projects p ON p.id = i.project_id
        WHERE i.provider = 'posthog'
          AND i.config->>'project_id' = $1
        ORDER BY p.url DESC NULLS LAST
        """,
        str(ph_project_id),
    )
    return [dict(r) for r in rows]


def _resolve_target(raw: dict, token_project_id: UUID, routes: list[dict]) -> UUID:
    """Route a PostHog event to the cockpit project whose URL it belongs to."""
    if not routes:
        return token_project_id
    host, path = _event_url_parts(raw)
    best_score = 0
    best_id = token_project_id
    for route in routes:
        score = _url_match_score(host, path, route.get("url") or "")
        if score > best_score:
            best_score = score
            best_id = route["id"]
    return best_id


@ingest_router.post("/posthog", status_code=202)
async def ingest_posthog(body: Any = Body(...), authorization: str = Header(default="")) -> dict:
    """Target for a PostHog webhook destination (default body `{event, person}`).

    Same bearer token as /events. $pageview becomes `visit`, $pathname -> properties.path,
    distinct_id -> user_key; PostHog's uuid dedupes retries and backfills.

    When several cockpit projects share one PostHog project (BetterAt apps under
    getbetterat.xyz), events are routed to the project whose URL matches the event's
    path/host.
    """
    project_id = await _project_for_token(authorization)
    raws = posthog.unwrap_payload(body)
    if len(raws) > 1000:
        raise HTTPException(status_code=413, detail="Max 1000 events per request")

    routes = await _posthog_routes(project_id)
    if not routes:
        accepted, skipped = await posthog.store_events(project_id, raws)
        return {"accepted": accepted, "skipped": skipped}

    groups: dict[UUID, list[dict]] = defaultdict(list)
    for raw in raws:
        target = _resolve_target(raw, project_id, routes)
        groups[target].append(raw)

    accepted = skipped = 0
    for pid, batch in groups.items():
        a, s = await posthog.store_events(pid, batch)
        accepted += a
        skipped += s
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
