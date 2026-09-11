"""PostHog → first-party events.

Two paths feed the same `events` table (deduped on PostHog's event uuid):
  * live: a PostHog webhook destination posts each event to /api/v1/posthog
  * backfill: `sync` pulls recent history through the query API (keyset-paginated
    on timestamp; PostHog discourages scheduled exports via /query, so this is
    only run on demand from the Integrations page)
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlparse
from uuid import UUID

import httpx

from src.db import get_pool

# PostHog's auto-generated events. $pageview becomes our `visit`; the rest are noise
# for a funnel/landing view and are dropped.
EVENT_ALIASES = {"$pageview": "visit"}
IGNORED_EVENTS = {
    "$pageleave",
    "$autocapture",
    "$identify",
    "$set",
    "$create_alias",
    "$merge_dangerously",
    "$groupidentify",
    "$feature_flag_called",
    "$feature_enrollment_update",
    "$web_vitals",
    "$rageclick",
    "$dead_click",
    "$exception",
    "$opt_in",
    "$snapshot",
    "$$heatmap",
    "$$client_ingestion_warning",
    "$screen",
    "$survey_shown",
    "$survey_dismissed",
    "$survey_sent",
}
# Context properties worth keeping (renamed to first-party names).
CONTEXT_PROPS = {
    "$current_url": "url",
    "$referrer": "referrer",
    "$referring_domain": "referring_domain",
    "$browser": "browser",
    "$os": "os",
    "$device_type": "device_type",
    "$geoip_country_code": "country",
}
PAGE_SIZE = 5000
MAX_BACKFILL_ROWS = 50_000


def _parse_ts(value: Any) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    text = str(value).replace("Z", "+00:00")
    if " " in text and "T" not in text:
        text = text.replace(" ", "T", 1)
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def normalize_event(raw: dict) -> tuple[str, str | None, datetime | None, dict, str | None] | None:
    """Map a PostHog event (webhook `{event}` object or query row) onto our schema.

    Returns (name, user_key, ts, properties, external_id) or None if the event is noise.
    """
    name = raw.get("event")
    if not name or not isinstance(name, str):
        return None
    if name in IGNORED_EVENTS:
        return None
    name = EVENT_ALIASES.get(name, name)
    if name.startswith("$"):
        return None

    props_in = raw.get("properties") or {}
    if isinstance(props_in, str):
        try:
            props_in = json.loads(props_in)
        except ValueError:
            props_in = {}
    if not isinstance(props_in, dict):
        props_in = {}

    props: dict = {}
    path = props_in.get("$pathname")
    if not path and props_in.get("$current_url"):
        path = urlparse(str(props_in["$current_url"])).path or "/"
    if path:
        props["path"] = path
    for src, dst in CONTEXT_PROPS.items():
        if props_in.get(src) not in (None, ""):
            props[dst] = props_in[src]
    for k, v in props_in.items():
        if k.startswith(("$", "token", "distinct_id")) or v is None:
            continue
        props[k] = v

    user_key = raw.get("distinct_id")
    external_id = raw.get("uuid")
    return (
        name,
        str(user_key) if user_key else None,
        _parse_ts(raw.get("timestamp")),
        props,
        str(external_id) if external_id else None,
    )


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


async def shared_routes(project_id: UUID) -> list[dict]:
    """Cockpit projects sharing the same PostHog project as the given project."""
    pool = await get_pool()
    token_int = await pool.fetchrow(
        "SELECT config FROM integrations WHERE project_id = $1 AND provider = 'posthog'",
        project_id,
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


def resolve_target(raw: dict, token_project_id: UUID, routes: list[dict]) -> UUID:
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


async def store_events_routed(project_id: UUID, raws: list[dict]) -> tuple[int, int]:
    """Store events under the cockpit project each event's URL belongs to."""
    routes = await shared_routes(project_id)
    if not routes:
        return await store_events(project_id, raws)
    groups: dict[UUID, list[dict]] = {}
    for raw in raws:
        groups.setdefault(resolve_target(raw, project_id, routes), []).append(raw)
    accepted = skipped = 0
    for pid, batch in groups.items():
        a, s = await store_events(pid, batch)
        accepted += a
        skipped += s
    return accepted, skipped


def unwrap_payload(body: Any) -> list[dict]:
    """Accept the webhook default body ({event, person}), a bare event, or a list of either."""
    if isinstance(body, list):
        items = body
    elif isinstance(body, dict) and isinstance(body.get("batch"), list):
        items = body["batch"]
    else:
        items = [body]
    out = []
    for item in items:
        if not isinstance(item, dict):
            continue
        ev = item.get("event")
        if isinstance(ev, dict):
            out.append(ev)
        elif isinstance(ev, str):
            out.append(item)
    return out


