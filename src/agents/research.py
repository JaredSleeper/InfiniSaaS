"""Competitor research for the landing-page agent.

Two bounded, cacheable steps:
- ``discover``: a web-search-grounded LLM call names direct competitors (domain, positioning,
  pricing) for a project, from its wiki/description.
- ``crawl``: sitemap-first crawl of a competitor site → page inventory ``[{path, title, h1,
  type}]`` with a heuristic page type (comparison, alternative, use_case, …) so the agent can
  see *which kinds* of landing pages competitors invest in, not just how many.
"""

from __future__ import annotations

import asyncio
import re
from collections import Counter
from html import unescape
from urllib.parse import urljoin, urlparse

import httpx

from src.agents import llm

UA = {"User-Agent": "Mozilla/5.0 infinisaas-research/1.0"}
MAX_SITEMAP_URLS = 600
MAX_META_FETCHES = 40
META_CONCURRENCY = 6
CRAWL_TIMEOUT = 45

# Ordered: first match wins. Inventory types are a superset of landing_pages.page_type.
_PATH_RULES: tuple[tuple[re.Pattern[str], str], ...] = tuple(
    (re.compile(p, re.IGNORECASE), t)
    for p, t in (
        (r"^/?$", "home"),
        (
            r"/(blog|news|changelog|release-notes|updates|authors?|tags?|categor(y|ies))(/|$)",
            "blog",
        ),
        (
            r"/(about(-us)?|team|careers|jobs|contact|legal|privacy|terms-of|security|press"
            r"|affiliates?|affiliate-program)(/|$)",
            "company",
        ),
        (r"/(docs|documentation|help|support|api|developers?|reference)(/|$)", "docs"),
        (r"/(pricing|plans)(/|$)", "pricing"),
        (r"/(vs|versus|compare|comparison)(/|$)|-vs-", "comparison"),
        (r"/alternatives?(/|$)|-alternatives?(/|$)", "alternative"),
        (r"/(integrations?|apps|connect|connectors?|plugins?)(/|$)", "integration"),
        (r"/(templates?|examples?|gallery|library|recipes?|playbooks?)(/|$)", "template"),
        (r"/(use-?cases?|solutions?|for|cases?)(/|$)", "use_case"),
        (r"/(industries|industry|verticals?|sectors?)(/|$)", "industry"),
        (r"/(customers?|case-?studies|stories|testimonials|reviews?)(/|$)", "customers"),
        (r"/(glossary|dictionary|what-is|definitions?)(/|$)", "glossary"),
        (r"/(guides?|learn|academy|resources?|tutorials?|how-to|ebooks?|webinars?)(/|$)", "guide"),
        (r"/(tools?|calculators?|generators?|checkers?|free)(/|$)", "tool"),
        (r"/(features?|product|platform|capabilities)(/|$)", "feature"),
        (r"/(login|signin|sign-in|signup|sign-up|register|account|app)(/|$)", "app"),
    )
)

_TAG = re.compile(r"<[^>]+>")
_LOC = re.compile(r"<loc>\s*([^<\s]+)\s*</loc>", re.IGNORECASE)
_HREF = re.compile(r"""<a\b[^>]*\bhref\s*=\s*["']([^"'#]+)["']""", re.IGNORECASE)
_SKIP_EXT = re.compile(
    r"\.(png|jpe?g|gif|svg|webp|ico|css|js|pdf|xml|zip|mp4|woff2?)$", re.IGNORECASE
)


def classify_path(path: str) -> str:
    for rx, kind in _PATH_RULES:
        if rx.search(path):
            return kind
    return "other"


def _norm_path(url: str) -> str:
    path = urlparse(url).path or "/"
    path = re.sub(r"/+", "/", path)
    return path.rstrip("/") or "/"


def _tag_text(html: str, tag: str) -> str | None:
    m = re.search(rf"<{tag}\b[^>]*>(.*?)</{tag}>", html, re.IGNORECASE | re.DOTALL)
    if not m:
        return None
    return unescape(_TAG.sub("", m.group(1))).strip()[:200] or None


