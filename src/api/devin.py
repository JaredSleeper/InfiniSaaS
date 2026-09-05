from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, HTTPException, Query

from src.api.projects import require_project
from src.api.wiki import wiki_markdown
from src.config import settings
from src.db import get_pool
from src.errors import safe_error
from src.integrations import devin
from src.models import DevinMessage, DevinPromptPreview, DevinSessionCreate, DevinSessionOut

router = APIRouter()


async def _source_context(source_type: str, source_id: UUID | None) -> tuple[str, str]:
    """Return (title, markdown) for the record a session is launched from."""
    if source_id is None or source_type == "manual":
        return "", ""
    pool = await get_pool()
    if source_type == "feature_request":
        r = await pool.fetchrow("SELECT * FROM feature_requests WHERE id = $1", source_id)
        if r:
            fb = await pool.fetch(
                "SELECT author, content FROM feedback WHERE feature_request_id = $1 LIMIT 10",
                source_id,
            )
            quotes = "\n".join(f"- {f['author'] or 'user'}: {f['content']}" for f in fb)
            return r["title"], (
                f"## Feature request: {r['title']}\nPriority: {r['priority']} · "
                f"Status: {r['status']} · Votes: {r['votes']}\n\n{r['description']}"
                + (f"\n\n### Supporting feedback\n{quotes}" if quotes else "")
            )
    elif source_type == "recommendation":
        r = await pool.fetchrow("SELECT * FROM recommendations WHERE id = $1", source_id)
        if r:
            return r["title"], (
                f"## Agent recommendation: {r['title']}\nKind: {r['kind']} · "
                f"Impact: {r['impact']} · Effort: {r['effort']}\n\n{r['body']}"
            )
    elif source_type == "experiment":
        r = await pool.fetchrow("SELECT * FROM experiments WHERE id = $1", source_id)
        if r:
            return r["name"], (
                f"## Experiment: {r['name']}\nChannel: {r['channel']} · Status: {r['status']}\n\n"
                f"Hypothesis: {r['hypothesis']}"
            )
    elif source_type == "landing_page":
        r = await pool.fetchrow("SELECT * FROM landing_pages WHERE id = $1", source_id)
        if r:
            facts = [f"Path: `{r['path']}`"]
            if r["url"]:
                facts.append(f"URL: {r['url']}")
            facts += [f"Channel: {r['channel']}", f"Status: {r['status']}"]
            if r["target_keyword"]:
                facts.append(f"Target keyword: {r['target_keyword']}")
            if r["headline"]:
                facts.append(f"Headline: {r['headline']}")
            if r["angle"]:
                facts.append(f"Angle: {r['angle']}")
            md = f"## Landing page: {r['name']}\n" + "\n".join(facts)
            if r["brief"]:
                md += f"\n\n### Brief\n{r['brief']}"
            if r["notes"]:
                md += f"\n\n### Notes\n{r['notes']}"
            md += (
                "\n\nInstrument the page so the cockpit can measure it: fire the project's "
                f'`visit` event with `properties.path = "{r["path"]}"` on load, and keep '
                "signup/pay events tagged with the same user_key."
            )
            return r["name"], md
    return "", ""


async def build_prompt(body: DevinSessionCreate) -> DevinPromptPreview:
    parts: list[str] = []
    title = body.title
    project = await require_project(body.project_id) if body.project_id else None
    if project:
        header = f"# Project: {project['name']}"
        facts = []
        if project.get("url"):
            facts.append(f"URL: {project['url']}")
        if project.get("repo_url"):
            facts.append(f"Repo: {project['repo_url']}")
        facts.append(f"Stage: {project['stage']}")
        if project.get("description"):
            facts.append(project["description"])
        parts.append(header + "\n" + "\n".join(facts))
        if body.include_wiki:
            wiki = await wiki_markdown(body.project_id)
            if wiki:
                parts.append("# Product context (from InfiniSaaS wiki)\n" + wiki)
    src_title, src_md = await _source_context(body.source_type, body.source_id)
    if src_md:
        parts.append(src_md)
    if not title:
        title = src_title or body.prompt.strip().splitlines()[0][:80]
    parts.append("# Task\n" + body.prompt.strip())
    if settings.public_url:
        parts.append(
            "When done, reply with a short summary and PR link; this session was launched from "
            f"the InfiniSaaS cockpit ({settings.public_url})."
        )
    return DevinPromptPreview(prompt="\n\n".join(parts), title=title)


