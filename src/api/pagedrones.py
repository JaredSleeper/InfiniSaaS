"""Cockpit-side controls for the PageDrones alert-template pipeline.

Everything here proxies the project's PageDrones admin API (token stays server-side, never
returned) and mirrors published templates into ``landing_pages`` via ``pagedrones.sync``.
Publishing still requires templates to be *vetted* — PageDrones enforces that, so the cockpit
cannot skip the approval gate.
"""

from __future__ import annotations

import asyncio
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query

from src.api.projects import require_project
from src.db import get_pool
from src.errors import safe_error
from src.integrations import pagedrones
from src.models import AlertBulkStatus, AlertGenerate, AlertVet, LandingPageBulkAlerts

router = APIRouter()

THEME_CONCURRENCY = 2


def _fail(exc: Exception) -> HTTPException:
    return HTTPException(status_code=502, detail=safe_error(exc))


@router.get("/projects/{project_id}/stats")
async def stats(project_id: UUID) -> dict:
    await require_project(project_id)
    try:
        client = await pagedrones.client_for(project_id)
        data = await client.stats()
    except Exception as exc:  # noqa: BLE001
        raise _fail(exc) from exc
    data["base_url"] = client.base_url
    data["alerts_url"] = client.base_url + pagedrones.ALERTS_PATH
    return data


@router.get("/projects/{project_id}/templates")
async def templates(
    project_id: UUID,
    status: str | None = None,
    batch_id: UUID | None = None,
    q: str | None = Query(None, max_length=120),
    limit: int = Query(300, ge=1, le=2000),
) -> list[dict]:
    await require_project(project_id)
    try:
        client = await pagedrones.client_for(project_id)
        rows = await client.list(
            status=status, batch_id=str(batch_id) if batch_id else None, q=q, limit=limit
        )
    except Exception as exc:  # noqa: BLE001
        raise _fail(exc) from exc
    for r in rows:
        r["url"] = f"{client.base_url}{pagedrones.ALERTS_PATH}/{r['slug']}"
    return rows


async def _record_batch(page_id: UUID, result: dict, theme: str) -> None:
    """Remember the batch on the theme idea and move it to draft ("in production")."""
    pool = await get_pool()
    inserted = result.get("inserted", 0)
    note = (
        f"PageDrones batch {result.get('batch_id')}: {inserted} alert candidates generated"
        + (f", {result['vetted']} vetted" if result.get("vetted") else "")
        + (f", {result['rejected']} rejected" if result.get("rejected") else "")
        + f" for theme “{theme[:120]}”."
    )
    await pool.execute(
        """UPDATE landing_pages
           SET status = CASE WHEN status IN ('idea', 'vetted') THEN 'draft' ELSE status END,
               meta = jsonb_set(meta, '{pagedrones_batches}',
                                coalesce(meta->'pagedrones_batches', '[]'::jsonb)
                                || to_jsonb($2::text)),
               notes = trim(both E'\\n' from notes || E'\\n' || $3), updated_at = now()
           WHERE id = $1""",
        page_id,
        str(result.get("batch_id")),
        note,
    )


def _summary(result: dict) -> dict:
    return {
        "batch_id": result.get("batch_id"),
        "requested": result.get("requested"),
        "inserted": result.get("inserted", 0),
        "skipped": result.get("skipped", 0),
        "vetted": result.get("vetted", 0),
        "rejected": result.get("rejected", 0),
        "mock": result.get("mock", False),
        "templates": [
            {
                "id": t["id"],
                "slug": t["slug"],
                "title": t["title"],
                "status": t["status"],
                "vet_score": t.get("vet_score"),
            }
            for t in result.get("templates", [])
        ],
    }


@router.post("/projects/{project_id}/generate")
async def generate(project_id: UUID, body: AlertGenerate) -> dict:
    """Free-form theme → N candidate templates in PageDrones (status 'candidate')."""
    await require_project(project_id)
    if body.landing_page_id:
        pool = await get_pool()
        owner = await pool.fetchval(
            "SELECT project_id FROM landing_pages WHERE id = $1", body.landing_page_id
        )
        if owner != project_id:
            raise HTTPException(status_code=404, detail="Landing page not found in this project")
    try:
        client = await pagedrones.client_for(project_id)
        result = await client.generate(
            body.theme, body.n, body.category, body.audience, body.notes, body.vet
        )
    except Exception as exc:  # noqa: BLE001
        raise _fail(exc) from exc
    if body.landing_page_id:
        await _record_batch(body.landing_page_id, result, body.theme)
    return _summary(result)


