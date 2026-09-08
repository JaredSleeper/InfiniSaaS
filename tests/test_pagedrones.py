"""Cockpit ↔ PageDrones loop against an in-memory emulation of the PageDrones admin API."""

from __future__ import annotations

import json
from uuid import UUID, uuid4

import httpx
import pytest
from asgi_lifespan import LifespanManager

from src.agents import runner
from src.db import get_pool
from src.integrations import pagedrones
from src.main import app

TOKEN = "pd-admin-secret-token"
BASE = "https://pagedrones.test"


class FakePageDrones:
    """Enough of /api/admin/alert-templates to exercise generate → vet → publish → sync."""

    def __init__(self):
        self.templates: dict[str, dict] = {}
        self.calls: list[tuple[str, str, dict | None]] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content) if request.content else None
        self.calls.append((request.method, request.url.path, body))
        if request.headers.get("Authorization") != f"Bearer {TOKEN}":
            return httpx.Response(401, json={"detail": "Invalid admin token"})
        path = request.url.path.removeprefix("/api/admin/alert-templates")
        if path == "/stats":
            by = {}
            for t in self.templates.values():
                by[t["status"]] = by.get(t["status"], 0) + 1
            return httpx.Response(
                200,
                json={
                    "by_status": by,
                    "subscribers": sum(t["subscribers"] for t in self.templates.values()),
                },
            )
        if path == "" and request.method == "GET":
            status = request.url.params.get("status")
            rows = [t for t in self.templates.values() if not status or t["status"] == status]
            return httpx.Response(200, json=rows)
        if path == "/generate":
            batch = str(uuid4())
            made = []
            for i in range(body["n"]):
                tid = str(uuid4())
                slug = f"{body['theme'].split(' ')[0].lower()}-{i}-{tid[:6]}"
                t = {
                    "id": tid,
                    "slug": slug,
                    "title": f"{body['theme'][:40]} #{i}",
                    "headline": f"Get alerted: {body['theme'][:40]} #{i}",
                    "description": "Watches the web for changes and emails you.",
                    "category": body.get("category") or "general",
                    "theme": body["theme"],
                    "audience": body.get("audience") or "",
                    "keywords": [f"{body['theme'].split(' ')[0].lower()} alert", "monitor"],
                    "prompt": "Report any new developments.",
                    "default_schedule": "daily",
                    "status": "candidate",
                    "vet_score": None,
                    "vet_notes": "",
                    "batch_id": batch,
                    "subscribers": 0,
                    "published_at": None,
                }
                self.templates[tid] = t
                made.append(t)
            return httpx.Response(
                200,
                json={
                    "batch_id": batch,
                    "requested": body["n"],
                    "inserted": len(made),
                    "skipped": 0,
                    "templates": made,
                    "mock": True,
                },
            )
        if path == "/vet":
            ids = (
                body["ids"]
                or [t["id"] for t in self.templates.values() if t["status"] == "candidate"][
                    : body["limit"]
                ]
            )
            out = []
            for i, tid in enumerate(ids):
                t = self.templates[tid]
                t["status"] = "vetted" if i % 2 == 0 else "rejected"
                t["vet_score"] = 82 if t["status"] == "vetted" else 12
                t["vet_notes"] = "3 sources, substantive" if i % 2 == 0 else "empty report"
                out.append(t)
            return httpx.Response(
                200,
                json={
                    "vetted": sum(1 for t in out if t["status"] == "vetted"),
                    "rejected": sum(1 for t in out if t["status"] == "rejected"),
                    "templates": out,
                },
            )
        if path == "/bulk-status":
            updated = 0
            for tid in body["ids"]:
                t = self.templates[tid]
                if body["status"] == "published" and t["status"] != "vetted":
                    continue
                t["status"] = body["status"]
                if body["status"] == "published":
                    t["published_at"] = "2026-09-05T00:00:00Z"
                updated += 1
            return httpx.Response(200, json={"updated": updated, "status": body["status"]})
        return httpx.Response(404, json={"detail": "nope"})


@pytest.fixture(scope="module")
def fake():
    fake = FakePageDrones()
    pagedrones.transport = httpx.MockTransport(fake.handler)
    yield fake
    pagedrones.transport = None


