from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, HTTPException, Query

from src.api.projects import require_project
from src.db import get_pool
from src.errors import safe_error
from src.integrations import railway, registry, uptime

router = APIRouter()


async def uptime_summary(project_id: UUID, days: int = 7) -> dict:
    pool = await get_pool()
    row = await pool.fetchrow(
        """
        SELECT count(*) AS n, count(*) FILTER (WHERE ok) AS ok_n,
               avg(latency_ms) FILTER (WHERE ok) AS avg_latency,
               max(ts) AS last_ts
        FROM uptime_checks
        WHERE project_id = $1 AND ts > now() - make_interval(days => $2)
        """,
        project_id,
        days,
    )
    last = await pool.fetchrow(
        "SELECT * FROM uptime_checks WHERE project_id = $1 ORDER BY ts DESC LIMIT 1", project_id
    )
    recent = await pool.fetch(
        """
        SELECT ts, ok, status_code, latency_ms FROM uptime_checks
        WHERE project_id = $1 ORDER BY ts DESC LIMIT 96
        """,
        project_id,
    )
    return {
        "checks": row["n"],
        "uptime_pct": round(row["ok_n"] / row["n"] * 100, 2) if row["n"] else None,
        "avg_latency_ms": round(float(row["avg_latency"])) if row["avg_latency"] else None,
        "last": (
            {
                "ts": last["ts"].isoformat(),
                "ok": last["ok"],
                "status_code": last["status_code"],
                "latency_ms": last["latency_ms"],
                "error": last["error"],
            }
            if last
            else None
        ),
        "recent": [
            {
                "ts": r["ts"].isoformat(),
                "ok": r["ok"],
                "code": r["status_code"],
                "ms": r["latency_ms"],
            }
            for r in reversed(recent)
        ],
    }


@router.get("")
async def ops(project_id: UUID, days: int = Query(default=7, ge=1, le=30)) -> dict:
    await require_project(project_id)
    result: dict = {"uptime": await uptime_summary(project_id, days), "railway": None}
    integ = await registry.get_integration("railway", project_id)
    if integ:
        try:
            token = await registry.get_secret("railway", project_id)
            result["railway"] = await railway.fetch_project(integ["config"]["project_id"], token)
        except Exception as exc:  # noqa: BLE001
            result["railway"] = {"error": safe_error(exc, 300)}
    return result


@router.post("/uptime/run")
async def run_uptime() -> dict:
    return {"checked": await uptime.check_all()}


@router.get("/portfolio")
async def portfolio_ops() -> list[dict]:
    pool = await get_pool()
    projects = await pool.fetch("SELECT id, name, slug, url FROM projects ORDER BY name")
    out = []
    for p in projects:
        out.append(
            {
                "project_id": str(p["id"]),
                "name": p["name"],
                "slug": p["slug"],
                "url": p["url"],
                **await uptime_summary(p["id"]),
            }
        )
    return out


@router.get("/railway/{project_id}")
async def railway_status(project_id: UUID) -> dict:
    integ = await registry.get_integration("railway", project_id)
    if not integ:
        raise HTTPException(status_code=404, detail="No Railway integration for this project")
    token = await registry.get_secret("railway", project_id)
    try:
        return await railway.fetch_project(integ["config"]["project_id"], token)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=safe_error(exc, 300)) from exc
