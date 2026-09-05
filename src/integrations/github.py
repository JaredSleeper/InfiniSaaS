"""GitHub → releases timeline: merged PRs on the default branch + published releases."""

from __future__ import annotations

from uuid import UUID

import httpx

from src.db import get_pool

API = "https://api.github.com"


def _client(token: str | None) -> httpx.AsyncClient:
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "infinisaas"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return httpx.AsyncClient(headers=headers, timeout=30)


async def verify(repo: str, token: str | None) -> str:
    async with _client(token) as client:
        r = await client.get(f"{API}/repos/{repo}")
        r.raise_for_status()
        return f"Connected to {r.json().get('full_name')}"


async def sync(project_id: UUID, repo: str, token: str | None) -> dict:
    async with _client(token) as client:
        prs = await client.get(
            f"{API}/repos/{repo}/pulls",
            params={"state": "closed", "sort": "updated", "direction": "desc", "per_page": 50},
        )
        prs.raise_for_status()
        rels = await client.get(f"{API}/repos/{repo}/releases", params={"per_page": 30})
        rels.raise_for_status()

    rows = []
    for pr in prs.json():
        if not pr.get("merged_at"):
            continue
        rows.append(
            (
                project_id,
                f"PR #{pr['number']}: {pr['title']}",
                (pr.get("body") or "")[:4000],
                pr["html_url"],
                f"pr-{pr['number']}",
                pr["merged_at"],
            )
        )
    for rel in rels.json():
        if rel.get("draft"):
            continue
        rows.append(
            (
                project_id,
                rel.get("name") or rel.get("tag_name"),
                (rel.get("body") or "")[:4000],
                rel["html_url"],
                f"release-{rel['id']}",
                rel.get("published_at") or rel.get("created_at"),
            )
        )

    pool = await get_pool()
    async with pool.acquire() as conn, conn.transaction():
        await conn.executemany(
            """
            INSERT INTO releases (project_id, title, body, url, external_id, source, released_at)
            VALUES ($1, $2, $3, $4, $5, 'github', $6::timestamptz)
            ON CONFLICT (project_id, source, external_id) WHERE external_id IS NOT NULL
            DO UPDATE SET title = EXCLUDED.title, body = EXCLUDED.body, url = EXCLUDED.url
            """,
            rows,
        )
    return {"releases_synced": len(rows)}
