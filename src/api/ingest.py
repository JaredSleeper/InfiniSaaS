from __future__ import annotations

from fastapi import APIRouter, Header, HTTPException

from src.db import get_pool
from src.models import IngestRequest

router = APIRouter()


@router.post("/metrics", status_code=202)
async def ingest_metrics(
    body: IngestRequest,
    authorization: str = Header(default=""),
) -> dict:
    token = authorization.removeprefix("Bearer ").strip()
    if not token:
        raise HTTPException(status_code=401, detail="Missing bearer token")
    pool = await get_pool()
    project = await pool.fetchrow("SELECT id FROM projects WHERE ingest_token = $1", token)
    if project is None:
        raise HTTPException(status_code=401, detail="Invalid ingest token")

    metrics = await pool.fetch("SELECT id, key FROM metrics WHERE project_id = $1", project["id"])
    by_key = {r["key"]: r["id"] for r in metrics}
    unknown = sorted({p.metric for p in body.points} - by_key.keys())
    if unknown:
        raise HTTPException(status_code=400, detail=f"Unknown metrics: {', '.join(unknown)}")

    async with pool.acquire() as conn, conn.transaction():
        await conn.executemany(
            """
            INSERT INTO metric_points (metric_id, ts, value, source)
            VALUES ($1, COALESCE($2, now()), $3, 'ingest')
            """,
            [(by_key[p.metric], p.ts, p.value) for p in body.points],
        )
    return {"accepted": len(body.points)}