def _meta_desc(html: str) -> str | None:
    for tag in re.findall(r"<meta\b[^>]*>", html, re.IGNORECASE):
        if re.search(r"""name\s*=\s*["']description["']""", tag, re.IGNORECASE):
            m = re.search(r"""content\s*=\s*["']([^"']*)["']""", tag, re.IGNORECASE)
            return unescape(m.group(1)).strip()[:300] if m else None
    return None


async def _get(client: httpx.AsyncClient, url: str) -> httpx.Response | None:
    try:
        r = await client.get(url, headers=UA)
    except Exception:  # noqa: BLE001
        return None
    return r if r.status_code < 400 else None


async def _sitemap_urls(client: httpx.AsyncClient, origin: str) -> list[str]:
    candidates = [urljoin(origin, "/sitemap.xml"), urljoin(origin, "/sitemap_index.xml")]
    robots = await _get(client, urljoin(origin, "/robots.txt"))
    if robots is not None:
        for line in robots.text.splitlines():
            if line.lower().startswith("sitemap:"):
                candidates.insert(0, line.split(":", 1)[1].strip())
    seen_maps: set[str] = set()
    urls: list[str] = []
    queue = [c for c in candidates if c]
    while queue and len(urls) < MAX_SITEMAP_URLS and len(seen_maps) < 12:
        sm = queue.pop(0)
        if sm in seen_maps:
            continue
        seen_maps.add(sm)
        r = await _get(client, sm)
        if r is None or "<" not in r.text[:200]:
            continue
        locs = _LOC.findall(r.text)
        if "<sitemapindex" in r.text[:2000].lower():
            queue.extend(locs[:10])
        else:
            urls.extend(locs)
    return urls[:MAX_SITEMAP_URLS]


def _internal_links(html: str, base: str) -> list[str]:
    host = urlparse(base).netloc.lower().removeprefix("www.")
    out: list[str] = []
    for href in _HREF.findall(html):
        url = urljoin(base, href.strip())
        u = urlparse(url)
        if u.scheme not in ("http", "https"):
            continue
        if u.netloc.lower().removeprefix("www.") != host or _SKIP_EXT.search(u.path):
            continue
        out.append(url.split("?")[0])
    return out


async def crawl(url: str) -> dict:
    """Return ``{"pages": [...], "error": ""}``; never raises."""
    origin_p = urlparse(url if url.startswith("http") else f"https://{url}")
    origin = f"{origin_p.scheme}://{origin_p.netloc}"
    pages: dict[str, dict] = {}
    error = ""
    try:
        async with asyncio.timeout(CRAWL_TIMEOUT):
            async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
                urls = await _sitemap_urls(client, origin)
                if not urls:
                    home = await _get(client, origin)
                    if home is None:
                        return {
                            "pages": [],
                            "error": "Site unreachable (no sitemap, homepage failed)",
                        }
                    urls = [origin, *_internal_links(home.text, str(home.url))]
                host = origin_p.netloc.lower().removeprefix("www.")
                for u in urls:
                    if urlparse(u).netloc.lower().removeprefix("www.") != host:
                        continue
                    if _SKIP_EXT.search(urlparse(u).path):
                        continue
                    path = _norm_path(u)
                    pages.setdefault(path, {"path": path, "type": classify_path(path)})
                # Titles/H1s for the most informative pages: marketing types first.
                priority = {
                    "home": 0, "comparison": 1, "alternative": 1, "use_case": 1, "persona": 1,
                    "industry": 1, "integration": 2, "template": 2, "feature": 2, "pricing": 2,
                    "tool": 3, "glossary": 4, "guide": 4, "other": 5,
                }  # fmt: skip
                targets = sorted(
                    (p for p in pages.values() if p["type"] in priority),
                    key=lambda p: (priority[p["type"]], len(p["path"])),
                )[:MAX_META_FETCHES]
                sem = asyncio.Semaphore(META_CONCURRENCY)

                async def enrich(p: dict) -> None:
                    async with sem:
                        r = await _get(client, urljoin(origin, p["path"]))
                    if r is None:
                        return
                    html = r.text[:200_000]
                    title, h1 = _tag_text(html, "title"), _tag_text(html, "h1")
                    desc = _meta_desc(html)
                    if title:
                        p["title"] = title
                    if h1:
                        p["h1"] = h1
                    if desc:
                        p["description"] = desc

                await asyncio.gather(*(enrich(p) for p in targets))
    except TimeoutError:
        error = f"Crawl timed out after {CRAWL_TIMEOUT}s (partial inventory kept)"
    except Exception as exc:  # noqa: BLE001
        error = f"Crawl failed: {exc}"[:300]
    return {"pages": sorted(pages.values(), key=lambda p: p["path"]), "error": error}


