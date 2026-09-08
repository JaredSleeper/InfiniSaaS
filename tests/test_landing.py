from __future__ import annotations

import asyncio
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
    await pool.execute("DELETE FROM competitors WHERE project_id = $1", project["id"])
    await pool.execute("UPDATE agents SET config = '{}' WHERE project_id = $1", project["id"])
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
    idea = r.json()
    url = f"/api/landing-pages/performance?project_id={project['id']}"
    # backlog rows (idea/vetted/rejected) are not scored in the performance table
    assert all(p["page"]["id"] != idea["id"] for p in (await client.get(url)).json()["pages"])
    await client.patch(f"/api/landing-pages/{idea['id']}", json={"status": "draft"})
    perf = (await client.get(url)).json()
    row = next(p for p in perf["pages"] if p["page"]["path"] == "/speedreading/idea")
    assert row["visitors"] == 0 and row["signup_rate"] is None and row["cpa"] is None
    await client.patch(f"/api/landing-pages/{idea['id']}", json={"status": "idea"})


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
    assert paths == {"/speedreading/test"}  # backlog rows are summarized, not listed
    assert lp["backlog_counts"] == {"idea": 1}
    assert any(d["path"] == "/speedreading/drills" for d in lp["unregistered_paths_with_traffic"])
    assert "wiki" in ctx and "analytics" in ctx
    assert ctx["competitors"] == [] and ctx["research"]["discovered"] == 0
    prompt = runner._prompt_for({"kind": "landing_pages", "instructions": ""}, ctx)
    assert "backlog" in prompt and "/speedreading/drills" in prompt

    async def fake_crawl(url):
        return {"pages": [{"path": "/vs/x", "type": "comparison", "title": "vs"}], "error": ""}

    monkeypatch.setattr(runner.landing_agent.research, "crawl", fake_crawl)

    async def fake_complete(system, prompt, max_tokens=4000, web_searches=0):
        if system.startswith("You are a market researcher"):
            assert web_searches > 0 and "Find up to 10 competitors" in prompt
            return runner.llm.LLMResult(
                text="""Here you go: {"competitors": [{"name": "Spreeder",
                  "url": "www.spreeder.com/x", "positioning": "RSVP trainer"},
                  {"name": "no url"}], "market_notes": "Lots of vs pages."}""",
                input_tokens=2,
                output_tokens=2,
            )
        if system.startswith("You are a growth strategist"):
            assert "spreeder.com" in prompt
            assert "Produce exactly 15 new landing-page ideas" in prompt
            return runner.llm.LLMResult(
                text="""{"ideas": [
                  {"path": "speedreading/vs-spreeder/", "name": "vs Spreeder",
                   "headline": "Speed Reading vs Spreeder", "angle": "Comparison",
                   "target_keyword": "Spreeder Alternative", "page_type": "comparison",
                   "cluster": "alternatives", "channel": "seo", "score": 82,
                   "rationale": "Competitor has 12 comparison pages", "brief": "Table + CTA"},
                  {"path": "/speedreading/idea", "name": "dup path", "headline": "x",
                   "angle": "x", "target_keyword": "fresh kw", "page_type": "guide",
                   "cluster": "c", "channel": "seo", "score": 50, "rationale": "", "brief": ""},
                  {"path": "/speedreading/other", "name": "dup keyword", "headline": "x",
                   "angle": "x", "target_keyword": "spreeder alternative", "page_type": "guide",
                   "cluster": "c", "channel": "seo", "score": 50, "rationale": "", "brief": ""},
                  {"path": "/speedreading/for-students", "name": "Students", "headline": "x",
                   "angle": "x", "target_keyword": "speed reading for students",
                   "page_type": "bogus_type", "cluster": "personas", "channel": "nope",
                   "score": 140, "rationale": "", "brief": ""},
                  {"name": "no path", "headline": "x", "target_keyword": "zzz"}
                ]}""",
                input_tokens=5,
                output_tokens=7,
            )
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

    async def run_and_wait():
        r = await client.post(f"/api/agents/{agent['id']}/run")
        assert r.status_code == 202 and r.json()["status"] == "running", r.text
        run = r.json()
        for _ in range(200):
            run = (await client.get(f"/api/agents/runs/{run['id']}")).json()
            if run["status"] != "running":
                break
            await asyncio.sleep(0.05)
        assert run["status"] == "succeeded", run
        return run

    run = await run_and_wait()
    pool = await get_pool()
    run_ctx = (await pool.fetchrow("SELECT context FROM agent_runs WHERE id = $1", run["id"]))[
        "context"
    ]
    assert run_ctx["ideas"]["inserted"] == 2 and run_ctx["ideas"]["returned"] == 5
    assert run_ctx["research"]["discovered"] == 1 and run_ctx["research"]["crawled"] == 1
    assert run["input_tokens"] == 8 and run["output_tokens"] == 10
    assert "2 new page ideas added to the backlog" in run["summary"]
    assert "1 competitors discovered" in run["summary"]
    comps = (await client.get(f"/api/competitors?project_id={project['id']}")).json()
    assert [c["domain"] for c in comps] == ["spreeder.com"]
    assert comps[0]["source"] == "agent" and comps[0]["page_count"] == 1
    agents = (await client.get(f"/api/agents?project_id={project['id']}")).json()
    agent_row = next(a for a in agents if a["id"] == agent["id"])
    assert agent_row["config"]["research_state"]["market_notes"] == "Lots of vs pages."

    ideas = (
        await client.get(f"/api/landing-pages?project_id={project['id']}&status=idea&source=agent")
    ).json()
    by_path = {p["path"]: p for p in ideas}
    assert set(by_path) == {"/speedreading/vs-spreeder", "/speedreading/for-students"}
    vs = by_path["/speedreading/vs-spreeder"]
    assert vs["page_type"] == "comparison" and vs["score"] == 82 and vs["cluster"] == "alternatives"
    assert vs["target_keyword"] == "spreeder alternative" and vs["agent_run_id"] == run["id"]
    students = by_path["/speedreading/for-students"]
    assert students["page_type"] == "other" and students["channel"] == "seo"
    assert students["score"] == 100
    # the manual idea page is untouched and still listed without the source filter
    listed = (await client.get(f"/api/landing-pages?project_id={project['id']}&status=idea")).json()
    assert len(listed) == 3

    # a second run must not re-add the same paths/keywords
    run2 = await run_and_wait()
    assert "0 new page ideas" in run2["summary"]
    n = await pool.fetchval(
        "SELECT count(*) FROM landing_pages WHERE project_id = $1 AND source = 'agent'",
        project["id"],
    )
    assert n == 2

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


