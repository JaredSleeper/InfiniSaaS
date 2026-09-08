"""Landing pages: registry CRUD + cross-project performance comparison.

Attribution conventions (all derived from data the cockpit already collects):
- Product events carry ``properties.path``; a visitor is attributed to the landing page
  their *first* visit event landed on, and their later signup/pay events count for it.
- Search Console rows (``seo_keywords`` with source ``gsc``) carry the ranking page URL.
- Paid spend joins through the page's linked campaign.
- The latest on-page audit for the page URL supplies the SEO score.
"""

from __future__ import annotations

from collections import defaultdict
from urllib.parse import urlparse
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query

from src.api import devin as devin_api
from src.api.crud import make_router
from src.api.events import DEFAULT_FUNNEL
from src.api.projects import require_project
from src.db import get_pool
from src.models import (
    DevinSessionCreate,
    DevinSessionOut,
    DiscoveredPath,
    LandingPageBulk,
    LandingPageBulkDevin,
    LandingPageCreate,
    LandingPageOut,
    LandingPagePerf,
    LandingPageUpdate,
    LandingPerformance,
)

router = make_router(
    "landing_pages",
    LandingPageCreate,
    LandingPageUpdate,
    LandingPageOut,
    order_by=(
        "CASE status WHEN 'live' THEN 0 WHEN 'draft' THEN 1 WHEN 'vetted' THEN 2"
        " WHEN 'idea' THEN 3 ELSE 4 END, score DESC NULLS LAST, created_at DESC"
    ),
    filters=("status", "channel", "source"),
    limit=2000,
)
perf_router = APIRouter()


@perf_router.post("/bulk-status")
async def bulk_status(body: LandingPageBulk) -> dict:
    pool = await get_pool()
    res = await pool.execute(
        "UPDATE landing_pages SET status = $2, updated_at = now() WHERE id = ANY($1::uuid[])",
        body.ids,
        body.status,
    )
    return {"updated": int(res.split()[-1]), "status": body.status}


@perf_router.post("/bulk-devin", response_model=DevinSessionOut, status_code=201)
async def bulk_devin(body: LandingPageBulkDevin) -> DevinSessionOut:
    """One Devin session that builds every selected page from its brief."""
    pool = await get_pool()
    rows = await pool.fetch(
        "SELECT * FROM landing_pages WHERE id = ANY($1::uuid[]) ORDER BY score DESC NULLS LAST",
        body.ids,
    )
    if not rows:
        raise HTTPException(status_code=404, detail="No landing pages found")
    project_ids = {r["project_id"] for r in rows}
    if len(project_ids) != 1:
        raise HTTPException(status_code=400, detail="Select pages from a single project")
    pages = [dict(r) for r in rows]
    sections = "\n\n".join(devin_api.landing_page_md(p, heading="###") for p in pages)
    prompt = (
        f"Build the following {len(pages)} landing pages. Each has a brief; reuse one shared "
        "template/layout where pages belong to the same cluster or type, keep copy specific to "
        "each page's target keyword and promise, add proper <title>/meta/H1 per page, and "
        "link them from a sensible hub page or nav. Open a single PR.\n\n"
        + (
            f"Operator instructions:\n{body.instructions.strip()}\n\n"
            if body.instructions.strip()
            else ""
        )
        + "## Pages\n\n"
        + sections
    )
    first = pages[0]
    session = await devin_api.create_session(
        DevinSessionCreate(
            prompt=prompt,
            title=f"Build {len(pages)} landing pages",
            project_id=first["project_id"],
            source_type="landing_page",
            source_id=first["id"],
            include_wiki=body.include_wiki,
        )
    )
    await pool.execute(
        """UPDATE landing_pages
           SET status = CASE WHEN status IN ('idea','vetted') THEN 'draft' ELSE status END,
               notes = trim(both E'\\n' from notes || E'\\n' || $2), updated_at = now()
           WHERE id = ANY($1::uuid[])""",
        [p["id"] for p in pages],
        f"Sent to Devin ({session.url}) with {len(pages) - 1} other page(s).",
    )
    return session


def _norm_path(value: str | None) -> str | None:
    if not value:
        return None
    if value.startswith(("http://", "https://")):
        value = urlparse(value).path or "/"
    if not value.startswith("/"):
        value = "/" + value
    return value.rstrip("/") or "/"


