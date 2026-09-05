from __future__ import annotations

import httpx

from src.integrations.registry import get_secret


async def post(text: str, blocks: list[dict] | None = None) -> bool:
    webhook = await get_secret("slack", None)
    if not webhook:
        return False
    payload: dict = {"text": text}
    if blocks:
        payload["blocks"] = blocks
    async with httpx.AsyncClient(timeout=20) as client:
        r = await client.post(webhook, json=payload)
        r.raise_for_status()
    return True


async def verify(webhook: str) -> str:
    async with httpx.AsyncClient(timeout=20) as client:
        r = await client.post(webhook, json={"text": "InfiniSaaS connected to this channel."})
        r.raise_for_status()
    return "Test message sent"
