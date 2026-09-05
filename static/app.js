/* InfiniSaaS cockpit — vanilla JS hash-routed SPA */

const $view = document.getElementById("view");
const $backdrop = document.getElementById("modal-backdrop");
const $modal = document.getElementById("modal");

const CHANNELS = ["seo", "paid", "social", "content", "email", "community", "product", "pricing", "other"];
const STAGES = ["idea", "building", "live", "scaling", "paused", "retired"];
const HEALTH = ["unknown", "healthy", "watch", "critical"];
const EXP_STATUSES = ["idea", "planned", "running", "concluded", "abandoned"];
const CAMP_STATUSES = ["planned", "active", "paused", "done"];

/* ── helpers ── */

/* Set by boot.js when Clerk is active; returns a bearer token or null. */
window.__getAuthToken = window.__getAuthToken || (async () => null);

async function api(path, opts = {}) {
  const headers = { "Content-Type": "application/json" };
  const token = await window.__getAuthToken();
  if (token) headers.Authorization = `Bearer ${token}`;
  const res = await fetch(path, { headers, ...opts });
  if (res.status === 401 && window.INFINI && window.INFINI.authEnabled && window.__signIn) {
    window.__signIn();
    throw new Error("Sign in required");
  }
  if (!res.ok) {
    let detail = res.statusText;
    try { detail = (await res.json()).detail || detail; } catch { /* noop */ }
    throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
  }
  return res.status === 204 ? null : res.json();
}

function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));
}

function badge(value) {
  return `<span class="badge ${esc(value)}">${esc(value)}</span>`;
}

function fmtValue(v, kind, unit) {
  const n = Number(v);
  const s = n >= 1000 ? n.toLocaleString("en-US", { maximumFractionDigits: 0 })
    : n.toLocaleString("en-US", { maximumFractionDigits: 2 });
  if (kind === "currency") return `$${s}`;
  return unit ? `${s} ${unit}` : s;
}

function fmtDate(iso) {
  if (!iso) return "—";
  return new Date(iso).toLocaleDateString("en-US", { month: "short", day: "numeric" });
}

function sparkline(points, color, w = 160, h = 36) {
  if (!points || points.length < 2) {
    return `<div class="muted mono" style="font-size:11px">no data yet</div>`;
  }
  const vals = points.map((p) => p.value);
  const min = Math.min(...vals);
  const max = Math.max(...vals);
  const span = max - min || 1;
  const pts = points.map((p, i) => {
    const x = (i / (points.length - 1)) * (w - 4) + 2;
    const y = h - 4 - ((p.value - min) / span) * (h - 8);
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  }).join(" ");
  return `<svg class="spark" viewBox="0 0 ${w} ${h}" preserveAspectRatio="none" aria-hidden="true">
    <polyline points="${pts}" stroke="${esc(color)}"/></svg>`;
}

function bigChart(points, color, kind, unit, emptyMsg = "Not enough datapoints to chart yet — add a few below.") {
  const w = 560, h = 140;
  if (!points || points.length < 2) {
    return `<div class="empty">${emptyMsg}</div>`;
  }
  const vals = points.map((p) => p.value);
  const min = Math.min(...vals);
  const max = Math.max(...vals);
  const span = max - min || 1;
  const pts = points.map((p, i) => {
    const x = (i / (points.length - 1)) * (w - 8) + 4;
    const y = h - 18 - ((p.value - min) / span) * (h - 34);
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  }).join(" ");
  const last = points[points.length - 1];
  return `<svg class="metric-chart" viewBox="0 0 ${w} ${h}" preserveAspectRatio="none">
    <polyline points="${pts}" fill="none" stroke="${esc(color)}" stroke-width="2"/>
    <text x="${w - 6}" y="14" text-anchor="end" fill="var(--muted)" font-size="11" font-family="IBM Plex Mono">
      ${esc(fmtValue(last.value, kind, unit))} · ${esc(fmtDate(last.ts))}</text>
  </svg>`;
}