def _url_path(url: str | None) -> str | None:
    return _norm_path(url) if url else None


def _rate(num: int, den: int) -> float | None:
    return round(num / den * 100, 2) if den else None


def _funnel(project: dict) -> tuple[str, str, str]:
    steps = (project.get("settings") or {}).get("funnel") or DEFAULT_FUNNEL
    visit = steps[0]
    signup = steps[1] if len(steps) > 1 else steps[0]
    pay = steps[-1]
    return visit, signup, pay


async def _event_stats(project: dict, days: int) -> dict[str, dict]:
    """Per-path pageviews, first-touch visitors and their downstream signups/pays."""
    visit, signup, pay = _funnel(project)
    pool = await get_pool()
    rows = await pool.fetch(
        """
        WITH visits AS (
            SELECT user_key, ts,
                   rtrim('/' || ltrim(regexp_replace(regexp_replace(properties->>'path',
                                      '^https?://[^/]*', ''), '[?#].*$', ''), '/'), '/') AS path
            FROM events
            WHERE project_id = $1 AND name = $2 AND ts > now() - make_interval(days => $3)
              AND NULLIF(properties->>'path', '') IS NOT NULL
        ),
        first_touch AS (
            SELECT DISTINCT ON (user_key) user_key, path
            FROM visits WHERE user_key IS NOT NULL ORDER BY user_key, ts
        ),
        converted AS (
            SELECT ft.path,
                   count(*) AS visitors,
                   count(*) FILTER (WHERE EXISTS (
                       SELECT 1 FROM events e WHERE e.project_id = $1 AND e.name = $4
                         AND e.user_key = ft.user_key)) AS signups,
                   count(*) FILTER (WHERE EXISTS (
                       SELECT 1 FROM events e WHERE e.project_id = $1 AND e.name = $5
                         AND e.user_key = ft.user_key)) AS pays
            FROM first_touch ft GROUP BY ft.path
        ),
        views AS (SELECT path, count(*) AS pageviews FROM visits GROUP BY path)
        SELECT v.path, v.pageviews,
               COALESCE(c.visitors, 0) AS visitors,
               COALESCE(c.signups, 0) AS signups,
               COALESCE(c.pays, 0) AS pays
        FROM views v LEFT JOIN converted c ON c.path = v.path
        """,
        project["id"],
        visit,
        days,
        signup,
        pay,
    )
    return {(r["path"] or "/"): dict(r) for r in rows}


async def _gsc_stats(project_id: UUID) -> dict[str, dict]:
    pool = await get_pool()
    rows = await pool.fetch(
        """
        SELECT target_url, clicks, impressions, position
        FROM seo_keywords
        WHERE project_id = $1 AND target_url IS NOT NULL AND clicks IS NOT NULL
        """,
        project_id,
    )
    agg: dict[str, dict] = defaultdict(
        lambda: {"clicks": 0, "impressions": 0, "keywords": 0, "best_position": None}
    )
    for r in rows:
        path = _url_path(r["target_url"])
        if path is None:
            continue
        a = agg[path]
        a["clicks"] += r["clicks"] or 0
        a["impressions"] += r["impressions"] or 0
        a["keywords"] += 1
        if r["position"] is not None:
            pos = float(r["position"])
            a["best_position"] = pos if a["best_position"] is None else min(a["best_position"], pos)
    return dict(agg)


async def _ad_stats(project_id: UUID, days: int) -> dict[UUID, dict]:
    pool = await get_pool()
    rows = await pool.fetch(
        """
        SELECT campaign_id, sum(spend) AS spend, sum(clicks) AS clicks,
               sum(conversions) AS conversions
        FROM ad_spend
        WHERE project_id = $1 AND campaign_id IS NOT NULL
          AND day > current_date - $2::int
        GROUP BY campaign_id
        """,
        project_id,
        days,
    )
    return {r["campaign_id"]: dict(r) for r in rows}


async def _audit_scores(project_id: UUID) -> dict[str, dict]:
    pool = await get_pool()
    rows = await pool.fetch(
        """
        SELECT DISTINCT ON (url) url, score, ts FROM seo_audits
        WHERE project_id = $1 ORDER BY url, ts DESC
        """,
        project_id,
    )
    out: dict[str, dict] = {}
    for r in rows:
        path = _url_path(r["url"])
        if path is not None and path not in out:
            out[path] = {"score": r["score"], "ts": r["ts"]}
    return out


