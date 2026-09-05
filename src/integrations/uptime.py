"""HTTP uptime probe for every live project with a URL."""

from __future__ import annotations

import time

import httpx
import structlog

from src.db import get_pool

log = structlog.get_logger()


async def check_all() -> int:
    pool = await get_pool()
    projects = await pool.fetch(
        "SELECT id, url FROM projects WHERE url IS NOT NULL AND url <> '' AND stage <> 'retired'"
    )
    results = []
    async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
        for p in projects:
            t0 = time.monotonic()
            try:
                r = await client.get(p["url"], headers={"User-Agent": "infinisaas-uptime/1.0"})
                ms = int((time.monotonic() - t0) * 1000)
                results.append((p["id"], r.status_code, ms, r.status_code < 400, ""))
            except Exception as exc:  # noqa: BLE001
                ms = int((time.monotonic() - t0) * 1000)
                results.append((p["id"], None, ms, False, str(exc)[:300]))
    if results:
        await pool.executemany(
            """
            INSERT INTO uptime_checks (project_id, status_code, latency_ms, ok, error)
            VALUES ($1, $2, $3, $4, $5)
            """,
            results,
        )
    await pool.execute("DELETE FROM uptime_checks WHERE ts < now() - interval '30 days'")
    return len(results)
