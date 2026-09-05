from __future__ import annotations

from datetime import datetime
from uuid import UUID

import asyncpg


async def ensure_metric(
    pool: asyncpg.Pool,
    project_id: UUID,
    key: str,
    name: str,
    unit: str,
    kind: str,
    is_key: bool,
) -> UUID:
    row = await pool.fetchrow(
        """
        INSERT INTO metrics (project_id, key, name, unit, kind, is_key)
        VALUES ($1, $2, $3, $4, $5, $6)
        ON CONFLICT (project_id, key) DO UPDATE SET key = EXCLUDED.key
        RETURNING id
        """,
        project_id,
        key,
        name,
        unit,
        kind,
        is_key,
    )
    return row["id"]


async def replace_points(
    pool: asyncpg.Pool,
    metric_id: UUID,
    source: str,
    points: list[tuple[datetime, float]],
    since_days: int,
) -> None:
    """Replace all points from `source` in the last `since_days` days with `points`.

    since_days=0 keeps history and appends a fresh reading (used for gauges like MRR)
    but drops any earlier reading from today so repeated syncs don't stack up.
    """
    async with pool.acquire() as conn, conn.transaction():
        if since_days > 0:
            await conn.execute(
                """
                DELETE FROM metric_points
                WHERE metric_id = $1 AND source = $2
                  AND ts > now() - make_interval(days => $3)
                """,
                metric_id,
                source,
                since_days,
            )
        else:
            await conn.execute(
                """
                DELETE FROM metric_points
                WHERE metric_id = $1 AND source = $2 AND ts::date = current_date
                """,
                metric_id,
                source,
            )
        if points:
            await conn.executemany(
                "INSERT INTO metric_points (metric_id, ts, value, source) VALUES ($1, $2, $3, $4)",
                [(metric_id, ts, value, source) for ts, value in points],
            )


async def series(
    pool: asyncpg.Pool, project_id: UUID, key: str, days: int
) -> list[tuple[datetime, float]]:
    rows = await pool.fetch(
        """
        SELECT mp.ts, mp.value FROM metric_points mp
        JOIN metrics m ON m.id = mp.metric_id
        WHERE m.project_id = $1 AND m.key = $2 AND mp.ts > now() - make_interval(days => $3)
        ORDER BY mp.ts
        """,
        project_id,
        key,
        days,
    )
    return [(r["ts"], float(r["value"])) for r in rows]


def window_sum(points: list[tuple[datetime, float]], start: datetime, end: datetime) -> float:
    return sum(v for ts, v in points if start <= ts < end)


def last_value(points: list[tuple[datetime, float]]) -> float | None:
    return points[-1][1] if points else None
