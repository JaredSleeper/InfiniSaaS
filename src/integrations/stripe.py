"""Stripe → metrics: daily gross revenue (last 90 days), MRR, active subscriptions."""

from __future__ import annotations

import time
from collections import defaultdict
from datetime import UTC, datetime
from uuid import UUID

import httpx

from src.db import get_pool
from src.services.metrics import ensure_metric, replace_points

API = "https://api.stripe.com/v1"
_INTERVAL_MONTHS = {"day": 1 / 30, "week": 1 / 4.33, "month": 1, "year": 12}


async def _paginate(client: httpx.AsyncClient, path: str, params: dict) -> list[dict]:
    out: list[dict] = []
    params = {**params, "limit": 100}
    while True:
        r = await client.get(f"{API}{path}", params=params)
        r.raise_for_status()
        body = r.json()
        out.extend(body.get("data", []))
        if not body.get("has_more") or not out:
            return out
        params["starting_after"] = out[-1]["id"]


async def verify(secret: str) -> str:
    async with httpx.AsyncClient(auth=(secret, ""), timeout=30) as client:
        r = await client.get(f"{API}/balance")
        r.raise_for_status()
        return "Connected"


async def sync(project_id: UUID, secret: str, days: int = 90) -> dict:
    since = int(time.time()) - days * 86400
    async with httpx.AsyncClient(auth=(secret, ""), timeout=60) as client:
        txns = await _paginate(
            client,
            "/balance_transactions",
            {"created[gte]": since, "type[]": "charge"},
        )
        refunds = await _paginate(
            client, "/balance_transactions", {"created[gte]": since, "type[]": "refund"}
        )
        subs = await _paginate(client, "/subscriptions", {"status": "active"})

    daily: dict[str, float] = defaultdict(float)
    for t in txns + refunds:
        day = datetime.fromtimestamp(t["created"], tz=UTC).date().isoformat()
        daily[day] += t["amount"] / 100.0

    mrr = 0.0
    for s in subs:
        for item in s.get("items", {}).get("data", []):
            price = item.get("price") or {}
            rec = price.get("recurring") or {}
            months = _INTERVAL_MONTHS.get(rec.get("interval"), 1) * (rec.get("interval_count") or 1)
            mrr += (price.get("unit_amount") or 0) / 100.0 * (item.get("quantity") or 1) / months

    pool = await get_pool()
    revenue_id = await ensure_metric(pool, project_id, "revenue", "Revenue", "$", "currency", True)
    mrr_id = await ensure_metric(pool, project_id, "mrr", "MRR", "$", "currency", False)
    subs_id = await ensure_metric(
        pool, project_id, "active_subscriptions", "Active subscriptions", "", "gauge", False
    )
    points = [
        (datetime.fromisoformat(d).replace(hour=12, tzinfo=UTC), v)
        for d, v in sorted(daily.items())
    ]
    await replace_points(pool, revenue_id, "stripe", points, since_days=days)
    now = datetime.now(UTC)
    await replace_points(pool, mrr_id, "stripe", [(now, round(mrr, 2))], since_days=0)
    await replace_points(pool, subs_id, "stripe", [(now, float(len(subs)))], since_days=0)
    return {
        "days_with_revenue": len(daily),
        "mrr": round(mrr, 2),
        "active_subscriptions": len(subs),
    }
