/* InfiniSaaS v2 — landing pages: registry, cross-project comparison, idea backlog, competitors, agent hand-off */

window.V2 = window.V2 || { tabs: {} };

(function () {
  const LP_STATUSES = ["idea", "vetted", "draft", "live", "retired", "rejected"];
  const BACKLOG = ["idea", "vetted", "rejected"];
  const PAGE_TYPES = ["home", "feature", "use_case", "persona", "industry", "comparison", "alternative", "integration",
    "template", "glossary", "guide", "pricing", "tool", "other"];
  const money = (v) => v == null ? "—" : "$" + Number(v).toLocaleString(undefined, { maximumFractionDigits: 2 });
  const num = (v) => v == null ? "—" : Number(v).toLocaleString();
  const pct = (v) => v == null ? "—" : Number(v).toFixed(1) + "%";
  const scoreColor = (s) => s >= 80 ? "var(--good)" : s >= 60 ? "var(--warn)" : "var(--bad)";
  const rateColor = (v, good, warn) => v == null ? "" : `color:${v >= good ? "var(--good)" : v >= warn ? "var(--warn)" : "var(--bad)"}`;
  const ago = (iso) => {
    if (!iso) return "never";
    const h = (Date.now() - new Date(iso)) / 36e5;
    return h < 1 ? "just now" : h < 48 ? `${Math.round(h)}h ago` : `${Math.round(h / 24)}d ago`;
  };
  const scoreChip = (s) => s == null ? `<span class="muted">—</span>` : `<span class="score-chip" style="color:${scoreColor(s)}; border-color:${scoreColor(s)}">${s}</span>`;
  const typeLabel = (t) => String(t || "other").replace(/_/g, " ");
  const batchBadge = (p) => {
    const n = ((p.meta || {}).pagedrones_batches || []).length;
    return n ? ` <span class="badge" title="Alert batches generated in PageDrones from this theme (${n})">⚡ ${n} batch${n === 1 ? "" : "es"}</span>` : "";
  };

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
      channel: "seo", status: "idea", page_type: "other", cluster: "", score: null, rationale: "",
      brief: "", notes: "", campaign_id: null, experiment_id: null, ...prefill };
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
        <div class="grid-3">
          <div><label>Page type</label><select name="page_type">${options(PAGE_TYPES, lp.page_type)}</select></div>
          <div><label>Cluster <span class="muted">(topic group)</span></label><input name="cluster" value="${esc(lp.cluster)}" placeholder="alternatives"></div>
          <div><label>Score <span class="muted">(0–100)</span></label><input name="score" type="number" min="0" max="100" value="${lp.score == null ? "" : lp.score}"></div>
        </div>
        <div class="grid-2">
          <div><label>Status</label><select name="status">${options(LP_STATUSES, lp.status)}</select></div>
          <div><label>Campaign <span class="muted">(joins ad spend)</span></label><select name="campaign_id">${pick(camps, lp.campaign_id, "campaign")}</select></div>
        </div>
        <label>Experiment</label><select name="experiment_id">${pick(exps, lp.experiment_id, "experiment")}</select>
        <label>Angle <span class="muted">(who it's for, why this framing)</span></label><textarea name="angle" rows="2">${esc(lp.angle)}</textarea>
        <label>Rationale <span class="muted">(why this page should exist — evidence)</span></label><textarea name="rationale" rows="2">${esc(lp.rationale)}</textarea>
        <label>Brief <span class="muted">(what to build — sent to Devin)</span></label><textarea name="brief" rows="4">${esc(lp.brief)}</textarea>
        <label>Notes</label><textarea name="notes" rows="2">${esc(lp.notes)}</textarea>
        ${actionsRow(existing ? `<button class="btn btn-danger" type="button" data-delete="${lp.id}">Delete</button>` : "")}
      </form>`, async (fd) => {
      const body = {};
      for (const k of ["name", "path", "url", "headline", "target_keyword", "channel", "status", "page_type", "cluster", "angle", "rationale", "brief", "notes"]) body[k] = fd.get(k);
      body.url = body.url || null;
      body.score = fd.get("score") === "" ? null : Number(fd.get("score"));
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

  /* ── comparison table (live / draft / retired pages) ── */
  function pageRow(r, showProject) {
    const p = r.page;
    const href = p.url || null;
    return `<tr data-lp-row="${p.id}">
      <td>
        <div><strong>${href ? `<a href="${esc(href)}" target="_blank" rel="noopener">${esc(p.name)}</a>` : esc(p.name)}</strong> ${badge(p.status)}${p.source === "pagedrones" ? ` <span class="badge" title="Published PageDrones alert template — synced from /alerts; subscribers = users who created a drone from it">⚡ alert · ${num((p.meta || {}).subscribers || 0)} subs</span>` : ""}${batchBadge(p)}</div>
        <div class="mono muted" style="font-size:11px">${showProject ? `<a href="#/p/${p.project_id}/landing" style="color:${esc(r.accent_color)}">●</a> ` : ""}${esc(p.path)}${p.target_keyword ? ` · <span title="target keyword">🔍 ${esc(p.target_keyword)}</span>` : ""}</div>
        ${p.headline ? `<div class="muted clamp-2" style="font-size:12px; margin-top:2px">“${esc(p.headline)}”</div>` : ""}
      </td>
      <td>${badge(p.channel)}<div class="muted" style="font-size:11px">${esc(typeLabel(p.page_type))}${r.campaign_name ? ` · ${esc(r.campaign_name)}` : ""}</div></td>
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
      <div class="card" style="padding:0; overflow-x:auto"><table>
        <thead><tr>${showProject ? "<th>Project</th>" : ""}<th>Path</th><th style="text-align:right">Visitors</th><th style="text-align:right">Views</th><th></th></tr></thead>
        <tbody>${perf.discovered.map((d, i) => `<tr>${showProject ? `<td>${esc(d.project_name)}</td>` : ""}
          <td class="mono">${esc(d.path)}</td><td class="mono" style="text-align:right">${num(d.visitors)}</td><td class="mono" style="text-align:right">${num(d.pageviews)}</td>
          <td style="text-align:right"><button class="btn btn-sm" data-lp-track="${i}">Track</button></td></tr>`).join("")}</tbody></table></div>`;
  }

  function devinPromptFor(p) {
    const verb = p.status === "live" ? "Improve" : "Build";
    return `${verb} the landing page at ${p.path}${p.headline ? ` ("${p.headline}")` : ""}. Follow the brief, keep the site's design system, instrument visit/signup events with properties.path, and open a PR.`;
  }

  function bindTable(root, perf, rerender) {
    const byId = (id) => perf.pages.find((r) => r.page.id === id).page;
    root.querySelectorAll("[data-lp-edit]").forEach((b) => b.addEventListener("click", () => {
      const p = byId(b.dataset.lpEdit); V2.landingModal(p.project_id, p, rerender);
    }));
    root.querySelectorAll("[data-lp-devin]").forEach((b) => b.addEventListener("click", () => {
      const p = byId(b.dataset.lpDevin);
      V2.devinModal({ project_id: p.project_id, source_type: "landing_page", source_id: p.id, title: p.name, prompt: devinPromptFor(p) });
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

  /* ── idea backlog: agent-generated + manual ideas, vetted in bulk before they become drafts ── */
  /* Filter/selection state survives re-renders, keyed by scope ("global" or a project id). */
  const backlogState = {};
  function stateFor(key) {
    return backlogState[key] || (backlogState[key] = { status: "open", type: "", cluster: "", minScore: 0, q: "", limit: 50, selected: new Set() });
  }

  function filterBacklog(pages, st) {
    const q = st.q.trim().toLowerCase();
    return pages
      .filter((p) => BACKLOG.includes(p.status))
      .filter((p) => st.status === "open" ? p.status !== "rejected" : st.status === "all" ? true : p.status === st.status)
      .filter((p) => !st.type || p.page_type === st.type)
      .filter((p) => !st.cluster || p.cluster === st.cluster)
      .filter((p) => !st.minScore || (p.score != null && p.score >= st.minScore))
      .filter((p) => !q || [p.name, p.path, p.target_keyword, p.headline, p.cluster, p.angle].some((v) => String(v || "").toLowerCase().includes(q)))
      .sort((a, b) => (b.score ?? -1) - (a.score ?? -1) || (a.created_at < b.created_at ? 1 : -1));
  }

  function backlogRow(p, st, showProject, projectsById) {
    const proj = projectsById[p.project_id];
    return `<tr class="${st.selected.has(p.id) ? "selected" : ""}">
      <td style="width:28px"><input type="checkbox" data-bl-sel="${p.id}" ${st.selected.has(p.id) ? "checked" : ""}></td>
      <td>
        <div><strong>${esc(p.name)}</strong> ${p.status !== "idea" ? badge(p.status) : ""}${p.source === "agent" ? `<span class="muted" style="font-size:11px" title="Generated by the landing page agent"> ✦</span>` : ""}${batchBadge(p)}</div>
        <div class="mono muted" style="font-size:11px">${showProject && proj ? `<a href="#/p/${p.project_id}/landing" style="color:${esc(proj.accent_color)}" title="${esc(proj.name)}">●</a> ` : ""}${esc(p.path)}${p.target_keyword ? ` · 🔍 ${esc(p.target_keyword)}` : ""}</div>
        ${p.headline ? `<div class="muted clamp-2" style="font-size:12px; margin-top:2px">“${esc(p.headline)}”</div>` : ""}
      </td>
      <td><span class="badge">${esc(typeLabel(p.page_type))}</span>${p.cluster ? `<div class="muted" style="font-size:11px; margin-top:3px">${esc(p.cluster)}</div>` : ""}</td>
      <td style="text-align:center">${scoreChip(p.score)}</td>
      <td class="muted" style="font-size:12px; max-width:360px" title="${esc(p.rationale)}${p.angle ? `\n\nAngle: ${esc(p.angle)}` : ""}"><div class="clamp-2">${esc(p.rationale || p.angle || "")}</div></td>
      <td style="text-align:right; white-space:nowrap">
        <button class="btn btn-sm btn-devin" data-bl-devin="${p.id}" title="Send to Devin">◆</button>
        <button class="btn btn-sm" data-bl-edit="${p.id}">Edit</button>
      </td>
    </tr>`;
  }

  V2.backlogSection = function (pages, { key, showProject = false, projects = [], hasAgent = false, alerts = false } = {}) {
    const st = stateFor(key);
    const all = pages.filter((p) => BACKLOG.includes(p.status));
    const counts = { idea: 0, vetted: 0, rejected: 0 };
    all.forEach((p) => { counts[p.status] += 1; });
    const clusters = {};
    all.filter((p) => p.status !== "rejected").forEach((p) => { if (p.cluster) clusters[p.cluster] = (clusters[p.cluster] || 0) + 1; });
    const types = {};
    all.filter((p) => p.status !== "rejected").forEach((p) => { types[p.page_type] = (types[p.page_type] || 0) + 1; });
    const rows = filterBacklog(pages, st);
    const shown = rows.slice(0, st.limit);
    const projectsById = Object.fromEntries(projects.map((p) => [p.id, p]));
    const sel = st.selected.size;
    const opt = (v, label, cur) => `<option value="${esc(v)}" ${v === cur ? "selected" : ""}>${esc(label)}</option>`;
    return `<div class="section" style="margin-top:24px" id="bl-${esc(key)}">
      <div class="section-head"><h2>Idea backlog <span class="muted">(${counts.idea} ideas · ${counts.vetted} vetted · ${counts.rejected} rejected)</span></h2>
        <span class="muted" style="font-size:12px">${hasAgent ? "Every agent run adds a scored batch. Vet the ones worth building, reject the rest, then send vetted ideas to Devin in bulk." : "Ideas accumulate here; add the landing page agent to generate them from competitor research and your keywords."}</span></div>
      ${all.length ? `
      <div class="card-row filter-bar">
        <span class="seg">
          ${[["open", "open"], ["idea", "ideas"], ["vetted", "vetted"], ["rejected", "rejected"], ["all", "all"]].map(([v, l]) => `<button class="btn btn-sm ${st.status === v ? "btn-primary" : ""}" data-bl-status="${v}">${l}</button>`).join("")}
        </span>
        <select data-bl-type style="width:auto">${opt("", `any type (${Object.keys(types).length})`, st.type)}${Object.entries(types).sort((a, b) => b[1] - a[1]).map(([t, n]) => opt(t, `${typeLabel(t)} (${n})`, st.type)).join("")}</select>
        <select data-bl-cluster style="width:auto">${opt("", `any cluster (${Object.keys(clusters).length})`, st.cluster)}${Object.entries(clusters).sort((a, b) => b[1] - a[1]).map(([c, n]) => opt(c, `${c} (${n})`, st.cluster)).join("")}</select>
        <select data-bl-score style="width:auto">${[0, 50, 60, 70, 80, 90].map((s) => opt(String(s), s ? `score ≥ ${s}` : "any score", String(st.minScore))).join("")}</select>
        <input data-bl-q placeholder="search path, keyword, headline…" value="${esc(st.q)}" style="width:220px">
        <span class="muted" style="font-size:12px; margin-left:auto">${rows.length} match${rows.length === 1 ? "" : "es"}</span>
      </div>
      <div class="bulk-bar ${sel ? "" : "hidden"}">
        <b>${sel} selected</b>
        <button class="btn btn-sm" data-bl-bulk="vetted">✓ Vet</button>
        <button class="btn btn-sm" data-bl-bulk="rejected">✕ Reject</button>
        <button class="btn btn-sm" data-bl-bulk="idea">↺ Back to idea</button>
        <button class="btn btn-sm" data-bl-bulk="draft">→ Draft</button>
        <button class="btn btn-sm btn-devin" data-bl-bulk-devin>◆ Send ${sel} to Devin</button>
        ${alerts ? `<button class="btn btn-sm" data-bl-bulk-alerts title="Use each selected idea as a theme: PageDrones generates a batch of alert-template candidates per theme (nothing is published)">⚡ Alerts from ${sel}</button>` : ""}
        <button class="btn btn-sm" data-bl-clear style="margin-left:auto">Clear</button>
      </div>
      <div class="card" style="padding:0; overflow-x:auto"><table class="backlog">
        <thead><tr><th style="width:28px"><input type="checkbox" data-bl-all ${rows.length && rows.every((p) => st.selected.has(p.id)) ? "checked" : ""} title="Select all ${rows.length} matching"></th>
          <th>Page idea</th><th>Type · cluster</th><th style="text-align:center" title="Agent score 0–100: search intent × competition × ICP fit">Score</th><th>Why</th><th></th></tr></thead>
        <tbody>${shown.map((p) => backlogRow(p, st, showProject, projectsById)).join("") || `<tr><td colspan="6" class="muted" style="text-align:center; padding:18px">No ideas match this filter.</td></tr>`}</tbody></table>
        ${rows.length > shown.length ? `<div style="padding:10px; text-align:center"><button class="btn btn-sm" data-bl-more>Show ${Math.min(100, rows.length - shown.length)} more of ${rows.length - shown.length}</button></div>` : ""}
      </div>` : `<div class="empty">No ideas yet. ${hasAgent ? "Run the <b>landing page agent</b> — each run researches competitors and adds a batch of scored page ideas here." : "Add the landing page agent (above) to start generating ideas, or add pages manually with status <b>idea</b>."}</div>`}
    </div>`;
  };

  async function bulkDevinModal(pages, rerender) {
    const pid = pages[0].project_id;
    if (pages.some((p) => p.project_id !== pid)) { alert("Select ideas from a single project to send them to one Devin session."); return; }
    if (pages.length > 50) { alert("Send at most 50 pages per Devin session."); return; }
    const status = await api("/api/devin/status");
    openModal(`
      <h2><span class="devin-mark">◆</span> Build ${pages.length} landing page${pages.length === 1 ? "" : "s"} with Devin</h2>
      ${status.configured ? "" : `<div class="notice">DEVIN_API_KEY is not configured — the session will be recorded as <b>mock</b>.</div>`}
      <form>
        <div class="card" style="max-height:220px; overflow:auto; padding:8px 12px; font-size:12px">
          ${pages.map((p) => `<div class="mono">${esc(p.path)} <span class="muted">— ${esc(p.name)}${p.score != null ? ` · ${p.score}` : ""}</span></div>`).join("")}
        </div>
        <label>Extra instructions <span class="muted">(briefs, headlines and keywords are included automatically)</span></label>
        <textarea name="instructions" rows="4" placeholder="Reuse the existing page template; add each new page to the sitemap; one PR for the whole batch."></textarea>
        <label><input type="checkbox" name="include_wiki" checked style="width:auto"> Include product wiki as context</label>
        <div class="muted" style="font-size:12px; margin-top:8px">Selected ideas move to <b>draft</b> and get the session link in their notes.</div>
        <div class="form-error"></div>
        <div class="actions"><button class="btn" type="button" data-close>Cancel</button>
          <button class="btn btn-devin" type="submit">◆ Launch session</button></div>
      </form>`, async (fd) => {
      const created = await api("/api/landing-pages/bulk-devin", { method: "POST", body: JSON.stringify({
        ids: pages.map((p) => p.id), instructions: fd.get("instructions") || "", include_wiki: fd.get("include_wiki") === "on" }) });
      window.open(created.url, "_blank", "noopener");
      rerender();
    });
  }

  function bindBacklog(root, pages, key, rerender) {
    const st = stateFor(key);
    const sec = root.querySelector(`#bl-${key}`);
    if (!sec) return;
    const byId = (id) => pages.find((p) => p.id === id);
    const rows = filterBacklog(pages, st);
    const set = (patch) => { Object.assign(st, patch); rerender(); };
    sec.querySelectorAll("[data-bl-status]").forEach((b) => b.addEventListener("click", () => set({ status: b.dataset.blStatus, limit: 50 })));
    const on = (selector, event, fn) => { const el = sec.querySelector(selector); if (el) el.addEventListener(event, fn); };
    on("[data-bl-type]", "change", (e) => set({ type: e.target.value, limit: 50 }));
    on("[data-bl-cluster]", "change", (e) => set({ cluster: e.target.value, limit: 50 }));
    on("[data-bl-score]", "change", (e) => set({ minScore: Number(e.target.value), limit: 50 }));
    on("[data-bl-q]", "input", (e) => {
      clearTimeout(st._t); st._t = setTimeout(() => set({ q: e.target.value, limit: 50 }), 250);
    });
    on("[data-bl-more]", "click", () => set({ limit: st.limit + 100 }));
    on("[data-bl-all]", "change", (e) => {
      if (e.target.checked) rows.forEach((p) => st.selected.add(p.id)); else rows.forEach((p) => st.selected.delete(p.id));
      rerender();
    });
    on("[data-bl-clear]", "click", () => { st.selected.clear(); rerender(); });
    sec.querySelectorAll("[data-bl-sel]").forEach((cb) => cb.addEventListener("change", () => {
      if (cb.checked) st.selected.add(cb.dataset.blSel); else st.selected.delete(cb.dataset.blSel);
      rerender();
    }));
    sec.querySelectorAll("[data-bl-bulk]").forEach((b) => b.addEventListener("click", async () => {
      const ids = [...st.selected].filter(byId);
      if (!ids.length) return;
      b.disabled = true; b.textContent = "…";
      try {
        await api("/api/landing-pages/bulk-status", { method: "POST", body: JSON.stringify({ ids, status: b.dataset.blBulk }) });
        st.selected.clear();
      } catch (ex) { alert(ex.message); }
      rerender();
    }));
    on("[data-bl-bulk-devin]", "click", () => {
      const sel = [...st.selected].map(byId).filter(Boolean);
      if (sel.length) bulkDevinModal(sel, () => { st.selected.clear(); rerender(); });
    });
    on("[data-bl-bulk-alerts]", "click", () => {
      const sel = [...st.selected].map(byId).filter(Boolean);
      if (sel.length) alertsFromIdeasModal(sel, () => { st.selected.clear(); rerender(); });
    });
    sec.querySelectorAll("[data-bl-edit]").forEach((b) => b.addEventListener("click", () => {
      const p = byId(b.dataset.blEdit); V2.landingModal(p.project_id, p, rerender);
    }));
    sec.querySelectorAll("[data-bl-devin]").forEach((b) => b.addEventListener("click", () => bulkDevinModal([byId(b.dataset.blDevin)], rerender)));
  }

  /* ── PageDrones alert templates: theme → candidates → vet → bulk publish → live /alerts pages ── */
  const ALERT_STATUSES = ["candidate", "vetted", "published", "rejected"];
  const alertState = {};
  function alertStateFor(key) {
    return alertState[key] || (alertState[key] = { status: "candidate", q: "", selected: new Set(), notice: "" });
  }

  function alertsFromIdeasModal(pages, rerender) {
    const pid = pages[0].project_id;
    if (pages.some((p) => p.project_id !== pid)) { alert("Select ideas from a single project."); return; }
    if (pages.length > 10) { alert("Generate from at most 10 themes at once (each theme is one PageDrones batch)."); return; }
    openModal(`
      <h2>⚡ Generate alert templates from ${pages.length} theme${pages.length === 1 ? "" : "s"}</h2>
      <form>
        <div class="card" style="max-height:200px; overflow:auto; padding:8px 12px; font-size:12px">
          ${pages.map((p) => `<div><b>${esc(p.headline || p.name)}</b>${p.page_type !== "use_case" ? ` <span class="muted">(${esc(typeLabel(p.page_type))} — works best with use-case ideas)</span>` : ""}<div class="muted clamp-2">${esc(p.angle || "")}</div></div>`).join("")}
        </div>
        <div class="grid-2">
          <div><label>Alerts per theme</label><input name="n" type="number" min="1" max="50" value="10"></div>
          <div><label style="margin-top:26px"><input type="checkbox" name="vet" style="width:auto"> Vet immediately <span class="muted">(runs each alert once; slow, costs API calls)</span></label></div>
        </div>
        <label>Extra guidance for PageDrones <span class="muted">(optional)</span></label>
        <textarea name="notes" rows="3" placeholder="Prefer alerts that fire weekly at most; cite official sources; avoid paywalled sites."></textarea>
        <div class="muted" style="font-size:12px; margin-top:8px">Creates <b>candidates</b> in PageDrones — nothing goes public until you vet and bulk-publish them below. Ideas move to <b>draft</b> and remember their batch.</div>
        <div class="form-error"></div>
        <div class="actions"><button class="btn" type="button" data-close>Cancel</button>
          <button class="btn btn-primary" type="submit">⚡ Generate</button></div>
      </form>`, async (fd) => {
      const res = await api(`/api/pagedrones/projects/${pid}/generate-from-ideas`, { method: "POST", body: JSON.stringify({
        ids: pages.map((p) => p.id), n: Number(fd.get("n")) || 10, vet: fd.get("vet") === "on", notes: fd.get("notes") || "" }) });
      const st = alertStateFor(pid);
      st.status = res.vetted ? "vetted" : "candidate";
      st.notice = `${res.inserted} alert candidate${res.inserted === 1 ? "" : "s"} generated from ${res.themes} theme${res.themes === 1 ? "" : "s"}${res.vetted ? ` · ${res.vetted} vetted, ${res.rejected} rejected` : ""}${res.failed ? ` · <span style="color:var(--bad)">${res.failed} theme${res.failed === 1 ? "" : "s"} failed: ${esc(res.results.filter((r) => r.error).map((r) => r.error).join("; "))}</span>` : ""}.${res.results.some((r) => r.mock) ? " <span class=\"muted\">(PageDrones ran in mock mode — no LLM key there.)</span>" : ""}`;
      rerender();
    });
  }

  function alertGenerateModal(pid, rerender) {
    openModal(`
      <h2>⚡ Generate alert templates</h2>
      <form>
        <label>Theme <span class="muted">(audience + what changes)</span></label>
        <input name="theme" required minlength="3" maxlength="300" placeholder="Compliance leads tracking new state privacy regulations">
        <div class="grid-3">
          <div><label>How many</label><input name="n" type="number" min="1" max="50" value="10"></div>
          <div><label>Category</label><input name="category" maxlength="80" placeholder="compliance"></div>
          <div><label>Audience</label><input name="audience" maxlength="200" placeholder="compliance officers"></div>
        </div>
        <label>Notes for the generator</label><textarea name="notes" rows="3" maxlength="2000"></textarea>
        <label><input type="checkbox" name="vet" style="width:auto"> Vet immediately <span class="muted">(runs each alert once)</span></label>
        <div class="muted" style="font-size:12px; margin-top:8px">Tip: select <b>use-case</b> ideas in the backlog and use “Alerts from N” to keep themes linked to their landing-page idea.</div>
        <div class="form-error"></div>
        <div class="actions"><button class="btn" type="button" data-close>Cancel</button>
          <button class="btn btn-primary" type="submit">⚡ Generate</button></div>
      </form>`, async (fd) => {
      const body = { theme: fd.get("theme"), n: Number(fd.get("n")) || 10, category: fd.get("category") || "", audience: fd.get("audience") || "", notes: fd.get("notes") || "", vet: fd.get("vet") === "on" };
      const res = await api(`/api/pagedrones/projects/${pid}/generate`, { method: "POST", body: JSON.stringify(body) });
      const st = alertStateFor(pid);
      st.status = res.vetted ? "vetted" : "candidate";
      st.notice = `${res.inserted} candidate${res.inserted === 1 ? "" : "s"} generated${res.skipped ? ` (${res.skipped} duplicates skipped)` : ""}${res.vetted ? ` · ${res.vetted} vetted, ${res.rejected} rejected` : ""}.${res.mock ? " <span class=\"muted\">(PageDrones ran in mock mode.)</span>" : ""}`;
      rerender();
    });
  }

  function alertRow(t, st) {
    const score = t.vet_score;
    return `<tr class="${st.selected.has(t.id) ? "selected" : ""}">
      <td style="width:28px"><input type="checkbox" data-al-sel="${t.id}" ${st.selected.has(t.id) ? "checked" : ""}></td>
      <td>
        <div><strong>${t.status === "published" ? `<a href="${esc(t.url)}" target="_blank" rel="noopener">${esc(t.title)}</a>` : esc(t.title)}</strong> ${badge(t.status)}</div>
        <div class="mono muted" style="font-size:11px">/alerts/${esc(t.slug)}${t.default_schedule ? ` · ${esc(t.default_schedule)}` : ""}</div>
        ${t.headline ? `<div class="muted clamp-2" style="font-size:12px; margin-top:2px">“${esc(t.headline)}”</div>` : ""}
      </td>
      <td><span class="badge">${esc(t.category || "general")}</span>${t.theme ? `<div class="muted clamp-2" style="font-size:11px; margin-top:3px; max-width:220px" title="${esc(t.theme)}">${esc(t.theme)}</div>` : ""}</td>
      <td style="text-align:center">${scoreChip(score)}</td>
      <td class="muted" style="font-size:12px; max-width:340px" title="${esc(t.vet_notes || "")}${t.sample_output ? `\n\nSample:\n${esc(t.sample_output).slice(0, 600)}` : ""}"><div class="clamp-2">${esc(t.vet_notes || (t.status === "candidate" ? "not vetted yet" : ""))}</div></td>
      <td class="mono" style="text-align:right">${t.status === "published" ? num(t.subscribers) : `<span class="muted">—</span>`}</td>
    </tr>`;
  }

  V2.alertsSection = function (pd, key) {
    const st = alertStateFor(key);
    const by = (pd.stats && pd.stats.by_status) || {};
    const counts = Object.fromEntries(ALERT_STATUSES.map((s) => [s, by[s] || 0]));
    const q = st.q.trim().toLowerCase();
    const rows = (pd.templates || [])
      .filter((t) => st.status === "all" || t.status === st.status)
      .filter((t) => !q || [t.title, t.slug, t.theme, t.category, t.headline].some((v) => String(v || "").toLowerCase().includes(q)))
      .sort((a, b) => (b.vet_score ?? -1) - (a.vet_score ?? -1) || (a.created_at < b.created_at ? 1 : -1));
    const selected = rows.filter((t) => st.selected.has(t.id));
    const sel = selected.length;
    const vettedSel = selected.filter((t) => t.status === "vetted").length;
    const publishedSel = selected.filter((t) => t.status === "published").length;
    const hostLabel = pd.stats ? pd.stats.base_url.replace(/^https?:\/\//, "") : "";
    return `<div class="section" style="margin-top:24px" id="alerts-${esc(key)}">
      <div class="section-head"><h2>⚡ Alert templates <span class="muted">(${counts.candidate} candidates · ${counts.vetted} vetted · ${counts.published} published · ${num(pd.stats ? pd.stats.subscribers : 0)} subscribers)</span></h2>
        <span>${pd.stats ? `<a class="btn btn-sm" href="${esc(pd.stats.alerts_url)}" target="_blank" rel="noopener">${esc(hostLabel)}/alerts ↗</a>` : ""}
          <button class="btn btn-sm" data-al-sync title="Mirror every published template as a live landing page (and retire unpublished ones)">Sync pages</button>
          <button class="btn btn-sm" data-al-vet-next title="Run the 10 oldest candidates through the real pipeline">Vet next 10</button>
          <button class="btn btn-sm btn-primary" data-al-generate>⚡ Generate from theme</button></span></div>
      <div class="muted" style="font-size:12px; margin-bottom:8px">Pre-built drones users subscribe to from public <code>/alerts/&lt;slug&gt;</code> pages. Flow: generate candidates from a theme → <b>vet</b> (each alert actually runs once; empty/thin reports are rejected) → select vetted ones → <b>publish</b>. Published templates become live landing pages here automatically.</div>
      <div id="al-status">${st.notice ? `<div class="notice">${st.notice}</div>` : ""}${pd.error ? `<div class="notice">PageDrones unreachable: ${esc(pd.error)} — check the integration under <a href="#/settings">Settings → Integrations</a>.</div>` : ""}</div>
      ${pd.templates ? `
      <div class="card-row filter-bar">
        <span class="seg">${[...ALERT_STATUSES, "all"].map((s) => `<button class="btn btn-sm ${st.status === s ? "btn-primary" : ""}" data-al-status="${s}">${s}${s === "all" ? "" : ` (${counts[s]})`}</button>`).join("")}</span>
        <input data-al-q placeholder="search title, slug, theme…" value="${esc(st.q)}" style="width:220px">
        <span class="muted" style="font-size:12px; margin-left:auto">${rows.length} match${rows.length === 1 ? "" : "es"}</span>
      </div>
      <div class="bulk-bar ${sel ? "" : "hidden"}">
        <b>${sel} selected</b>
        <button class="btn btn-sm" data-al-bulk="vet" ${sel - publishedSel ? "" : "disabled"} title="Run the selected alerts once and score them">▶ Vet</button>
        <button class="btn btn-sm btn-primary" data-al-bulk="published" ${vettedSel ? "" : "disabled"} title="Only vetted templates can be published">↑ Publish ${vettedSel}${vettedSel !== sel ? ` of ${sel}` : ""}</button>
        <button class="btn btn-sm" data-al-bulk="vetted" ${publishedSel ? "" : "disabled"} title="Take published templates offline (their landing pages retire)">↓ Unpublish ${publishedSel || ""}</button>
        <button class="btn btn-sm" data-al-bulk="rejected">✕ Reject</button>
        <button class="btn btn-sm" data-al-clear style="margin-left:auto">Clear</button>
      </div>
      <div class="card" style="padding:0; overflow-x:auto"><table class="backlog">
        <thead><tr><th style="width:28px"><input type="checkbox" data-al-all ${rows.length && rows.every((t) => st.selected.has(t.id)) ? "checked" : ""}></th>
          <th>Alert</th><th>Category · theme</th><th style="text-align:center" title="Vet score 0–100 from a real run: results found × substance × cost">Vet</th><th>Vet notes</th><th style="text-align:right">Subs</th></tr></thead>
        <tbody>${rows.slice(0, 200).map((t) => alertRow(t, st)).join("") || `<tr><td colspan="6" class="muted" style="text-align:center; padding:18px">${pd.templates.length ? "No templates match this filter." : "No alert templates yet — generate a batch from a theme, or select use-case ideas in the backlog and click “Alerts from N”."}</td></tr>`}</tbody></table>
        ${rows.length > 200 ? `<div class="muted" style="padding:10px; text-align:center">Showing 200 of ${rows.length} — narrow the filter.</div>` : ""}
      </div>` : ""}
    </div>`;
  };

  function bindAlerts(root, pd, pid, rerender) {
    const sec = root.querySelector(`#alerts-${pid}`);
    if (!sec) return;
    const st = alertStateFor(pid);
    st.notice = "";
    const on = (selector, event, fn) => { const el = sec.querySelector(selector); if (el) el.addEventListener(event, fn); };
    const busy = (b, label) => { b.disabled = true; b.textContent = label; };
    const run = async (b, label, fn) => {
      busy(b, label);
      try { st.notice = await fn(); st.selected.clear(); } catch (ex) { st.notice = `<span style="color:var(--bad)">${esc(ex.message)}</span>`; }
      rerender();
    };
    on("[data-al-generate]", "click", () => alertGenerateModal(pid, rerender));
    on("[data-al-sync]", "click", (e) => run(e.target, "Syncing…", async () => {
      const r = await api(`/api/pagedrones/projects/${pid}/sync`, { method: "POST" });
      return `Synced ${r.published} published template${r.published === 1 ? "" : "s"}: ${r.registered} new page${r.registered === 1 ? "" : "s"}, ${r.updated} updated, ${r.retired} retired · ${num(r.subscribers)} subscribers.`;
    }));
    on("[data-al-vet-next]", "click", (e) => run(e.target, "Vetting… (1–3 min)", async () => {
      const r = await api(`/api/pagedrones/projects/${pid}/vet`, { method: "POST", body: JSON.stringify({ limit: 10 }) });
      st.status = "vetted";
      return `Vetted ${r.templates.length}: <b>${r.vetted} passed</b>, ${r.rejected} rejected.`;
    }));
    sec.querySelectorAll("[data-al-status]").forEach((b) => b.addEventListener("click", () => { st.status = b.dataset.alStatus; rerender(); }));
    on("[data-al-q]", "input", (e) => { clearTimeout(st._t); st._t = setTimeout(() => { st.q = e.target.value; rerender(); }, 250); });
    const rows = (pd.templates || []);
    on("[data-al-all]", "change", (e) => {
      const visible = rows.filter((t) => st.status === "all" || t.status === st.status);
      if (e.target.checked) visible.forEach((t) => st.selected.add(t.id)); else visible.forEach((t) => st.selected.delete(t.id));
      rerender();
    });
    on("[data-al-clear]", "click", () => { st.selected.clear(); rerender(); });
    sec.querySelectorAll("[data-al-sel]").forEach((cb) => cb.addEventListener("change", () => {
      if (cb.checked) st.selected.add(cb.dataset.alSel); else st.selected.delete(cb.dataset.alSel);
      rerender();
    }));
    sec.querySelectorAll("[data-al-bulk]").forEach((b) => b.addEventListener("click", () => {
      const ids = [...st.selected].filter((id) => rows.some((t) => t.id === id));
      if (!ids.length) return;
      const action = b.dataset.alBulk;
      if (action === "vet") {
        const todo = ids.filter((id) => rows.find((t) => t.id === id).status !== "published");
        return run(b, "Vetting… (1–3 min)", async () => {
          const r = await api(`/api/pagedrones/projects/${pid}/vet`, { method: "POST", body: JSON.stringify({ ids: todo, limit: todo.length }) });
          st.status = "vetted";
          return `Vetted ${r.templates.length}: <b>${r.vetted} passed</b>, ${r.rejected} rejected.`;
        });
      }
      let todo = ids;
      if (action === "published") {
        todo = ids.filter((id) => rows.find((t) => t.id === id).status === "vetted");
        if (!confirm(`Publish ${todo.length} vetted alert template${todo.length === 1 ? "" : "s"}? They go live on /alerts immediately and become landing pages here.`)) return;
      } else if (action === "vetted") {
        todo = ids.filter((id) => rows.find((t) => t.id === id).status === "published");
      }
      return run(b, "…", async () => {
        const r = await api(`/api/pagedrones/projects/${pid}/templates/bulk-status`, { method: "POST", body: JSON.stringify({ ids: todo, status: action }) });
        if (action === "published") st.status = "published";
        const s = r.sync || {};
        return `${r.updated} template${r.updated === 1 ? "" : "s"} → <b>${esc(action)}</b>${r.sync ? ` · landing pages: ${s.registered} new, ${s.updated} updated, ${s.retired} retired` : ""}.`;
      });
    }));
  }

  /* ── competitors (per project) ── */
  function competitorRow(c) {
    const types = Object.entries(c.page_types || {}).sort((a, b) => b[1] - a[1]).slice(0, 5);
    return `<tr style="${c.status === "ignored" ? "opacity:0.55" : ""}">
      <td><div><strong><a href="${esc(c.url)}" target="_blank" rel="noopener">${esc(c.name)}</a></strong> ${c.status === "ignored" ? badge("ignored") : ""}${c.source === "agent" ? `<span class="muted" style="font-size:11px" title="Discovered by the landing page agent"> ✦</span>` : ""}</div>
        <div class="mono muted" style="font-size:11px">${esc(c.domain)}${c.pricing ? ` · ${esc(c.pricing)}` : ""}</div></td>
      <td class="muted" style="font-size:12px; max-width:380px" title="${esc(c.positioning)}${c.strengths ? `\n\nStrengths: ${esc(c.strengths)}` : ""}${c.weaknesses ? `\n\nWeaknesses: ${esc(c.weaknesses)}` : ""}"><div class="clamp-2">${esc(c.positioning || c.notes || "")}</div></td>
      <td><div class="mono">${num(c.page_count)} <span class="muted" style="font-size:11px">pages</span></div>
        <div class="muted" style="font-size:11px">${types.map(([t, n]) => `${esc(typeLabel(t))} ${n}`).join(" · ")}</div></td>
      <td class="muted" style="font-size:12px; white-space:nowrap">${c.crawl_error ? `<span style="color:var(--bad)" title="${esc(c.crawl_error)}">crawl failed</span><br>` : ""}${ago(c.crawled_at)}</td>
      <td style="text-align:right; white-space:nowrap">
        <button class="btn btn-sm" data-comp-crawl="${c.id}" title="Re-crawl sitemap and page metadata">Recrawl</button>
        <button class="btn btn-sm" data-comp-toggle="${c.id}">${c.status === "ignored" ? "Unignore" : "Ignore"}</button>
        <button class="btn btn-sm btn-danger" data-comp-del="${c.id}" title="Delete">✕</button>
      </td>
    </tr>`;
  }

  V2.competitorsSection = function (comps) {
    const active = comps.filter((c) => c.status === "active");
    const pages = active.reduce((s, c) => s + c.page_count, 0);
    return `<div class="section" style="margin-top:24px" id="competitors">
      <div class="section-head"><h2>Competitors <span class="muted">(${active.length} tracked · ${num(pages)} pages indexed)</span></h2>
        <span><button class="btn btn-sm" id="comp-discover" title="Web-search for competitors and crawl their sites (1–2 min)">Discover competitors</button>
          <button class="btn btn-sm" id="comp-add">+ Competitor</button></span></div>
      <div id="comp-status"></div>
      ${comps.length ? `<div class="card" style="padding:0; overflow-x:auto"><table>
        <thead><tr><th>Competitor</th><th>Positioning</th><th>Site inventory</th><th>Crawled</th><th></th></tr></thead>
        <tbody>${comps.map(competitorRow).join("")}</tbody></table></div>`
        : `<div class="empty">No competitors yet. <b>Discover</b> uses web search to find them and crawls their sitemaps so the agent can see which pages they rank with; or add one by URL.</div>`}
    </div>`;
  };

  function competitorModal(projectId, rerender) {
    openModal(`
      <h2>Add competitor</h2>
      <form>
        <div class="grid-2">
          <div><label>Name</label><input name="name" required placeholder="Spreeder"></div>
          <div><label>URL</label><input name="url" required placeholder="https://www.spreeder.com"></div>
        </div>
        <label>Positioning <span class="muted">(how they pitch themselves)</span></label><textarea name="positioning" rows="2"></textarea>
        <label>Pricing</label><input name="pricing" placeholder="$7.99/mo">
        <label>Notes</label><textarea name="notes" rows="2"></textarea>
        <div class="muted" style="font-size:12px; margin-top:8px">Saving crawls the site's sitemap (up to 600 URLs, ~30s).</div>
        ${actionsRow()}
      </form>`, async (fd) => {
      const body = {};
      for (const k of ["name", "url", "positioning", "pricing", "notes"]) body[k] = fd.get(k);
      await api(`/api/competitors/projects/${projectId}`, { method: "POST", body: JSON.stringify(body) });
      rerender();
    });
  }

  function bindCompetitors(root, comps, projectId, rerender) {
    const sec = root.querySelector("#competitors");
    if (!sec) return;
    const status = sec.querySelector("#comp-status");
    sec.querySelector("#comp-add").addEventListener("click", () => competitorModal(projectId, rerender));
    const disc = sec.querySelector("#comp-discover");
    disc.addEventListener("click", async () => {
      disc.disabled = true; disc.textContent = "Searching…";
      status.innerHTML = `<div class="notice">Searching the web for competitors and crawling their sitemaps… usually 1–2 minutes.</div>`;
      try {
        const res = await api(`/api/competitors/projects/${projectId}/discover`, { method: "POST" });
        await rerender();
        const s = root.querySelector("#comp-status");
        if (s) s.innerHTML = `<div class="notice">${res.mock ? "ANTHROPIC_API_KEY is not configured — discovery ran in mock mode. " : ""}<b>${res.competitors.length} new competitor${res.competitors.length === 1 ? "" : "s"}</b> found${res.competitors.length ? `: ${res.competitors.map((c) => esc(c.name)).join(", ")}` : ""}.${res.market_notes ? `<div class="muted" style="font-size:12px; margin-top:6px">${esc(res.market_notes)}</div>` : ""}</div>`;
      } catch (ex) {
        status.innerHTML = `<div class="notice">Discovery failed: ${esc(ex.message)}</div>`;
        disc.disabled = false; disc.textContent = "Discover competitors";
      }
    });
    sec.querySelectorAll("[data-comp-crawl]").forEach((b) => b.addEventListener("click", async () => {
      b.disabled = true; b.textContent = "…";
      try { await api(`/api/competitors/${b.dataset.compCrawl}/crawl`, { method: "POST" }); } catch (ex) { alert(ex.message); }
      rerender();
    }));
    sec.querySelectorAll("[data-comp-toggle]").forEach((b) => b.addEventListener("click", async () => {
      const c = comps.find((x) => x.id === b.dataset.compToggle);
      await api(`/api/competitors/${c.id}`, { method: "PATCH", body: JSON.stringify({ status: c.status === "ignored" ? "active" : "ignored" }) });
      rerender();
    }));
    sec.querySelectorAll("[data-comp-del]").forEach((b) => b.addEventListener("click", async () => {
      if (!confirm("Delete this competitor and its cached inventory?")) return;
      await api(`/api/competitors/${b.dataset.compDel}`, { method: "DELETE" });
      rerender();
    }));
  }

  function daysSeg(days) {
    return `<span class="seg">${[7, 30, 90].map((d) => `<button class="btn btn-sm ${d === days ? "btn-primary" : ""}" data-days="${d}">${d}d</button>`).join("")}</span>`;
  }

  /* ── global dashboard: #/landing-pages ── */
  V2.renderLandingPages = async function (days = 30, filter = {}) {
    days = Number(days) || 30;
    const [perf, projects, recs, allPages, agents] = await Promise.all([
      api(`/api/landing-pages/performance?days=${days}`), api("/api/projects"),
      api("/api/recommendations?status=open&limit=200"), api("/api/landing-pages"),
      api("/api/agents"),
    ]);
    const lpRecs = recs.filter((r) => r.kind === "landing_page" && (!filter.project || r.project_id === filter.project));
    const rows = perf.pages.filter((r) => (!filter.project || r.page.project_id === filter.project) && (!filter.status || r.page.status === filter.status));
    const shown = { ...perf, pages: rows, discovered: perf.discovered.filter((d) => !filter.project || d.project_id === filter.project) };
    const backlog = allPages.filter((p) => !filter.project || p.project_id === filter.project);
    const hasAgent = agents.some((a) => a.kind === "landing_pages" && (!filter.project || a.project_id === filter.project));
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
          ${["live", "draft", "retired"].map((s) => `<button class="btn btn-sm ${filter.status === s ? "btn-primary" : ""}" data-st="${s}">${s}</button>`).join("")}
        </span>
      </div>
      ${V2.landingTable(shown, { showProject: true }) || `<div class="empty">${perf.pages.length ? "No pages match this filter." : `No live or draft landing pages registered yet. Add one, track an untracked path below, or vet ideas from the backlog and send them to Devin.<br><span class="muted" style="font-size:12px">Tracking works via the events ingest / PostHog: <code>visit</code> events with <code>properties.path</code>.</span>`}</div>`}
      ${discoveredList(shown, true)}
      ${V2.backlogSection(backlog, { key: "global", showProject: true, projects, hasAgent })}
      <div class="section" style="margin-top:24px">
        <div class="section-head"><h2>Strategic recommendations <span class="muted">(${lpRecs.length} open)</span></h2><a href="#/inbox" class="muted" style="font-size:12px">all recommendations →</a></div>
        <div class="grid-2">${lpRecs.map((r) => V2.recCard(r, { showProject: true, projects })).join("") || `<div class="empty">Nothing open. The landing page agent's strategic actions (prioritise, rewrite, test, retire) land here after each run.</div>`}</div>
      </div>`;
    document.getElementById("add-lp").addEventListener("click", () => {
      if (!projects.length) { alert("Create a project first."); return; }
      V2.landingModal(filter.project || null, null, rerender, {}, projects);
    });
    $view.querySelectorAll("[data-days]").forEach((b) => b.addEventListener("click", () => V2.renderLandingPages(b.dataset.days, filter)));
    $view.querySelectorAll("[data-proj]").forEach((b) => b.addEventListener("click", () => V2.renderLandingPages(days, { ...filter, project: b.dataset.proj || null })));
    $view.querySelectorAll("[data-st]").forEach((b) => b.addEventListener("click", () => V2.renderLandingPages(days, { ...filter, status: b.dataset.st || null })));
    bindTable($view, shown, rerender);
    bindBacklog($view, backlog, "global", rerender);
    V2.bindRecCards($view, lpRecs, rerender);
  };

  /* ── project tab ── */
  V2.tabs.landing = async function (id, p, root, days) {
    days = Number(days) || 30;
    const [perf, recs, agents, pages, comps, integrations] = await Promise.all([
      api(`/api/landing-pages/performance?project_id=${id}&days=${days}`),
      api(`/api/recommendations?project_id=${id}&status=open`),
      api(`/api/agents?project_id=${id}`),
      api(`/api/landing-pages?project_id=${id}`),
      api(`/api/competitors?project_id=${id}`),
      api("/api/integrations"),
    ]);
    const pdInteg = integrations.find((i) => i.provider === "pagedrones" && i.project_id === id);
    let pd = null;
    if (pdInteg) {
      pd = { integration: pdInteg, stats: null, templates: null, error: "" };
      try {
        [pd.stats, pd.templates] = await Promise.all([
          api(`/api/pagedrones/projects/${id}/stats`), api(`/api/pagedrones/projects/${id}/templates?limit=2000`)]);
      } catch (ex) { pd.error = ex.message; }
    }
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
        ${V2.landingTable(perf, { project: p }) || `<div class="empty">No live or draft landing pages for ${esc(p.name)} yet.<br><span class="muted" style="font-size:12px">Register the pages you already have (path = what you send as <code>properties.path</code> on <code>visit</code> events), then let the agent fill the backlog below.</span></div>`}
        ${discoveredList(perf, false)}
      </div>
      ${V2.backlogSection(pages, { key: id, hasAgent: !!agent, alerts: !!pd })}
      ${pd ? V2.alertsSection(pd, id) : ""}
      <div class="section" style="margin-top:24px">
        <div class="section-head"><h2>Strategic recommendations <span class="muted">(${lpRecs.length} open)</span></h2></div>
        <div class="grid-2">${lpRecs.map((r) => V2.recCard(r)).join("") || `<div class="muted" style="font-size:12px">Nothing open. ${agent ? "Each agent run adds ideas to the backlog and 3–6 strategic actions (prioritise, rewrite, test, retire) here." : "Add the landing page agent to get ideas and recommendations."}</div>`}</div>
      </div>
      ${V2.competitorsSection(comps)}`;
    document.getElementById("add-lp").addEventListener("click", () => V2.landingModal(id, null, rerender));
    root.querySelectorAll("[data-days]").forEach((b) => b.addEventListener("click", () => { location.hash = `#/p/${id}/landing/${b.dataset.days}`; }));
    const run = document.getElementById("run-lp-agent");
    if (run) run.addEventListener("click", async () => {
      const status = document.getElementById("lp-agent-status");
      run.textContent = "Running…"; run.disabled = true;
      const working = (secs) => `<div class="notice">Landing page agent is researching competitors, reading the wiki + keywords and generating a batch of page ideas… usually 1–3 minutes${secs ? ` (${secs}s)` : ""}. You can leave this tab; the run finishes on the server.</div>`;
      status.innerHTML = working();
      let result;
      try { result = await runAgent(agent.id, { onTick: (_r, secs) => { status.innerHTML = working(secs); } }); }
      catch (ex) { status.innerHTML = `<div class="notice">Run failed: ${esc(ex.message)}. <a href="#/p/${id}/agents">Run history →</a></div>`; run.textContent = "Run landing page agent"; run.disabled = false; return; }
      if (!status.isConnected) return;
      await rerender();
      const s = document.getElementById("lp-agent-status");
      const lead = esc((result.summary || "").split("\n")[0]).replace(/^_(.+?)\._$/, "<b>$1</b>.");
      if (s) s.innerHTML = `<div class="notice">Run ${esc(result.status)}${result.error ? ` — ${esc(result.error)}` : ""}${lead ? `: ${lead}` : ""} New ideas are in the <a href="#bl-${id}">backlog</a>; strategic actions below. <a href="#/p/${id}/agents">Run history →</a></div>`;
    });
    const add = document.getElementById("add-lp-agent");
    if (add) add.addEventListener("click", async () => {
      await api("/api/agents", { method: "POST", body: JSON.stringify({ project_id: id, kind: "landing_pages", name: "Landing page agent", schedule: "weekly" }) });
      rerender();
    });
    bindTable(root, perf, rerender);
    bindBacklog(root, pages, id, rerender);
    if (pd) bindAlerts(root, pd, id, rerender);
    bindCompetitors(root, comps, id, rerender);
    V2.bindRecCards(root, lpRecs, rerender);
  };
})();