async def store_events(project_id: UUID, raws: list[dict]) -> tuple[int, int]:
    """Insert normalized events; returns (accepted, skipped) where skipped covers noise + dupes."""
    rows = []
    for raw in raws:
        norm = normalize_event(raw)
        if norm:
            rows.append(norm)
    if not rows:
        return 0, len(raws)
    pool = await get_pool()
    async with pool.acquire() as conn, conn.transaction():
        inserted = await conn.fetch(
            """
            INSERT INTO events (project_id, name, user_key, ts, properties, source, external_id)
            SELECT $1, r.name, r.user_key, COALESCE(r.ts, now()), r.properties, 'posthog',
                   r.external_id
            FROM unnest($2::text[], $3::text[], $4::timestamptz[], $5::jsonb[], $6::text[])
                AS r(name, user_key, ts, properties, external_id)
            ON CONFLICT (project_id, external_id) WHERE external_id IS NOT NULL DO NOTHING
            RETURNING id
            """,
            project_id,
            [r[0] for r in rows],
            [r[1] for r in rows],
            [r[2] for r in rows],
            [r[3] for r in rows],
            [r[4] for r in rows],
        )
    accepted = len(inserted)
    return accepted, len(raws) - accepted


def app_host(host: str) -> str:
    host = (host or "https://us.posthog.com").strip().rstrip("/")
    if not host.startswith("http"):
        host = "https://" + host
    return host


def project_url(host: str, ph_project_id: str) -> str:
    return f"{app_host(host)}/project/{ph_project_id}"


def _pid(ph_project_id: str) -> str:
    pid = str(ph_project_id).strip()
    if not pid.isdigit():
        raise RuntimeError("PostHog project id must be numeric (Settings → Project → Project ID)")
    return pid


async def _query(host: str, ph_project_id: str, key: str, hogql: str, name: str) -> list[list]:
    url = f"{app_host(host)}/api/projects/{_pid(ph_project_id)}/query/"
    async with httpx.AsyncClient(timeout=60) as client:
        r = await client.post(
            url,
            headers={"Authorization": f"Bearer {key}"},
            json={"query": {"kind": "HogQLQuery", "query": hogql}, "name": name},
        )
        if r.status_code == 401:
            raise RuntimeError("PostHog rejected the personal API key")
        if r.status_code == 403:
            raise RuntimeError("Personal API key lacks Query Read on this project")
        if r.status_code == 404:
            raise RuntimeError(f"PostHog project {ph_project_id} not found on {app_host(host)}")
        r.raise_for_status()
        return r.json().get("results") or []


async def verify(host: str, ph_project_id: str, key: str) -> str:
    url = f"{app_host(host)}/api/projects/{_pid(ph_project_id)}/"
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.get(url, headers={"Authorization": f"Bearer {key}"})
        if r.status_code in (401, 403):
            raise RuntimeError("PostHog rejected the personal API key for this project")
        if r.status_code == 404:
            raise RuntimeError(f"PostHog project {ph_project_id} not found on {app_host(host)}")
        r.raise_for_status()
        data = r.json()
    rows = await _query(
        host,
        ph_project_id,
        key,
        "SELECT count() FROM events WHERE timestamp >= now() - INTERVAL 7 DAY",
        "infinisaas verify",
    )
    n = rows[0][0] if rows and rows[0] else 0
    return f"Connected to “{data.get('name', ph_project_id)}” · {n} events in the last 7 days"


async def sync(project_id: UUID, host: str, ph_project_id: str, key: str, days: int = 30) -> dict:
    """One-off backfill: pull the last `days` of non-noise events, newest cursor wins."""
    ignored = ", ".join(f"'{e}'" for e in sorted(IGNORED_EVENTS))
    cursor: int | None = None  # unix ms of the last row seen (keyset pagination)
    fetched = accepted = 0
    while fetched < MAX_BACKFILL_ROWS:
        since = (
            f"timestamp > fromUnixTimestamp64Milli({cursor})"
            if cursor
            else f"timestamp >= now() - INTERVAL {int(days)} DAY"
        )
        hogql = (
            "SELECT toString(uuid), event, distinct_id, toString(timestamp), properties, "
            "toUnixTimestamp64Milli(timestamp) "
            f"FROM events WHERE {since} AND event NOT IN ({ignored}) "
            f"ORDER BY timestamp ASC LIMIT {PAGE_SIZE}"
        )
        rows = await _query(host, ph_project_id, key, hogql, "infinisaas backfill")
        if not rows:
            break
        raws = [
            {
                "uuid": r[0],
                "event": r[1],
                "distinct_id": r[2],
                "timestamp": r[3],
                "properties": r[4],
            }
            for r in rows
        ]
        ok, _ = await store_events_routed(project_id, raws)
        accepted += ok
        fetched += len(rows)
        last_ms = int(rows[-1][5])
        if len(rows) < PAGE_SIZE or last_ms == cursor:
            break
        cursor = last_ms
    return {"fetched": fetched, "imported": accepted, "days": days}
