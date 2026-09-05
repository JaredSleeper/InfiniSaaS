from __future__ import annotations

from uuid import UUID, uuid4

import httpx
import pytest
from asgi_lifespan import LifespanManager

from src.main import app


@pytest.fixture(scope="module")
async def client():
    async with LifespanManager(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
            yield c


@pytest.fixture(scope="module")
async def project(client):
    projects = (await client.get("/api/projects")).json()
    return next(p for p in projects if p["slug"] == "blackjack")


async def test_wiki_seeded_and_editable(client, project):
    pages = (await client.get(f"/api/projects/{project['id']}/wiki")).json()
    slugs = {p["slug"] for p in pages}
    assert {"overview", "positioning", "pricing", "tech"} <= slugs
    r = await client.put(
        f"/api/projects/{project['id']}/wiki/positioning",
        json={"content": "## Ideal customer\nCasual players who want to stop losing money."},
    )
    assert r.status_code == 200
    assert "Casual players" in r.json()["content"]


async def test_feature_request_lifecycle(client, project):
    r = await client.post(
        f"/api/feature-requests/projects/{project['id']}",
        json={"title": "Card counting trainer", "priority": "high"},
    )
    assert r.status_code == 201, r.text
    fr = r.json()
    r = await client.patch(
        f"/api/feature-requests/{fr['id']}", json={"status": "planned", "votes": 3}
    )
    assert r.json()["status"] == "planned" and r.json()["votes"] == 3
    listed = (await client.get(f"/api/feature-requests?project_id={project['id']}")).json()
    assert any(x["id"] == fr["id"] for x in listed)
    fb = await client.post(
        f"/api/feedback/projects/{project['id']}",
        json={
            "content": "Please add counting drills",
            "sentiment": "positive",
            "feature_request_id": fr["id"],
        },
    )
    assert fb.status_code == 201, fb.text


async def test_devin_session_from_feature_request(client, project):
    fr = (
        await client.post(
            f"/api/feature-requests/projects/{project['id']}",
            json={"title": "Dark mode", "description": "Users play at night."},
        )
    ).json()
    body = {
        "prompt": "Implement this feature request.",
        "project_id": project["id"],
        "source_type": "feature_request",
        "source_id": fr["id"],
    }
    preview = (await client.post("/api/devin/preview", json=body)).json()
    assert "Dark mode" in preview["prompt"]
    assert "Casual players" in preview["prompt"]  # wiki context injected
    assert preview["title"] == "Dark mode"

    status = (await client.get("/api/devin/status")).json()
    r = await client.post("/api/devin/sessions", json=body)
    assert r.status_code == 201, r.text
    sess = r.json()
    assert sess["url"].startswith("https://app.devin.ai/sessions/")
    if not status["configured"]:
        assert sess["status"] == "mock"
    fr2 = (await client.get(f"/api/feature-requests/{fr['id']}")).json()
    assert fr2["status"] == "building"
    linked = (await client.get(f"/api/devin/sessions?source_id={fr['id']}")).json()
    assert len(linked) == 1
    r = await client.post(f"/api/devin/sessions/{sess['id']}/refresh")
    assert r.status_code == 200
    r = await client.post(f"/api/devin/sessions/{sess['id']}/message", json={"message": "hi"})
    assert r.status_code == 202


async def test_events_ingest_and_funnel(client, project):
    await client.patch(f"/api/projects/{project['id']}", json={"settings": {}})
    token = (await client.get(f"/api/projects/{project['id']}/ingest-token")).json()["ingest_token"]
    events = [{"name": "visit", "user_key": f"u{i}"} for i in range(10)]
    events += [{"name": "signup", "user_key": f"u{i}"} for i in range(4)]
    events += [{"name": "pay", "user_key": "u1", "properties": {"plan": "pro"}}]
    r = await client.post(
        "/api/v1/events", json={"events": events}, headers={"Authorization": f"Bearer {token}"}
    )
    assert r.status_code == 202
    r = await client.post("/api/v1/events", json={"events": events[:1]})
    assert r.status_code == 401
    summary = (await client.get(f"/api/analytics?project_id={project['id']}")).json()
    steps = {s["step"]: s for s in summary["funnel"]}
    assert steps["visit"]["users"] >= 10
    assert steps["signup"]["users"] >= 4
    assert steps["signup"]["rate"] is not None


async def test_costs_ads_and_finance(client, project):
    r = await client.post(
        f"/api/costs/projects/{project['id']}",
        json={
            "category": "infra",
            "amount": 20,
            "period_start": "2026-09-01",
            "period_end": "2026-09-30",
            "note": "Railway",
        },
    )
    assert r.status_code == 201, r.text
    r = await client.post(
        f"/api/ad-spend/projects/{project['id']}",
        json={
            "platform": "reddit",
            "day": "2026-09-03",
            "spend": 50,
            "clicks": 100,
            "impressions": 5000,
            "conversions": 5,
        },
    )
    assert r.status_code == 201, r.text
    # upsert same key updates in place
    r = await client.post(
        f"/api/ad-spend/projects/{project['id']}",
        json={
            "platform": "reddit",
            "day": "2026-09-03",
            "spend": 60,
            "clicks": 120,
            "impressions": 5000,
            "conversions": 6,
        },
    )
    assert r.status_code == 201
    fin = (await client.get(f"/api/finance?project_id={project['id']}")).json()
    assert fin["ad_spend"] == 60
    assert fin["cac"] == 10.0
    assert fin["total_costs"] >= 60
    port = (await client.get("/api/finance/portfolio")).json()
    assert any(p["project_id"] == project["id"] for p in port["projects"])


async def test_targets_and_alerts(client, project):
    metrics = (await client.get(f"/api/projects/{project['id']}/metrics")).json()
    revenue = next(m for m in metrics if m["key"] == "revenue")
    r = await client.post(
        "/api/targets", json={"metric_id": revenue["id"], "target_value": 1000, "label": "Q4"}
    )
    assert r.status_code == 201, r.text
    r = await client.post(
        "/api/alerts",
        json={"metric_id": revenue["id"], "condition": "stale_days", "threshold": 0},
    )
    assert r.status_code == 201, r.text
    from src.api.targets import evaluate_alerts

    fired = await evaluate_alerts()
    assert isinstance(fired, list)
    alerts = (await client.get(f"/api/alerts?project_id={project['id']}")).json()
    assert len(alerts) >= 1


async def test_integrations_registry_encrypts_secret(client, project):
    r = await client.put(
        "/api/integrations/github",
        json={
            "project_id": project["id"],
            "config": {"repo": "JaredSleeper/InfiniSaaS"},
            "secret": "ghp_supersecret",
        },
    )
    assert r.status_code == 201 or r.status_code == 200, r.text
    row = r.json()
    assert row["has_secret"] is True
    assert "ghp_" not in r.text
    listed = (await client.get("/api/integrations")).json()
    assert "ghp_" not in str(listed)
    from src.integrations.registry import get_secret

    assert await get_secret("github", UUID(project["id"])) == "ghp_supersecret"
    r = await client.put("/api/integrations/stripe", json={"project_id": None, "secret": "sk"})
    assert r.status_code == 400
    r = await client.put("/api/integrations/github", json={"project_id": project["id"]})
    assert r.status_code == 400  # missing repo config


async def test_agents_bootstrap_and_mock_run(client, project):
    r = await client.post(f"/api/agents/bootstrap/{project['id']}")
    assert r.status_code == 201, r.text
    agents = r.json()
    assert {a["kind"] for a in agents} >= {"weekly_brief", "seo", "analytics", "ads"}
    brief = next(a for a in agents if a["kind"] == "analytics")
    r = await client.post(f"/api/agents/{brief['id']}/run")
    assert r.status_code == 201, r.text
    run = r.json()
    assert run["status"] == "succeeded", run
    recs = (await client.get(f"/api/recommendations?project_id={project['id']}")).json()
    assert recs
    rec = recs[0]
    r = await client.post(f"/api/recommendations/{rec['id']}/to-experiment")
    assert r.status_code == 200
    assert r.json()["experiment_id"] and r.json()["status"] == "accepted"
    r = await client.patch(f"/api/recommendations/{rec['id']}", json={"status": "done"})
    assert r.json()["status"] == "done"


async def test_seo_keywords_and_content(client, project):
    r = await client.post(
        f"/api/seo/keywords/projects/{project['id']}",
        json={"keyword": f"blackjack trainer {uuid4().hex[:6]}", "target_url": project["url"]},
    )
    assert r.status_code == 201, r.text
    r = await client.post(
        f"/api/seo/keywords/projects/{project['id']}", json={"keyword": r.json()["keyword"]}
    )
    assert r.status_code == 409
    r = await client.post(
        f"/api/content/projects/{project['id']}",
        json={"title": "Basic strategy explained", "channel": "seo", "status": "drafting"},
    )
    assert r.status_code == 201, r.text
    r = await client.post(
        f"/api/releases/projects/{project['id']}", json={"title": "v1.2 — counting drills"}
    )
    assert r.status_code == 201, r.text
    assert r.json()["released_at"]


async def test_ops_portfolio(client):
    r = await client.get("/api/ops/portfolio")
    assert r.status_code == 200
    assert isinstance(r.json(), list)


async def test_project_patch_repo_and_settings(client, project):
    r = await client.patch(
        f"/api/projects/{project['id']}",
        json={
            "repo_url": "https://github.com/JaredSleeper/getbetterat",
            "settings": {"funnel": ["visit", "play", "pay"]},
        },
    )
    assert r.status_code == 200, r.text
    assert r.json()["settings"]["funnel"] == ["visit", "play", "pay"]
    summary = (await client.get(f"/api/analytics?project_id={project['id']}")).json()
    assert summary["funnel_steps"] == ["visit", "play", "pay"]
