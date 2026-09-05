from __future__ import annotations

import re
from typing import get_args
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query

from src.agents import llm, runner
from src.api.crud import fetch_one, insert_row, update_row
from src.api.projects import require_project
from src.db import get_pool
from src.models import (
    AgentCreate,
    AgentOut,
    AgentRunOut,
    AgentUpdate,
    Channel,
    LandingPageCreate,
    RecommendationOut,
    RecommendationUpdate,
)

router = APIRouter()
recs_router = APIRouter()
CHANNELS = frozenset(get_args(Channel))

DEFAULT_AGENTS = [
    ("weekly_brief", "Weekly brief", "weekly"),
    ("seo", "SEO agent", "weekly"),
    ("analytics", "Product analytics agent", "weekly"),
    ("ads", "Paid ads agent", "manual"),
    ("landing_pages", "Landing page agent", "weekly"),
]


@router.get("/status")
async def status() -> dict:
    return {"llm_configured": llm.configured()}


@router.get("", response_model=list[AgentOut])
async def list_agents(project_id: UUID | None = Query(default=None)) -> list[AgentOut]:
    pool = await get_pool()
    rows = await pool.fetch(
        """
        SELECT * FROM agents WHERE ($1::uuid IS NULL OR project_id = $1 OR project_id IS NULL)
        ORDER BY project_id NULLS FIRST, kind, name
        """,
        project_id,
    )
    return [AgentOut(**dict(r)) for r in rows]


@router.post("", response_model=AgentOut, status_code=201)
async def create_agent(body: AgentCreate) -> AgentOut:
    if body.project_id:
        await require_project(body.project_id)
    elif body.kind != "weekly_brief" and body.kind != "custom":
        raise HTTPException(status_code=400, detail=f"{body.kind} agents must belong to a project")
    pool = await get_pool()
    row = await pool.fetchrow(
        """
        INSERT INTO agents (project_id, kind, name, instructions, schedule, enabled, config)
        VALUES ($1, $2, $3, $4, $5, $6, $7) RETURNING *
        """,
        body.project_id,
        body.kind,
        body.name,
        body.instructions,
        body.schedule,
        body.enabled,
        body.config,
    )
    return AgentOut(**dict(row))


@router.post("/bootstrap/{project_id}", response_model=list[AgentOut], status_code=201)
async def bootstrap(project_id: UUID) -> list[AgentOut]:
    """Create the standard agent set for a project (idempotent by kind)."""
    await require_project(project_id)
    pool = await get_pool()
    out = []
    for kind, name, schedule in DEFAULT_AGENTS:
        existing = await pool.fetchrow(
            "SELECT * FROM agents WHERE project_id = $1 AND kind = $2", project_id, kind
        )
        if existing:
            out.append(AgentOut(**dict(existing)))
            continue
        row = await pool.fetchrow(
            """
            INSERT INTO agents (project_id, kind, name, schedule)
            VALUES ($1, $2, $3, $4) RETURNING *
            """,
            project_id,
            kind,
            name,
            schedule,
        )
        out.append(AgentOut(**dict(row)))
    return out


@router.patch("/{agent_id}", response_model=AgentOut)
async def update_agent(agent_id: UUID, body: AgentUpdate) -> AgentOut:
    return AgentOut(
        **await update_row("agents", agent_id, body.model_dump(exclude_unset=True), True)
    )


@router.delete("/{agent_id}", status_code=204)
async def delete_agent(agent_id: UUID) -> None:
    await fetch_one("agents", agent_id)
    pool = await get_pool()
    await pool.execute("DELETE FROM agents WHERE id = $1", agent_id)


@router.post("/{agent_id}/run", response_model=AgentRunOut, status_code=201)
async def run_now(agent_id: UUID) -> AgentRunOut:
    await fetch_one("agents", agent_id)
    run_id = await runner.run_agent(agent_id, trigger="manual")
    return AgentRunOut(**await fetch_one("agent_runs", run_id))


@router.get("/{agent_id}/runs", response_model=list[AgentRunOut])
async def list_runs(agent_id: UUID, limit: int = Query(default=20, le=100)) -> list[AgentRunOut]:
    pool = await get_pool()
    rows = await pool.fetch(
        "SELECT * FROM agent_runs WHERE agent_id = $1 ORDER BY created_at DESC LIMIT $2",
        agent_id,
        limit,
    )
    return [AgentRunOut(**dict(r)) for r in rows]


