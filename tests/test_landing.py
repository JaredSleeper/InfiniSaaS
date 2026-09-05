from __future__ import annotations

from datetime import date

import httpx
import pytest
from asgi_lifespan import LifespanManager

from src.agents import runner
from src.db import get_pool
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
    return next(p for p in projects if p["slug"] == "speedreading")


@pytest.fixture(scope="module")
async def clean(client, project):
    pool = await get_pool()
    await pool.execute("DELETE FROM landing_pages WHERE project_id = $1", project["id"])
    await pool.execute("DELETE FROM events WHERE project_id = $1", project["id"])
    await pool.execute("DELETE FROM recommendations WHERE project_id = $1", project["id"])
    await client.patch(f"/api/projects/{project['id']}", json={"settings": {}})


async def test_landing_page_crud_and_validation(client, project, clean):
    r = await client.post(
        f"/api/landing-pages/projects/{project['id']}",
        json={"name": "Speed reading test", "path": "speedreading/test/", "status": "live"},
    )
    assert r.status_code == 201, r.text
    page = r.json()
    assert page["path"] == "/speedreading/test"  # normalized: leading slash, no trailing slash
    assert page["channel"] == "seo" and page["url"] is None

    dup = await client.post(
        f"/api/landing-pages/projects/{project['id']}",
        json={"name": "dup", "path": "/speedreading/test"},
    )
    assert dup.status_code == 409

    bad = await client.post(
        f"/api/landing-pages/projects/{project['id']}",
        json={"name": "x", "path": "/a b", "url": "ftp://nope"},
    )
    assert bad.status_code == 422

    r = await client.patch(
        f"/api/landing-pages/{page['id']}",
        json={
            "url": "https://getbetterat.xyz/speedreading/test",
            "headline": "How fast do you read?",
            "target_keyword": "reading speed test",
        },
    )
    assert r.status_code == 200 and r.json()["headline"] == "How fast do you read?"

    listed = (await client.get(f"/api/landing-pages?project_id={project['id']}&status=live")).json()
    assert [x["id"] for x in listed] == [page["id"]]


async def test_performance_attributes_events_by_path(client, project, clean):
    token = (await client.get(f"/api/projects/{project['id']}/ingest-token")).json()["ingest_token"]
    ev = [
        {"name": "visit", "user_key": f"t{i}", "properties": {"path": "/speedreading/test/"}}
        for i in range(8)
    ]
    ev += [{"name": "visit", "user_key": None, "properties": {"path": "/speedreading/test"}}]
    ev += [{"name": "signup", "user_key": f"t{i}"} for i in range(4)]
    ev += [{"name": "pay", "user_key": "t0"}]
    # traffic on a path that is not registered yet -> shows up as "discovered"
    ev += [
        {"name": "visit", "user_key": f"d{i}", "properties": {"path": "/speedreading/drills"}}
        for i in range(3)
    ]
    # events with no path are ignored (not lumped into "/"); full URLs + query strings collapse
    ev += [{"name": "visit", "user_key": "nopath"}]
    ev += [
        {
            "name": "visit",
            "user_key": "u1",
            "properties": {"path": "https://getbetterat.xyz/speedreading/drills?x=1"},
        }
    ]
    r = await client.post(
        "/api/v1/events", json={"events": ev}, headers={"Authorization": f"Bearer {token}"}
    )
    assert r.status_code == 202

    pool = await get_pool()
    camp = await pool.fetchrow(
        """INSERT INTO campaigns (project_id, name, channel, status)
           VALUES ($1, 'Reddit test', 'paid', 'active') RETURNING id""",
        project["id"],
    )
    page = (await client.get(f"/api/landing-pages?project_id={project['id']}")).json()[0]
    await client.patch(f"/api/landing-pages/{page['id']}", json={"campaign_id": str(camp["id"])})
    r = await client.post(
        f"/api/ad-spend/projects/{project['id']}",
        json={
            "platform": "reddit",
            "campaign_id": str(camp["id"]),
            "day": date.today().isoformat(),
            "spend": 40,
            "clicks": 20,
            "conversions": 2,
        },
    )
    assert r.status_code in (200, 201), r.text
    await pool.execute(
        """INSERT INTO seo_keywords (project_id, keyword, target_url, clicks, impressions, position)
           VALUES ($1, 'reading speed test', 'https://getbetterat.xyz/speedreading/test', 30, 1000,
                   4.2)
           ON CONFLICT (project_id, keyword) DO UPDATE SET clicks = 30, impressions = 1000,
             target_url = EXCLUDED.target_url, position = 4.2""",
        project["id"],
    )

    perf = (await client.get(f"/api/landing-pages/performance?project_id={project['id']}")).json()
    row = next(p for p in perf["pages"] if p["page"]["id"] == page["id"])
    assert row["pageviews"] == 9 and row["visitors"] == 8
    assert row["signups"] == 4 and row["pays"] == 1
    assert row["signup_rate"] == 50.0 and row["pay_rate"] == 12.5
    assert row["gsc_clicks"] == 30 and row["gsc_impressions"] == 1000 and row["gsc_ctr"] == 3.0
    assert row["gsc_position"] == 4.2
    assert row["ad_spend"] == 40.0 and row["cpa"] == 10.0
    assert row["campaign_name"] == "Reddit test"
    assert row["seo_score"] is None
    disc = {d["path"]: d for d in perf["discovered"]}
    assert disc["/speedreading/drills"]["visitors"] == 4
    assert "/speedreading/test" not in disc and "/" not in disc

    # portfolio-wide view includes this project's page and never leaks secrets
    port = (await client.get("/api/landing-pages/performance")).json()
    assert any(p["page"]["id"] == page["id"] for p in port["pages"])
    assert token not in repr(port)


