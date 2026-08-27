from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

router = APIRouter()

BASE_DIR = Path(__file__).resolve().parent.parent.parent
static_dir = BASE_DIR / "static"
templates = Jinja2Templates(directory=BASE_DIR / "templates")


def _static_mount(app) -> None:
    if static_dir.is_dir():
        app.mount("/static", StaticFiles(directory=static_dir), name="static")


@router.get("/", response_class=HTMLResponse)
async def dashboard(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request, "dashboard.html", {})