function options(list, selected) {
  return list.map((v) => `<option value="${v}" ${v === selected ? "selected" : ""}>${v}</option>`).join("");
}

/* ── modal ── */

function openModal(html, onSubmit) {
  $modal.innerHTML = html;
  $backdrop.classList.remove("hidden");
  const form = $modal.querySelector("form");
  if (form) {
    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      const err = $modal.querySelector(".form-error");
      try {
        await onSubmit(new FormData(form));
        closeModal();
        render();
      } catch (ex) {
        if (err) err.textContent = ex.message;
      }
    });
  }
  $modal.querySelectorAll("[data-close]").forEach((b) => b.addEventListener("click", closeModal));
  const first = $modal.querySelector("input, select, textarea");
  if (first) first.focus();
}

function closeModal() {
  $backdrop.classList.add("hidden");
  $modal.innerHTML = "";
  $modal.classList.remove("modal-wide");
}

$backdrop.addEventListener("click", (e) => { if (e.target === $backdrop) closeModal(); });
document.addEventListener("keydown", (e) => { if (e.key === "Escape") closeModal(); });

/* ── cockpit ── */

async function renderCockpit() {
  const data = await api("/api/overview");
  const c = data.counts;
  $view.innerHTML = `
    <div class="page-head"><h1>Portfolio cockpit</h1></div>
    <div class="stat-strip">
      <div class="stat"><div class="num">${data.projects.length}</div><div class="lbl">Projects</div></div>
      <div class="stat"><div class="num">${c.running_experiments}</div><div class="lbl">Experiments running</div></div>
      <div class="stat"><div class="num">${c.active_campaigns}</div><div class="lbl">Campaigns active</div></div>
      <div class="stat"><div class="num">${c.total_learnings}</div><div class="lbl">Learnings logged</div></div>
    </div>
    <div id="strips"></div>
    <div id="cockpit-v2"></div>
    <div class="grid-2 section">
      <div>
        <div class="section-head"><h2>Active experiments</h2><a href="#/experiments">all →</a></div>
        <div id="active-exps"></div>
      </div>
      <div>
        <div class="section-head"><h2>Recent learnings</h2><a href="#/learnings">all →</a></div>
        <div id="recent-learnings"></div>
      </div>
    </div>`;

  const strips = document.getElementById("strips");
  strips.innerHTML = data.projects.map((p) => {
    const km = p.key_metric;
    const last = km && km.points.length ? km.points[km.points.length - 1] : null;
    return `<div class="strip" data-goto="#/p/${p.id}" role="link" tabindex="0">
      <div class="accent" style="background:${esc(p.accent_color)}"></div>
      <div>
        <div class="title">${esc(p.name)}</div>
        <div class="sub">${esc(p.url || p.slug)}</div>
      </div>
      <div class="col-hide">${badge(p.stage)}</div>
      <div>${badge(p.health)}</div>
      <div class="col-hide">${km ? sparkline(km.points, p.accent_color) : '<span class="muted mono" style="font-size:11px">no key metric</span>'}</div>
      <div class="kv col-hide">${last ? fmtValue(last.value, km.kind, km.unit) : "—"}
        <div class="sub">${km ? esc(km.name) : ""}</div></div>
    </div>`;
  }).join("") || `<div class="empty">No projects yet. Add your first one.</div>`;

  strips.querySelectorAll("[data-goto]").forEach((el) => {
    const go = () => { location.hash = el.dataset.goto; };
    el.addEventListener("click", go);
    el.addEventListener("keydown", (e) => { if (e.key === "Enter") go(); });
  });

  document.getElementById("active-exps").innerHTML = data.active_experiments.map((e) => `
    <div class="card">
      <div class="card-row">
        <strong>${esc(e.name)}</strong>
        <span>${badge(e.channel)} ${badge(e.status)}</span>
      </div>
      <div class="muted" style="font-size:12px">
        <span style="color:${esc(e.project_accent)}">●</span> ${esc(e.project_name)}
        ${e.hypothesis ? " — " + esc(e.hypothesis) : ""}</div>
    </div>`).join("") || `<div class="empty">Nothing planned or running. Queue up an experiment.</div>`;

  document.getElementById("recent-learnings").innerHTML = data.recent_learnings.map((l) => `
    <div class="card">
      <div>${esc(l.content)}</div>
      <div class="muted" style="font-size:12px; margin-top:4px">
        ${l.project_name ? `<span style="color:${esc(l.project_accent)}">●</span> ${esc(l.project_name)} · ` : ""}${fmtDate(l.created_at)}</div>
    </div>`).join("") || `<div class="empty">No learnings logged yet.</div>`;

  await V2.cockpitExtras(document.getElementById("cockpit-v2"), data.projects);
}

