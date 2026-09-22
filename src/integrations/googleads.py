"""Google Ads → ad_spend/ad_metrics sync + offline conversion upload.

Read path: GAQL searchStream pulls per-campaign (into ad_spend) and
per-keyword/search-term (into ad_metrics) stats. Write path: events carrying a
gclid are uploaded as offline click conversions so Smart Bidding optimizes on
real product outcomes, not clicks.
"""

from __future__ import annotations

import json
from datetime import date
from uuid import UUID

import httpx

from src.db import get_pool

TOKEN_URL = "https://oauth2.googleapis.com/token"
API_BASE = "https://googleads.googleapis.com/v18"
SYNC_DAYS = 30


def _creds(secret_json: str) -> dict:
    """Secret blob: {"client_id","client_secret","refresh_token","developer_token"}."""
    c = json.loads(secret_json)
    missing = [
        k
        for k in ("client_id", "client_secret", "refresh_token", "developer_token")
        if not c.get(k)
    ]
    if missing:
        raise RuntimeError(f"Secret JSON missing keys: {', '.join(missing)}")
    return c


def _customer(cfg: dict) -> str:
    cid = str(cfg.get("customer_id") or "").replace("-", "").strip()
    if not cid.isdigit():
        raise RuntimeError("config.customer_id must be the 10-digit Google Ads customer ID")
    return cid


async def _access_token(creds: dict) -> str:
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.post(
            TOKEN_URL,
            data={
                "grant_type": "refresh_token",
                "client_id": creds["client_id"],
                "client_secret": creds["client_secret"],
                "refresh_token": creds["refresh_token"],
            },
        )
        if r.status_code != 200:
            raise RuntimeError(f"OAuth refresh failed: {r.text[:300]}")
        return r.json()["access_token"]


async def _search_stream(token: str, creds: dict, cfg: dict, gaql: str) -> list[dict]:
    cid = _customer(cfg)
    headers = {
        "Authorization": f"Bearer {token}",
        "developer-token": creds["developer_token"],
    }
    login = str(cfg.get("login_customer_id") or "").replace("-", "").strip()
    if login:
        headers["login-customer-id"] = login
    async with httpx.AsyncClient(timeout=120) as client:
        r = await client.post(
            f"{API_BASE}/customers/{cid}/googleAds:searchStream",
            headers=headers,
            json={"query": gaql},
        )
        if r.status_code != 200:
            raise RuntimeError(f"GAQL failed ({r.status_code}): {r.text[:400]}")
        results: list[dict] = []
        for chunk in r.json():
            results.extend(chunk.get("results", []))
        return results


def _micros(v) -> float:
    return round(int(v or 0) / 1_000_000, 4)


CAMPAIGN_GAQL = """
SELECT segments.date, campaign.id, campaign.name, campaign.status,
       metrics.cost_micros, metrics.impressions, metrics.clicks, metrics.conversions
FROM campaign
WHERE segments.date DURING LAST_30_DAYS
"""

KEYWORD_GAQL = """
SELECT segments.date, campaign.id, ad_group.id, ad_group.name,
       ad_group_criterion.keyword.text,
       metrics.cost_micros, metrics.impressions, metrics.clicks, metrics.conversions
FROM keyword_view
WHERE segments.date DURING LAST_30_DAYS
"""

SEARCH_TERM_GAQL = """
SELECT segments.date, campaign.id, search_term_view.search_term,
       metrics.cost_micros, metrics.impressions, metrics.clicks, metrics.conversions
FROM search_term_view
WHERE segments.date DURING LAST_30_DAYS
"""


async def _upsert_campaign(project_id: UUID, google_id: str, name: str, status: str) -> UUID:
    """Get-or-create the cockpit campaign row for a Google Ads campaign."""
    pool = await get_pool()
    external = f"gads:{google_id}"
    row = await pool.fetchrow(
        "SELECT id FROM campaigns WHERE project_id = $1 AND external_id = $2",
        project_id,
        external,
    )
    if row:
        return row["id"]
    row = await pool.fetchrow(
        """INSERT INTO campaigns (project_id, name, channel, status, url, external_id)
           VALUES ($1, $2, 'paid', $3, NULL, $4)
           ON CONFLICT DO NOTHING RETURNING id""",
        project_id,
        name,
        "active" if status == "ENABLED" else "paused",
        external,
    )
    if row:
        return row["id"]
    return await pool.fetchval(
        "SELECT id FROM campaigns WHERE project_id = $1 AND external_id = $2",
        project_id,
        external,
    )


