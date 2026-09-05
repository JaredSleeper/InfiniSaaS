"""Google Search Console (service account) → SEO metrics + top queries."""

from __future__ import annotations

import json
import time
from datetime import UTC, date, datetime, timedelta
from urllib.parse import quote
from uuid import UUID

import httpx
import jwt

from src.db import get_pool
from src.services.metrics import ensure_metric, replace_points

TOKEN_URL = "https://oauth2.googleapis.com/token"
SCOPE = "https://www.googleapis.com/auth/webmasters.readonly"


async def _access_token(sa_json: str) -> str:
    sa = json.loads(sa_json)
    now = int(time.time())
    assertion = jwt.encode(
        {
            "iss": sa["client_email"],
            "scope": SCOPE,
            "aud": TOKEN_URL,
            "iat": now,
            "exp": now + 3600,
        },
        sa["private_key"],
        algorithm="RS256",
    )
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.post(
            TOKEN_URL,
            data={
                "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
                "assertion": assertion,
            },
        )
        r.raise_for_status()
        return r.json()["access_token"]


async def _query(token: str, site_url: str, body: dict) -> list[dict]:
    site = quote(site_url, safe="")
    url = f"https://www.googleapis.com/webmasters/v3/sites/{site}/searchAnalytics/query"
    async with httpx.AsyncClient(timeout=60) as client:
        r = await client.post(url, headers={"Authorization": f"Bearer {token}"}, json=body)
        r.raise_for_status()
        return r.json().get("rows", [])


def _filters(path_prefix: str | None) -> list[dict]:
    if not path_prefix:
        return []
    return [{"filters": [{"dimension": "page", "operator": "contains", "expression": path_prefix}]}]


async def verify(sa_json: str, site_url: str) -> str:
    token = await _access_token(sa_json)
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.get(
            "https://www.googleapis.com/webmasters/v3/sites",
            headers={"Authorization": f"Bearer {token}"},
        )
        r.raise_for_status()
        sites = {s["siteUrl"] for s in r.json().get("siteEntry", [])}
    if site_url not in sites:
        raise RuntimeError(f"Service account has no access to {site_url}. Visible: {sorted(sites)}")
    return f"Connected to {site_url}"


async def sync(project_id: UUID, sa_json: str, site_url: str, path_prefix: str | None) -> dict:
    token = await _access_token(sa_json)
    end = date.today() - timedelta(days=2)  # GSC data lags ~2 days
    start = end - timedelta(days=90)
    daily = await _query(
        token,
        site_url,
        {
            "startDate": start.isoformat(),
            "endDate": end.isoformat(),
            "dimensions": ["date"],
            "dimensionFilterGroups": _filters(path_prefix),
            "rowLimit": 1000,
        },
    )
    queries = await _query(
        token,
        site_url,
        {
            "startDate": (end - timedelta(days=28)).isoformat(),
            "endDate": end.isoformat(),
            "dimensions": ["query", "page"],
            "dimensionFilterGroups": _filters(path_prefix),
            "rowLimit": 200,
        },
    )

    pool = await get_pool()
    defs = {
        "gsc_clicks": ("Search clicks", "", "counter", False),
        "gsc_impressions": ("Search impressions", "", "counter", False),
        "gsc_ctr": ("Search CTR", "%", "gauge", False),
        "gsc_position": ("Avg. position", "", "gauge", False),
    }
    ids = {k: await ensure_metric(pool, project_id, k, *v) for k, v in defs.items()}
    pts = {k: [] for k in defs}
    for row in daily:
        ts = datetime.fromisoformat(row["keys"][0]).replace(hour=12, tzinfo=UTC)
        pts["gsc_clicks"].append((ts, float(row["clicks"])))
        pts["gsc_impressions"].append((ts, float(row["impressions"])))
        pts["gsc_ctr"].append((ts, round(float(row["ctr"]) * 100, 2)))
        pts["gsc_position"].append((ts, round(float(row["position"]), 1)))
    for k, points in pts.items():
        await replace_points(pool, ids[k], "gsc", points, since_days=93)

    async with pool.acquire() as conn, conn.transaction():
        await conn.execute(
            "DELETE FROM seo_keywords WHERE project_id = $1 AND source = 'gsc'", project_id
        )
        await conn.executemany(
            """
            INSERT INTO seo_keywords
                (project_id, keyword, target_url, source, clicks, impressions, ctr, position,
                 checked_at)
            VALUES ($1, $2, $3, 'gsc', $4, $5, $6, $7, now())
            ON CONFLICT (project_id, keyword) DO UPDATE
                SET target_url = EXCLUDED.target_url, source = 'gsc',
                    clicks = EXCLUDED.clicks, impressions = EXCLUDED.impressions,
                    ctr = EXCLUDED.ctr, position = EXCLUDED.position, checked_at = now()
            """,
            [
                (
                    project_id,
                    r["keys"][0][:200],
                    r["keys"][1],
                    int(r["clicks"]),
                    int(r["impressions"]),
                    round(float(r["ctr"]) * 100, 2),
                    round(float(r["position"]), 1),
                )
                for r in queries
            ],
        )
    return {"days": len(daily), "queries": len(queries)}