/* ── project detail ── */

const PROJECT_TABS = [
  ["overview", "Overview"], ["wiki", "Wiki"], ["product", "Product"], ["growth", "Growth"],
  ["analytics", "Analytics"], ["finance", "Finance"], ["ops", "Ops"], ["agents", "Agents"],
  ["devin", "Devin"],
];

async function renderProject(id, tab = "overview", sub) {
  const p = await api(`/api/projects/${id}`);
  window.__currentProject = p;

  $view.innerHTML = `
    <div class="page-head">
      <div>
        <div class="detail-head">
          <span class="accent-dot" style="background:${esc(p.accent_color)}"></span>
          <h1>${esc(p.name)}</h1>
          ${badge(p.stage)} ${badge(p.health)}
        </div>
        <div class="muted">${p.url ? `<a href="${esc(p.url)}" target="_blank" rel="noopener">${esc(p.url)}</a> — ` : ""}${esc(p.description)}</div>
      </div>
      <div>
        <button class="btn btn-devin" id="proj-devin">◆ Send to Devin</button>
        <button class="btn" id="edit-project">Edit</button>
        <button class="btn" id="show-token">Ingest token</button>
      </div>
    </div>
    <nav class="tabs" id="proj-tabs">
      ${PROJECT_TABS.map(([k, label]) =>
        `<a href="#/p/${id}/${k}" class="${k === tab ? "active" : ""}">${label}</a>`).join("")}
    </nav>
    <div id="tab-body"></div>`;

  document.getElementById("proj-devin").addEventListener("click", () =>
    V2.devinModal({ project_id: id }));
  bindProjectHeader(id, p);
  const body = document.getElementById("tab-body");
  if (tab === "overview") await renderProjectOverview(id, p, body);
  else if (V2.tabs[tab]) await V2.tabs[tab](id, p, body, sub);
  else body.innerHTML = `<div class="empty">Unknown tab.</div>`;
}