def inventory_summary(pages: list[dict], samples_per_type: int = 10) -> dict:
    """Compact, LLM-friendly view of a crawled inventory."""
    counts = Counter(p.get("type", "other") for p in pages)
    samples: dict[str, list[str]] = {}
    # Pages we fetched a title/H1 for are the informative ones; surface those first.
    for p in sorted(pages, key=lambda p: (not (p.get("h1") or p.get("title")), p["path"])):
        t = p.get("type", "other")
        if t in ("blog", "docs", "company", "app"):
            continue
        bucket = samples.setdefault(t, [])
        if len(bucket) < samples_per_type:
            label = p.get("h1") or p.get("title")
            bucket.append(f"{p['path']} — {label}" if label else p["path"])
    return {"total_pages": len(pages), "by_type": dict(counts.most_common()), "samples": samples}


DISCOVER_SYSTEM = """You are a market researcher. Use web search to identify the direct
competitors and closest alternatives of the product described. Prefer products a buyer would
genuinely evaluate side by side; include 1-2 adjacent/indirect players only if the market is
thin. Respond with ONLY a JSON object:
{"competitors": [{"name": "...", "url": "https://...", "positioning": "<1 sentence: who it's
for + core promise>", "pricing": "<known pricing / free tier, or 'unknown'>",
"strengths": "<short>", "weaknesses": "<short>"}],
 "market_notes": "<2-4 sentences: how competitors structure their marketing sites — page types,
angles, keywords they target>"}"""


async def discover(project: dict, wiki: str, known: list[str], max_n: int = 10) -> dict:
    """Web-search-grounded competitor discovery. Returns
    ``{"competitors": [...], "market_notes": str, "mock": bool}``."""
    prompt = (
        f"Product: {project['name']} ({project.get('url') or 'no url'})\n"
        f"Description: {project.get('description') or ''}\n\n"
        + (f"Wiki excerpt:\n{wiki[:3000]}\n\n" if wiki else "")
        + (f"Already known (skip these domains): {', '.join(known)}\n\n" if known else "")
        + f"Find up to {max_n} competitors. Search the web; cite real, currently live products."
    )
    result = await llm.complete(DISCOVER_SYSTEM, prompt, max_tokens=3000, web_searches=8)
    parsed = llm.extract_json(result.text) or {}
    out: list[dict] = []
    for c in parsed.get("competitors", []) if isinstance(parsed, dict) else []:
        if not isinstance(c, dict) or not c.get("url") or not c.get("name"):
            continue
        url = str(c["url"]).strip()
        if not url.startswith("http"):
            url = "https://" + url
        domain = domain_of(url)
        if not domain or domain in known:
            continue
        out.append(
            {
                "name": str(c["name"])[:160],
                "url": url,
                "domain": domain,
                "positioning": str(c.get("positioning") or "")[:600],
                "pricing": str(c.get("pricing") or "")[:400],
                "strengths": str(c.get("strengths") or "")[:600],
                "weaknesses": str(c.get("weaknesses") or "")[:600],
            }
        )
    return {
        "competitors": out[:max_n],
        "market_notes": str(parsed.get("market_notes") or "")[:2000] if parsed else "",
        "mock": result.mock,
        "tokens": (result.input_tokens, result.output_tokens),
    }


_DOMAIN_RE = re.compile(r"^(?:[a-z0-9-]+\.)+[a-z]{2,}(?::\d+)?$")


def domain_of(url: str) -> str:
    """Registrable host of ``url`` (no www.), or "" if it is not a plausible domain."""
    host = (
        urlparse(url.strip() if url.strip().startswith("http") else f"https://{url.strip()}")
        .netloc.lower()
        .removeprefix("www.")
    )
    return host if _DOMAIN_RE.match(host) else ""
