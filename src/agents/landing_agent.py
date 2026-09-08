"""Landing-page agent v2: competitor research + a growing backlog of scored page ideas.

Per run:
1. ``refresh_research`` — discover competitors (web-search LLM) when the project has few,
   and (re)crawl stale inventories. Cached in ``competitors``; nothing here is invented.
2. ``generate_ideas`` — one LLM call asks for ``batch_size`` new pages, typed and scored,
   deduped against every existing row (path + keyword) and inserted as ``status='idea'``.
3. The generic runner then produces the ≤6 "do this now" recommendations as before.

Agent ``config`` knobs: ``batch_size`` (default 15), ``max_competitors`` (10),
``recrawl_days`` (7), ``research`` (False disables discovery/crawl).
"""

from __future__ import annotations

import asyncio
import json
import re
from datetime import UTC, datetime, timedelta
from uuid import UUID

import structlog

from src.agents import llm, research
from src.api.wiki import wiki_markdown
from src.db import get_pool
from src.models import LandingPageType

log = structlog.get_logger()

PAGE_TYPES: tuple[str, ...] = LandingPageType.__args__  # type: ignore[attr-defined]
CHANNELS = {"seo", "paid", "social", "content", "email", "community", "product", "pricing", "other"}
DEFAULT_BATCH = 15
MAX_BATCH = 50
MAX_CONTEXT_IDEAS = 400
CRAWL_CONCURRENCY = 4

IDEAS_SYSTEM = """You are a growth strategist building a programmatic landing-page portfolio for
one software product. Sites in this portfolio may grow to hundreds of pages, so think in
clusters (topic families that share a template) and page types, not one-off pages.

You get: the product wiki, current pages with performance, keyword data, a compact list of
EVERY existing page/idea (never repeat a path or a keyword from it), and competitor research
(positioning + the page types/paths competitors invest in). Use the competitor inventories to
find gaps they cover and we don't, and gaps nobody covers.

Respond with ONLY a JSON object:
{"ideas": [{
  "path": "/kebab-case-route",
  "name": "<short internal name>",
  "headline": "<H1, <=90 chars, states the promise>",
  "angle": "<1-2 sentences: who it's for and why this page wins>",
  "target_keyword": "<primary search phrase, lowercase>",
  "page_type": "home|feature|use_case|persona|industry|comparison|alternative|integration|
template|glossary|guide|pricing|tool|other",
  "cluster": "<topic family, 1-3 words, reuse existing cluster names when it fits>",
  "channel": "seo|paid|social|content|email|community|product|pricing|other",
  "score": <0-100 = search intent x low competition x ICP fit>,
  "rationale": "<why this score, cite competitor/keyword evidence from context; <=200 chars>",
  "brief": "<what the page must contain: sections, proof, CTA, metric that proves it worked>"
}]}
Rules: exactly the requested number of ideas, all distinct, every path new, every
target_keyword new; spread across at least 3 page types; never invent metrics or facts
about the product — only use what the wiki/context states."""


def _norm_path(path: str) -> str:
    path = "/" + str(path).strip().strip("/")
    return re.sub(r"/+", "/", path)[:400]


# ── research ────────────────────────────────────────────────────────────────


