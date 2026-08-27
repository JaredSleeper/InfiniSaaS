from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI

from src.api import campaigns, experiments, health, ingest, learnings, metrics, overview, projects
from src.db import close_db, init_db
from src.web import routes as web_routes


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    yield
    await close_db()


app = FastAPI(
    title="InfiniSaaS",
    description="Portfolio cockpit: projects, metrics, experiments, marketing engine",
    version="0.1.0",
    lifespan=lifespan,
)

app.include_router(health.router)
app.include_router(overview.router, prefix="/api/overview")
app.include_router(projects.router, prefix="/api/projects")
app.include_router(metrics.router, prefix="/api/projects/{project_id}/metrics")
app.include_router(experiments.router, prefix="/api/experiments")
app.include_router(campaigns.router, prefix="/api/campaigns")
app.include_router(learnings.router, prefix="/api/learnings")
app.include_router(ingest.router, prefix="/api/v1")
app.include_router(web_routes.router, tags=["web"])
web_routes._static_mount(app)

logger = structlog.get_logger()
