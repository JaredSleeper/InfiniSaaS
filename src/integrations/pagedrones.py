"""PageDrones alert templates ↔ cockpit landing pages.

PageDrones keeps the pipeline (generate → vet → bulk publish, all behind its ADMIN_TOKEN);
the cockpit drives it and mirrors the *published* templates as ``landing_pages`` rows
(``source='pagedrones'``, ``page_type='use_case'``, ``external_id`` = template id) so every
``/alerts/<slug>`` page gets the same visit → signup → monitor_created funnel, GSC data and
agent scrutiny as any other landing page. Templates that leave ``published`` retire their page.

Use-case *themes* accepted in the cockpit are ordinary backlog ideas; generating from one
records the PageDrones ``batch_id`` in ``meta.pagedrones_batches`` so published children can
be traced back to the theme (``meta.theme_landing_page_id``).
"""

from __future__ import annotations

import contextlib
import json
from typing import Any
from uuid import UUID

import httpx
import structlog

from src.db import get_pool
from src.integrations import registry

log = structlog.get_logger()

ADMIN = "/api/admin/alert-templates"
ALERTS_PATH = "/alerts"
# Tests swap this for an httpx.MockTransport that emulates the PageDrones admin API.
transport: httpx.AsyncBaseTransport | None = None


def _base(url: str) -> str:
    url = (url or "").strip().rstrip("/")
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    return url


class Client:
    def __init__(self, base_url: str, token: str, timeout: float = 300):
        self.base_url = _base(base_url)
        self._headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
        self._timeout = timeout

    async def _req(
        self, method: str, path: str, *, params: dict | None = None, body: dict | None = None
    ) -> Any:
        async with httpx.AsyncClient(timeout=self._timeout, transport=transport) as client:
            r = await client.request(
                method,
                self.base_url + path,
                params={k: v for k, v in (params or {}).items() if v not in (None, "")},
                json=body,
                headers=self._headers,
            )
        if r.status_code == 401:
            raise RuntimeError("PageDrones rejected the admin token")
        if r.status_code == 503:
            raise RuntimeError("PageDrones admin API is not configured (ADMIN_TOKEN unset)")
        if r.status_code >= 400:
            detail = ""
            with contextlib.suppress(ValueError, AttributeError):
                detail = str(r.json().get("detail", ""))[:200]
            raise RuntimeError(f"PageDrones HTTP {r.status_code}{': ' + detail if detail else ''}")
        return r.json()

    async def stats(self) -> dict:
        return await self._req("GET", f"{ADMIN}/stats")

    async def list(
        self,
        status: str | None = None,
        batch_id: str | None = None,
        q: str | None = None,
        limit: int = 500,
    ) -> list[dict]:
        return await self._req(
            "GET",
            ADMIN,
            params={"status": status, "batch_id": batch_id, "q": q, "limit": limit},
        )

    async def generate(
        self,
        theme: str,
        n: int,
        category: str = "",
        audience: str = "",
        notes: str = "",
        vet: bool = False,
    ) -> dict:
        return await self._req(
            "POST",
            f"{ADMIN}/generate",
            body={
                "theme": theme[:300],
                "n": n,
                "category": category[:80],
                "audience": audience[:200],
                "notes": notes[:2000],
                "vet": vet,
            },
        )

    async def vet(self, ids: list[str], limit: int = 10) -> dict:
        return await self._req("POST", f"{ADMIN}/vet", body={"ids": ids, "limit": limit})

    async def bulk_status(self, ids: list[str], status: str) -> dict:
        return await self._req("POST", f"{ADMIN}/bulk-status", body={"ids": ids, "status": status})


async def client_for(project_id: UUID) -> Client:
    row = await registry.get_integration("pagedrones", project_id)
    if row is None:
        raise RuntimeError("Connect the PageDrones integration for this project first")
    token = await registry.get_secret("pagedrones", project_id)
    if not token:
        raise RuntimeError("PageDrones integration has no admin token")
    return Client((row["config"] or {}).get("base_url", ""), token)


async def verify(base_url: str, token: str) -> str:
    stats = await Client(base_url, token, timeout=30).stats()
    by = stats.get("by_status") or {}
    return (
        f"Connected: {by.get('published', 0)} published, {by.get('vetted', 0)} vetted, "
        f"{by.get('candidate', 0)} candidates, {stats.get('subscribers', 0)} subscribers"
    )


