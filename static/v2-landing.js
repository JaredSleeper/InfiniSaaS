/* InfiniSaaS v2 — landing pages: registry, cross-project comparison, agent hand-off */

window.V2 = window.V2 || { tabs: {} };

(function () {
  const LP_STATUSES = ["idea", "draft", "live", "retired"];
  const money = (v) => v == null ? "—" : "$" + Number(v).toLocaleString(undefined, { maximumFractionDigits: 2 });
  const num = (v) => v == null ? "—" : Number(v).toLocaleString();
  const pct = (v) => v == null ? "—" : Number(v).toFixed(1) + "%";
  const scoreColor = (s) => s >= 80 ? "var(--good)" : s >= 60 ? "var(--warn)" : "var(--bad)";
  const rateColor = (v, good, warn) => v == null ? "" : `color:${v >= good ? "var(--good)" : v >= warn ? "var(--warn)" : "var(--bad)"}`;

  function actionsRow(extra = "") {
    return `<div class="form-error"></div>
      <div class="actions">${extra}<button class="btn" type="button" data-close>Cancel</button>
        <button class="btn btn-primary" type="submit">Save</button></div>`;
  }

  /* ── create / edit modal ── */
  /* projectId may be null (portfolio view): the form then includes a project picker. */
  V2.landingModal = async function (projectId, existing, after, prefill = {}, projects = []) {
    const q = projectId ? `?project_id=${projectId}` : "";
    const [allCamps, allExps] = await Promise.all([api(`/api/campaigns${q}`), api(`/api/experiments${q}`)]);
    const lp = existing || { name: "", path: "", url: "", headline: "", angle: "", target_keyword: "",
      channel: "seo", status: "idea", brief: "", notes: "", campaign_id: null, experiment_id: null, ...prefill };
    const pick = (list, sel, label) => `<option value="">— no ${label} —</option>` +
      list.map((x) => `<option value="${x.id}" ${x.id === sel ? "selected" : ""}>${esc(x.name)}</option>`).join("");
    const forProject = (list, pid) => list.filter((x) => x.project_id === pid);
    const initialPid = projectId || (projects[0] && projects[0].id);
    const camps = projectId ? allCamps : forProject(allCamps, initialPid);
    const exps = projectId ? allExps : forProject(allExps, initialPid);
    openModal(`
      <h2>${existing ? "Edit" : "New"} landing page</h2>
      <form>
        ${projectId ? "" : `<label>Project</label><select name="project_id">${projects.map((p) => `<option value="${p.id}">${esc(p.name)}</option>`).join("")}</select>`}
        <div class="grid-2">
          <div><label>Name</label><input name="name" value="${esc(lp.name)}" required placeholder="Basic strategy trainer"></div>
          <div><label>Path <span class="muted">(matches events.properties.path)</span></label><input name="path" value="${esc(lp.path)}" required placeholder="/blackjack/basic-strategy"></div>
        </div>
        <label>Live URL <span class="muted">(for Search Console + audits)</span></label><input name="url" value="${esc(lp.url || "")}" placeholder="https://getbetterat.xyz/blackjack/basic-strategy">
        <label>Headline</label><input name="headline" value="${esc(lp.headline)}" placeholder="The promise above the fold">
        <div class="grid-2">
          <div><label>Target keyword</label><input name="target_keyword" value="${esc(lp.target_keyword)}"></div>
          <div><label>Channel</label><select name="channel">${options(CHANNELS, lp.channel)}</select></div>
        </div>
        <div class="grid-2">
          <div><label>Status</label><select name="status">${options(LP_STATUSES, lp.status)}</select></div>
          <div><label>Campaign <span class="muted">(joins ad spend)</span></label><select name="campaign_id">${pick(camps, lp.campaign_id, "campaign")}</select></div>
        </div>
        <label>Experiment</label><select name="experiment_id">${pick(exps, lp.experiment_id, "experiment")}</select>
        <label>Angle <span class="muted">(who it's for, why this framing)</span></label><textarea name="angle" rows="2">${esc(lp.angle)}</textarea>
        <label>Brief <span class="muted">(what to build — sent to Devin)</span></label><textarea name="brief" rows="4">${esc(lp.brief)}</textarea>
        <label>Notes</label><textarea name="notes" rows="2">${esc(lp.notes)}</textarea>
        ${actionsRow(existing ? `<button class="btn btn-danger" type="button" data-delete="${lp.id}">Delete</button>` : "")}
      </form>`, async (fd) => {
      const body = {};
      for (const k of ["name", "path", "url", "headline", "target_keyword", "channel", "status", "angle", "brief", "notes"]) body[k] = fd.get(k);
      body.url = body.url || null;
      body.campaign_id = fd.get("campaign_id") || null;
      body.experiment_id = fd.get("experiment_id") || null;
      const pid = projectId || fd.get("project_id");
      if (existing) await api(`/api/landing-pages/${lp.id}`, { method: "PATCH", body: JSON.stringify(body) });
      else await api(`/api/landing-pages/projects/${pid}`, { method: "POST", body: JSON.stringify(body) });
    });
    const projSel = $modal.querySelector("[name=project_id]");
    if (projSel) projSel.addEventListener("change", () => {
      $modal.querySelector("[name=campaign_id]").innerHTML = pick(forProject(allCamps, projSel.value), null, "campaign");
      $modal.querySelector("[name=experiment_id]").innerHTML = pick(forProject(allExps, projSel.value), null, "experiment");
    });
    const del = $modal.querySelector("[data-delete]");
    if (del) del.addEventListener("click", async () => {
      if (!confirm("Delete this landing page? Its events stay; only the registry row goes.")) return;
      await api(`/api/landing-pages/${del.dataset.delete}`, { method: "DELETE" });
      closeModal(); after();
    });
  };

  /* ── comparison table ── */
  function pageRow(r, showProject) {
    const p = r.page;
    const href = p.url || null;
    return `<tr data-lp-row="${p.id}">
      <td>
        <div><strong>${href ? `<a href="${esc(href)}" target="_blank" rel="noopener">${esc(p.name)}</a>` : esc(p.name)}</strong> ${badge(p.status)}</div>
        <div class="mono muted" style="font-size:11px">${showProject ? `<a href="#/p/${p.project_id}/landing" style="color:${esc(r.accent_color)}">●</a> ` : ""}${esc(p.path)}${p.target_keyword ? ` · <span title="target keyword">🔍 ${esc(p.target_keyword)}</span>` : ""}</div>
        ${p.headline ? `<div class="muted clamp-2" style="font-size:12px; margin-top:2px">“${esc(p.headline)}”</div>` : ""}
      </td>
      <td>${badge(p.channel)}${r.campaign_name ? `<div class="muted" style="font-size:11px">${esc(r.campaign_name)}</div>` : ""}</td>
      <td class="mono" style="text-align:right">${num(r.visitors)}<div class="muted" style="font-size:11px">${num(r.pageviews)} views</div></td>
      <td class="mono" style="text-align:right">${num(r.signups)}<div style="font-size:11px; ${rateColor(r.signup_rate, 5, 2)}">${pct(r.signup_rate)}</div></td>
      <td class="mono" style="text-align:right">${num(r.pays)}<div style="font-size:11px; ${rateColor(r.pay_rate, 1, 0.3)}">${pct(r.pay_rate)}</div></td>
      <td class="mono" style="text-align:right">${r.gsc_clicks == null ? "—" : `${num(r.gsc_clicks)}<div class="muted" style="font-size:11px">${num(r.gsc_impressions)} impr · ${pct(r.gsc_ctr)}${r.gsc_position != null ? ` · #${Number(r.gsc_position).toFixed(1)}` : ""}</div>`}</td>
      <td class="mono" style="text-align:right">${r.ad_spend == null ? "—" : `${money(r.ad_spend)}<div class="muted" style="font-size:11px">${r.cpa != null ? `CPA ${money(r.cpa)}` : `${num(r.ad_clicks)} clicks`}</div>`}</td>
      <td class="mono" style="text-align:right">${r.seo_score == null ? `<span class="muted">—</span>` : `<span style="color:${scoreColor(r.seo_score)}">${r.seo_score}</span>`}</td>
      <td style="text-align:right; white-space:nowrap">
        <button class="btn btn-sm btn-devin" data-lp-devin="${p.id}" title="Send to Devin">◆</button>
        ${href ? `<button class="btn btn-sm" data-lp-audit="${p.id}" title="Run SEO audit">Audit</button>` : ""}
        <button class="btn btn-sm" data-lp-edit="${p.id}">Edit</button>
      </td>
    </tr>`;
  }

  function leaders(rows) {
    const withTraffic = rows.filter((r) => r.visitors >= 5 && r.signup_rate != null);
    if (withTraffic.length < 2) return "";
    const sorted = [...withTraffic].sort((a, b) => b.signup_rate - a.signup_rate);
    const best = sorted[0], worst = sorted[sorted.length - 1];
    const card = (label, r, color) => `<div class="stat"><div class="num" style="color:${color}">${pct(r.signup_rate)}</div>
      <div class="lbl">${label} · ${esc(r.page.name)} <span class="muted">${num(r.visitors)} visitors</span></div></div>`;
    const totalV = rows.reduce((s, r) => s + r.visitors, 0), totalS = rows.reduce((s, r) => s + r.signups, 0);
    return `<div class="stat-strip">
      <div class="stat"><div class="num">${num(totalV)}</div><div class="lbl">Visitors <span class="muted">${rows.length} pages</span></div></div>
      <div class="stat"><div class="num">${totalV ? pct(totalS / totalV * 100) : "—"}</div><div class="lbl">Blended signup rate</div></div>
      ${card("Best", best, "var(--good)")}${card("Worst", worst, "var(--bad)")}
    </div>`;
  }

  /* Column labels follow the project's funnel (settings.funnel = [visit, signup, ..., pay]). */
  function funnelLabels(project) {
    const steps = (project && project.settings && project.settings.funnel) || [];
    const signup = steps[1] || "signup", pay = steps[steps.length - 1] || "pay";
    return {
      signup: signup === "signup" ? "Signups" : esc(signup),
      pay: pay === "pay" ? "Pays" : esc(pay),
      hint: `First-touch visitors to this path who later fired the project's funnel step (${esc(signup)} / ${esc(pay)}). Change under Analytics → Funnel steps.`,
    };
  }

  V2.landingTable = function (perf, { showProject = false, project = null } = {}) {
    if (!perf.pages.length) return "";
    const f = funnelLabels(project);
    const hint = project ? f.hint : "First-touch visitors who later fired the project's signup / pay funnel step (varies per project).";
    return `${leaders(perf.pages)}
      <div class="card" style="padding:0; overflow-x:auto"><table>
        <thead><tr><th>Page</th><th>Channel</th>
          <th style="text-align:right" title="Unique users whose first visit event (in the window) was on this path">Visitors</th>
          <th style="text-align:right" title="${hint}">${f.signup}</th>
          <th style="text-align:right" title="${hint}">${f.pay}</th>
          <th style="text-align:right">Search clicks</th><th style="text-align:right">Ad spend</th><th style="text-align:right">SEO</th><th></th></tr></thead>
        <tbody>${perf.pages.map((r) => pageRow(r, showProject)).join("")}</tbody></table></div>`;
  };

  function discoveredList(perf, showProject) {
    if (!perf.discovered.length) return "";
    return `<div class="section-head" style="margin-top:20px"><h3>Untracked paths with traffic <span class="muted">(${perf.days}d)</span></h3></div>
      <div class="card" style="padding:0"><table>
        <thead><tr>${showProject ? "<th>Project</th>" : ""}<th>Path</th><th style="text-align:right">Visitors</th><th style="text-align:right">Views</th><th></th></tr></thead>
        <tbody>${perf.discovered.map((d, i) => `<tr>${showProject ? `<td>${esc(d.project_name)}</td>` : ""}
          <td class="mono">${esc(d.path)}</td><td class="mono" style="text-align:right">${num(d.visitors)}</td><td class="mono" style="text-align:right">${num(d.pageviews)}</td>
          <td style="text-align:right"><button class="btn btn-sm" data-lp-track="${i}">Track</button></td></tr>`).join("")}</tbody></table></div>`;
  }

  function bindTable(root, perf, rerender) {
    const byId = (id) => perf.pages.find((r) => r.page.id === id).page;
    root.querySelectorAll("[data-lp-edit]").forEach((b) => b.addEventListener("click", () => {
      const p = byId(b.dataset.lpEdit); V2.landingModal(p.project_id, p, rerender);
    }));
    root.querySelectorAll("[data-lp-devin]").forEach((b) => b.addEventListener("click", () => {
      const p = byId(b.dataset.lpDevin);
      const verb = p.status === "live" ? "Improve" : "Build";
      V2.devinModal({ project_id: p.project_id, source_type: "landing_page", source_id: p.id, title: p.name,
        prompt: `${verb} the landing page at ${p.path}${p.headline ? ` ("${p.headline}")` : ""}. Follow the brief, keep the site's design system, instrument visit/signup events with properties.path, and open a PR.` });
    }));
    root.querySelectorAll("[data-lp-audit]").forEach((b) => b.addEventListener("click", async () => {
      const p = byId(b.dataset.lpAudit);
      b.textContent = "…"; b.disabled = true;
      try { await api(`/api/seo/audits/projects/${p.project_id}`, { method: "POST", body: JSON.stringify({ url: p.url }) }); }
      catch (ex) { alert(ex.message); }
      rerender();
    }));
    root.querySelectorAll("[data-lp-track]").forEach((b) => b.addEventListener("click", () => {
      const d = perf.discovered[Number(b.dataset.lpTrack)];
      const name = d.path.split("/").filter(Boolean).pop() || "home";
      V2.landingModal(d.project_id, null, rerender, { path: d.path, status: "live", name: name.replace(/[-_]/g, " ") });
    }));
  }

  function daysSeg(days) {
    return `<span class="seg">${[7, 30, 90].map((d) => `<button class="btn btn-sm ${d === days ? "btn-primary" : ""}" data-days="${d}">${d}d</button>`).join("")}</span>`;
  }

  /* ── global dashboard: #/landing-pages ── */
  V2.renderLandingPages = async function (days = 30, filter = {}) {
    days = Number(days) || 30;
    const [perf, projects, recs] = await Promise.all([
      api(`/api/landing-pages/performance?days=${days}`), api("/api/projects"),
      api("/api/recommendations?status=open&limit=200"),
    ]);
    const lpRecs = recs.filter((r) => r.kind === "landing_page");
    const rows = perf.pages.filter((r) => (!filter.project || r.page.project_id === filter.project) && (!filter.status || r.page.status === filter.status));
    const shown = { ...perf, pages: rows, discovered: perf.discovered.filter((d) => !filter.project || d.project_id === filter.project) };
    const rerender = () => V2.renderLandingPages(days, filter);
    $view.innerHTML = `
      <div class="page-head">
        <div><h1>Landing pages</h1><div class="muted">Every page across the portfolio, compared on the same funnel: first-touch visitors → signups → payments, plus Search Console, paid CPA and on-page SEO.</div></div>
        <div>${daysSeg(days)} <button class="btn btn-primary" id="add-lp">+ Landing page</button></div>
      </div>
      <div class="card-row" style="margin-bottom:12px">
        <span class="seg">
          <button class="btn btn-sm ${filter.project ? "" : "btn-primary"}" data-proj="">All projects</button>
          ${projects.map((p) => `<button class="btn btn-sm ${filter.project === p.id ? "btn-primary" : ""}" data-proj="${p.id}"><span style="color:${esc(p.accent_color)}">●</span> ${esc(p.name)}</button>`).join("")}
        </span>
        <span class="seg">
          <button class="btn btn-sm ${filter.status ? "" : "btn-primary"}" data-st="">any status</button>
          ${LP_STATUSES.map((s) => `<button class="btn btn-sm ${filter.status === s ? "btn-primary" : ""}" data-st="${s}">${s}</button>`).join("")}
        </span>
      </div>
      ${V2.landingTable(shown, { showProject: true }) || `<div class="empty">${perf.pages.length ? "No pages match this filter." : `No landing pages registered yet. Add one, or run the <b>Landing page agent</b> on a project's Agents tab and accept a suggestion.<br><span class="muted" style="font-size:12px">Tracking works via the events ingest: send <code>visit</code> events with <code>properties.path</code>.</span>`}</div>`}
      ${discoveredList(shown, true)}
      <div class="section" style="margin-top:24px">
        <div class="section-head"><h2>Page suggestions <span class="muted">(${lpRecs.length} open)</span></h2><a href="#/inbox" class="muted" style="font-size:12px">all recommendations →</a></div>
        <div class="grid-2">${lpRecs.map((r) => V2.recCard(r, { showProject: true, projects })).join("") || `<div class="empty">No open page suggestions. Run a project's <b>Landing page agent</b> — it reads the wiki, keywords and this table and proposes pages to build, test or retire.</div>`}</div>
      </div>`;
    document.getElementById("add-lp").addEventListener("click", () => {
      if (!projects.length) { alert("Create a project first."); return; }
      V2.landingModal(filter.project || null, null, rerender, {}, projects);
    });
    $view.querySelectorAll("[data-days]").forEach((b) => b.addEventListener("click", () => V2.renderLandingPages(b.dataset.days, filter)));
    $view.querySelectorAll("[data-proj]").forEach((b) => b.addEventListener("click", () => V2.renderLandingPages(days, { ...filter, project: b.dataset.proj || null })));
    $view.querySelectorAll("[data-st]").forEach((b) => b.addEventListener("click", () => V2.renderLandingPages(days, { ...filter, status: b.dataset.st || null })));
    bindTable($view, shown, rerender);
    V2.bindRecCards($view, lpRecs, rerender);
  };

  /* ── project tab ── */
  V2.tabs.landing = async function (id, p, root, days) {
    days = Number(days) || 30;
    const [perf, recs, agents] = await Promise.all([
      api(`/api/landing-pages/performance?project_id=${id}&days=${days}`),
      api(`/api/recommendations?project_id=${id}&status=open`),
      api(`/api/agents?project_id=${id}`),
    ]);
    const lpRecs = recs.filter((r) => r.kind === "landing_page");
    const agent = agents.find((a) => a.kind === "landing_pages" && a.project_id === id);
    const rerender = () => V2.tabs.landing(id, p, root, days);
    root.innerHTML = `
      <div class="section" style="margin-top:12px">
        <div class="section-head"><h2>Landing pages <span class="muted">(${perf.pages.length})</span></h2>
          <span>${daysSeg(days)}
            ${agent ? `<button class="btn btn-sm" id="run-lp-agent">Run landing page agent</button>` : `<button class="btn btn-sm" id="add-lp-agent">Add landing page agent</button>`}
            <button class="btn btn-sm btn-primary" id="add-lp">+ Landing page</button></span></div>
        <div id="lp-agent-status"></div>
        ${V2.landingTable(perf, { project: p }) || `<div class="empty">No landing pages for ${esc(p.name)} yet.<br><span class="muted" style="font-size:12px">Register the pages you already have (path = what you send as <code>properties.path</code> on <code>visit</code> events), then let the agent suggest new ones.</span></div>`}
        ${discoveredList(perf, false)}
        <div class="section-head" style="margin-top:24px"><h3>Page suggestions <span class="muted">(${lpRecs.length} open)</span></h3></div>
        <div class="grid-2">${lpRecs.map((r) => V2.recCard(r)).join("") || `<div class="muted" style="font-size:12px">Nothing open. ${agent ? "Run the landing page agent for suggestions grounded in the wiki, keywords and this table." : "Add the landing page agent to get suggestions."}</div>`}</div>
      </div>`;
    document.getElementById("add-lp").addEventListener("click", () => V2.landingModal(id, null, rerender));
    root.querySelectorAll("[data-days]").forEach((b) => b.addEventListener("click", () => { location.hash = `#/p/${id}/landing/${b.dataset.days}`; }));
    const run = document.getElementById("run-lp-agent");
    if (run) run.addEventListener("click", async () => {
      const status = document.getElementById("lp-agent-status");
      run.textContent = "Running…"; run.disabled = true;
      status.innerHTML = `<div class="notice">Landing page agent is reading the wiki, keywords and this table… usually 20–60s.</div>`;
      let result;
      try { result = await api(`/api/agents/${agent.id}/run`, { method: "POST" }); }
      catch (ex) { status.innerHTML = `<div class="notice">Run failed: ${esc(ex.message)}</div>`; run.textContent = "Run landing page agent"; run.disabled = false; return; }
      const after = await api(`/api/recommendations?project_id=${id}&status=open`);
      const fresh = after.filter((r) => r.kind === "landing_page").length - lpRecs.length;
      await rerender();
      const s = document.getElementById("lp-agent-status");
      if (s) s.innerHTML = `<div class="notice">Run ${esc(result.status)}${result.error ? ` — ${esc(result.error)}` : ""}: ${fresh > 0 ? `<b>${fresh} new page suggestion${fresh === 1 ? "" : "s"}</b> below` : "no new page suggestions"}${result.summary ? ` — ${esc(result.summary.replace(/\.$/, ""))}` : ""}. <a href="#/p/${id}/agents">Run history →</a></div>`;
    });
    const add = document.getElementById("add-lp-agent");
    if (add) add.addEventListener("click", async () => {
      await api("/api/agents", { method: "POST", body: JSON.stringify({ project_id: id, kind: "landing_pages", name: "Landing page agent", schedule: "weekly" }) });
      rerender();
    });
    bindTable(root, perf, rerender);
    V2.bindRecCards(root, lpRecs, rerender);
  };
})();
