from __future__ import annotations

import base64
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from src.config import settings

router = APIRouter()

BASE_DIR = Path(__file__).resolve().parent.parent.parent
static_dir = BASE_DIR / "static"
templates = Jinja2Templates(directory=BASE_DIR / "templates")

ASSET_VERSION = "6"


def _static_mount(app) -> None:
    if static_dir.is_dir():
        app.mount("/static", StaticFiles(directory=static_dir), name="static")


def _clerk_frontend_api() -> str:
    """Derive the Clerk frontend API host from the publishable key (pk_test_<b64 host$>)."""
    key = settings.clerk_publishable_key
    if not key:
        return ""
    try:
        payload = key.split("_", 2)[2]
        payload += "=" * (-len(payload) % 4)
        return base64.b64decode(payload).decode().rstrip("$")
    except Exception:  # noqa: BLE001
        return ""


@router.get("/", response_class=HTMLResponse)
async def dashboard(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {
            "auth_enabled": settings.auth_enabled and bool(settings.clerk_publishable_key),
            "clerk_publishable_key": settings.clerk_publishable_key,
            "clerk_frontend_api": _clerk_frontend_api(),
            "asset_version": ASSET_VERSION,
        },
    )