# ── sync: published templates → landing pages ───────────────────────────────


def _keyword(t: dict) -> str:
    kws = t.get("keywords") or []
    return str(kws[0])[:200].lower() if kws else str(t.get("title", ""))[:200].lower()


def page_from_template(t: dict, base_url: str) -> dict:
    """Map a PageDrones template row onto landing_pages columns (all bounded)."""
    slug = str(t["slug"])
    path = f"{ALERTS_PATH}/{slug}"
    desc = str(t.get("description") or "")
    schedule = t.get("default_schedule") or ""
    brief = (
        f"Pre-built PageDrones alert (use-case page). Users subscribe with one click and pick a "
        f"fixed schedule (default: {schedule or 'daily'}).\n\n{desc}\n\nDrone prompt:\n"
        f"{str(t.get('prompt') or '')[:1500]}"
    )
    meta = {
        "template_id": str(t["id"]),
        "slug": slug,
        "category": t.get("category") or "",
        "theme": t.get("theme") or "",
        "audience": t.get("audience") or "",
        "batch_id": str(t["batch_id"]) if t.get("batch_id") else None,
        "default_schedule": schedule,
        "vet_score": t.get("vet_score"),
        "subscribers": int(t.get("subscribers") or 0),
        "published_at": t.get("published_at"),
        "keywords": [str(k)[:80] for k in (t.get("keywords") or [])[:12]],
    }
    return {
        "name": str(t.get("title") or slug)[:160],
        "path": path,
        "url": _base(base_url) + path,
        "headline": str(t.get("headline") or t.get("title") or "")[:300],
        "angle": (
            f"{t.get('audience') or 'Anyone'} who wants to be alerted about "
            f"{(t.get('theme') or t.get('category') or slug)}. {desc}"
        )[:1000],
        "target_keyword": _keyword(t),
        "page_type": "use_case",
        "cluster": str(t.get("category") or "alerts")[:120],
        "score": t.get("vet_score"),
        "rationale": str(t.get("vet_notes") or "")[:1000],
        "brief": brief[:4000],
        "external_id": str(t["id"]),
        "meta": meta,
    }


async def _theme_lookup(project_id: UUID, batch_ids: set[str]) -> dict[str, dict]:
    """batch_id → theme landing page (id, name) for batches generated from cockpit ideas."""
    if not batch_ids:
        return {}
    pool = await get_pool()
    rows = await pool.fetch(
        """SELECT id, name, meta FROM landing_pages
           WHERE project_id = $1 AND meta ? 'pagedrones_batches'""",
        project_id,
    )
    out: dict[str, dict] = {}
    for r in rows:
        for b in (r["meta"] or {}).get("pagedrones_batches") or []:
            if str(b) in batch_ids:
                out[str(b)] = {"id": str(r["id"]), "name": r["name"]}
    return out


async def register_published(project_id: UUID, base_url: str, templates: list[dict]) -> dict:
    """Upsert one live landing page per published template; retire pages whose template
    is no longer published. Manual edits to name/headline/notes are kept on existing rows."""
    pool = await get_pool()
    published = [t for t in templates if t.get("status") == "published"]
    themes = await _theme_lookup(
        project_id, {str(t["batch_id"]) for t in published if t.get("batch_id")}
    )
    registered = updated = 0
    for t in published:
        page = page_from_template(t, base_url)
        theme = themes.get(page["meta"]["batch_id"] or "")
        if theme:
            page["meta"]["theme_landing_page_id"] = theme["id"]
            page["meta"]["theme"] = page["meta"]["theme"] or theme["name"]
        res = await pool.fetchrow(
            """
            INSERT INTO landing_pages
                (project_id, name, path, url, headline, angle, target_keyword, channel, status,
                 page_type, cluster, score, rationale, source, brief, external_id, meta)
            VALUES ($1, $2, $3, $4, $5, $6, $7, 'seo', 'live', 'use_case', $8, $9, $10,
                    'pagedrones', $11, $12, $13)
            ON CONFLICT (project_id, path) DO UPDATE SET
                url = EXCLUDED.url,
                angle = EXCLUDED.angle,
                target_keyword = CASE WHEN landing_pages.target_keyword = ''
                                      THEN EXCLUDED.target_keyword
                                      ELSE landing_pages.target_keyword END,
                status = CASE WHEN landing_pages.status IN ('idea', 'vetted', 'draft', 'retired')
                              THEN 'live' ELSE landing_pages.status END,
                page_type = 'use_case',
                cluster = EXCLUDED.cluster,
                score = EXCLUDED.score,
                rationale = EXCLUDED.rationale,
                source = 'pagedrones',
                brief = CASE WHEN landing_pages.brief = '' THEN EXCLUDED.brief
                             ELSE landing_pages.brief END,
                external_id = EXCLUDED.external_id,
                meta = landing_pages.meta || EXCLUDED.meta,
                updated_at = now()
            RETURNING (xmax = 0) AS inserted
            """,
            project_id,
            page["name"],
            page["path"],
            page["url"],
            page["headline"],
            page["angle"],
            page["target_keyword"],
            page["cluster"],
            page["score"],
            page["rationale"],
            page["brief"],
            page["external_id"],
            page["meta"],
        )
        if res["inserted"]:
            registered += 1
        else:
            updated += 1
    keep = [str(t["id"]) for t in published]
    retired = await pool.execute(
        """
        UPDATE landing_pages SET status = 'retired', updated_at = now()
        WHERE project_id = $1 AND source = 'pagedrones' AND status = 'live'
          AND external_id IS NOT NULL AND NOT (external_id = ANY($2::text[]))
        """,
        project_id,
        keep,
    )
    return {
        "published": len(published),
        "registered": registered,
        "updated": updated,
        "retired": int(retired.split()[-1]),
        "subscribers": sum(int(t.get("subscribers") or 0) for t in published),
    }