async def _sync_campaigns(project_id: UUID, rows: list[dict]) -> int:
    pool = await get_pool()
    n = 0
    for r in rows:
        seg, camp, m = r.get("segments", {}), r.get("campaign", {}), r.get("metrics", {})
        day = date.fromisoformat(seg["date"])
        campaign_id = await _upsert_campaign(
            project_id,
            camp["id"],
            camp.get("name") or f"Google campaign {camp['id']}",
            camp.get("status", "ENABLED"),
        )
        await pool.execute(
            """INSERT INTO ad_spend
                   (project_id, campaign_id, platform, day, spend, impressions, clicks,
                    conversions, source)
               VALUES ($1, $2, 'google', $3, $4, $5, $6, $7, 'google_ads')
               ON CONFLICT (project_id, platform, campaign_id, day) DO UPDATE
                   SET spend = EXCLUDED.spend, impressions = EXCLUDED.impressions,
                       clicks = EXCLUDED.clicks, conversions = EXCLUDED.conversions,
                       source = 'google_ads'""",
            project_id,
            campaign_id,
            day,
            _micros(m.get("costMicros")),
            int(m.get("impressions", 0)),
            int(m.get("clicks", 0)),
            int(float(m.get("conversions", 0))),
        )
        n += 1
    return n


async def _sync_metrics(
    project_id: UUID, campaign_map: dict[str, UUID], rows: list[dict], level: str
) -> int:
    pool = await get_pool()
    n = 0
    for r in rows:
        seg, m = r.get("segments", {}), r.get("metrics", {})
        day = date.fromisoformat(seg["date"])
        gcid = str(r.get("campaign", {}).get("id", ""))
        if level == "keyword":
            kw = r.get("adGroupCriterion", {}).get("keyword", {}).get("text", "")
            gid = str(r.get("adGroup", {}).get("id", ""))
            ext = f"kw:{gid}:{kw}"
            name = kw
        else:  # search_term
            term = r.get("searchTermView", {}).get("searchTerm", "")
            ext = f"st:{gcid}:{term}"
            name = term
            gid = ""
        await pool.execute(
            """INSERT INTO ad_metrics
                   (project_id, campaign_id, level, external_campaign_id,
                    external_ad_group_id, external_id, name, day,
                    spend, impressions, clicks, conversions)
               VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12)
               ON CONFLICT (project_id, platform, level, external_id, day) DO UPDATE
                   SET campaign_id = EXCLUDED.campaign_id, name = EXCLUDED.name,
                       spend = EXCLUDED.spend, impressions = EXCLUDED.impressions,
                       clicks = EXCLUDED.clicks, conversions = EXCLUDED.conversions""",
            project_id,
            campaign_map.get(gcid),
            level,
            gcid,
            gid,
            ext,
            name,
            day,
            _micros(m.get("costMicros")),
            int(m.get("impressions", 0)),
            int(m.get("clicks", 0)),
            float(m.get("conversions", 0)),
        )
        n += 1
    return n


async def _upload_click_conversion(headers: dict, cid: str, conv: dict) -> dict:
    async with httpx.AsyncClient(timeout=60) as client:
        r = await client.post(
            f"{API_BASE}/customers/{cid}:uploadClickConversions",
            headers=headers,
            json={"conversions": [conv], "partialFailure": True},
        )
    if r.status_code != 200:
        raise RuntimeError(f"Conversion upload failed ({r.status_code}): {r.text[:300]}")
    return r.json()


def _action_name(cfg: dict, cid: str, key: str) -> str | None:
    action = str(cfg.get(key) or "").strip()
    if not action:
        return None
    if "/" not in action:  # bare numeric id
        return f"customers/{cid}/conversionActions/{action}"
    return action