async function renderProjectOverview(id, p, root) {
  const [metricsList, exps, camps] = await Promise.all([
    api(`/api/projects/${id}/metrics`),
    api(`/api/experiments?project_id=${id}`),
    api(`/api/campaigns?project_id=${id}`),
  ]);
  _expCache = exps;

  root.innerHTML = `
    <div class="section" style="margin-top:12px">
      <div class="section-head"><h2>Metrics</h2>
        <span><button class="btn btn-sm" id="add-metric">+ Metric</button></span></div>
      <div id="metric-select-row" style="margin-bottom:10px"></div>
      <div id="metric-chart"></div>
      <div class="card" style="margin-top:10px">
        <form id="add-point-form" style="display:flex; gap:10px; align-items:flex-end; flex-wrap:wrap">
          <div style="flex:1; min-width:120px"><label for="pt-value">Value</label>
            <input id="pt-value" name="value" type="number" step="any" required></div>
          <div style="flex:1; min-width:150px"><label for="pt-date">Date (optional)</label>
            <input id="pt-date" name="date" type="date"></div>
          <button class="btn btn-primary" type="submit">Add datapoint</button>
        </form>
      </div>
    </div>

    <div class="grid-2 section">
      <div>
        <div class="section-head"><h2>Experiments</h2>
          <button class="btn btn-sm" id="add-exp">+ Experiment</button></div>
        <div id="proj-exps"></div>
      </div>
      <div>
        <div class="section-head"><h2>Campaigns</h2>
          <button class="btn btn-sm" id="add-camp">+ Campaign</button></div>
        <div id="proj-camps"></div>
      </div>
    </div>`;

  /* metrics */
  let currentMetric = metricsList.find((m) => m.is_key) || metricsList[0] || null;
  const selRow = document.getElementById("metric-select-row");

  async function drawMetric() {
    const chart = document.getElementById("metric-chart");
    selRow.innerHTML = metricsList.map((m) =>
      `<button class="btn btn-sm ${m.id === (currentMetric && currentMetric.id) ? "btn-primary" : ""}" data-metric="${m.id}">
        ${esc(m.name)}${m.is_key ? " ★" : ""}</button>`).join(" ") || `<span class="muted">No metrics defined.</span>`;
    selRow.querySelectorAll("[data-metric]").forEach((b) => b.addEventListener("click", () => {
      currentMetric = metricsList.find((m) => m.id === b.dataset.metric);
      drawMetric();
    }));
    if (!currentMetric) { chart.innerHTML = `<div class="empty">Define a metric to start charting.</div>`; return; }
    const points = await api(`/api/projects/${id}/metrics/${currentMetric.id}/points?days=365`);
    chart.innerHTML = bigChart(points, p.accent_color, currentMetric.kind, currentMetric.unit);
  }
  await drawMetric();

  document.getElementById("add-point-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    if (!currentMetric) return;
    const fd = new FormData(e.target);
    const bodyData = { value: Number(fd.get("value")), source: "manual" };
    if (fd.get("date")) bodyData.ts = new Date(fd.get("date") + "T12:00:00Z").toISOString();
    await api(`/api/projects/${id}/metrics/${currentMetric.id}/points`, {
      method: "POST", body: JSON.stringify(bodyData),
    });
    e.target.reset();
    await drawMetric();
  });

  document.getElementById("add-metric").addEventListener("click", () => {
    openModal(`
      <h2>New metric</h2>
      <form>
        <label>Key (snake_case)</label><input name="key" required pattern="[a-z0-9][a-z0-9_]*">
        <label>Name</label><input name="name" required>
        <label>Kind</label><select name="kind">${options(["gauge", "counter", "currency"], "gauge")}</select>
        <label>Unit</label><input name="unit" placeholder="e.g. users, $">
        <label><input type="checkbox" name="is_key" style="width:auto"> Key metric (shown on cockpit)</label>
        <div class="form-error"></div>
        <div class="actions"><button class="btn" type="button" data-close>Cancel</button>
          <button class="btn btn-primary" type="submit">Create</button></div>
      </form>`, async (fd) => {
      await api(`/api/projects/${id}/metrics`, {
        method: "POST",
        body: JSON.stringify({
          key: fd.get("key"), name: fd.get("name"), kind: fd.get("kind"),
          unit: fd.get("unit") || "", is_key: fd.get("is_key") === "on",
        }),
      });
    });
  });

  /* experiments + campaigns lists */
  document.getElementById("proj-exps").innerHTML = exps.map(expCard).join("")
    || `<div class="empty">No experiments yet. What's the next growth bet?</div>`;
  bindExpCards(metricsList);
  _campCache = camps;
  document.getElementById("proj-camps").innerHTML = camps.map(campCard).join("")
    || `<div class="empty">No campaigns yet.</div>`;
  bindCampCards();

  document.getElementById("add-exp").addEventListener("click", () => expModal(id, metricsList));
  document.getElementById("add-camp").addEventListener("click", () => campModal(id));
}

