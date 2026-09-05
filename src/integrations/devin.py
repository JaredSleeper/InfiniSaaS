"""Devin API client. Runs in mock mode when no API key is configured so the UI still works."""

from __future__ import annotations

import uuid

import httpx

from src.config import settings


class DevinNotConfigured(RuntimeError):
    pass


def configured() -> bool:
    return bool(settings.devin_api_key)


def _headers() -> dict:
    return {"Authorization": f"Bearer {settings.devin_api_key}"}


async def create_session(prompt: str, title: str, tags: list[str]) -> dict:
    if not configured():
        sid = f"mock-{uuid.uuid4().hex[:12]}"
        return {"session_id": sid, "url": f"https://app.devin.ai/sessions/{sid}", "mock": True}
    async with httpx.AsyncClient(timeout=60) as client:
        r = await client.post(
            f"{settings.devin_api_base}/sessions",
            headers=_headers(),
            json={"prompt": prompt, "title": title[:120], "tags": tags[:10]},
        )
        if r.status_code >= 400:
            raise RuntimeError(f"Devin API {r.status_code}: {r.text[:300]}")
        body = r.json()
        return {"session_id": body["session_id"], "url": body["url"], "mock": False}


async def get_session(session_id: str) -> dict:
    if not configured() or session_id.startswith("mock-"):
        return {"status": "mock", "pr_url": None, "title": None}
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.get(f"{settings.devin_api_base}/sessions/{session_id}", headers=_headers())
        if r.status_code >= 400:
            raise RuntimeError(f"Devin API {r.status_code}: {r.text[:300]}")
        body = r.json()
    pr = body.get("pull_request") or {}
    return {
        "status": body.get("status_enum") or body.get("status") or "unknown",
        "pr_url": pr.get("url") if isinstance(pr, dict) else None,
        "title": body.get("title"),
    }


async def send_message(session_id: str, message: str) -> None:
    if not configured() or session_id.startswith("mock-"):
        return
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.post(
            f"{settings.devin_api_base}/sessions/{session_id}/message",
            headers=_headers(),
            json={"message": message},
        )
        if r.status_code >= 400:
            raise RuntimeError(f"Devin API {r.status_code}: {r.text[:300]}")