@router.get("/status")
async def status() -> dict:
    return {"configured": devin.configured(), "api_base": settings.devin_api_base}


@router.post("/preview", response_model=DevinPromptPreview)
async def preview(body: DevinSessionCreate) -> DevinPromptPreview:
    return await build_prompt(body)


@router.get("/sessions", response_model=list[DevinSessionOut])
async def list_sessions(
    project_id: UUID | None = Query(default=None),
    source_type: str | None = Query(default=None),
    source_id: UUID | None = Query(default=None),
) -> list[DevinSessionOut]:
    pool = await get_pool()
    rows = await pool.fetch(
        """
        SELECT * FROM devin_sessions
        WHERE ($1::uuid IS NULL OR project_id = $1)
          AND ($2::text IS NULL OR source_type = $2)
          AND ($3::uuid IS NULL OR source_id = $3)
        ORDER BY created_at DESC LIMIT 200
        """,
        project_id,
        source_type,
        source_id,
    )
    return [DevinSessionOut(**dict(r)) for r in rows]


@router.post("/sessions", response_model=DevinSessionOut, status_code=201)
async def create_session(body: DevinSessionCreate) -> DevinSessionOut:
    built = await build_prompt(body)
    tags = ["infinisaas"]
    if body.project_id:
        project = await require_project(body.project_id)
        tags.append(project["slug"])
    try:
        created = await devin.create_session(built.prompt, built.title, tags)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=safe_error(exc)) from exc
    pool = await get_pool()
    row = await pool.fetchrow(
        """
        INSERT INTO devin_sessions
            (project_id, session_id, url, title, prompt, status, source_type, source_id)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
        RETURNING *
        """,
        body.project_id,
        created["session_id"],
        created["url"],
        built.title,
        built.prompt,
        "mock" if created["mock"] else "working",
        body.source_type,
        body.source_id,
    )
    if body.source_type == "recommendation" and body.source_id:
        await pool.execute(
            """
            UPDATE recommendations
            SET devin_session_id = $2, status = 'accepted', updated_at = now()
            WHERE id = $1
            """,
            body.source_id,
            row["id"],
        )
    if body.source_type == "feature_request" and body.source_id:
        await pool.execute(
            """
            UPDATE feature_requests SET status = 'building', updated_at = now()
            WHERE id = $1 AND status IN ('inbox', 'considering', 'planned')
            """,
            body.source_id,
        )
    return DevinSessionOut(**dict(row))


async def _require_session(row_id: UUID) -> dict:
    pool = await get_pool()
    row = await pool.fetchrow("SELECT * FROM devin_sessions WHERE id = $1", row_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return dict(row)


@router.post("/sessions/{row_id}/refresh", response_model=DevinSessionOut)
async def refresh(row_id: UUID) -> DevinSessionOut:
    row = await _require_session(row_id)
    try:
        remote = await devin.get_session(row["session_id"])
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=safe_error(exc)) from exc
    pool = await get_pool()
    updated = await pool.fetchrow(
        """
        UPDATE devin_sessions
        SET status = $2, pr_url = coalesce($3, pr_url), title = coalesce($4, title),
            updated_at = now()
        WHERE id = $1 RETURNING *
        """,
        row_id,
        remote["status"],
        remote["pr_url"],
        remote["title"] or None,
    )
    return DevinSessionOut(**dict(updated))


@router.post("/sessions/{row_id}/message", status_code=202)
async def message(row_id: UUID, body: DevinMessage) -> dict:
    row = await _require_session(row_id)
    try:
        await devin.send_message(row["session_id"], body.message)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=safe_error(exc)) from exc
    return {"sent": True}


@router.delete("/sessions/{row_id}", status_code=204)
async def forget(row_id: UUID) -> None:
    await _require_session(row_id)
    pool = await get_pool()
    await pool.execute("DELETE FROM devin_sessions WHERE id = $1", row_id)


async def refresh_active() -> int:
    """Scheduler entrypoint: poll status for sessions that aren't finished."""
    if not devin.configured():
        return 0
    pool = await get_pool()
    rows = await pool.fetch(
        """
        SELECT id FROM devin_sessions
        WHERE status NOT IN ('finished', 'expired', 'mock')
          AND created_at > now() - interval '7 days'
        """
    )
    n = 0
    for r in rows:
        try:
            await refresh(r["id"])
            n += 1
        except HTTPException:
            pass
    return n
