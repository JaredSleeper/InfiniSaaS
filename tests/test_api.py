from __future__ import annotations

import httpx
import pytest
from asgi_lifespan import LifespanManager

from src.main import app


@pytest.fixture(scope="session")
async def client():
    async with LifespanManager(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
            yield c


async def test_healthz(client):
    r = await client.get("/healthz")
    assert r.status_code == 200


async def test_seeded_projects(client):
    r = await client.get("/api/projects")
    assert r.status_code == 200
    slugs = {p["slug"] for p in r.json()}
    assert {"blackjack", "speedreading", "situationmonitor"} <= slugs


async def test_metric_point_roundtrip(client):
    projects = (await client.get("/api/projects")).json()
    project = next(p for p in projects if p["slug"] == "blackjack")
    metrics = (await client.get(f"/api/projects/{project['id']}/metrics")).json()
    revenue = next(m for m in metrics if m["key"] == "revenue")

    r = await client.post(
        f"/api/projects/{project['id']}/metrics/{revenue['id']}/points",
        json={"value": 12.5},
    )
    assert r.status_code == 201
    points = (
        await client.get(f"/api/projects/{project['id']}/metrics/{revenue['id']}/points")
    ).json()
    assert any(p["value"] == 12.5 for p in points)


async def test_ingest_flow(client):
    projects = (await client.get("/api/projects")).json()
    project = next(p for p in projects if p["slug"] == "speedreading")
    token = (await client.get(f"/api/projects/{project['id']}/ingest-token")).json()["ingest_token"]

    r = await client.post(
        "/api/v1/metrics",
        json={"points": [{"metric": "signups", "value": 3}]},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 202
    assert r.json() == {"accepted": 1}

    r = await client.post(
        "/api/v1/metrics",
        json={"points": [{"metric": "nope", "value": 1}]},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 400

    r = await client.post(
        "/api/v1/metrics",
        json={"points": [{"metric": "signups", "value": 1}]},
        headers={"Authorization": "Bearer wrong"},
    )
    assert r.status_code == 401


async def test_experiment_lifecycle(client):
    projects = (await client.get("/api/projects")).json()
    project = next(p for p in projects if p["slug"] == "blackjack")

    r = await client.post(
        f"/api/experiments/projects/{project['id']}",
        json={"name": "SEO landing test", "channel": "seo", "hypothesis": "ranks for blackjack"},
    )
    assert r.status_code == 201
    exp = r.json()
    assert exp["status"] == "idea"

    r = await client.patch(f"/api/experiments/{exp['id']}", json={"status": "running"})
    assert r.json()["started_at"] is not None

    r = await client.patch(
        f"/api/experiments/{exp['id']}",
        json={"status": "concluded", "result": "positive", "learnings": "it worked"},
    )
    body = r.json()
    assert body["ended_at"] is not None
    assert body["result"] == "positive"

    r = await client.delete(f"/api/experiments/{exp['id']}")
    assert r.status_code == 204


async def test_overview(client):
    r = await client.get("/api/overview")
    assert r.status_code == 200
    body = r.json()
    assert len(body["projects"]) >= 3
    assert "counts" in body
    assert all("ingest_token" not in p for p in body["projects"])