function bindProjectHeader(id, p) {
  document.getElementById("show-token").addEventListener("click", async () => {
    const t = await api(`/api/projects/${id}/ingest-token`);
    openModal(`
      <h2>Ingest token</h2>
      <p class="muted">Push metrics from ${esc(p.name)} with:</p>
      <div class="token-box">POST /api/v1/metrics<br>Authorization: Bearer ${esc(t.ingest_token)}<br>{"points": [{"metric": "revenue", "value": 42}]}</div>
      <p class="muted" style="margin-top:10px">Push product events (funnel) with the same token:</p>
      <div class="token-box">POST /api/v1/events<br>{"events": [{"name": "signup", "user_key": "u_123", "properties": {"plan": "pro"}}]}</div>
      <div class="actions"><button class="btn" type="button" data-close>Close</button></div>`);
  });

  document.getElementById("edit-project").addEventListener("click", () => {
    openModal(`
      <h2>Edit project</h2>
      <form>
        <label>Name</label><input name="name" value="${esc(p.name)}" required>
        <label>URL</label><input name="url" value="${esc(p.url || "")}">
        <label>Repo URL</label><input name="repo_url" value="${esc(p.repo_url || "")}" placeholder="https://github.com/owner/repo">
        <label>Stage</label><select name="stage">${options(STAGES, p.stage)}</select>
        <label>Health</label><select name="health">${options(HEALTH, p.health)}</select>
        <label>Accent color</label><input name="accent_color" type="color" value="${esc(p.accent_color)}">
        <label>Description</label><textarea name="description">${esc(p.description)}</textarea>
        <div class="form-error"></div>
        <div class="actions">
          <button class="btn btn-danger" type="button" id="delete-project">Delete</button>
          <button class="btn" type="button" data-close>Cancel</button>
          <button class="btn btn-primary" type="submit">Save</button></div>
      </form>`, async (fd) => {
      await api(`/api/projects/${id}`, {
        method: "PATCH",
        body: JSON.stringify({
          name: fd.get("name"), url: fd.get("url") || null, repo_url: fd.get("repo_url") || null,
          stage: fd.get("stage"),
          health: fd.get("health"), accent_color: fd.get("accent_color"),
          description: fd.get("description"),
        }),
      });
    });
    document.getElementById("delete-project").addEventListener("click", async () => {
      if (!confirm(`Delete ${p.name} and all its data?`)) return;
      await api(`/api/projects/${id}`, { method: "DELETE" });
      closeModal();
      location.hash = "#/";
    });
  });
}

/* ── experiments ── */

function expCard(e) {
  return `<div class="card" data-exp="${e.id}">
    <div class="card-row">
      <strong>${esc(e.name)}</strong>
      <span>${badge(e.channel)} ${badge(e.status)}${e.result ? " " + badge(e.result) : ""}</span>
    </div>
    ${e.hypothesis ? `<div class="muted" style="font-size:12px; margin-top:4px">${esc(e.hypothesis)}</div>` : ""}
    ${e.learnings ? `<div style="font-size:12px; margin-top:4px">↳ ${esc(e.learnings)}</div>` : ""}
    <div class="muted mono" style="font-size:11px; margin-top:6px">
      ${e.started_at ? "started " + fmtDate(e.started_at) : "not started"}${e.ended_at ? " · ended " + fmtDate(e.ended_at) : ""}
      <button class="btn btn-sm" style="float:right" data-edit-exp="${e.id}">edit</button></div>
  </div>`;
}

let _expCache = [];

function bindExpCards(metricsList = []) {
  document.querySelectorAll("[data-edit-exp]").forEach((b) => b.addEventListener("click", () => {
    const e = _expCache.find((x) => x.id === b.dataset.editExp);
    if (e) expModal(e.project_id, metricsList, e);
  }));
}