@router.get("/runs/recent", response_model=list[AgentRunOut])
async def recent_runs(
    project_id: UUID | None = Query(default=None), limit: int = Query(default=20, le=100)
) -> list[AgentRunOut]:
    pool = await get_pool()
    rows = await pool.fetch(
        """
        SELECT r.* FROM agent_runs r JOIN agents a ON a.id = r.agent_id
        WHERE ($1::uuid IS NULL OR a.project_id = $1 OR a.project_id IS NULL)
        ORDER BY r.created_at DESC LIMIT $2
        """,
        project_id,
        limit,
    )
    return [AgentRunOut(**dict(r)) for r in rows]


# --- recommendations -------------------------------------------------------


@recs_router.get("", response_model=list[RecommendationOut])
async def list_recs(
    project_id: UUID | None = Query(default=None),
    status: str | None = Query(default="open"),
    limit: int = Query(default=100, le=500),
) -> list[RecommendationOut]:
    pool = await get_pool()
    rows = await pool.fetch(
        """
        SELECT * FROM recommendations
        WHERE ($1::uuid IS NULL OR project_id = $1) AND ($2::text IS NULL OR status = $2)
        ORDER BY CASE impact WHEN 'high' THEN 0 WHEN 'medium' THEN 1 ELSE 2 END,
                 CASE effort WHEN 'low' THEN 0 WHEN 'medium' THEN 1 ELSE 2 END,
                 created_at DESC
        LIMIT $3
        """,
        project_id,
        status,
        limit,
    )
    return [RecommendationOut(**dict(r)) for r in rows]


@recs_router.patch("/{rec_id}", response_model=RecommendationOut)
async def update_rec(rec_id: UUID, body: RecommendationUpdate) -> RecommendationOut:
    values = body.model_dump(exclude_unset=True)
    return RecommendationOut(**await update_row("recommendations", rec_id, values, True))


@recs_router.post("/{rec_id}/to-experiment", response_model=RecommendationOut)
async def rec_to_experiment(rec_id: UUID) -> RecommendationOut:
    rec = await fetch_one("recommendations", rec_id)
    if rec["project_id"] is None:
        raise HTTPException(status_code=400, detail="Recommendation has no project")
    pool = await get_pool()
    exp = await pool.fetchrow(
        """
        INSERT INTO experiments (project_id, name, hypothesis, channel, status)
        VALUES ($1, $2, $3, 'other', 'idea') RETURNING id
        """,
        rec["project_id"],
        rec["title"][:200],
        rec["body"],
    )
    row = await pool.fetchrow(
        """
        UPDATE recommendations SET experiment_id = $2, status = 'accepted', updated_at = now()
        WHERE id = $1 RETURNING *
        """,
        rec_id,
        exp["id"],
    )
    return RecommendationOut(**dict(row))


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:80] or "page"


@recs_router.post("/{rec_id}/to-landing-page", response_model=RecommendationOut)
async def rec_to_landing_page(rec_id: UUID) -> RecommendationOut:
    """Accept a recommendation into a draft landing page, prefilled from its page brief."""
    rec = await fetch_one("recommendations", rec_id)
    if rec["project_id"] is None:
        raise HTTPException(status_code=400, detail="Recommendation has no project")
    if rec["landing_page_id"] is not None:
        return RecommendationOut(**rec)
    page = (rec.get("data") or {}).get("page") or {}
    if not isinstance(page, dict):
        page = {}
    brief = LandingPageCreate(
        name=rec["title"][:160],
        path=str(page.get("path") or "/" + _slug(rec["title"])),
        headline=str(page.get("headline", ""))[:300],
        angle=str(page.get("angle", "")),
        target_keyword=str(page.get("target_keyword", ""))[:200],
        channel=page["channel"] if page.get("channel") in CHANNELS else "seo",
        status="draft",
        brief=rec["body"],
    )
    pool = await get_pool()
    values = {"project_id": rec["project_id"], **brief.model_dump()}
    base_path = values["path"]
    for attempt in range(1, 6):
        try:
            lp = await insert_row("landing_pages", values)
            break
        except HTTPException as exc:
            if exc.status_code != 409 or attempt == 5:
                raise
            values["path"] = f"{base_path}-{attempt + 1}"
    row = await pool.fetchrow(
        """
        UPDATE recommendations SET landing_page_id = $2, status = 'accepted', updated_at = now()
        WHERE id = $1 RETURNING *
        """,
        rec_id,
        lp["id"],
    )
    return RecommendationOut(**dict(row))
