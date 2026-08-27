from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, HTTPException, Query

from src.api.projects import require_project
from src.db import get_pool
from src.models import MetricCreate, MetricOut, MetricPointIn

router = APIRouter()


@router.get("", response_model=list[MetricOut])
async def list_metrics(project_id: UUID) -> list[MetricOut]:
    await require_project(project_id)
    pool = await get_pool()
    rows = await pool.fetch(
        "SELECT * FROM metrics WHERE project_id = $1 ORDER BY created_at", project_id
    )
    return [MetricOut(**dict(r)) for r in rows]


@router.post("", response_model=MetricOut, status_code=201)
async def create_metric(project_id: UUID, body: MetricCreate) -> MetricOut:
    await require_project(project_id)
    pool = await get_pool()
    try:
        row = await pool.fetchrow(
            """
            INSERT INTO metrics (project_id, key, name, unit, kind, is_key)
            VALUES ($1, $2, $3, $4, $5, $6)
            RETURNING *
            """,
            project_id,
            body.key,
            body.name,
            body.unit,
            body.kind,
            body.is_key,
        )
    except Exception as exc:
        if "unique" in str(exc).lower():
            raise HTTPException(status_code=409, detail="Metric key already exists") from exc
        raise
    return MetricOut(**dict(row))


@router.delete("/{metric_id}", status_code=204)
async def delete_metric(project_id: UUID, metric_id: UUID) -> None:
    pool = await get_pool()
    result = await pool.execute(
        "DELETE FROM metrics WHERE id = $1 AND project_id = $2", metric_id, project_id
    )
    if result == "DELETE 0":
        raise HTTPException(status_code=404, detail="Metric not found")


@router.get("/{metric_id}/points")
async def list_points(
    project_id: UUID,
    metric_id: UUID,
    days: int = Query(default=90, ge=1, le=730),
) -> list[dict]:
    pool = await get_pool()
    metric = await pool.fetchrow(
        "SELECT id FROM metrics WHERE id = $1 AND project_id = $2", metric_id, project_id
    )
    if metric is None:
        raise HTTPException(status_code=404, detail="Metric not found")
    rows = await pool.fetch(
        """
        SELECT ts, value, source FROM metric_points
        WHERE metric_id = $1 AND ts > now() - make_interval(days => $2)
        ORDER BY ts
        """,
        metric_id,
        days,
    )
    return [
        {"ts": r["ts"].isoformat(), "value": float(r["value"]), "source": r["source"]}
        for r in rows
    ]


@router.post("/{metric_id}/points", status_code=201)
async def add_point(project_id: UUID, metric_id: UUID, body: MetricPointIn) -> dict:
    pool = await get_pool()
    metric = await pool.fetchrow(
        "SELECT id FROM metrics WHERE id = $1 AND project_id = $2", metric_id, project_id
    )
    if metric is None:
        raise HTTPException(status_code=404, detail="Metric not found")
    row = await pool.fetchrow(
        """
        INSERT INTO metric_points (metric_id, ts, value, source)
        VALUES ($1, COALESCE($2, now()), $3, $4)
        RETURNING ts, value, source
        """,
        metric_id,
        body.ts,
        body.value,
        body.source,
    )
    return {"ts": row["ts"].isoformat(), "value": float(row["value"]), "source": row["source"]}
