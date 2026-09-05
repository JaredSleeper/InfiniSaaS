from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, HTTPException

from src.api.projects import require_project
from src.db import get_pool
from src.errors import safe_error
from src.integrations import github, gsc, railway, registry, slack, stripe
from src.integrations.registry import PROVIDERS
from src.models import IntegrationOut, IntegrationUpsert, Provider

router = APIRouter()


@router.get("/providers")
async def providers() -> dict:
    return PROVIDERS


@router.get("", response_model=list[IntegrationOut])
async def list_integrations() -> list[IntegrationOut]:
    pool = await get_pool()
    rows = await pool.fetch("SELECT * FROM integrations ORDER BY provider, created_at")
    return [IntegrationOut(**registry.public_row(r)) for r in rows]


@router.put("/{provider}", response_model=IntegrationOut)
async def upsert(provider: Provider, body: IntegrationUpsert) -> IntegrationOut:
    meta = PROVIDERS[provider]
    if meta["scope"] == "project" and body.project_id is None:
        raise HTTPException(status_code=400, detail=f"{meta['label']} is configured per project")
    if meta["scope"] == "global":
        body.project_id = None
    if body.project_id:
        await require_project(body.project_id)
    for f in meta["config_fields"]:
        if f["required"] and not body.config.get(f["key"]):
            raise HTTPException(status_code=400, detail=f"Missing config: {f['label']}")
    row = await registry.upsert_integration(provider, body.project_id, body.config, body.secret)
    return IntegrationOut(**row)


@router.delete("/{integration_id}", status_code=204)
async def delete(integration_id: UUID) -> None:
    pool = await get_pool()
    res = await pool.execute("DELETE FROM integrations WHERE id = $1", integration_id)
    if res.endswith("0"):
        raise HTTPException(status_code=404, detail="Integration not found")


async def _load(integration_id: UUID) -> tuple[dict, str | None]:
    pool = await get_pool()
    row = await pool.fetchrow("SELECT * FROM integrations WHERE id = $1", integration_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Integration not found")
    secret = await registry.get_secret(row["provider"], row["project_id"])
    return dict(row), secret


async def _run(integration_id: UUID, action: str) -> dict:
    row, secret = await _load(integration_id)
    provider, cfg, pid = row["provider"], row["config"], row["project_id"]
    try:
        if provider == "stripe":
            if not secret:
                raise RuntimeError("No Stripe key stored")
            result = (
                await stripe.verify(secret)
                if action == "verify"
                else await stripe.sync(pid, secret)
            )
        elif provider == "github":
            result = (
                await github.verify(cfg["repo"], secret)
                if action == "verify"
                else await github.sync(pid, cfg["repo"], secret)
            )
        elif provider == "railway":
            result = await railway.verify(cfg["project_id"], secret)
        elif provider == "gsc":
            if not secret:
                raise RuntimeError("No service-account JSON stored")
            result = (
                await gsc.verify(secret, cfg["site_url"])
                if action == "verify"
                else await gsc.sync(pid, secret, cfg["site_url"], cfg.get("path_prefix"))
            )
        elif provider == "slack":
            if not secret:
                raise RuntimeError("No webhook stored")
            result = await slack.verify(secret)
        else:
            result = "Stored"
    except Exception as exc:  # noqa: BLE001
        msg = safe_error(exc)
        await registry.set_status(row["id"], "error", msg)
        raise HTTPException(status_code=502, detail=msg) from exc
    detail = result if isinstance(result, str) else f"Synced: {result}"
    await registry.set_status(row["id"], "ok", detail, synced=(action == "sync"))
    return {"ok": True, "detail": detail, "result": result}


@router.post("/{integration_id}/verify")
async def verify(integration_id: UUID) -> dict:
    return await _run(integration_id, "verify")


@router.post("/{integration_id}/sync")
async def sync(integration_id: UUID) -> dict:
    return await _run(integration_id, "sync")


async def sync_all() -> int:
    """Scheduler entrypoint: sync every syncable integration, swallowing errors."""
    pool = await get_pool()
    rows = await pool.fetch(
        "SELECT id FROM integrations"
        " WHERE provider IN ('stripe', 'github', 'gsc') AND status <> 'error'"
    )
    n = 0
    for r in rows:
        try:
            await _run(r["id"], "sync")
            n += 1
        except HTTPException:
            pass
    return n