async def test_zero_traffic_page_has_null_rates(client, project, clean):
    r = await client.post(
        f"/api/landing-pages/projects/{project['id']}",
        json={"name": "Idea page", "path": "/speedreading/idea", "status": "idea"},
    )
    assert r.status_code == 201
    perf = (await client.get(f"/api/landing-pages/performance?project_id={project['id']}")).json()
    row = next(p for p in perf["pages"] if p["page"]["path"] == "/speedreading/idea")
    assert row["visitors"] == 0 and row["signup_rate"] is None and row["cpa"] is None


async def test_landing_agent_context_and_rec_to_page(client, project, clean, monkeypatch):
    r = await client.post(f"/api/agents/bootstrap/{project['id']}")
    assert r.status_code == 201
    agent = next(a for a in r.json() if a["kind"] == "landing_pages")
    assert agent["schedule"] == "weekly"

    ctx = await runner.build_context(
        {
            "kind": "landing_pages",
            "project_id": project["id"],
            "config": {},
            "name": agent["name"],
            "instructions": "",
        }
    )
    lp = ctx["landing_pages"]
    paths = {p["path"] for p in lp["pages"]}
    assert "/speedreading/test" in paths and "/speedreading/idea" in paths
    assert any(d["path"] == "/speedreading/drills" for d in lp["unregistered_paths_with_traffic"])
    assert "wiki" in ctx and "analytics" in ctx
    prompt = runner._prompt_for({"kind": "landing_pages", "instructions": ""}, ctx)
    assert "kind landing_page" in prompt and "/speedreading/drills" in prompt

    async def fake_complete(system, prompt, max_tokens=4000):
        assert "landing_page" in system
        return runner.llm.LLMResult(
            text="""{"summary": "ok", "recommendations": [
              {"title": "Build a WPM calculator page", "body": "Rank for wpm calculator.",
               "kind": "landing_page", "impact": "high", "effort": "medium",
               "page": {"path": "/speedreading/wpm-calculator", "headline": "Free WPM calculator",
                        "angle": "Utility first", "target_keyword": "wpm calculator",
                        "channel": "seo", "evil": "ignored"}},
              {"title": "Retire /speedreading/idea", "body": "No traffic.", "kind": "landing_page",
               "impact": "low", "effort": "low", "page": {"channel": "bogus"}}
            ]}""",
            input_tokens=1,
            output_tokens=1,
        )

    monkeypatch.setattr(runner.llm, "complete", fake_complete)
    r = await client.post(f"/api/agents/{agent['id']}/run")
    assert r.status_code == 201 and r.json()["status"] == "succeeded", r.text
    recs = (await client.get(f"/api/recommendations?project_id={project['id']}&status=open")).json()
    rec = next(x for x in recs if x["title"] == "Build a WPM calculator page")
    assert rec["kind"] == "landing_page"
    assert rec["data"]["page"]["path"] == "/speedreading/wpm-calculator"
    assert "evil" not in rec["data"]["page"]
    retire = next(x for x in recs if x["title"].startswith("Retire"))
    assert "channel" not in retire["data"]["page"]

    r = await client.post(f"/api/recommendations/{rec['id']}/to-landing-page")
    assert r.status_code == 200, r.text
    accepted = r.json()
    assert accepted["status"] == "accepted" and accepted["landing_page_id"]
    page = (await client.get(f"/api/landing-pages/{accepted['landing_page_id']}")).json()
    assert page["status"] == "draft" and page["path"] == "/speedreading/wpm-calculator"
    assert page["headline"] == "Free WPM calculator" and page["target_keyword"] == "wpm calculator"
    assert page["brief"] == "Rank for wpm calculator."

    # idempotent: accepting again returns the same page
    again = (await client.post(f"/api/recommendations/{rec['id']}/to-landing-page")).json()
    assert again["landing_page_id"] == accepted["landing_page_id"]

    # a rec without a page brief gets a slug path; collisions get suffixed
    r = await client.post(f"/api/recommendations/{retire['id']}/to-landing-page")
    assert r.status_code == 200
    slug_page = (await client.get(f"/api/landing-pages/{r.json()['landing_page_id']}")).json()
    assert slug_page["path"] == "/retire-speedreading-idea"

    # Devin prompt built from a landing page carries the brief and instrumentation hint
    pv = await client.post(
        "/api/devin/preview",
        json={
            "project_id": project["id"],
            "source_type": "landing_page",
            "source_id": page["id"],
            "prompt": "Build it.",
        },
    )
    assert pv.status_code == 200, pv.text
    assert "Free WPM calculator" in pv.json()["prompt"]
    assert 'properties.path = "/speedreading/wpm-calculator"' in pv.json()["prompt"]

    # deleting the page nulls the link on the recommendation instead of failing
    d = await client.delete(f"/api/landing-pages/{page['id']}")
    assert d.status_code == 204
    rec_after = (
        await client.get(f"/api/recommendations?project_id={project['id']}&status=accepted")
    ).json()
    assert next(x for x in rec_after if x["id"] == rec["id"])["landing_page_id"] is None
