"""Agent framework: build context → LLM → parse recommendations → persist run."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from uuid import UUID

import structlog

from src.agents import llm, seo_audit
from src.api.events import analytics_summary
from src.api.finance import finance_summary
from src.api.landing import landing_performance
from src.api.ops import uptime_summary
from src.api.wiki import wiki_markdown
from src.db import get_pool
from src.errors import safe_error
from src.integrations import slack
from src.services.metrics import series, window_sum

log = structlog.get_logger()

SYSTEM = """You are a growth/product operator embedded in InfiniSaaS, a portfolio cockpit for a
solo founder's software products. You receive structured data about one project (or the whole
portfolio) and must return concrete, prioritized recommendations.

Respond with ONLY a JSON object:
{
  "summary": "<3-6 sentence brief in markdown; lead with what changed and why it matters>",
  "recommendations": [
    {"title": "<imperative, <=90 chars>", "body": "<what/why/how, markdown, <=600 chars>",
     "kind": "experiment|task|content|alert|insight|landing_page",
     "impact": "low|medium|high", "effort": "low|medium|high",
     "page": {"path": "/route", "headline": "...", "angle": "...",
              "target_keyword": "...", "channel": "seo|paid|social|content|email|other"}}
  ]
}
"page" is only for kind "landing_page" (a new page to build or an existing page to rewrite).
Rules: max 6 recommendations, no duplicates of open recommendations listed in the context,
prefer experiments with a measurable metric, cite numbers from the context, never invent data."""

_VALID_KIND = {"experiment", "task", "content", "alert", "insight", "landing_page"}
_VALID_CHANNEL = {
    "seo",
    "paid",
    "social",
    "content",
    "email",
    "community",
    "product",
    "pricing",
    "other",
}
_PAGE_FIELDS = ("path", "headline", "angle", "target_keyword", "channel")
_VALID_LEVEL = {"low", "medium", "high"}


async def _project_snapshot(project_id: UUID, days: int = 7) -> dict:
    pool = await get_pool()
    p = dict(await pool.fetchrow("SELECT * FROM projects WHERE id = $1", project_id))
    now = datetime.now(UTC)
    start, prev = now - timedelta(days=days), now - timedelta(days=days * 2)
    metrics = await pool.fetch(
        "SELECT key, name, unit, kind, is_key FROM metrics WHERE project_id = $1", project_id
    )
    deltas = []
    for m in metrics:
        pts = await series(pool, project_id, m["key"], days * 2 + 1)
        if not pts:
            continue
        if m["kind"] == "gauge":
            cur = pts[-1][1]
            before = next((v for ts, v in reversed(pts) if ts < start), None)
        else:
            cur, before = window_sum(pts, start, now), window_sum(pts, prev, start)
        deltas.append(
            {
                "metric": m["name"],
                "key": m["key"],
                "unit": m["unit"],
                "kind": m["kind"],
                "current": cur,
                "previous": before,
                "is_key": m["is_key"],
            }
        )
    experiments = await pool.fetch(
        """SELECT name, channel, status, result, hypothesis FROM experiments
           WHERE project_id = $1 AND (status IN ('planned','running')
             OR updated_at > now() - make_interval(days => $2))
           ORDER BY updated_at DESC LIMIT 15""",
        project_id,
        days,
    )
    campaigns = await pool.fetch(
        "SELECT name, channel, status, budget FROM campaigns"
        " WHERE project_id = $1 AND status <> 'done'",
        project_id,
    )
    frs = await pool.fetch(
        """SELECT title, status, priority, votes FROM feature_requests
           WHERE project_id = $1 AND status NOT IN ('shipped','declined')
           ORDER BY votes DESC LIMIT 15""",
        project_id,
    )
    feedback = await pool.fetch(
        """SELECT source, sentiment, author, left(content, 300) AS content FROM feedback
           WHERE project_id = $1 ORDER BY created_at DESC LIMIT 12""",
        project_id,
    )
    releases = await pool.fetch(
        """SELECT title, released_at FROM releases WHERE project_id = $1
           AND released_at > now() - make_interval(days => $2)
           ORDER BY released_at DESC LIMIT 10""",
        project_id,
        days,
    )
    open_recs = await pool.fetch(
        "SELECT title, kind FROM recommendations"
        " WHERE project_id = $1 AND status = 'open' LIMIT 20",
        project_id,
    )
    learnings = await pool.fetch(
        "SELECT content FROM learnings WHERE project_id = $1 ORDER BY created_at DESC LIMIT 8",
        project_id,
    )
    return {
        "project": {
            k: p[k] for k in ("name", "slug", "url", "repo_url", "stage", "health", "description")
        },
        "window_days": days,
        "metric_deltas": deltas,
        "experiments": [dict(r) for r in experiments],
        "campaigns": [
            dict(r) | {"budget": float(r["budget"]) if r["budget"] else None} for r in campaigns
        ],
        "feature_requests": [dict(r) for r in frs],
        "recent_feedback": [dict(r) for r in feedback],
        "recent_releases": [
            {"title": r["title"], "released_at": r["released_at"].isoformat()} for r in releases
        ],
        "open_recommendations": [dict(r) for r in open_recs],
        "learnings": [r["content"] for r in learnings],
        "finance": await finance_summary(project_id, 30),
        "uptime": {k: v for k, v in (await uptime_summary(project_id)).items() if k != "recent"},
    }


async def _seo_context(project_id: UUID, config: dict) -> dict:
    pool = await get_pool()
    p = await pool.fetchrow("SELECT url FROM projects WHERE id = $1", project_id)
    url = config.get("url") or p["url"]
    audit = None
    if url:
        audit = await seo_audit.audit(url)
        await pool.execute(
            "INSERT INTO seo_audits (project_id, url, score, findings, page)"
            " VALUES ($1,$2,$3,$4,$5)",
            project_id,
            url,
            audit["score"],
            audit["findings"],
            audit["page"],
        )
    keywords = await pool.fetch(
        """SELECT keyword, target_url, position, clicks, impressions, ctr, source, notes
           FROM seo_keywords WHERE project_id = $1
           ORDER BY clicks DESC NULLS LAST, position ASC NULLS LAST LIMIT 60""",
        project_id,
    )
    gsc = {}
    for key in ("gsc_clicks", "gsc_impressions", "gsc_ctr", "gsc_position"):
        pts = await series(pool, project_id, key, 60)
        if pts:
            now = datetime.now(UTC)
            gsc[key] = {
                "last_28d": window_sum(pts, now - timedelta(days=28), now)
                if key in ("gsc_clicks", "gsc_impressions")
                else round(sum(v for _, v in pts[-28:]) / max(1, len(pts[-28:])), 2),
                "prev_28d": window_sum(pts, now - timedelta(days=56), now - timedelta(days=28))
                if key in ("gsc_clicks", "gsc_impressions")
                else round(sum(v for _, v in pts[-56:-28]) / max(1, len(pts[-56:-28])), 2),
            }
    return {
        "audit": audit,
        "keywords": [
            dict(r)
            | {
                "position": float(r["position"]) if r["position"] is not None else None,
                "ctr": float(r["ctr"]) if r["ctr"] is not None else None,
            }
            for r in keywords
        ],
        "search_console": gsc,
    }


async def _ads_context(project_id: UUID) -> dict:
    pool = await get_pool()
    rows = await pool.fetch(
        """SELECT platform, sum(spend) AS spend, sum(impressions) AS impressions,
                  sum(clicks) AS clicks, sum(conversions) AS conversions,
                  count(DISTINCT day) AS days
           FROM ad_spend WHERE project_id = $1 AND day > current_date - 30 GROUP BY platform""",
        project_id,
    )
    weekly = await pool.fetch(
        """SELECT date_trunc('week', day)::date AS week, sum(spend) AS spend,
                  sum(conversions) AS conv
           FROM ad_spend WHERE project_id = $1 AND day > current_date - 90 GROUP BY 1 ORDER BY 1""",
        project_id,
    )
    return {
        "by_platform_30d": [
            {
                **dict(r),
                "spend": float(r["spend"]),
                "cpc": round(float(r["spend"]) / r["clicks"], 2) if r["clicks"] else None,
                "cac": round(float(r["spend"]) / r["conversions"], 2) if r["conversions"] else None,
            }
            for r in rows
        ],
        "weekly_90d": [
            {"week": r["week"].isoformat(), "spend": float(r["spend"]), "conversions": r["conv"]}
            for r in weekly
        ],
    }


async def _landing_context(project_id: UUID) -> dict:
    perf = await landing_performance(project_id, 30)
    pool = await get_pool()
    keywords = await pool.fetch(
        """SELECT keyword, target_url, position, clicks, impressions, ctr
           FROM seo_keywords WHERE project_id = $1
           ORDER BY impressions DESC NULLS LAST, clicks DESC NULLS LAST LIMIT 40""",
        project_id,
    )
    pages = []
    for row in perf.pages:
        page = row.page
        pages.append(
            {
                "name": page.name,
                "path": page.path,
                "url": page.url,
                "status": page.status,
                "channel": page.channel,
                "headline": page.headline,
                "angle": page.angle,
                "target_keyword": page.target_keyword,
                "campaign": row.campaign_name,
                "pageviews_30d": row.pageviews,
                "visitors_30d": row.visitors,
                "signups_30d": row.signups,
                "pays_30d": row.pays,
                "signup_rate_pct": row.signup_rate,
                "pay_rate_pct": row.pay_rate,
                "gsc_clicks": row.gsc_clicks,
                "gsc_impressions": row.gsc_impressions,
                "gsc_ctr_pct": row.gsc_ctr,
                "gsc_best_position": row.gsc_position,
                "ad_spend_30d": row.ad_spend,
                "cpa": row.cpa,
                "seo_score": row.seo_score,
            }
        )
    return {
        "window_days": perf.days,
        "pages": pages,
        "unregistered_paths_with_traffic": [
            {"path": d.path, "pageviews": d.pageviews, "visitors": d.visitors}
            for d in perf.discovered
        ],
        "keywords": [
            dict(r)
            | {
                "position": float(r["position"]) if r["position"] is not None else None,
                "ctr": float(r["ctr"]) if r["ctr"] is not None else None,
            }
            for r in keywords
        ],
    }


async def build_context(agent: dict) -> dict:
    kind, project_id, config = agent["kind"], agent["project_id"], agent["config"] or {}
    ctx: dict = {
        "agent": {"kind": kind, "name": agent["name"], "instructions": agent["instructions"]}
    }
    if project_id is None:
        pool = await get_pool()
        ids = [
            r["id"] for r in await pool.fetch("SELECT id FROM projects WHERE stage <> 'retired'")
        ]
        ctx["portfolio"] = [await _project_snapshot(pid) for pid in ids]
        return ctx
    ctx["snapshot"] = await _project_snapshot(project_id)
    ctx["wiki"] = await wiki_markdown(project_id, max_chars=6000)
    if kind == "seo":
        ctx["seo"] = await _seo_context(project_id, config)
    elif kind == "ads":
        ctx["ads"] = await _ads_context(project_id)
    elif kind == "analytics":
        ctx["analytics"] = await analytics_summary(project_id, 30)
        ctx["analytics"].pop("series", None)
    elif kind == "landing_pages":
        ctx["landing_pages"] = await _landing_context(project_id)
        ctx["analytics"] = await analytics_summary(project_id, 30)
        ctx["analytics"].pop("series", None)
    return ctx


def _prompt_for(agent: dict, ctx: dict) -> str:
    focus = {
        "weekly_brief": "Write the weekly brief: what moved, what's at risk, what to do next week.",
        "seo": "Act as an SEO lead. Use the on-page audit, keyword data and Search Console numbers "
        "to find the highest-leverage fixes and content opportunities.",
        "ads": "Act as a performance marketer. Judge spend efficiency (CPC/CAC/ROAS vs revenue), "
        "recommend budget shifts, new platforms/tests, or pausing what doesn't work.",
        "analytics": "Act as a product analyst. Read the funnel and event data, find the biggest "
        "drop-off, and propose experiments to fix it.",
        "landing_pages": "Act as a conversion + acquisition strategist for landing pages. Compare "
        "the pages in context (visitors, signup/pay rates, Search Console clicks/CTR, paid CPA, "
        "SEO score). Propose: new pages for underserved keywords or ICP segments from the wiki "
        "(kind landing_page with a full page object: path, headline, angle, target_keyword, "
        "channel), headline/angle tests on the best-trafficked pages (kind experiment), and "
        "rewrites or retirement of pages that get traffic but don't convert. Paths with traffic "
        "that aren't registered as landing pages are candidates to track. Be specific about "
        "the promise each page makes and which metric proves it worked.",
        "custom": "Follow the agent instructions in the context.",
    }[agent["kind"]]
    instr = agent["instructions"].strip()
    return (
        f"{focus}\n\n"
        + (f"Operator instructions:\n{instr}\n\n" if instr else "")
        + "Context (JSON):\n```json\n"
        + json.dumps(ctx, default=str)[:60000]
        + "\n```"
    )


def _clean_page(page: dict) -> dict:
    """Keep only the known page-brief fields, as bounded strings."""
    out = {k: str(page[k])[:400] for k in _PAGE_FIELDS if page.get(k)}
    if out.get("channel") not in _VALID_CHANNEL:
        out.pop("channel", None)
    return out


async def run_agent(agent_id: UUID, trigger: str = "manual") -> UUID:
    pool = await get_pool()
    agent = dict(await pool.fetchrow("SELECT * FROM agents WHERE id = $1", agent_id))
    run = await pool.fetchrow(
        """INSERT INTO agent_runs (agent_id, status, trigger, started_at)
           VALUES ($1, 'running', $2, now()) RETURNING id""",
        agent_id,
        trigger,
    )
    run_id = run["id"]
    try:
        ctx = await build_context(agent)
        result = await llm.complete(SYSTEM, _prompt_for(agent, ctx))
        parsed = llm.extract_json(result.text) or {}
        summary = parsed.get("summary") or result.text[:2000]
        recs = []
        for r in parsed.get("recommendations", [])[:6]:
            if not isinstance(r, dict) or not r.get("title"):
                continue
            page = r.get("page")
            data = {"page": _clean_page(page)} if isinstance(page, dict) else {}
            recs.append(
                (
                    run_id,
                    agent_id,
                    agent["project_id"],
                    str(r["title"])[:200],
                    str(r.get("body", ""))[:2000],
                    r.get("kind") if r.get("kind") in _VALID_KIND else "task",
                    r.get("impact") if r.get("impact") in _VALID_LEVEL else "medium",
                    r.get("effort") if r.get("effort") in _VALID_LEVEL else "medium",
                    data,
                )
            )
        async with pool.acquire() as conn, conn.transaction():
            await conn.executemany(
                """INSERT INTO recommendations
                   (agent_run_id, agent_id, project_id, title, body, kind, impact, effort, data)
                   VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9)""",
                recs,
            )
            await conn.execute(
                """UPDATE agent_runs SET status = 'succeeded', finished_at = now(), summary = $2,
                   context = $3, input_tokens = $4, output_tokens = $5 WHERE id = $1""",
                run_id,
                summary,
                {"keys": list(ctx), "mock": result.mock, "recommendations": len(recs)},
                result.input_tokens,
                result.output_tokens,
            )
            await conn.execute("UPDATE agents SET last_run_at = now() WHERE id = $1", agent_id)
        if agent["kind"] == "weekly_brief" and not result.mock:
            try:
                await slack.post(f"*{agent['name']}*\n{summary}")
            except Exception as exc:  # noqa: BLE001
                log.warning("slack_post_failed", error=str(exc))
    except Exception as exc:  # noqa: BLE001
        log.exception("agent_run_failed", agent_id=str(agent_id))
        await pool.execute(
            "UPDATE agent_runs SET status = 'failed', finished_at = now(), error = $2"
            " WHERE id = $1",
            run_id,
            safe_error(exc, 2000),
        )
    return run_id


async def run_due(now: datetime | None = None) -> int:
    """Scheduler entrypoint: run enabled daily/weekly agents whose interval elapsed."""
    now = now or datetime.now(UTC)
    pool = await get_pool()
    rows = await pool.fetch(
        """
        SELECT id FROM agents WHERE enabled AND schedule <> 'manual' AND (
          last_run_at IS NULL
          OR (schedule = 'daily'  AND last_run_at < $1::timestamptz - interval '23 hours')
          OR (schedule = 'weekly' AND last_run_at < $1::timestamptz - interval '6 days 23 hours'))
        """,
        now,
    )
    for r in rows:
        await run_agent(r["id"], trigger="schedule")
    return len(rows)
