from contextlib import asynccontextmanager

import structlog
from fastapi import Depends, FastAPI, Request
from fastapi.responses import RedirectResponse

from src import scheduler
from src.api import (
    agents,
    campaigns,
    competitors,
    devin,
    events,
    experiments,
    finance,
    health,
    ingest,
    integrations,
    landing,
    learnings,
    metrics,
    ops,
    overview,
    pagedrones,
    product,
    projects,
    seo,
    targets,
    wiki,
)
from src.auth import current_user
from src.config import settings
from src.db import close_db, init_db
from src.web import routes as web_routes


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    scheduler.start()
    yield
    await scheduler.stop()
    await close_db()


app = FastAPI(
    title="InfiniSaaS",
    description="Portfolio cockpit: projects, metrics, experiments, marketing engine, agents",
    version="0.2.0",
    lifespan=lifespan,
)


@app.middleware("http")
async def canonical_host_redirect(request: Request, call_next):
    """Send browser traffic on non-canonical hosts (e.g. the *.railway.app URL) to PUBLIC_URL.

    Clerk production instances only serve the registered domain, so the SPA is blank elsewhere.
    Health checks and API/ingest calls are left alone.
    """
    canonical = settings.canonical_host
    host = request.headers.get("x-forwarded-host") or request.headers.get("host") or ""
    path = request.url.path
    if canonical and host.split(":")[0] != canonical and not path.startswith(("/api/", "/healthz")):
        url = request.url.replace(scheme="https", netloc=canonical)
        return RedirectResponse(str(url), status_code=308)
    return await call_next(request)


# Public: health, ingest (per-project bearer tokens), and the SPA shell
app.include_router(health.router)
app.include_router(ingest.router, prefix="/api/v1")
app.include_router(events.ingest_router, prefix="/api/v1")
app.include_router(web_routes.router, tags=["web"])
web_routes._static_mount(app)

# Dashboard API: protected by Clerk when configured (no-op locally)
auth = [Depends(current_user)]
app.include_router(overview.router, prefix="/api/overview", dependencies=auth)
app.include_router(projects.router, prefix="/api/projects", dependencies=auth)
app.include_router(metrics.router, prefix="/api/projects/{project_id}/metrics", dependencies=auth)
app.include_router(wiki.router, prefix="/api/projects/{project_id}/wiki", dependencies=auth)
app.include_router(experiments.router, prefix="/api/experiments", dependencies=auth)
app.include_router(campaigns.router, prefix="/api/campaigns", dependencies=auth)
app.include_router(learnings.router, prefix="/api/learnings", dependencies=auth)
app.include_router(integrations.router, prefix="/api/integrations", dependencies=auth)
app.include_router(events.router, prefix="/api/analytics", dependencies=auth)
app.include_router(finance.router, prefix="/api/finance", dependencies=auth)
app.include_router(finance.costs_router, prefix="/api/costs", dependencies=auth)
app.include_router(finance.ads_router, prefix="/api/ad-spend", dependencies=auth)
app.include_router(ops.router, prefix="/api/ops", dependencies=auth)
app.include_router(targets.router, prefix="/api", dependencies=auth)
app.include_router(product.feature_requests, prefix="/api/feature-requests", dependencies=auth)
app.include_router(product.feedback, prefix="/api/feedback", dependencies=auth)
app.include_router(product.releases, prefix="/api/releases", dependencies=auth)
app.include_router(product.content, prefix="/api/content", dependencies=auth)
app.include_router(product.seo_keywords, prefix="/api/seo/keywords", dependencies=auth)
app.include_router(seo.router, prefix="/api/seo", dependencies=auth)
app.include_router(landing.perf_router, prefix="/api/landing-pages", dependencies=auth)
app.include_router(landing.router, prefix="/api/landing-pages", dependencies=auth)
app.include_router(competitors.router, prefix="/api/competitors", dependencies=auth)
app.include_router(pagedrones.router, prefix="/api/pagedrones", dependencies=auth)
app.include_router(devin.router, prefix="/api/devin", dependencies=auth)
app.include_router(agents.router, prefix="/api/agents", dependencies=auth)
app.include_router(agents.recs_router, prefix="/api/recommendations", dependencies=auth)

logger = structlog.get_logger()