async def test_bulk_status_and_bulk_devin(client, project, clean):
    pool = await get_pool()
    ideas = (
        await client.get(f"/api/landing-pages?project_id={project['id']}&status=idea&source=agent")
    ).json()
    ids = [p["id"] for p in ideas]
    assert len(ids) == 2

    r = await client.post("/api/landing-pages/bulk-status", json={"ids": ids, "status": "vetted"})
    assert r.status_code == 200 and r.json()["updated"] == 2
    vetted = (
        await client.get(f"/api/landing-pages?project_id={project['id']}&status=vetted")
    ).json()
    assert {p["id"] for p in vetted} == set(ids)
    bad = await client.post("/api/landing-pages/bulk-status", json={"ids": ids, "status": "nope"})
    assert bad.status_code == 422

    r = await client.post(
        "/api/landing-pages/bulk-devin", json={"ids": ids, "instructions": "Use Astro."}
    )
    assert r.status_code == 201, r.text
    sess = r.json()
    assert sess["source_type"] == "landing_page" and sess["project_id"] == project["id"]
    assert "Build 2 landing pages" in sess["title"]
    assert "Use Astro." in sess["prompt"]
    assert "/speedreading/vs-spreeder" in sess["prompt"]
    assert "/speedreading/for-students" in sess["prompt"]
    assert 'properties.path = "/speedreading/vs-spreeder"' in sess["prompt"]
    rows = await pool.fetch(
        "SELECT status, notes FROM landing_pages WHERE id = ANY($1::uuid[])", ids
    )
    assert {r["status"] for r in rows} == {"draft"}
    assert all(sess["url"] in r["notes"] for r in rows)

    other = (await client.get("/api/projects")).json()
    other_project = next(p for p in other if p["id"] != project["id"])
    foreign = await client.post(
        f"/api/landing-pages/projects/{other_project['id']}",
        json={"name": "foreign", "path": "/foreign"},
    )
    mixed = await client.post(
        "/api/landing-pages/bulk-devin", json={"ids": [ids[0], foreign.json()["id"]]}
    )
    assert mixed.status_code == 400
    await client.delete(f"/api/landing-pages/{foreign.json()['id']}")


