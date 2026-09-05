from __future__ import annotations

import re
from uuid import UUID

from fastapi import APIRouter, HTTPException

from src.api.projects import require_project
from src.db import get_pool
from src.models import WikiPageOut, WikiPageUpsert

router = APIRouter()

_SLUG = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")


@router.get("", response_model=list[WikiPageOut])
async def list_pages(project_id: UUID) -> list[WikiPageOut]:
    await require_project(project_id)
    pool = await get_pool()
    rows = await pool.fetch(
        "SELECT * FROM wiki_pages WHERE project_id = $1 ORDER BY sort_order, title", project_id
    )
    return [WikiPageOut(**dict(r)) for r in rows]


@router.put("/{slug}", response_model=WikiPageOut)
async def upsert_page(project_id: UUID, slug: str, body: WikiPageUpsert) -> WikiPageOut:
    if not _SLUG.match(slug):
        raise HTTPException(status_code=400, detail="Invalid slug")
    await require_project(project_id)
    pool = await get_pool()
    row = await pool.fetchrow(
        """
        INSERT INTO wiki_pages (project_id, slug, title, content, sort_order)
        VALUES ($1, $2, coalesce($3, $2), $4, coalesce($5, 100))
        ON CONFLICT (project_id, slug) DO UPDATE
            SET title = coalesce($3, wiki_pages.title),
                content = $4,
                sort_order = coalesce($5, wiki_pages.sort_order),
                updated_at = now()
        RETURNING *
        """,
        project_id,
        slug,
        body.title,
        body.content,
        body.sort_order,
    )
    return WikiPageOut(**dict(row))


@router.delete("/{slug}", status_code=204)
async def delete_page(project_id: UUID, slug: str) -> None:
    pool = await get_pool()
    res = await pool.execute(
        "DELETE FROM wiki_pages WHERE project_id = $1 AND slug = $2", project_id, slug
    )
    if res.endswith("0"):
        raise HTTPException(status_code=404, detail="Page not found")


async def wiki_markdown(project_id: UUID, max_chars: int = 12000) -> str:
    """Concatenated wiki used as context for agents and Devin prompts."""
    pool = await get_pool()
    rows = await pool.fetch(
        "SELECT title, content FROM wiki_pages WHERE project_id = $1 ORDER BY sort_order",
        project_id,
    )
    parts = []
    for r in rows:
        body = r["content"].strip()
        if not body or _is_template_only(body):
            continue
        parts.append(f"# {r['title']}\n{body}")
    text = "\n\n".join(parts)
    return text[:max_chars] + ("\n…(truncated)" if len(text) > max_chars else "")


def _is_template_only(body: str) -> bool:
    return all(line.startswith(("#", "|")) or not line.strip() for line in body.splitlines())
