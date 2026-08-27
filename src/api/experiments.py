from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, HTTPException, Query

from src.api.projects import require_project
from src.db import get_pool
from src.models import ExperimentCreate, ExperimentOut, ExperimentUpdate

router = APIRouter()


@router.get("", response_model=list[ExperimentOut])
async def list_experiments(
    project_id: UUID | None = Query(default=None),
    status: str | None = Query(default=None),
) -> list[ExperimentOut]:
    pool = await get_pool()
    rows = await pool.fetch(
        """
        SELECT * FROM experiments
        WHERE ($1::uuid IS NULL OR project_id = $1)
          AND ($2::text IS NULL OR status = $2)
        ORDER BY created_at DESC
        """,
        project_id,
        status,
    )
    return [ExperimentOut(**dict(r)) for r in rows]


@router.post("/projects/{project_id}", response_model=ExperimentOut, status_code=201)
async def create_experiment(project_id: UUID, body: ExperimentCreate) -> ExperimentOut:
    await require_project(project_id)
    pool = await get_pool()
    row = await pool.fetchrow(
        """
        INSERT INTO experiments (project_id, name, hypothesis, channel, target_metric_id, status)
        VALUES ($1, $2, $3, $4, $5, $6)
        RETURNING *
        """,
        project_id,
        body.name,
        body.hypothesis,
        body.channel,
        body.target_metric_id,
        body.status,
    )
    return ExperimentOut(**dict(row))


async def _require_experiment(experiment_id: UUID) -> dict:
    pool = await get_pool()
    row = await pool.fetchrow("SELECT * FROM experiments WHERE id = $1", experiment_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Experiment not found")
    return dict(row)


@router.patch("/{experiment_id}", response_model=ExperimentOut)
async def update_experiment(experiment_id: UUID, body: ExperimentUpdate) -> ExperimentOut:
    current = await _require_experiment(experiment_id)
    updates = body.model_dump(exclude_unset=True)

    if updates.get("status") == "running" and current["started_at"] is None:
        updates.setdefault("started_at", None)
    merged = {**current, **updates}

    pool = await get_pool()
    row = await pool.fetchrow(
        """
        UPDATE experiments
        SET name = $2, hypothesis = $3, channel = $4, target_metric_id = $5,
            status = $6, result = $7, learnings = $8,
            started_at = CASE
                WHEN $6 = 'running' AND started_at IS NULL AND $9::timestamptz IS NULL
                    THEN now()
                ELSE COALESCE($9, started_at)
            END,
            ended_at = CASE
                WHEN $6 IN ('concluded', 'abandoned') AND ended_at IS NULL
                     AND $10::timestamptz IS NULL
                    THEN now()
                ELSE COALESCE($10, ended_at)
            END,
            updated_at = now()
        WHERE id = $1
        RETURNING *
        """,
        experiment_id,
        merged["name"],
        merged["hypothesis"],
        merged["channel"],
        merged["target_metric_id"],
        merged["status"],
        merged["result"],
        merged["learnings"],
        updates.get("started_at"),
        updates.get("ended_at"),
    )
    return ExperimentOut(**dict(row))


@router.delete("/{experiment_id}", status_code=204)
async def delete_experiment(experiment_id: UUID) -> None:
    await _require_experiment(experiment_id)
    pool = await get_pool()
    await pool.execute("DELETE FROM experiments WHERE id = $1", experiment_id)