async def test_competitors_crud_crawl_and_context(client, project, clean, monkeypatch):
    from src.agents import landing_agent, research

    pool = await get_pool()
    await pool.execute("DELETE FROM competitors WHERE project_id = $1", project["id"])

    async def fake_crawl(url):
        assert url == "https://www.spreeder.com"
        return {
            "pages": [
                {"path": "/", "type": "home", "title": "Spreeder"},
                {"path": "/pricing", "type": "pricing", "title": "Pricing"},
                {"path": "/vs/readsy", "type": "comparison", "h1": "Spreeder vs Readsy"},
                {"path": "/blog/post", "type": "blog", "title": "Post"},
            ],
            "error": "",
        }

    monkeypatch.setattr(research, "crawl", fake_crawl)
    r = await client.post(
        f"/api/competitors/projects/{project['id']}",
        json={"name": "Spreeder", "url": "https://www.spreeder.com", "positioning": "RSVP app"},
    )
    assert r.status_code == 201, r.text
    comp = r.json()
    assert comp["domain"] == "spreeder.com" and comp["page_count"] == 4
    assert comp["crawled_at"] and comp["source"] == "manual"
    assert {p["type"] for p in comp["pages"]} == {"home", "pricing", "comparison", "blog"}

    dup = await client.post(
        f"/api/competitors/projects/{project['id']}",
        json={"name": "Spreeder again", "url": "http://spreeder.com/x"},
    )
    assert dup.status_code == 409
    bad = await client.post(
        f"/api/competitors/projects/{project['id']}", json={"name": "x", "url": "not a url"}
    )
    assert bad.status_code == 422

    listed = (await client.get(f"/api/competitors?project_id={project['id']}")).json()
    assert [c["id"] for c in listed] == [comp["id"]] and listed[0]["pages"] == []
    assert listed[0]["page_types"] == {"home": 1, "pricing": 1, "comparison": 1, "blog": 1}
    assert comp["page_types"] == listed[0]["page_types"]
    full = (
        await client.get(f"/api/competitors?project_id={project['id']}&include_pages=true")
    ).json()
    assert len(full[0]["pages"]) == 4

    ctx = await landing_agent.competitor_context(project["id"])
    assert len(ctx) == 1
    assert ctx[0]["domain"] == "spreeder.com" and ctx[0]["positioning"] == "RSVP app"
    inv = ctx[0]["site"]
    assert inv["total_pages"] == 4 and inv["by_type"]["comparison"] == 1
    assert "blog" not in inv["samples"] and inv["samples"]["comparison"] == [
        "/vs/readsy — Spreeder vs Readsy"
    ]

    r = await client.patch(f"/api/competitors/{comp['id']}", json={"status": "ignored"})
    assert r.status_code == 200 and r.json()["status"] == "ignored"
    assert await landing_agent.competitor_context(project["id"]) == []

    # research refresh in mock mode discovers nothing and only recrawls stale rows
    stats = await landing_agent.refresh_research(
        project["id"], {"id": None, "project_id": project["id"], "config": {}}
    )
    assert stats["discovered"] == 0 and stats["crawled"] == 0
    r = await client.delete(f"/api/competitors/{comp['id']}")
    assert r.status_code == 204
    assert (await client.get(f"/api/competitors/{comp['id']}")).status_code == 404
