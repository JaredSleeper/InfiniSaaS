from __future__ import annotations

import json
from pathlib import Path

import asyncpg

from src.config import settings

_pool: asyncpg.Pool | None = None


async def _init_connection(conn: asyncpg.Connection) -> None:
    for typename in ("json", "jsonb"):
        await conn.set_type_codec(
            typename,
            encoder=json.dumps,
            decoder=json.loads,
            schema="pg_catalog",
        )


async def init_db() -> asyncpg.Pool:
    global _pool
    _pool = await asyncpg.create_pool(
        settings.database_url,
        min_size=2,
        max_size=10,
        command_timeout=60,
        init=_init_connection,
    )
    schema = Path(__file__).resolve().parent.parent / "init.sql"
    if schema.exists():
        async with _pool.acquire() as conn:
            await conn.execute("SELECT pg_advisory_lock(815502)")
            try:
                await conn.execute(schema.read_text())
            finally:
                await conn.execute("SELECT pg_advisory_unlock(815502)")
    return _pool


async def close_db() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None


async def get_pool() -> asyncpg.Pool:
    if _pool is None:
        raise RuntimeError("DB pool is not initialized")
    return _pool
