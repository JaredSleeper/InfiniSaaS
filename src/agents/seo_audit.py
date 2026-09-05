"""Zero-dependency on-page SEO audit: fetches a URL and scores common issues."""

from __future__ import annotations

import re
import time
from html import unescape
from urllib.parse import urljoin, urlparse

import httpx

_TAG = re.compile(r"<[^>]+>")


def _attr(tag: str, name: str) -> str | None:
    m = re.search(rf'{name}\s*=\s*["\']([^"\']*)["\']', tag, re.IGNORECASE)
    return unescape(m.group(1)) if m else None


def _meta(html: str, key: str, value: str) -> str | None:
    for tag in re.findall(r"<meta\b[^>]*>", html, re.IGNORECASE):
        if (_attr(tag, key) or "").lower() == value.lower():
            return _attr(tag, "content")
    return None


async def audit(url: str) -> dict:
    findings: list[dict] = []
    page: dict = {"url": url}

    def add(severity: str, code: str, message: str) -> None:
        findings.append({"severity": severity, "code": code, "message": message})

    t0 = time.monotonic()
    async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
        try:
            r = await client.get(url, headers={"User-Agent": "Mozilla/5.0 infinisaas-seo/1.0"})
        except Exception as exc:  # noqa: BLE001
            return {
                "score": 0,
                "findings": [
                    {"severity": "high", "code": "fetch", "message": f"Fetch failed: {exc}"}
                ],
                "page": page,
            }
        ttfb_ms = int((time.monotonic() - t0) * 1000)
        html = r.text
        page.update(status=r.status_code, final_url=str(r.url), ttfb_ms=ttfb_ms, bytes=len(html))
        if r.status_code >= 400:
            add("high", "status", f"Page returned HTTP {r.status_code}")
        if str(r.url).startswith("http://"):
            add("high", "https", "Page is served over HTTP, not HTTPS")
        if ttfb_ms > 1500:
            add("medium", "ttfb", f"Slow response: {ttfb_ms} ms to first byte")

        origin = f"{urlparse(str(r.url)).scheme}://{urlparse(str(r.url)).netloc}"
        robots_ok = sitemap_ok = None
        try:
            rb = await client.get(urljoin(origin, "/robots.txt"))
            robots_ok = rb.status_code == 200
            sm = await client.get(urljoin(origin, "/sitemap.xml"))
            sitemap_ok = sm.status_code == 200
        except Exception:  # noqa: BLE001, S110
            pass
        page.update(robots_txt=robots_ok, sitemap_xml=sitemap_ok)
        if robots_ok is False:
            add("low", "robots", "No robots.txt at site root")
        if sitemap_ok is False:
            add("medium", "sitemap", "No sitemap.xml at site root")

    title_m = re.search(r"<title[^>]*>(.*?)</title>", html, re.IGNORECASE | re.DOTALL)
    title = unescape(_TAG.sub("", title_m.group(1)).strip()) if title_m else ""
    page["title"] = title
    if not title:
        add("high", "title", "Missing <title>")
    elif len(title) < 20 or len(title) > 65:
        add("medium", "title_length", f"Title is {len(title)} chars (aim for 30–60)")

    desc = _meta(html, "name", "description") or ""
    page["description"] = desc
    if not desc:
        add("high", "description", "Missing meta description")
    elif len(desc) < 70 or len(desc) > 165:
        add("low", "description_length", f"Meta description is {len(desc)} chars (aim 110–160)")

    h1s = re.findall(r"<h1\b[^>]*>(.*?)</h1>", html, re.IGNORECASE | re.DOTALL)
    page["h1"] = [unescape(_TAG.sub("", h).strip()) for h in h1s][:3]
    if not h1s:
        add("high", "h1", "No <h1> on the page")
    elif len(h1s) > 1:
        add("low", "h1_multiple", f"{len(h1s)} <h1> tags (prefer one)")

    canonical = next(
        (
            _attr(t, "href")
            for t in re.findall(r"<link\b[^>]*>", html, re.IGNORECASE)
            if (_attr(t, "rel") or "").lower() == "canonical"
        ),
        None,
    )
    page["canonical"] = canonical
    if not canonical:
        add("medium", "canonical", "No canonical link")

    og_title = _meta(html, "property", "og:title")
    og_image = _meta(html, "property", "og:image")
    page.update(og_title=bool(og_title), og_image=bool(og_image))
    if not og_title:
        add("low", "og_title", "Missing og:title (social previews)")
    if not og_image:
        add("low", "og_image", "Missing og:image (social previews)")

    robots_meta = (_meta(html, "name", "robots") or "").lower()
    if "noindex" in robots_meta:
        add("high", "noindex", "Page has meta robots noindex")

    viewport = _meta(html, "name", "viewport")
    if not viewport:
        add("medium", "viewport", "Missing viewport meta (mobile)")

    imgs = re.findall(r"<img\b[^>]*>", html, re.IGNORECASE)
    no_alt = [i for i in imgs if not _attr(i, "alt")]
    page.update(images=len(imgs), images_without_alt=len(no_alt))
    if no_alt:
        add("low", "img_alt", f"{len(no_alt)} of {len(imgs)} images lack alt text")

    body_m = re.search(r"<body[^>]*>(.*)</body>", html, re.IGNORECASE | re.DOTALL)
    body_text = body_m.group(1) if body_m else html
    body_text = re.sub(
        r"<(script|style|noscript)\b.*?</\1>", " ", body_text, flags=re.IGNORECASE | re.DOTALL
    )
    words = _TAG.sub(" ", body_text).split()
    page["word_count"] = len(words)
    if len(words) < 250:
        add("medium", "thin_content", f"Only ~{len(words)} words of visible text")

    json_ld = "application/ld+json" in html.lower()
    page["structured_data"] = json_ld
    if not json_ld:
        add("low", "schema", "No JSON-LD structured data")

    links = re.findall(r"<a\b[^>]*href=[\"']([^\"'#]+)", html, re.IGNORECASE)
    host = urlparse(str(page.get("final_url", url))).netloc
    internal = [link for link in links if urlparse(urljoin(url, link)).netloc == host]
    page.update(links=len(links), internal_links=len(internal))
    if len(internal) < 3:
        add("low", "internal_links", f"Only {len(internal)} internal links")

    weights = {"high": 15, "medium": 7, "low": 3}
    score = max(0, 100 - sum(weights[f["severity"]] for f in findings))
    return {"score": score, "findings": findings, "page": page}