async def sync(project_id: UUID, base_url: str, token: str) -> dict:
    templates = await Client(base_url, token).list(status="published", limit=2000)
    result = await register_published(project_id, base_url, templates)
    log.info("pagedrones_sync", project_id=str(project_id), **result)
    return result


async def sync_project(project_id: UUID) -> dict:
    """Sync using the stored integration; used after publish/unpublish from the cockpit."""
    row = await registry.get_integration("pagedrones", project_id)
    token = await registry.get_secret("pagedrones", project_id)
    if row is None or not token:
        raise RuntimeError("Connect the PageDrones integration for this project first")
    try:
        result = await sync(project_id, (row["config"] or {}).get("base_url", ""), token)
    except Exception as exc:
        await registry.set_status(row["id"], "error", str(exc)[:500])
        raise
    await registry.set_status(row["id"], "ok", json.dumps(result)[:500], synced=True)
    return result


# ── agent context ───────────────────────────────────────────────────────────


async def context(project_id: UUID) -> dict | None:
    """What the landing agent needs to know: is the loop enabled, and how are the published
    use-case pages doing (subscribers per page). DB-only so agent runs never hit PageDrones."""
    row = await registry.get_integration("pagedrones", project_id)
    if row is None:
        return None
    pool = await get_pool()
    pages = await pool.fetch(
        """SELECT path, name, status, cluster, score, meta FROM landing_pages
           WHERE project_id = $1 AND source = 'pagedrones'
           ORDER BY (meta->>'subscribers')::int DESC NULLS LAST, score DESC NULLS LAST
           LIMIT 60""",
        project_id,
    )
    themes = await pool.fetch(
        """SELECT name, status, jsonb_array_length(meta->'pagedrones_batches') AS batches
           FROM landing_pages WHERE project_id = $1 AND meta ? 'pagedrones_batches'
           ORDER BY updated_at DESC LIMIT 30""",
        project_id,
    )
    return {
        "enabled": True,
        "how_it_works": (
            "use_case ideas in the backlog can be turned into a batch of pre-built alert "
            "templates (PageDrones generates + vets N alerts per theme; the operator publishes "
            "the good ones in bulk; each published alert becomes its own /alerts/<slug> "
            "landing page tracked here). Propose use_case ideas phrased as alert THEMES: "
            "'<audience> tracking <what changes>' — specific, recurring, checkable on the web."
        ),
        "live_pages": sum(1 for p in pages if p["status"] == "live"),
        "retired_pages": sum(1 for p in pages if p["status"] == "retired"),
        "themes_generated": [dict(t) for t in themes],
        "pages": [
            {
                "path": p["path"],
                "name": p["name"],
                "status": p["status"],
                "category": p["cluster"],
                "vet_score": p["score"],
                "subscribers": (p["meta"] or {}).get("subscribers", 0),
                "theme": (p["meta"] or {}).get("theme", ""),
            }
            for p in pages
        ],
    }
