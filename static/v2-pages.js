/* InfiniSaaS v2 — portfolio pages: cockpit extras, inbox, settings */

window.V2 = window.V2 || { tabs: {} };

(function () {
  const money = (v) => v == null ? "—" : "$" + Number(v).toLocaleString(undefined, { maximumFractionDigits: 0 });
  const pct = (v) => v == null ? "—" : Number(v).toFixed(1) + "%";

  /* ── cockpit extras: money strip, ops row, open recommendations, recent Devin ── */
  V2.cockpitExtras = async function (root, projects) {
    const [fin, ops, recs, sessions] = await Promise.all([
      api("/api/finance/portfolio"), api("/api/ops/portfolio"),
      api("/api/recommendations?status=open&limit=6"), api("/api/devin/sessions"),
    ]);
    const t = fin.totals;
    root.innerHTML = `
      <div class="section">
        <div class="section-head"><h2>Money <span class="muted">30d</span></h2></div>
        <div class="stat-strip">
          <div class="stat"><div class="num" style="color:var(--good)">${money(t.revenue)}</div><div class="lbl">Revenue</div></div>
          <div class="stat"><div class="num">${money(t.mrr)}</div><div class="lbl">MRR</div></div>
          <div class="stat"><div class="num">${money(t.total_costs)}</div><div class="lbl">Costs <span class="muted">ads ${money(t.ad_spend)}</span></div></div>
          <div class="stat"><div class="num" style="color:${t.net >= 0 ? "var(--good)" : "var(--bad)"}">${money(t.net)}</div><div class="lbl">Net</div></div>
        </div>
        <div class="card" style="padding:0"><table>
          <thead><tr><th>Project</th><th style="text-align:right">Revenue</th><th style="text-align:right">MRR</th><th style="text-align:right">Costs</th><th style="text-align:right">Net</th><th style="text-align:right">CAC</th><th style="text-align:right">Uptime 7d</th><th></th></tr></thead>
          <tbody>${fin.projects.map((p) => {
            const o = ops.find((x) => x.project_id === p.project_id) || {};
            return `<tr>
              <td><span style="color:${esc(p.accent_color)}">●</span> <a href="#/p/${p.project_id}/finance">${esc(p.name)}</a></td>
              <td class="mono" style="text-align:right">${money(p.revenue)}</td>
              <td class="mono" style="text-align:right">${money(p.mrr)}</td>
              <td class="mono" style="text-align:right">${money(p.total_costs)}</td>
              <td class="mono" style="text-align:right; color:${p.net >= 0 ? "var(--good)" : "var(--bad)"}">${money(p.net)}</td>
              <td class="mono" style="text-align:right">${p.cac != null ? money(p.cac) : "—"}</td>
              <td class="mono" style="text-align:right">${o.uptime_pct != null ? `<span style="color:${o.uptime_pct >= 99 ? "var(--good)" : "var(--warn)"}">${pct(o.uptime_pct)}</span>` : "—"}</td>
              <td style="text-align:right">${o.last ? `<span class="badge ${o.last.ok ? "healthy" : "critical"}">${o.last.ok ? "up" : "down"}</span>` : ""}</td>
            </tr>`; }).join("")}</tbody></table></div>
      </div>
      <div class="grid-2 section">
        <div>
          <div class="section-head"><h2>Recommendations</h2><a href="#/inbox">inbox →</a></div>
          <div id="cockpit-recs">${recs.map((r) => V2.recCard(r, { showProject: true, projects })).join("") || `<div class="empty">No open recommendations. Run an agent from a project's Agents tab.</div>`}</div>
        </div>
        <div>
          <div class="section-head"><h2><span class="devin-mark">◆</span> Devin sessions</h2><a href="#/devin">all →</a></div>
          ${sessions.slice(0, 5).map((s) => V2.sessionCard(s, { compact: true })).join("") || `<div class="empty">No Devin sessions yet.</div>`}
        </div>
      </div>`;
    V2.bindRecCards(root, recs, render);
    V2.bindSessionCards(root, render);
  };

  /* ── Inbox: open recommendations + fresh feature requests + feedback across the portfolio ── */
  V2.renderInbox = async function (status = "open") {
    const [projects, recs, frs, fbs] = await Promise.all([
      api("/api/projects"), api(`/api/recommendations?status=${status}&limit=200`),
      api("/api/feature-requests?status=inbox"), api("/api/feedback"),
    ]);
    const pname = (pid) => { const p = projects.find((x) => x.id === pid); return p ? `<span style="color:${esc(p.accent_color)}">●</span> ${esc(p.name)}` : ""; };
    $view.innerHTML = `
      <div class="page-head"><div><h1>Inbox</h1><div class="muted">Everything waiting for a decision across the portfolio.</div></div>
        <span class="seg">${["open", "accepted", "done", "dismissed"].map((s) => `<button class="btn btn-sm ${s === status ? "btn-primary" : ""}" data-status="${s}">${s}</button>`).join("")}</span></div>
      <div class="grid-2">
        <div>
          <div class="section-head"><h2>Recommendations <span class="muted">(${recs.length} ${status})</span></h2></div>
          <div id="inbox-recs">${recs.map((r) => V2.recCard(r, { showProject: true, projects })).join("") || `<div class="empty">Nothing ${status}.</div>`}</div>
        </div>
        <div>
          <div class="section-head"><h2>New feature requests <span class="muted">(${frs.length})</span></h2></div>
          ${frs.map((f) => `<div class="card"><div class="card-row"><strong>${esc(f.title)}</strong><span>${badge(f.priority)} <a class="btn btn-sm" href="#/p/${f.project_id}/product">Triage</a></span></div>
            <div class="muted" style="font-size:12px; margin-top:4px">${pname(f.project_id)} · ${fmtDate(f.created_at)}</div></div>`).join("") || `<div class="empty">Inbox zero on feature requests.</div>`}
          <div class="section-head" style="margin-top:28px"><h2>Recent feedback</h2></div>
          ${fbs.slice(0, 8).map((f) => `<div class="card"><div>${badge(f.sentiment)} ${esc(f.content)}</div>
            <div class="muted" style="font-size:12px; margin-top:4px">${pname(f.project_id)} · ${esc(f.source)} · ${fmtDate(f.created_at)}</div></div>`).join("") || `<div class="empty">No feedback yet.</div>`}
        </div>
      </div>`;
    $view.querySelectorAll("[data-status]").forEach((b) => b.addEventListener("click", () => V2.renderInbox(b.dataset.status)));
    V2.bindRecCards($view, recs, () => V2.renderInbox(status));
  };

  /* ── Settings: integrations registry + environment status ── */
  V2.renderSettings = async function () {
    const [providers, integs, projects, devin, llm] = await Promise.all([
      api("/api/integrations/providers"), api("/api/integrations"), api("/api/projects"),
      api("/api/devin/status"), api("/api/agents/status"),
    ]);
    const pname = (pid) => (projects.find((x) => x.id === pid) || {}).name || "—";
    const envRow = (label, ok, hint) => `<div class="card-row" style="padding:6px 0; border-bottom:1px solid var(--line)"><span>${label}</span><span>${ok ? `<span class="badge healthy">configured</span>` : `<span class="badge watch">missing</span>`} <span class="muted" style="font-size:11px">${hint}</span></span></div>`;
    $view.innerHTML = `
      <div class="page-head"><div><h1>Settings</h1><div class="muted">Integrations are stored encrypted server-side; secrets never reach the browser.</div></div></div>
      <div class="grid-2">
        <div>
          <div class="section-head"><h2>Integrations</h2><button class="btn btn-sm btn-primary" id="add-integ">+ Connect</button></div>
          ${integs.map((i) => {
            const meta = providers[i.provider] || {};
            return `<div class="card">
              <div class="card-row"><strong>${esc(meta.label || i.provider)}</strong> <span>${badge(i.status === "ok" ? "healthy" : i.status === "error" ? "critical" : i.status)}</span></div>
              <div class="muted" style="font-size:12px; margin-top:4px">${i.project_id ? esc(pname(i.project_id)) : "Global"}${Object.entries(i.config).map(([k, v]) => ` · ${esc(k)}: <span class="mono">${esc(v)}</span>`).join("")}${i.has_secret ? " · 🔒 secret set" : " · no secret"}</div>
              ${i.status_detail ? `<div class="mono" style="font-size:11px; margin-top:4px; color:${i.status === "error" ? "var(--bad)" : "var(--muted)"}">${esc(i.status_detail)}</div>` : ""}
              <div class="card-row" style="margin-top:8px"><span class="mono muted" style="font-size:11px">${i.last_synced_at ? "synced " + fmtDate(i.last_synced_at) : "never synced"} · ${esc(meta.syncs || "")}</span>
                <span><button class="btn btn-sm" data-verify="${i.id}">Verify</button> <button class="btn btn-sm" data-sync="${i.id}">Sync</button>
                  <button class="btn btn-sm" data-edit-integ="${i.id}">Edit</button> <button class="btn btn-sm btn-danger" data-del-integ="${i.id}">Remove</button></span></div>
            </div>`; }).join("") || `<div class="empty">No integrations yet. Connect Stripe, GitHub, Railway, Search Console or Slack.</div>`}
        </div>
        <div>
          <div class="section-head"><h2>Environment</h2></div>
          <div class="card">
            ${envRow("Devin API", devin.configured, devin.configured ? "sessions spawn for real" : "DEVIN_API_KEY → mock sessions")}
            ${envRow("Anthropic (agents)", llm.llm_configured, llm.llm_configured ? "" : "ANTHROPIC_API_KEY → mock recommendations")}
            ${envRow("Auth (Clerk)", window.INFINI.authEnabled, window.INFINI.authEnabled ? "" : "CLERK_JWKS_URL + CLERK_PUBLISHABLE_KEY → open access")}
            <p class="muted" style="font-size:12px; margin:10px 0 0">These come from Railway service variables, not from this UI.</p>
          </div>
          <div class="section-head" style="margin-top:20px"><h2>Ingest endpoints</h2></div>
          <div class="card muted" style="font-size:12px">
            Each project has a bearer token (project page → "Ingest token").<br>
            <span class="mono">POST /api/v1/metrics</span> — metric points<br>
            <span class="mono">POST /api/v1/events</span> — product events for funnels / DAU<br>
            Background loop: uptime every 5 min, integrations hourly, agents on schedule, alerts each tick.
          </div>
        </div>
      </div>`;

    function integModal(existing) {
      const provKey = existing ? existing.provider : Object.keys(providers)[0];
      const draw = (prov) => {
        const meta = providers[prov];
        const form = document.getElementById("integ-form");
        form.querySelector("#dyn").innerHTML = `
          ${meta.scope === "project" ? `<label>Project</label><select name="project_id" required ${existing ? "disabled" : ""}>
            ${projects.map((p) => `<option value="${p.id}" ${existing && existing.project_id === p.id ? "selected" : ""}>${esc(p.name)}</option>`).join("")}</select>` : `<p class="muted" style="font-size:12px">Global — shared by all projects.</p>`}
          ${meta.config_fields.map((f) => `<label>${esc(f.label)}${f.required ? " *" : ""}</label><input name="cfg_${f.key}" ${f.required ? "required" : ""} value="${esc(existing ? existing.config[f.key] || "" : "")}">`).join("")}
          <label>${esc(meta.secret_label)}${existing && existing.has_secret ? " <span class='muted'>(leave blank to keep)</span>" : ""}</label>
          <textarea name="secret" rows="2" autocomplete="off" spellcheck="false" ${existing && existing.has_secret ? "" : "required"}></textarea>
          <p class="muted" style="font-size:12px">Syncs: ${esc(meta.syncs)}</p>`;
      };
      openModal(`
        <h2>${existing ? "Edit" : "Connect"} integration</h2>
        <form id="integ-form">
          <label>Provider</label><select name="provider" id="prov" ${existing ? "disabled" : ""}>${Object.entries(providers).map(([k, m]) => `<option value="${k}" ${k === provKey ? "selected" : ""}>${esc(m.label)}</option>`).join("")}</select>
          <div id="dyn"></div>
          <div class="form-error"></div>
          <div class="actions"><button class="btn" type="button" data-close>Cancel</button><button class="btn btn-primary" type="submit">Save & verify</button></div>
        </form>`, async (fd) => {
        const prov = existing ? existing.provider : fd.get("provider");
        const meta = providers[prov];
        const config = {};
        meta.config_fields.forEach((f) => { const v = fd.get(`cfg_${f.key}`); if (v) config[f.key] = v; });
        const body = { project_id: meta.scope === "project" ? (existing ? existing.project_id : fd.get("project_id")) : null, config };
        if (fd.get("secret")) body.secret = fd.get("secret");
        const row = await api(`/api/integrations/${prov}`, { method: "PUT", body: JSON.stringify(body) });
        try { await api(`/api/integrations/${row.id}/verify`, { method: "POST" }); } catch { /* status shown in list */ }
      });
      draw(provKey);
      document.getElementById("prov").addEventListener("change", (e) => draw(e.target.value));
    }

    document.getElementById("add-integ").addEventListener("click", () => integModal(null));
    $view.querySelectorAll("[data-edit-integ]").forEach((b) => b.addEventListener("click", () => integModal(integs.find((i) => i.id === b.dataset.editInteg))));
    $view.querySelectorAll("[data-del-integ]").forEach((b) => b.addEventListener("click", async () => {
      if (!confirm("Remove this integration and its stored secret?")) return;
      await api(`/api/integrations/${b.dataset.delInteg}`, { method: "DELETE" }); V2.renderSettings();
    }));
    $view.querySelectorAll("[data-verify]").forEach((b) => b.addEventListener("click", async () => {
      b.textContent = "…"; try { await api(`/api/integrations/${b.dataset.verify}/verify`, { method: "POST" }); } catch (ex) { alert(ex.message); } V2.renderSettings();
    }));
    $view.querySelectorAll("[data-sync]").forEach((b) => b.addEventListener("click", async () => {
      b.textContent = "…"; try { await api(`/api/integrations/${b.dataset.sync}/sync`, { method: "POST" }); } catch (ex) { alert(ex.message); } V2.renderSettings();
    }));
  };
})();
