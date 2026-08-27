from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, HTTPException, Query

from src.db import get_pool
from src.models import LearningCreate, LearningOut

router = APIRouter()


@router.get("", response_model=list[LearningOut])
async def list_learnings(
    project_id: UUID | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
) -> list[LearningOut]:
    pool = await get_pool()
    rows = await pool.fetch(
        """
        SELECT * FROM learnings
        WHERE ($1::uuid IS NULL OR project_id = $1)
        ORDER BY created_at DESC
        LIMIT $2
        """,
        project_id,
        limit,
    )
    return [LearningOut(**dict(r)) for r in rows]


@router.post("", response_model=LearningOut, status_code=201)
async def create_learning(body: LearningCreate) -> LearningOut:
    pool = await get_pool()
    row = await pool.fetchrow(
        """
        INSERT INTO learnings (project_id, experiment_id, content)
        VALUES ($1, $2, $3)
        RETURNING *
        """,
        body.project_id,
        body.experiment_id,
        body.content,
    )
    return LearningOut(**dict(row))


@router.delete("/{learning_id}", status_code=204)
async def delete_learning(learning_id: UUID) -> None:
    pool = await get_pool()
    result = await pool.execute("DELETE FROM learnings WHERE id = $1", learning_id)
    if result == "DELETE 0":
        raise HTTPException(status_code=404, detail="Learning not found")
