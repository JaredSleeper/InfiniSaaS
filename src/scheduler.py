"""In-process background loop: uptime probes, integration syncs, alerts, due agents, Devin polls."""

from __future__ import annotations

import asyncio
import contextlib
from datetime import UTC, datetime

import asyncpg
import structlog

from src.agents import runner
from src.api import devin, integrations, targets
from src.config import settings
from src.db import get_pool
from src.integrations import uptime

log = structlog.get_logger()
_task: asyncio.Task | None = None
_last_hourly: datetime | None = None

# Session-level advisory lock so exactly one uvicorn worker (or Railway replica) runs the loop.
LEADER_LOCK_ID = 815503


async def tick() -> dict:
    global _last_hourly
    results: dict = {}
    now = datetime.now(UTC)
    for name, coro in (
        ("uptime", uptime.check_all()),
        ("devin", devin.refresh_active()),
        ("alerts", targets.evaluate_alerts()),
        ("agents", runner.run_due(now)),
    ):
        try:
            results[name] = await coro
        except Exception as exc:  # noqa: BLE001
            log.warning("scheduler_step_failed", step=name, error=str(exc))
    if _last_hourly is None or (now - _last_hourly).total_seconds() > 3600:
        _last_hourly = now
        try:
            results["integrations"] = await integrations.sync_all()
        except Exception as exc:  # noqa: BLE001
            log.warning("scheduler_step_failed", step="integrations", error=str(exc))
    return results


async def _acquire_leadership() -> asyncpg.Connection:
    pool = await get_pool()
    while True:
        conn = await pool.acquire()
        if await conn.fetchval("SELECT pg_try_advisory_lock($1)", LEADER_LOCK_ID):
            return conn
        await pool.release(conn)
        await asyncio.sleep(settings.scheduler_interval_seconds)


async def _loop() -> None:
    await asyncio.sleep(10)
    leader = await _acquire_leadership()
    log.info("scheduler_leader_acquired")
    try:
        while True:
            res = await tick()
            log.info("scheduler_tick", **{k: str(v)[:80] for k, v in res.items()})
            await asyncio.sleep(settings.scheduler_interval_seconds)
    finally:
        with contextlib.suppress(Exception):
            await leader.execute("SELECT pg_advisory_unlock($1)", LEADER_LOCK_ID)
            await (await get_pool()).release(leader)


def start() -> None:
    global _task
    if settings.scheduler_enabled and _task is None:
        _task = asyncio.get_running_loop().create_task(_loop())


async def stop() -> None:
    global _task
    if _task:
        _task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await _task
        _task = None