async def _project_performance(project: dict, days: int) -> tuple[list, list]:
    pool = await get_pool()
    pages = await pool.fetch(
        """
        SELECT lp.*, c.name AS campaign_name FROM landing_pages lp
        LEFT JOIN campaigns c ON c.id = lp.campaign_id
        WHERE lp.project_id = $1 AND lp.status NOT IN ('idea', 'vetted', 'rejected')
        ORDER BY lp.created_at
        """,
        project["id"],
    )
    events = await _event_stats(project, days)
    gsc = await _gsc_stats(project["id"])
    ads = await _ad_stats(project["id"], days)
    audits = await _audit_scores(project["id"])

    perf: list[LandingPagePerf] = []
    registered: set[str] = set()
    for row in pages:
        page = dict(row)
        campaign_name = page.pop("campaign_name")
        path = _norm_path(page["path"]) or "/"
        registered.add(path)
        url_path = _url_path(page["url"]) or path
        ev = events.get(path) or events.get(url_path) or {}
        g = gsc.get(url_path) or gsc.get(path) or {}
        ad = ads.get(page["campaign_id"]) if page["campaign_id"] else None
        audit = audits.get(url_path) or audits.get(path) or {}
        visitors = int(ev.get("visitors", 0))
        signups = int(ev.get("signups", 0))
        pays = int(ev.get("pays", 0))
        spend = float(ad["spend"]) if ad and ad["spend"] is not None else None
        impressions = g.get("impressions")
        clicks = g.get("clicks")
        perf.append(
            LandingPagePerf(
                page=LandingPageOut(**page),
                project_name=project["name"],
                project_slug=project["slug"],
                accent_color=project["accent_color"],
                days=days,
                pageviews=int(ev.get("pageviews", 0)),
                visitors=visitors,
                signups=signups,
                pays=pays,
                signup_rate=_rate(signups, visitors),
                pay_rate=_rate(pays, visitors),
                gsc_clicks=clicks,
                gsc_impressions=impressions,
                gsc_ctr=_rate(clicks, impressions) if impressions else None,
                gsc_position=g.get("best_position"),
                gsc_keywords=int(g.get("keywords", 0)),
                ad_spend=spend,
                ad_clicks=int(ad["clicks"]) if ad and ad["clicks"] is not None else None,
                ad_conversions=(
                    int(ad["conversions"]) if ad and ad["conversions"] is not None else None
                ),
                cpa=round(spend / signups, 2) if spend and signups else None,
                seo_score=audit.get("score"),
                seo_audit_at=audit.get("ts"),
                campaign_name=campaign_name,
            )
        )
    discovered = [
        DiscoveredPath(
            project_id=project["id"],
            project_name=project["name"],
            path=path,
            pageviews=int(ev["pageviews"]),
            visitors=int(ev["visitors"]),
        )
        for path, ev in events.items()
        if path not in registered
    ]
    discovered.sort(key=lambda d: d.pageviews, reverse=True)
    return perf, discovered[:25]


async def landing_performance(project_id: UUID | None, days: int) -> LandingPerformance:
    pool = await get_pool()
    if project_id is not None:
        projects = [await require_project(project_id)]
    else:
        projects = [
            dict(r)
            for r in await pool.fetch(
                "SELECT * FROM projects WHERE stage <> 'retired' ORDER BY name"
            )
        ]
    pages: list[LandingPagePerf] = []
    discovered: list[DiscoveredPath] = []
    for project in projects:
        p, d = await _project_performance(project, days)
        pages.extend(p)
        discovered.extend(d)
    pages.sort(key=lambda r: (r.visitors, r.pageviews, r.gsc_clicks or 0), reverse=True)
    return LandingPerformance(days=days, pages=pages, discovered=discovered)


@perf_router.get("/performance", response_model=LandingPerformance)
async def performance(
    project_id: UUID | None = Query(default=None),
    days: int = Query(default=30, ge=1, le=365),
) -> LandingPerformance:
    return await landing_performance(project_id, days)