def theme_for(page: dict) -> tuple[str, str, str]:
    """(theme, category, notes) for a backlog idea used as an alert theme."""
    theme = page["headline"] or page["name"]
    if page["angle"]:
        theme = f"{theme} — {page['angle']}"
    notes = "\n\n".join(s for s in (page.get("rationale"), page.get("brief")) if s and s.strip())
    return theme[:300], (page["cluster"] or "")[:80], notes


@router.post("/projects/{project_id}/generate-from-ideas")
async def generate_from_ideas(project_id: UUID, body: LandingPageBulkAlerts) -> dict:
    """Each selected backlog idea becomes one PageDrones batch (theme = headline + angle)."""
    await require_project(project_id)
    pool = await get_pool()
    rows = await pool.fetch(
        "SELECT * FROM landing_pages WHERE id = ANY($1::uuid[]) AND project_id = $2"
        " ORDER BY score DESC NULLS LAST",
        body.ids,
        project_id,
    )
    if not rows:
        raise HTTPException(status_code=404, detail="No landing pages found in this project")
    try:
        client = await pagedrones.client_for(project_id)
    except Exception as exc:  # noqa: BLE001
        raise _fail(exc) from exc
    sem = asyncio.Semaphore(THEME_CONCURRENCY)

    async def one(page: dict) -> dict:
        theme, category, notes = theme_for(page)
        if body.notes.strip():
            notes = f"{body.notes.strip()}\n\n{notes}"
        async with sem:
            try:
                result = await client.generate(theme, body.n, category, "", notes, body.vet)
            except Exception as exc:  # noqa: BLE001
                return {
                    "landing_page_id": str(page["id"]),
                    "theme": theme,
                    "error": safe_error(exc),
                }
        await _record_batch(page["id"], result, theme)
        return {"landing_page_id": str(page["id"]), "theme": theme, **_summary(result)}

    results = await asyncio.gather(*(one(dict(r)) for r in rows))
    return {
        "themes": len(results),
        "inserted": sum(r.get("inserted", 0) for r in results),
        "vetted": sum(r.get("vetted", 0) for r in results),
        "rejected": sum(r.get("rejected", 0) for r in results),
        "failed": sum(1 for r in results if r.get("error")),
        "results": results,
    }


@router.post("/projects/{project_id}/vet")
async def vet(project_id: UUID, body: AlertVet) -> dict:
    """Run the selected (or the oldest ``limit``) candidates through the real pipeline."""
    await require_project(project_id)
    try:
        client = await pagedrones.client_for(project_id)
        result = await client.vet([str(i) for i in body.ids], body.limit)
    except Exception as exc:  # noqa: BLE001
        raise _fail(exc) from exc
    return {
        "vetted": result.get("vetted", 0),
        "rejected": result.get("rejected", 0),
        "templates": [
            {
                "id": t["id"],
                "slug": t["slug"],
                "status": t["status"],
                "vet_score": t.get("vet_score"),
                "vet_notes": t.get("vet_notes", ""),
            }
            for t in result.get("templates", [])
        ],
    }


@router.post("/projects/{project_id}/templates/bulk-status")
async def bulk_status(project_id: UUID, body: AlertBulkStatus) -> dict:
    """Bulk approve (publish) / reject; PageDrones blocks publishing anything not vetted.
    Landing pages are re-synced right after so the cockpit reflects the new catalog."""
    await require_project(project_id)
    try:
        client = await pagedrones.client_for(project_id)
        result = await client.bulk_status([str(i) for i in body.ids], body.status)
        result["sync"] = await pagedrones.sync_project(project_id)
    except Exception as exc:  # noqa: BLE001
        raise _fail(exc) from exc
    return result


@router.post("/projects/{project_id}/sync")
async def sync(project_id: UUID) -> dict:
    await require_project(project_id)
    try:
        return await pagedrones.sync_project(project_id)
    except Exception as exc:  # noqa: BLE001
        raise _fail(exc) from exc
