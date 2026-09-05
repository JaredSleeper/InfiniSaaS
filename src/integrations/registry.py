from __future__ import annotations

from uuid import UUID

from src.config import settings
from src.db import get_pool

PROVIDERS: dict[str, dict] = {
    "stripe": {
        "label": "Stripe",
        "scope": "project",
        "secret_label": "Restricted API key (read: charges, subscriptions, balance)",
        "config_fields": [],
        "syncs": "Daily revenue + active subscriptions/MRR into metrics",
    },
    "github": {
        "label": "GitHub",
        "scope": "project",
        "secret_label": "Personal access token (repo read)",
        "config_fields": [{"key": "repo", "label": "owner/repo", "required": True}],
        "syncs": "Merged PRs + releases into the release timeline",
    },
    "railway": {
        "label": "Railway",
        "scope": "project",
        "secret_label": "Account/team API token (optional if RAILWAY_API_TOKEN is set)",
        "config_fields": [{"key": "project_id", "label": "Railway project id", "required": True}],
        "syncs": "Service + latest deployment status in the Ops panel",
    },
    "gsc": {
        "label": "Google Search Console",
        "scope": "project",
        "secret_label": "Service-account JSON (add the account as a GSC user)",
        "config_fields": [
            {
                "key": "site_url",
                "label": "Property (e.g. sc-domain:getbetterat.xyz)",
                "required": True,
            },
            {"key": "path_prefix", "label": "Path filter (e.g. /blackjack)", "required": False},
        ],
        "syncs": "Clicks/impressions/CTR/position metrics + top queries for the SEO agent",
    },
    "slack": {
        "label": "Slack",
        "scope": "global",
        "secret_label": "Incoming webhook URL",
        "config_fields": [],
        "syncs": "Weekly briefs and alerts are posted here",
    },
    "custom": {
        "label": "Custom",
        "scope": "project",
        "secret_label": "Any secret",
        "config_fields": [{"key": "note", "label": "What is this?", "required": False}],
        "syncs": "Nothing — reference storage only",
    },
}


def public_row(row) -> dict:
    d = dict(row)
    d["has_secret"] = d.pop("secret_enc", None) is not None
    for k in ("id", "project_id"):
        if d.get(k) is not None:
            d[k] = str(d[k])
    for k in ("created_at", "updated_at", "last_synced_at"):
        if d.get(k) is not None:
            d[k] = d[k].isoformat()
    d["meta"] = PROVIDERS.get(d["provider"], {})
    return d


async def get_integration(provider: str, project_id: UUID | None) -> dict | None:
    pool = await get_pool()
    row = await pool.fetchrow(
        """
        SELECT id, project_id, provider, config, status, status_detail, last_synced_at,
               created_at, updated_at, (secret_enc IS NOT NULL) AS has_secret
        FROM integrations
        WHERE provider = $1 AND project_id IS NOT DISTINCT FROM $2
        """,
        provider,
        project_id,
    )
    return dict(row) if row else None


async def get_secret(provider: str, project_id: UUID | None) -> str | None:
    pool = await get_pool()
    return await pool.fetchval(
        """
        SELECT pgp_sym_decrypt(secret_enc, $3) FROM integrations
        WHERE provider = $1 AND project_id IS NOT DISTINCT FROM $2 AND secret_enc IS NOT NULL
        """,
        provider,
        project_id,
        settings.secrets_key,
    )


async def upsert_integration(
    provider: str, project_id: UUID | None, config: dict, secret: str | None
) -> dict:
    pool = await get_pool()
    if secret:
        row = await pool.fetchrow(
            """
            INSERT INTO integrations (project_id, provider, config, secret_enc)
            VALUES ($1, $2, $3, pgp_sym_encrypt($4, $5))
            ON CONFLICT (project_id, provider) DO UPDATE
                SET config = EXCLUDED.config, secret_enc = EXCLUDED.secret_enc,
                    status = 'unverified', status_detail = '', updated_at = now()
            RETURNING *
            """,
            project_id,
            provider,
            config,
            secret,
            settings.secrets_key,
        )
    else:
        row = await pool.fetchrow(
            """
            INSERT INTO integrations (project_id, provider, config)
            VALUES ($1, $2, $3)
            ON CONFLICT (project_id, provider) DO UPDATE
                SET config = EXCLUDED.config, updated_at = now()
            RETURNING *
            """,
            project_id,
            provider,
            config,
        )
    return public_row(row)


async def set_status(integration_id: UUID, status: str, detail: str = "", synced: bool = False):
    pool = await get_pool()
    await pool.execute(
        """
        UPDATE integrations
        SET status = $2, status_detail = $3,
            last_synced_at = CASE WHEN $4 THEN now() ELSE last_synced_at END,
            updated_at = now()
        WHERE id = $1
        """,
        integration_id,
        status,
        detail[:500],
        synced,
    )