async def refresh_research(project_id: UUID, agent: dict) -> dict:
    """Discover competitors if the project has few; recrawl stale ones. Returns a stats dict."""
    config = agent.get("config") or {}
    if config.get("research") is False:
        return {"skipped": True}
    pool = await get_pool()
    max_n = int(config.get("max_competitors") or 10)
    recrawl_days = int(config.get("recrawl_days") or 7)
    stats: dict = {"discovered": 0, "crawled": 0, "mock": False}

    rows = await pool.fetch(
        "SELECT domain FROM competitors WHERE project_id = $1 AND status = 'active'", project_id
    )
    known = [r["domain"] for r in rows]
    last = (config.get("research_state") or {}).get("discovered_at")
    stale = not last or datetime.fromisoformat(last) < datetime.now(UTC) - timedelta(days=30)
    if stale and len(known) < max_n:
        found = await discover_for(project_id, known, max_n - len(known))
        stats["mock"] = found["mock"]
        stats["discovered"] = len(found["competitors"])
        stats["input_tokens"], stats["output_tokens"] = found["tokens"]
        if found["market_notes"]:
            stats["market_notes"] = found["market_notes"]
        if not found["mock"] and agent.get("id"):
            state = {"discovered_at": datetime.now(UTC).isoformat()}
            if found["market_notes"]:
                state["market_notes"] = found["market_notes"]
            await pool.execute(
                """UPDATE agents
                   SET config = config || jsonb_build_object('research_state', $2::jsonb)
                   WHERE id = $1""",
                agent["id"],
                state,
            )

    to_crawl = await pool.fetch(
        """SELECT id, url FROM competitors
           WHERE project_id = $1 AND status = 'active'
             AND (crawled_at IS NULL OR crawled_at < now() - make_interval(days => $2))
           ORDER BY crawled_at NULLS FIRST LIMIT $3""",
        project_id,
        recrawl_days,
        max_n,
    )
    stats["crawled"] = await crawl_many([dict(r) for r in to_crawl])
    return stats


async def discover_for(project_id: UUID, known: list[str], max_n: int) -> dict:
    """Run web-search discovery and insert new competitors (source='agent')."""
    pool = await get_pool()
    project = dict(await pool.fetchrow("SELECT * FROM projects WHERE id = $1", project_id))
    wiki = await _wiki(project_id)
    found = await research.discover(project, wiki, known, max_n=max(1, max_n))
    inserted = []
    for c in found["competitors"]:
        row = await pool.fetchrow(
            """INSERT INTO competitors (project_id, name, domain, url, positioning, pricing,
                                        strengths, weaknesses, source)
               VALUES ($1,$2,$3,$4,$5,$6,$7,$8,'agent')
               ON CONFLICT (project_id, domain) DO NOTHING RETURNING *""",
            project_id,
            c["name"],
            c["domain"],
            c["url"],
            c["positioning"],
            c["pricing"],
            c["strengths"],
            c["weaknesses"],
        )
        if row:
            inserted.append(dict(row))
    found["competitors"] = inserted
    return found


async def crawl_many(rows: list[dict]) -> int:
    sem = asyncio.Semaphore(CRAWL_CONCURRENCY)

    async def one(row: dict) -> None:
        async with sem:
            await crawl_competitor(row["id"], row["url"])

    await asyncio.gather(*(one(r) for r in rows))
    return len(rows)


async def crawl_competitor(competitor_id: UUID, url: str) -> dict:
    result = await research.crawl(url)
    pool = await get_pool()
    row = await pool.fetchrow(
        """UPDATE competitors SET pages = $2, page_count = $3, crawled_at = now(),
                  crawl_error = $4, updated_at = now()
           WHERE id = $1 RETURNING *""",
        competitor_id,
        result["pages"],
        len(result["pages"]),
        result["error"],
    )
    return dict(row)


async def competitor_context(project_id: UUID) -> list[dict]:
    pool = await get_pool()
    rows = await pool.fetch(
        """SELECT name, domain, url, positioning, pricing, strengths, weaknesses, notes,
                  pages, page_count, crawled_at, crawl_error
           FROM competitors WHERE project_id = $1 AND status = 'active'
           ORDER BY page_count DESC, name LIMIT 12""",
        project_id,
    )
    out = []
    for r in rows:
        d = {
            k: r[k] for k in ("name", "domain", "positioning", "pricing", "strengths", "weaknesses")
        }
        if r["notes"]:
            d["notes"] = r["notes"]
        pages = r["pages"] if isinstance(r["pages"], list) else []
        if pages:
            d["site"] = research.inventory_summary(pages, samples_per_type=8)
        elif r["crawl_error"]:
            d["site"] = {"error": r["crawl_error"]}
        out.append(d)
    return out


