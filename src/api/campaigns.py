from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, HTTPException, Query

from src.api.projects import require_project
from src.db import get_pool
from src.models import CampaignCreate, CampaignOut, CampaignUpdate

router = APIRouter()


@router.get("", response_model=list[CampaignOut])
async def list_campaigns(
    project_id: UUID | None = Query(default=None),
    status: str | None = Query(default=None),
) -> list[CampaignOut]:
    pool = await get_pool()
    rows = await pool.fetch(
        """
        SELECT * FROM campaigns
        WHERE ($1::uuid IS NULL OR project_id = $1)
          AND ($2::text IS NULL OR status = $2)
        ORDER BY created_at DESC
        """,
        project_id,
        status,
    )
    return [CampaignOut(**dict(r)) for r in rows]


@router.post("/projects/{project_id}", response_model=CampaignOut, status_code=201)
async def create_campaign(project_id: UUID, body: CampaignCreate) -> CampaignOut:
    await require_project(project_id)
    pool = await get_pool()
    row = await pool.fetchrow(
        """
        INSERT INTO campaigns (project_id, name, channel, status, budget, url, notes)
        VALUES ($1, $2, $3, $4, $5, $6, $7)
        RETURNING *
        """,
        project_id,
        body.name,
        body.channel,
        body.status,
        body.budget,
        body.url,
        body.notes,
    )
    return CampaignOut(**dict(row))


async def _require_campaign(campaign_id: UUID) -> dict:
    pool = await get_pool()
    row = await pool.fetchrow("SELECT * FROM campaigns WHERE id = $1", campaign_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Campaign not found")
    return dict(row)


@router.patch("/{campaign_id}", response_model=CampaignOut)
async def update_campaign(campaign_id: UUID, body: CampaignUpdate) -> CampaignOut:
    current = await _require_campaign(campaign_id)
    updates = body.model_dump(exclude_unset=True)
    merged = {**current, **updates}
    pool = await get_pool()
    row = await pool.fetchrow(
        """
        UPDATE campaigns
        SET name = $2, channel = $3, status = $4, budget = $5, url = $6, notes = $7,
            started_at = CASE
                WHEN $4 = 'active' AND started_at IS NULL AND $8::timestamptz IS NULL
                    THEN now()
                ELSE COALESCE($8, started_at)
            END,
            ended_at = CASE
                WHEN $4 = 'done' AND ended_at IS NULL AND $9::timestamptz IS NULL
                    THEN now()
                ELSE COALESCE($9, ended_at)
            END,
            updated_at = now()
        WHERE id = $1
        RETURNING *
        """,
        campaign_id,
        merged["name"],
        merged["channel"],
        merged["status"],
        merged["budget"],
        merged["url"],
        merged["notes"],
        updates.get("started_at"),
        updates.get("ended_at"),
    )
    return CampaignOut(**dict(row))


@router.delete("/{campaign_id}", status_code=204)
async def delete_campaign(campaign_id: UUID) -> None:
    await _require_campaign(campaign_id)
    pool = await get_pool()
    await pool.execute("DELETE FROM campaigns WHERE id = $1", campaign_id)