@pytest.fixture(scope="module")
async def client(fake):
    async with LifespanManager(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
            yield c


@pytest.fixture(scope="module")
async def project(client):
    projects = (await client.get("/api/projects")).json()
    p = next(p for p in projects if p["slug"] == "situationmonitor")
    pool = await get_pool()
    await pool.execute("DELETE FROM landing_pages WHERE project_id = $1", p["id"])
    await pool.execute("DELETE FROM events WHERE project_id = $1", p["id"])
    for row in (await client.get("/api/integrations")).json():
        if row["provider"] == "pagedrones" and row["project_id"] == p["id"]:
            await client.delete(f"/api/integrations/{row['id']}")
    return p


async def test_provider_registered_and_token_never_exposed(client, project):
    providers = (await client.get("/api/integrations/providers")).json()
    assert providers["pagedrones"]["scope"] == "project"
    assert providers["pagedrones"]["config_fields"][0]["key"] == "base_url"

    r = await client.put(
        "/api/integrations/pagedrones",
        json={"project_id": project["id"], "config": {"base_url": BASE}, "secret": TOKEN},
    )
    assert r.status_code == 200, r.text
    integ = r.json()
    assert integ["has_secret"] is True and TOKEN not in r.text

    r = await client.post(f"/api/integrations/{integ['id']}/verify")
    assert r.status_code == 200, r.text
    assert r.json()["detail"].startswith("Connected: 0 published") and TOKEN not in r.text

    listed = (await client.get("/api/integrations")).json()
    assert TOKEN not in json.dumps(listed)


async def test_stats_requires_integration(client):
    projects = (await client.get("/api/projects")).json()
    other = next(p for p in projects if p["slug"] == "blackjack")
    r = await client.get(f"/api/pagedrones/projects/{other['id']}/stats")
    assert r.status_code == 502 and "Connect the PageDrones integration" in r.json()["detail"]


async def test_wrong_token_is_reported_without_leaking(client, project, fake):
    pool = await get_pool()
    row = await pool.fetchrow(
        "SELECT id FROM integrations WHERE provider = 'pagedrones' AND project_id = $1",
        UUID(project["id"]),
    )
    await client.put(
        "/api/integrations/pagedrones",
        json={"project_id": project["id"], "config": {"base_url": BASE}, "secret": "bad-token"},
    )
    r = await client.post(f"/api/integrations/{row['id']}/verify")
    assert r.status_code == 502
    assert r.json()["detail"] == "PageDrones rejected the admin token"
    assert "bad-token" not in r.text
    # restore
    await client.put(
        "/api/integrations/pagedrones",
        json={"project_id": project["id"], "config": {"base_url": BASE}, "secret": TOKEN},
    )


async def test_theme_idea_generates_candidates_only(client, project, fake):
    pid = project["id"]
    r = await client.post(
        f"/api/landing-pages/projects/{pid}",
        json={
            "name": "Regulatory watch",
            "path": "/alerts/use-cases/regulatory-watch",
            "headline": "Regulatory change alerts for compliance teams",
            "angle": "Compliance leads who must react to new rules within days",
            "page_type": "use_case",
            "cluster": "compliance",
            "status": "idea",
            "score": 88,
        },
    )
    assert r.status_code == 201, r.text
    theme_page = r.json()

    r = await client.post(
        f"/api/pagedrones/projects/{pid}/generate-from-ideas",
        json={"ids": [theme_page["id"]], "n": 4},
    )
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["themes"] == 1 and out["inserted"] == 4 and out["failed"] == 0
    res = out["results"][0]
    assert res["theme"].startswith("Regulatory change alerts for compliance teams — Compliance")
    assert all(t["status"] == "candidate" for t in res["templates"])
    # PageDrones saw the theme with vet=False (no auto-vet, never auto-publish)
    gen_calls = [c for c in fake.calls if c[1].endswith("/generate")]
    assert gen_calls[-1][2]["vet"] is False and gen_calls[-1][2]["category"] == "compliance"
    assert all(t["status"] == "candidate" for t in fake.templates.values())

    # theme idea moved to draft and remembers its batch
    page = (await client.get(f"/api/landing-pages/{theme_page['id']}")).json()
    assert page["status"] == "draft"
    assert page["meta"]["pagedrones_batches"] == [res["batch_id"]]
    assert "4 alert candidates generated" in page["notes"]

    # nothing published yet → nothing mirrored
    r = await client.post(f"/api/pagedrones/projects/{pid}/sync")
    assert r.status_code == 200, r.text
    assert r.json() == {
        "published": 0,
        "registered": 0,
        "updated": 0,
        "retired": 0,
        "subscribers": 0,
    }


async def test_generate_from_idea_of_other_project_is_rejected(client, project):
    projects = (await client.get("/api/projects")).json()
    other = next(p for p in projects if p["slug"] == "blackjack")
    r = await client.post(
        f"/api/landing-pages/projects/{other['id']}",
        json={"name": "bj", "path": "/alerts/use-cases/bj", "page_type": "use_case"},
    )
    assert r.status_code == 201, r.text
    foreign = r.json()
    r = await client.post(
        f"/api/pagedrones/projects/{project['id']}/generate-from-ideas",
        json={"ids": [foreign["id"]], "n": 2},
    )
    assert r.status_code == 404
    r = await client.post(
        f"/api/pagedrones/projects/{project['id']}/generate",
        json={"theme": "Anything at all", "n": 2, "landing_page_id": foreign["id"]},
    )
    assert r.status_code == 404
    await client.delete(f"/api/landing-pages/{foreign['id']}")


async def test_vet_publish_sync_registers_live_pages(client, project, fake):
    pid = project["id"]
    r = await client.post(f"/api/pagedrones/projects/{pid}/vet", json={"limit": 4})
    assert r.status_code == 200, r.text
    assert r.json()["vetted"] == 2 and r.json()["rejected"] == 2

    templates = (await client.get(f"/api/pagedrones/projects/{pid}/templates")).json()
    assert len(templates) == 4 and all(t["url"].startswith(f"{BASE}/alerts/") for t in templates)
    vetted = [t["id"] for t in templates if t["status"] == "vetted"]
    rejected = [t["id"] for t in templates if t["status"] == "rejected"]

    # publishing a rejected one is refused by PageDrones (not vetted) → not mirrored
    r = await client.post(
        f"/api/pagedrones/projects/{pid}/templates/bulk-status",
        json={"ids": vetted + rejected[:1], "status": "published"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["updated"] == 2
    assert r.json()["sync"]["registered"] == 2 and r.json()["sync"]["retired"] == 0

    pages = (await client.get(f"/api/landing-pages?project_id={pid}&source=pagedrones")).json()
    assert len(pages) == 2
    for p in pages:
        t = fake.templates[p["external_id"]]
        assert p["status"] == "live" and p["page_type"] == "use_case"
        assert p["path"] == f"/alerts/{t['slug']}" and p["url"] == f"{BASE}/alerts/{t['slug']}"
        assert p["cluster"] == "compliance" and p["score"] == 82
        assert p["target_keyword"] == "regulatory alert"
        assert p["meta"]["slug"] == t["slug"] and p["meta"]["default_schedule"] == "daily"
        assert p["meta"]["subscribers"] == 0
        # traced back to the theme idea it came from
        theme = await client.get(f"/api/landing-pages/{p['meta']['theme_landing_page_id']}")
        assert theme.json()["name"] == "Regulatory watch"

    # idempotent re-sync updates rather than duplicating; subscriber counts flow into meta,
    # and a manual rename survives
    live_id = pages[0]["external_id"]
    fake.templates[live_id]["subscribers"] = 7
    await client.patch(f"/api/landing-pages/{pages[0]['id']}", json={"name": "Renamed by me"})
    r = await client.post(f"/api/pagedrones/projects/{pid}/sync")
    assert r.json()["registered"] == 0 and r.json()["updated"] == 2
    assert r.json()["subscribers"] == 7
    again = (await client.get(f"/api/landing-pages?project_id={pid}&source=pagedrones")).json()
    assert len(again) == 2
    renamed = next(p for p in again if p["external_id"] == live_id)
    assert renamed["name"] == "Renamed by me" and renamed["meta"]["subscribers"] == 7

    # integration status reflects the sync
    integ = next(
        i
        for i in (await client.get("/api/integrations")).json()
        if i["provider"] == "pagedrones" and i["project_id"] == pid
    )
    assert integ["status"] == "ok" and integ["last_synced_at"] is not None


async def test_unpublish_retires_page_and_funnel_attaches(client, project, fake):
    pid = project["id"]
    pages = (await client.get(f"/api/landing-pages?project_id={pid}&status=live")).json()
    assert len(pages) == 2
    victim, keeper = pages[0], pages[1]

    r = await client.post(
        f"/api/pagedrones/projects/{pid}/templates/bulk-status",
        json={"ids": [victim["external_id"]], "status": "rejected"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["sync"]["retired"] == 1 and r.json()["sync"]["published"] == 1
    v = (await client.get(f"/api/landing-pages/{victim['id']}")).json()
    assert v["status"] == "retired"

    # PostHog-normalized events on the /alerts/<slug> path feed the page's funnel
    token = (await client.get(f"/api/projects/{pid}/ingest-token")).json()["ingest_token"]
    events = [
        {"name": name, "user_key": user, "properties": {"path": keeper["path"]}}
        for user, names in (
            ("u1", ["visit", "signup_completed", "monitor_created"]),
            ("u2", ["visit"]),
        )
        for name in names
    ]
    r = await client.post(
        "/api/v1/events",
        json={"events": events},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 202, r.text
    perf = (await client.get(f"/api/landing-pages/performance?project_id={pid}&days=30")).json()
    row = next(p for p in perf["pages"] if p["page"]["id"] == keeper["id"])
    assert row["visitors"] == 2 and row["signups"] == 1
    assert row["page"]["source"] == "pagedrones"


async def test_agent_context_includes_alert_templates(client, project):
    pool = await get_pool()
    agent = await pool.fetchrow(
        "SELECT * FROM agents WHERE project_id = $1 AND kind = 'landing_pages'",
        UUID(project["id"]),
    )
    if agent is None:
        r = await client.post(
            "/api/agents",
            json={"name": "LP", "kind": "landing_pages", "project_id": project["id"]},
        )
        assert r.status_code == 201, r.text
        agent = await pool.fetchrow("SELECT * FROM agents WHERE id = $1", UUID(r.json()["id"]))
    ctx = await runner.build_context(dict(agent))
    alerts = ctx["alert_templates"]
    assert alerts["enabled"] is True
    assert alerts["live_pages"] == 1 and alerts["retired_pages"] == 1
    assert alerts["themes_generated"][0]["name"] == "Regulatory watch"
    live = next(p for p in alerts["pages"] if p["status"] == "live")
    assert live["path"].startswith("/alerts/") and "subscribers" in live
    perf_pages = ctx["landing_pages"]["pages"]
    assert any("alert_subscribers" in p for p in perf_pages)