async def _wiki(project_id: UUID) -> str:
    return await wiki_markdown(project_id, max_chars=6000)


# ── ideas ───────────────────────────────────────────────────────────────────


async def existing_pages(project_id: UUID) -> list[dict]:
    pool = await get_pool()
    rows = await pool.fetch(
        """SELECT path, target_keyword, page_type, cluster, status, score
           FROM landing_pages WHERE project_id = $1
           ORDER BY status, score DESC NULLS LAST LIMIT $2""",
        project_id,
        MAX_CONTEXT_IDEAS,
    )
    return [dict(r) for r in rows]


def _compact(pages: list[dict]) -> list[str]:
    return [
        f"{p['path']} | {p['target_keyword'] or '-'} | {p['page_type']} | "
        f"{p['cluster'] or '-'} | {p['status']} | {p['score'] if p['score'] is not None else '-'}"
        for p in pages
    ]


def _clusters(pages: list[dict]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for p in pages:
        if p["cluster"]:
            counts[p["cluster"]] = counts.get(p["cluster"], 0) + 1
    return dict(sorted(counts.items(), key=lambda kv: -kv[1])[:40])


def _mock_ideas(n: int, existing: list[dict]) -> list[dict]:
    taken = {p["path"] for p in existing}
    out = []
    i = 0
    while len(out) < n and i < n * 3:
        i += 1
        path = f"/ideas/mock-{i}"
        if path in taken:
            continue
        out.append(
            {
                "path": path,
                "name": f"Mock idea {i}",
                "headline": f"Mock landing page {i}",
                "angle": "Generated without ANTHROPIC_API_KEY.",
                "target_keyword": f"mock keyword {i}",
                "page_type": PAGE_TYPES[i % len(PAGE_TYPES)],
                "cluster": "mock",
                "channel": "seo",
                "score": 50,
                "rationale": "mock",
                "brief": "mock",
            }
        )
    return out


def clean_idea(raw: dict) -> dict | None:
    if not isinstance(raw, dict) or not raw.get("path"):
        return None
    path = _norm_path(raw["path"])
    if path == "/":
        return None
    kw = str(raw.get("target_keyword") or "").strip().lower()[:200]
    page_type = raw.get("page_type") if raw.get("page_type") in PAGE_TYPES else "other"
    channel = raw.get("channel") if raw.get("channel") in CHANNELS else "seo"
    try:
        score = max(0, min(100, int(round(float(raw.get("score", 0))))))
    except (TypeError, ValueError):
        score = None
    name = str(raw.get("name") or raw.get("headline") or path.strip("/"))[:160]
    return {
        "path": path,
        "name": name,
        "headline": str(raw.get("headline") or "")[:300],
        "angle": str(raw.get("angle") or "")[:2000],
        "target_keyword": kw,
        "page_type": page_type,
        "cluster": str(raw.get("cluster") or "")[:120],
        "channel": channel,
        "score": score,
        "rationale": str(raw.get("rationale") or "")[:1000],
        "brief": str(raw.get("brief") or "")[:6000],
    }


async def persist_ideas(project_id: UUID, run_id: UUID | None, ideas: list[dict]) -> int:
    pool = await get_pool()
    rows = await pool.fetch(
        "SELECT path, lower(target_keyword) AS kw FROM landing_pages WHERE project_id = $1",
        project_id,
    )
    paths = {r["path"] for r in rows}
    kws = {r["kw"] for r in rows if r["kw"]}
    inserted = 0
    for idea in ideas:
        if idea["path"] in paths or (idea["target_keyword"] and idea["target_keyword"] in kws):
            continue
        res = await pool.execute(
            """INSERT INTO landing_pages
               (project_id, name, path, headline, angle, target_keyword, channel, status,
                page_type, cluster, score, rationale, source, agent_run_id, brief)
               VALUES ($1,$2,$3,$4,$5,$6,$7,'idea',$8,$9,$10,$11,'agent',$12,$13)
               ON CONFLICT (project_id, path) DO NOTHING""",
            project_id,
            idea["name"],
            idea["path"],
            idea["headline"],
            idea["angle"],
            idea["target_keyword"],
            idea["channel"],
            idea["page_type"],
            idea["cluster"],
            idea["score"],
            idea["rationale"],
            run_id,
            idea["brief"],
        )
        if res.endswith("1"):
            inserted += 1
            paths.add(idea["path"])
            if idea["target_keyword"]:
                kws.add(idea["target_keyword"])
    return inserted


async def generate_ideas(agent: dict, ctx: dict, run_id: UUID | None) -> dict:
    """LLM → clean → dedupe → insert. Returns stats for the run record."""
    project_id: UUID = agent["project_id"]
    config = agent.get("config") or {}
    n = max(1, min(MAX_BATCH, int(config.get("batch_size") or DEFAULT_BATCH)))
    existing = await existing_pages(project_id)
    idea_ctx = {
        "project": ctx.get("snapshot", {}).get("project"),
        "wiki": ctx.get("wiki"),
        "current_pages_with_performance": ctx.get("landing_pages", {}).get("pages"),
        "unregistered_paths_with_traffic": ctx.get("landing_pages", {}).get(
            "unregistered_paths_with_traffic"
        ),
        "keywords": ctx.get("landing_pages", {}).get("keywords"),
        "competitors": ctx.get("competitors"),
        "market_notes": ctx.get("market_notes"),
        "alert_templates": ctx.get("alert_templates"),
        "existing_clusters": _clusters(existing),
        "existing_pages_and_ideas (path | keyword | type | cluster | status | score)": _compact(
            existing
        ),
    }
    instr = (agent.get("instructions") or "").strip()
    alerts = ctx.get("alert_templates") or {}
    prompt = (
        f"Produce exactly {n} new landing-page ideas.\n\n"
        + (
            "This product turns use_case ideas into batches of pre-built alerts (see "
            "alert_templates.how_it_works): make at least a third of the ideas use_case THEMES "
            "— each one a family of 10-50 concrete alerts an audience would subscribe to, with "
            "the audience in the angle and the shared trigger in the brief. Favour themes like "
            "the ones with subscribers, avoid themes already generated.\n\n"
            if alerts.get("enabled")
            else ""
        )
        + (f"Operator instructions:\n{instr}\n\n" if instr else "")
        + "Context (JSON):\n```json\n"
        + json.dumps(idea_ctx, default=str)[:90000]
        + "\n```"
    )
    result = await llm.complete(IDEAS_SYSTEM, prompt, max_tokens=8000)
    if result.mock:
        raw = _mock_ideas(min(n, 3), existing)
    else:
        parsed = llm.extract_json(result.text) or {}
        raw = parsed.get("ideas") if isinstance(parsed, dict) else None
        if not isinstance(raw, list):
            raw = []
    ideas = [c for c in (clean_idea(r) for r in raw[: n * 2]) if c]
    # Dedupe inside the batch too.
    seen_p: set[str] = set()
    seen_k: set[str] = set()
    unique = []
    for i in ideas:
        if i["path"] in seen_p or (i["target_keyword"] and i["target_keyword"] in seen_k):
            continue
        seen_p.add(i["path"])
        if i["target_keyword"]:
            seen_k.add(i["target_keyword"])
        unique.append(i)
    inserted = await persist_ideas(project_id, run_id, unique[:n])
    log.info("landing_ideas", project_id=str(project_id), requested=n, inserted=inserted)
    return {
        "requested": n,
        "returned": len(raw),
        "inserted": inserted,
        "mock": result.mock,
        "input_tokens": result.input_tokens,
        "output_tokens": result.output_tokens,
    }