function expModal(projectId, metricsList, existing = null) {
  const e = existing || {};
  openModal(`
    <h2>${existing ? "Edit" : "New"} experiment</h2>
    <form>
      <label>Name</label><input name="name" value="${esc(e.name || "")}" required>
      <label>Hypothesis</label><textarea name="hypothesis" placeholder="If we do X, metric Y moves because Z">${esc(e.hypothesis || "")}</textarea>
      <label>Channel</label><select name="channel">${options(CHANNELS, e.channel || "product")}</select>
      <label>Target metric</label><select name="target_metric_id">
        <option value="">—</option>
        ${metricsList.map((m) => `<option value="${m.id}" ${m.id === e.target_metric_id ? "selected" : ""}>${esc(m.name)}</option>`).join("")}
      </select>
      <label>Status</label><select name="status">${options(EXP_STATUSES, e.status || "idea")}</select>
      ${existing ? `
        <label>Result</label><select name="result">
          <option value="">—</option>${options(["positive", "negative", "inconclusive"], e.result || "")}</select>
        <label>Learnings</label><textarea name="learnings">${esc(e.learnings || "")}</textarea>` : ""}
      <div class="form-error"></div>
      <div class="actions">
        ${existing ? `<button class="btn btn-danger" type="button" id="del-exp">Delete</button>` : ""}
        <button class="btn" type="button" data-close>Cancel</button>
        <button class="btn btn-primary" type="submit">${existing ? "Save" : "Create"}</button></div>
    </form>`, async (fd) => {
    const bodyData = {
      name: fd.get("name"), hypothesis: fd.get("hypothesis"), channel: fd.get("channel"),
      target_metric_id: fd.get("target_metric_id") || null, status: fd.get("status"),
    };
    if (existing) {
      bodyData.result = fd.get("result") || null;
      bodyData.learnings = fd.get("learnings");
      await api(`/api/experiments/${existing.id}`, { method: "PATCH", body: JSON.stringify(bodyData) });
    } else {
      await api(`/api/experiments/projects/${projectId}`, { method: "POST", body: JSON.stringify(bodyData) });
    }
  });
  if (existing) {
    document.getElementById("del-exp").addEventListener("click", async () => {
      if (!confirm("Delete this experiment?")) return;
      await api(`/api/experiments/${existing.id}`, { method: "DELETE" });
      closeModal();
      render();
    });
  }
}

async function renderExperiments() {
  const [exps, projects] = await Promise.all([api("/api/experiments"), api("/api/projects")]);
  _expCache = exps;
  const byProject = Object.fromEntries(projects.map((p) => [p.id, p]));
  $view.innerHTML = `
    <div class="page-head"><h1>Experiments</h1><span class="muted">${exps.length} total</span></div>
    ${EXP_STATUSES.map((st) => {
      const group = exps.filter((e) => e.status === st);
      if (!group.length) return "";
      return `<div class="section"><div class="section-head"><h2>${st} <span class="muted">(${group.length})</span></h2></div>
        ${group.map((e) => {
          const p = byProject[e.project_id];
          return expCard(e).replace("</strong>", `</strong> <span class="muted" style="font-size:12px"><span style="color:${esc(p ? p.accent_color : "#888")}">●</span> ${esc(p ? p.name : "?")}</span>`);
        }).join("")}</div>`;
    }).join("") || `<div class="empty">No experiments anywhere yet. Open a project to create one.</div>`}`;
  bindExpCards();
}

/* ── marketing / campaigns ── */

function campCard(c) {
  return `<div class="card">
    <div class="card-row">
      <strong>${c.url ? `<a href="${esc(c.url)}" target="_blank" rel="noopener">${esc(c.name)}</a>` : esc(c.name)}</strong>
      <span>${badge(c.channel)} ${badge(c.status)}</span>
    </div>
    ${c.notes ? `<div class="muted" style="font-size:12px; margin-top:4px">${esc(c.notes)}</div>` : ""}
    <div class="muted mono" style="font-size:11px; margin-top:6px">
      ${c.budget != null ? "budget $" + Number(c.budget).toLocaleString() + " · " : ""}
      ${c.started_at ? "started " + fmtDate(c.started_at) : "not started"}
      <button class="btn btn-sm" style="float:right" data-edit-camp="${c.id}">edit</button></div>
  </div>`;
}

let _campCache = [];

