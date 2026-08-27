from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, HTTPException

from src.db import get_pool
from src.models import ProjectCreate, ProjectOut, ProjectUpdate

router = APIRouter()


async def require_project(project_id: UUID) -> dict:
    pool = await get_pool()
    row = await pool.fetchrow("SELECT * FROM projects WHERE id = $1", project_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return dict(row)


@router.get("", response_model=list[ProjectOut])
async def list_projects() -> list[ProjectOut]:
    pool = await get_pool()
    rows = await pool.fetch("SELECT * FROM projects ORDER BY created_at")
    return [ProjectOut(**dict(r)) for r in rows]


@router.post("", response_model=ProjectOut, status_code=201)
async def create_project(body: ProjectCreate) -> ProjectOut:
    pool = await get_pool()
    try:
        row = await pool.fetchrow(
            """
            INSERT INTO projects (slug, name, url, stage, description, accent_color)
            VALUES ($1, $2, $3, $4, $5, $6)
            RETURNING *
            """,
            body.slug,
            body.name,
            body.url,
            body.stage,
            body.description,
            body.accent_color,
        )
    except Exception as exc:
        if "unique" in str(exc).lower():
            raise HTTPException(status_code=409, detail="Slug already exists") from exc
        raise
    return ProjectOut(**dict(row))


@router.get("/{project_id}", response_model=ProjectOut)
async def get_project(project_id: UUID) -> ProjectOut:
    return ProjectOut(**await require_project(project_id))


@router.patch("/{project_id}", response_model=ProjectOut)
async def update_project(project_id: UUID, body: ProjectUpdate) -> ProjectOut:
    current = await require_project(project_id)
    updates = body.model_dump(exclude_unset=True)
    merged = {**current, **updates}
    pool = await get_pool()
    row = await pool.fetchrow(
        """
        UPDATE projects
        SET name = $2, url = $3, stage = $4, health = $5,
            description = $6, accent_color = $7, updated_at = now()
        WHERE id = $1
        RETURNING *
        """,
        project_id,
        merged["name"],
        merged["url"],
        merged["stage"],
        merged["health"],
        merged["description"],
        merged["accent_color"],
    )
    return ProjectOut(**dict(row))


@router.delete("/{project_id}", status_code=204)
async def delete_project(project_id: UUID) -> None:
    await require_project(project_id)
    pool = await get_pool()
    await pool.execute("DELETE FROM projects WHERE id = $1", project_id)


@router.get("/{project_id}/ingest-token")
async def get_ingest_token(project_id: UUID) -> dict:
    project = await require_project(project_id)
    return {"ingest_token": project["ingest_token"]}
