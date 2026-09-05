from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from src.agents import seo_audit
from src.api.projects import require_project
from src.db import get_pool
from src.models import SeoAuditOut

router = APIRouter()


class AuditRequest(BaseModel):
    url: str | None = None


@router.get("/audits", response_model=list[SeoAuditOut])
async def list_audits(project_id: UUID, limit: int = Query(default=10, le=50)) -> list[SeoAuditOut]:
    await require_project(project_id)
    pool = await get_pool()
    rows = await pool.fetch(
        "SELECT * FROM seo_audits WHERE project_id = $1 ORDER BY ts DESC LIMIT $2",
        project_id,
        limit,
    )
    return [SeoAuditOut(**dict(r)) for r in rows]


@router.post("/audits/projects/{project_id}", response_model=SeoAuditOut, status_code=201)
async def run_audit(project_id: UUID, body: AuditRequest) -> SeoAuditOut:
    project = await require_project(project_id)
    url = body.url or project.get("url")
    if not url:
        raise HTTPException(status_code=400, detail="Project has no URL to audit")
    result = await seo_audit.audit(url)
    pool = await get_pool()
    row = await pool.fetchrow(
        """
        INSERT INTO seo_audits (project_id, url, score, findings, page)
        VALUES ($1, $2, $3, $4, $5) RETURNING *
        """,
        project_id,
        url,
        result["score"],
        result["findings"],
        result["page"],
    )
    return SeoAuditOut(**dict(row))