function bindCampCards() {
  document.querySelectorAll("[data-edit-camp]").forEach((b) => b.addEventListener("click", () => {
    const c = _campCache.find((x) => x.id === b.dataset.editCamp);
    if (c) campModal(c.project_id, c);
  }));
}

function campModal(projectId, existing = null) {
  const c = existing || {};
  openModal(`
    <h2>${existing ? "Edit" : "New"} campaign</h2>
    <form>
      <label>Name</label><input name="name" value="${esc(c.name || "")}" required>
      <label>Channel</label><select name="channel">${options(CHANNELS, c.channel || "content")}</select>
      <label>Status</label><select name="status">${options(CAMP_STATUSES, c.status || "planned")}</select>
      <label>Budget ($, optional)</label><input name="budget" type="number" step="any" value="${c.budget ?? ""}">
      <label>URL (optional)</label><input name="url" value="${esc(c.url || "")}">
      <label>Notes</label><textarea name="notes">${esc(c.notes || "")}</textarea>
      <div class="form-error"></div>
      <div class="actions">
        ${existing ? `<button class="btn btn-danger" type="button" id="del-camp">Delete</button>` : ""}
        <button class="btn" type="button" data-close>Cancel</button>
        <button class="btn btn-primary" type="submit">${existing ? "Save" : "Create"}</button></div>
    </form>`, async (fd) => {
    const bodyData = {
      name: fd.get("name"), channel: fd.get("channel"), status: fd.get("status"),
      budget: fd.get("budget") ? Number(fd.get("budget")) : null,
      url: fd.get("url") || null, notes: fd.get("notes"),
    };
    const method = existing ? "PATCH" : "POST";
    const path = existing ? `/api/campaigns/${existing.id}` : `/api/campaigns/projects/${projectId}`;
    await api(path, { method, body: JSON.stringify(bodyData) });
  });
  if (existing) {
    document.getElementById("del-camp").addEventListener("click", async () => {
      if (!confirm("Delete this campaign?")) return;
      await api(`/api/campaigns/${existing.id}`, { method: "DELETE" });
      closeModal();
      render();
    });
  }
}

async function renderMarketing() {
  const [camps, projects] = await Promise.all([api("/api/campaigns"), api("/api/projects")]);
  _campCache = camps;
  const byProject = Object.fromEntries(projects.map((p) => [p.id, p]));
  $view.innerHTML = `
    <div class="page-head"><h1>Marketing engine</h1><span class="muted">${camps.length} campaigns</span></div>
    ${CAMP_STATUSES.map((st) => {
      const group = camps.filter((c) => c.status === st);
      if (!group.length) return "";
      return `<div class="section"><div class="section-head"><h2>${st} <span class="muted">(${group.length})</span></h2></div>
        ${group.map((c) => {
          const p = byProject[c.project_id];
          return campCard(c).replace("</strong>", `</strong> <span class="muted" style="font-size:12px"><span style="color:${esc(p ? p.accent_color : "#888")}">●</span> ${esc(p ? p.name : "?")}</span>`);
        }).join("")}</div>`;
    }).join("") || `<div class="empty">No campaigns yet. Open a project to launch one.</div>`}`;
  bindCampCards();
}

/* ── learnings ── */

