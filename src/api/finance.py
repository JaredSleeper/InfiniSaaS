from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

from fastapi import APIRouter, Query

from src.api.crud import make_router
from src.api.projects import require_project
from src.db import get_pool
from src.models import AdSpendIn, AdSpendOut, CostCreate, CostOut, CostUpdate
from src.services.metrics import last_value, series, window_sum

costs_router = make_router(
    "costs",
    CostCreate,
    CostUpdate,
    CostOut,
    order_by="period_start DESC",
    filters=("category",),
    has_updated_at=False,
)

ads_router = APIRouter()
router = APIRouter()


@ads_router.get("", response_model=list[AdSpendOut])
async def list_ad_spend(
    project_id: UUID | None = Query(default=None),
    days: int = Query(default=90, ge=1, le=730),
) -> list[AdSpendOut]:
    pool = await get_pool()
    rows = await pool.fetch(
        """
        SELECT * FROM ad_spend
        WHERE ($1::uuid IS NULL OR project_id = $1)
          AND day > current_date - make_interval(days => $2)
        ORDER BY day DESC, platform
        """,
        project_id,
        days,
    )
    return [AdSpendOut(**dict(r)) for r in rows]


@ads_router.post("/projects/{project_id}", response_model=AdSpendOut, status_code=201)
async def upsert_ad_spend(project_id: UUID, body: AdSpendIn) -> AdSpendOut:
    await require_project(project_id)
    pool = await get_pool()
    row = await pool.fetchrow(
        """
        INSERT INTO ad_spend
            (project_id, campaign_id, platform, day, spend, impressions, clicks, conversions)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
        ON CONFLICT (project_id, platform, campaign_id, day) DO UPDATE
            SET spend = EXCLUDED.spend, impressions = EXCLUDED.impressions,
                clicks = EXCLUDED.clicks, conversions = EXCLUDED.conversions
        RETURNING *
        """,
        project_id,
        body.campaign_id,
        body.platform,
        body.day,
        body.spend,
        body.impressions,
        body.clicks,
        body.conversions,
    )
    return AdSpendOut(**dict(row))


@ads_router.delete("/{row_id}", status_code=204)
async def delete_ad_spend(row_id: int) -> None:
    pool = await get_pool()
    await pool.execute("DELETE FROM ad_spend WHERE id = $1", row_id)


async def finance_summary(project_id: UUID, days: int = 30) -> dict:
    await require_project(project_id)
    pool = await get_pool()
    now = datetime.now(UTC)
    start = now - timedelta(days=days)
    prev_start = start - timedelta(days=days)

    revenue = await series(pool, project_id, "revenue", days * 2 + 1)
    rev_cur = window_sum(revenue, start, now)
    rev_prev = window_sum(revenue, prev_start, start)
    mrr = last_value(await series(pool, project_id, "mrr", 400))
    subs = last_value(await series(pool, project_id, "active_subscriptions", 400))
    signups = window_sum(await series(pool, project_id, "signups", days + 1), start, now)

    cost_rows = await pool.fetch(
        """
        SELECT category, sum(amount) AS total FROM costs
        WHERE project_id = $1 AND period_end >= $2::date AND period_start <= $3::date
        GROUP BY category
        """,
        project_id,
        start.date(),
        now.date(),
    )
    costs_by_cat = {r["category"]: float(r["total"]) for r in cost_rows}
    ads = await pool.fetchrow(
        """
        SELECT coalesce(sum(spend), 0) AS spend, coalesce(sum(clicks), 0) AS clicks,
               coalesce(sum(impressions), 0) AS impressions,
               coalesce(sum(conversions), 0) AS conversions
        FROM ad_spend WHERE project_id = $1 AND day > current_date - make_interval(days => $2)
        """,
        project_id,
        days,
    )
    ad_spend = float(ads["spend"])
    total_costs = sum(costs_by_cat.values()) + ad_spend
    conversions = int(ads["conversions"])
    return {
        "days": days,
        "revenue": round(rev_cur, 2),
        "revenue_prev": round(rev_prev, 2),
        "mrr": mrr,
        "active_subscriptions": subs,
        "signups": signups,
        "costs_by_category": costs_by_cat,
        "ad_spend": round(ad_spend, 2),
        "ad_clicks": int(ads["clicks"]),
        "ad_impressions": int(ads["impressions"]),
        "ad_conversions": conversions,
        "total_costs": round(total_costs, 2),
        "net": round(rev_cur - total_costs, 2),
        "margin_pct": round((rev_cur - total_costs) / rev_cur * 100, 1) if rev_cur else None,
        "cac": round(ad_spend / conversions, 2) if conversions else None,
        "roas": round(rev_cur / ad_spend, 2) if ad_spend else None,
        "cpc": round(ad_spend / int(ads["clicks"]), 2) if ads["clicks"] else None,
        "arpu": round(mrr / subs, 2) if mrr and subs else None,
    }


@router.get("")
async def finance(project_id: UUID, days: int = Query(default=30, ge=7, le=365)) -> dict:
    return await finance_summary(project_id, days)


@router.get("/portfolio")
async def portfolio_finance(days: int = Query(default=30, ge=7, le=365)) -> dict:
    pool = await get_pool()
    projects = await pool.fetch("SELECT id, name, slug, accent_color FROM projects ORDER BY name")
    rows = []
    for p in projects:
        summary = await finance_summary(p["id"], days)
        rows.append(
            {
                "project_id": str(p["id"]),
                "name": p["name"],
                "slug": p["slug"],
                "accent_color": p["accent_color"],
                **summary,
            }
        )
    return {
        "days": days,
        "projects": rows,
        "totals": {
            "revenue": round(sum(r["revenue"] for r in rows), 2),
            "mrr": round(sum(r["mrr"] or 0 for r in rows), 2),
            "total_costs": round(sum(r["total_costs"] for r in rows), 2),
            "ad_spend": round(sum(r["ad_spend"] for r in rows), 2),
            "net": round(sum(r["net"] for r in rows), 2),
        },
    }