async def _upload_conversions(project_id: UUID, token: str, creds: dict, cfg: dict) -> dict:
    """Upload gclid-carrying monitor_created / signup_completed events once."""
    pool = await get_pool()
    cid = _customer(cfg)
    actions = {
        "monitor_created": _action_name(cfg, cid, "conv_action_monitor_created"),
        "signup_completed": _action_name(cfg, cid, "conv_action_signup_completed"),
    }
    actions = {e: a for e, a in actions.items() if a}
    if not actions:
        return {"uploaded": 0, "note": "no conversion actions configured"}
    events = await pool.fetch(
        """SELECT e.id, e.name, e.ts, e.properties->>'gclid' AS gclid
           FROM events e
           WHERE e.project_id = $1 AND e.name = ANY($2)
             AND e.properties->>'gclid' IS NOT NULL
             AND e.properties->>'gclid' <> ''
             AND e.ts > now() - interval '90 days'
             AND NOT EXISTS (
                 SELECT 1 FROM conversion_uploads u
                 WHERE u.project_id = e.project_id AND u.gclid = e.properties->>'gclid'
                   AND u.event_name = e.name)
           ORDER BY e.ts LIMIT 2000""",
        project_id,
        list(actions),
    )
    if not events:
        return {"uploaded": 0}
    headers = {
        "Authorization": f"Bearer {token}",
        "developer-token": creds["developer_token"],
    }
    login = str(cfg.get("login_customer_id") or "").replace("-", "").strip()
    if login:
        headers["login-customer-id"] = login
    uploaded = 0
    batch: list[dict] = []
    for ev in events:
        conv = {
            "gclid": ev["gclid"],
            "conversionAction": actions[ev["name"]],
            "conversionDateTime": ev["ts"].strftime("%Y-%m-%d %H:%M:%S+00:00"),
        }
        body = await _upload_click_conversion(headers, cid, conv)
        err = (body.get("partialFailureError") or {}).get("message")
        if err and "DUPLICATE" not in err.upper() and "already been uploaded" not in err.lower():
            batch.append({"event": ev["name"], "gclid": ev["gclid"][:20], "error": err})
            continue
        await pool.execute(
            """INSERT INTO conversion_uploads
                   (project_id, gclid, conversion_action_id, event_name, conversion_ts)
               VALUES ($1, $2, $3, $4, $5)
               ON CONFLICT (project_id, gclid, event_name) DO NOTHING""",
            project_id,
            ev["gclid"],
            actions[ev["name"]].rsplit("/", 1)[-1],
            ev["name"],
            ev["ts"],
        )
        uploaded += 1
    result: dict = {"uploaded": uploaded}
    if batch:
        result["errors"] = batch[:20]
    return result


async def verify(cfg: dict, secret_json: str) -> str:
    creds = _creds(secret_json)
    token = await _access_token(creds)
    rows = await _search_stream(
        token,
        creds,
        cfg,
        "SELECT campaign.id, campaign.name FROM campaign LIMIT 5",
    )
    names = [r.get("campaign", {}).get("name", "?") for r in rows]
    return f"Connected to {_customer(cfg)} ({len(rows)} campaigns: {', '.join(names) or 'none'})"


async def sync(project_id: UUID, cfg: dict, secret_json: str) -> dict:
    creds = _creds(secret_json)
    token = await _access_token(creds)

    camp_rows = await _search_stream(token, creds, cfg, CAMPAIGN_GAQL)
    campaign_map: dict[str, UUID] = {}
    for r in camp_rows:
        camp = r.get("campaign", {})
        campaign_map[str(camp["id"])] = await _upsert_campaign(
            project_id, camp["id"], camp.get("name") or "", camp.get("status", "ENABLED")
        )
    n_camps = await _sync_campaigns(project_id, camp_rows)

    kw_rows = await _search_stream(token, creds, cfg, KEYWORD_GAQL)
    n_kw = await _sync_metrics(project_id, campaign_map, kw_rows, "keyword")
    st_rows = await _search_stream(token, creds, cfg, SEARCH_TERM_GAQL)
    n_st = await _sync_metrics(project_id, campaign_map, st_rows, "search_term")

    conv = await _upload_conversions(project_id, token, creds, cfg)
    return {
        "campaign_days": n_camps,
        "keyword_days": n_kw,
        "search_term_days": n_st,
        "conversions_uploaded": conv.get("uploaded", 0),
        **({"conversion_errors": conv["errors"]} if conv.get("errors") else {}),
        **({"note": conv["note"]} if conv.get("note") else {}),
    }