async function renderLearnings() {
  const [learnings, projects] = await Promise.all([api("/api/learnings?limit=200"), api("/api/projects")]);
  const byProject = Object.fromEntries(projects.map((p) => [p.id, p]));
  $view.innerHTML = `
    <div class="page-head"><h1>Learnings log</h1>
      <button class="btn btn-primary" id="add-learning">+ Learning</button></div>
    <div id="learnings-list"></div>`;
  document.getElementById("learnings-list").innerHTML = learnings.map((l) => {
    const p = l.project_id ? byProject[l.project_id] : null;
    return `<div class="card">
      <div>${esc(l.content)}</div>
      <div class="muted" style="font-size:12px; margin-top:4px">
        ${p ? `<span style="color:${esc(p.accent_color)}">●</span> ${esc(p.name)} · ` : ""}${fmtDate(l.created_at)}
        <button class="btn btn-sm btn-danger" style="float:right" data-del-learning="${l.id}">delete</button></div>
    </div>`;
  }).join("") || `<div class="empty">Nothing here yet. Log what you learn from each experiment.</div>`;
  document.querySelectorAll("[data-del-learning]").forEach((b) => b.addEventListener("click", async () => {
    await api(`/api/learnings/${b.dataset.delLearning}`, { method: "DELETE" });
    render();
  }));
  document.getElementById("add-learning").addEventListener("click", () => {
    openModal(`
      <h2>Log a learning</h2>
      <form>
        <label>What did you learn?</label><textarea name="content" required></textarea>
        <label>Project (optional)</label><select name="project_id">
          <option value="">—</option>
          ${projects.map((p) => `<option value="${p.id}">${esc(p.name)}</option>`).join("")}</select>
        <div class="form-error"></div>
        <div class="actions"><button class="btn" type="button" data-close>Cancel</button>
          <button class="btn btn-primary" type="submit">Log it</button></div>
      </form>`, async (fd) => {
      await api("/api/learnings", {
        method: "POST",
        body: JSON.stringify({ content: fd.get("content"), project_id: fd.get("project_id") || null }),
      });
    });
  });
}

/* ── new project ── */

document.getElementById("new-project-btn").addEventListener("click", () => {
  openModal(`
    <h2>New project</h2>
    <form>
      <label>Slug (lowercase, dashes)</label><input name="slug" required pattern="[a-z0-9][a-z0-9-]*">
      <label>Name</label><input name="name" required>
      <label>URL (optional)</label><input name="url">
      <label>Stage</label><select name="stage">${options(STAGES, "idea")}</select>
      <label>Accent color</label><input name="accent_color" type="color" value="#4C8DFF">
      <label>Description</label><textarea name="description"></textarea>
      <div class="form-error"></div>
      <div class="actions"><button class="btn" type="button" data-close>Cancel</button>
        <button class="btn btn-primary" type="submit">Create</button></div>
    </form>`, async (fd) => {
    await api("/api/projects", {
      method: "POST",
      body: JSON.stringify({
        slug: fd.get("slug"), name: fd.get("name"), url: fd.get("url") || null,
        stage: fd.get("stage"), accent_color: fd.get("accent_color"),
        description: fd.get("description"),
      }),
    });
    location.hash = "#/";
  });
});

/* ── router ── */

async function render() {
  const hash = location.hash || "#/";
  document.querySelectorAll(".nav a").forEach((a) => a.classList.remove("active"));
  const mark = (name) => {
    const el = document.querySelector(`[data-nav="${name}"]`);
    if (el) el.classList.add("active");
  };
  try {
    if (hash.startsWith("#/p/")) {
      const [pid, tab, sub] = hash.slice(4).split("/");
      await renderProject(pid, tab || "overview", sub);
    } else if (hash === "#/inbox") {
      mark("inbox");
      await V2.renderInbox();
    } else if (hash === "#/devin") {
      mark("devin");
      await V2.renderDevin();
    } else if (hash === "#/settings") {
      mark("settings");
      await V2.renderSettings();
    } else if (hash === "#/experiments") {
      mark("experiments");
      await renderExperiments();
    } else if (hash === "#/marketing") {
      mark("marketing");
      await renderMarketing();
    } else if (hash === "#/learnings") {
      mark("learnings");
      await renderLearnings();
    } else {
      mark("cockpit");
      await renderCockpit();
    }
  } catch (ex) {
    $view.innerHTML = `<div class="empty">Something went wrong: ${esc(ex.message)}<br>
      <button class="btn" style="margin-top:10px" onclick="location.reload()">Reload</button></div>`;
  }
}

window.addEventListener("hashchange", render);
document.getElementById("ask-devin-btn").addEventListener("click", () => V2.devinModal({}));
