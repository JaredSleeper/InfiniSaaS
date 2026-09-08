"""Competitors: per-project registry with cached site inventories (see agents/research.py)."""

from __future__ import annotations

from uuid import UUID

import asyncpg
from fastapi import APIRouter, HTTPException, Query

from src.agents import landing_agent, research
from src.api.crud import fetch_one, update_row
from src.api.projects import require_project
from src.db import get_pool
from src.models import CompetitorCreate, CompetitorOut, CompetitorUpdate

router = APIRouter()


def _out(row: dict) -> CompetitorOut:
    if not isinstance(row.get("pages"), list):
        row["pages"] = []
    if not isinstance(row.get("page_types"), dict):
        counts: dict[str, int] = {}
        for p in row["pages"]:
            t = p.get("type") or "other"
            counts[t] = counts.get(t, 0) + 1
        row["page_types"] = counts
    return CompetitorOut(**row)


@router.get("", response_model=list[CompetitorOut])
async def list_competitors(
    project_id: UUID | None = Query(default=None),
    status: str | None = Query(default=None),
    include_pages: bool = Query(default=False),
) -> list[CompetitorOut]:
    pool = await get_pool()
    rows = await pool.fetch(
        """SELECT id, project_id, name, domain, url, positioning, pricing, strengths, weaknesses,
                  notes, source, status, page_count, crawled_at, crawl_error, created_at,
                  updated_at, CASE WHEN $3 THEN pages ELSE '[]'::jsonb END AS pages,
                  COALESCE((SELECT jsonb_object_agg(t, n) FROM (
                      SELECT COALESCE(p->>'type', 'other') AS t, count(*) AS n
                      FROM jsonb_array_elements(pages) p GROUP BY 1) s), '{}'::jsonb) AS page_types
           FROM competitors
           WHERE ($1::uuid IS NULL OR project_id = $1) AND ($2::text IS NULL OR status = $2)
           ORDER BY status, page_count DESC, name LIMIT 500""",
        project_id,
        status,
        include_pages,
    )
    return [_out(dict(r)) for r in rows]


@router.post("/projects/{project_id}", response_model=CompetitorOut, status_code=201)
async def create_competitor(
    project_id: UUID, body: CompetitorCreate, crawl: bool = Query(default=True)
) -> CompetitorOut:
    await require_project(project_id)
    pool = await get_pool()
    domain = research.domain_of(body.url)
    if not domain:
        raise HTTPException(status_code=422, detail="Invalid URL")
    try:
        row = await pool.fetchrow(
            """INSERT INTO competitors (project_id, name, domain, url, positioning, pricing,
                                        strengths, weaknesses, notes)
               VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9) RETURNING *""",
            project_id,
            body.name,
            domain,
            body.url,
            body.positioning,
            body.pricing,
            body.strengths,
            body.weaknesses,
            body.notes,
        )
    except asyncpg.UniqueViolationError as exc:
        raise HTTPException(status_code=409, detail=f"{domain} is already tracked") from exc
    out = dict(row)
    if crawl:
        out = await landing_agent.crawl_competitor(row["id"], body.url)
    return _out(out)


@router.post("/projects/{project_id}/discover")
async def discover(project_id: UUID, max_n: int = Query(default=8, ge=1, le=20)) -> dict:
    """Web-search discovery of new competitors, then crawl them. Synchronous (≈1-2 min)."""
    await require_project(project_id)
    pool = await get_pool()
    known = [
        r["domain"]
        for r in await pool.fetch(
            "SELECT domain FROM competitors WHERE project_id = $1", project_id
        )
    ]
    found = await landing_agent.discover_for(project_id, known, max_n)
    await landing_agent.crawl_many(found["competitors"])
    rows = await pool.fetch(
        "SELECT * FROM competitors WHERE id = ANY($1::uuid[])",
        [c["id"] for c in found["competitors"]],
    )
    return {
        "competitors": [_out(dict(r)) for r in rows],
        "market_notes": found["market_notes"],
        "mock": found["mock"],
    }


@router.get("/{row_id}", response_model=CompetitorOut)
async def get_competitor(row_id: UUID) -> CompetitorOut:
    return _out(await fetch_one("competitors", row_id))


@router.patch("/{row_id}", response_model=CompetitorOut)
async def patch_competitor(row_id: UUID, body: CompetitorUpdate) -> CompetitorOut:
    values = body.model_dump(exclude_unset=True)
    return _out(await update_row("competitors", row_id, values, touch=True))


@router.post("/{row_id}/crawl", response_model=CompetitorOut)
async def recrawl(row_id: UUID) -> CompetitorOut:
    row = await fetch_one("competitors", row_id)
    return _out(await landing_agent.crawl_competitor(row_id, row["url"]))


@router.delete("/{row_id}", status_code=204)
async def delete_competitor(row_id: UUID) -> None:
    pool = await get_pool()
    res = await pool.execute("DELETE FROM competitors WHERE id = $1", row_id)
    if res.endswith("0"):
        raise HTTPException(status_code=404, detail="Not found")
