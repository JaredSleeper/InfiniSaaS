/* InfiniSaaS v2 — Devin: prompt box, session spawning, session tracking */

window.V2 = window.V2 || { tabs: {} };

(function () {
  const SOURCE_LABEL = {
    manual: "Manual", feature_request: "Feature request", recommendation: "Recommendation",
    experiment: "Experiment", landing_page: "Landing page",
  };

  let _projects = null;
  async function projects() {
    if (!_projects) _projects = await api("/api/projects");
    return _projects;
  }
  V2.invalidateProjects = () => { _projects = null; };

  function statusBadge(s) {
    const map = { running: "running", working: "running", blocked: "watch", finished: "healthy",
      stopped: "paused", mock: "planned", error: "critical", suspended: "paused" };
    return `<span class="badge ${map[s] || ""}">${esc(s)}</span>`;
  }

  V2.sessionCard = function (s, { compact = false } = {}) {
    return `<div class="card devin-card" data-session="${s.id}">
      <div class="card-row">
        <strong><span class="devin-mark">◆</span> ${esc(s.title || "Untitled session")}</strong>
        <span>${statusBadge(s.status)} ${badge(SOURCE_LABEL[s.source_type] || s.source_type)}</span>
      </div>
      ${compact ? "" : `<div class="muted clamp-2" style="font-size:12px; margin-top:4px">${esc(s.prompt.split("# Task").pop().trim())}</div>`}
      <div class="card-row" style="margin-top:8px; font-size:12px">
        <span class="mono muted">${fmtDate(s.created_at)}${s.pr_url ? ` · <a href="${esc(s.pr_url)}" target="_blank" rel="noopener">PR</a>` : ""}</span>
        <span>
          <a class="btn btn-sm" href="${esc(s.url)}" target="_blank" rel="noopener">Open in Devin ↗</a>
          <button class="btn btn-sm" data-refresh="${s.id}">Refresh</button>
          <button class="btn btn-sm" data-message="${s.id}">Message</button>
          <button class="btn btn-sm btn-danger" data-forget="${s.id}">Forget</button>
        </span>
      </div>
    </div>`;
  };

  V2.bindSessionCards = function (root, rerender) {
    root.querySelectorAll("[data-refresh]").forEach((b) => b.addEventListener("click", async () => {
      b.textContent = "…";
      try { await api(`/api/devin/sessions/${b.dataset.refresh}/refresh`, { method: "POST" }); }
      catch (ex) { alert(ex.message); }
      rerender();
    }));
    root.querySelectorAll("[data-message]").forEach((b) => b.addEventListener("click", () => {
      openModal(`
        <h2>Message Devin</h2>
        <form>
          <label>Follow-up</label><textarea name="message" required placeholder="Also add tests for…"></textarea>
          <div class="form-error"></div>
          <div class="actions"><button class="btn" type="button" data-close>Cancel</button>
            <button class="btn btn-primary" type="submit">Send</button></div>
        </form>`, async (fd) => {
        await api(`/api/devin/sessions/${b.dataset.message}/message`, {
          method: "POST", body: JSON.stringify({ message: fd.get("message") }),
        });
      });
    }));
    root.querySelectorAll("[data-forget]").forEach((b) => b.addEventListener("click", async () => {
      if (!confirm("Remove this session from the cockpit? (The Devin session itself is untouched.)")) return;
      await api(`/api/devin/sessions/${b.dataset.forget}`, { method: "DELETE" });
      rerender();
    }));
  };

  /**
   * Prompt box modal. ctx: { project_id, source_type, source_id, prompt, title }
   */
  V2.devinModal = async function (ctx = {}) {
    const [status, plist] = await Promise.all([api("/api/devin/status"), projects()]);
    const projectOpts = `<option value="">— portfolio-level (no project) —</option>` +
      plist.map((p) => `<option value="${p.id}" ${p.id === ctx.project_id ? "selected" : ""}>${esc(p.name)}</option>`).join("");
    openModal(`
      <h2><span class="devin-mark">◆</span> Send to Devin</h2>
      ${status.configured ? "" : `<div class="notice">DEVIN_API_KEY is not configured — sessions will be recorded as <b>mock</b> so you can test the flow. Add the key in Railway to spawn real sessions.</div>`}
      <form id="devin-form">
        <label>Project (injects wiki + repo context)</label>
        <select name="project_id">${projectOpts}</select>
        ${ctx.source_type && ctx.source_type !== "manual" ? `<div class="muted" style="font-size:12px; margin-top:8px">Linked to ${esc(SOURCE_LABEL[ctx.source_type])}: <b>${esc(ctx.title || "")}</b></div>` : ""}
        <label>Task for Devin</label>
        <textarea name="prompt" rows="6" required placeholder="What should Devin build, fix, or investigate?">${esc(ctx.prompt || "")}</textarea>
        <label>Session title (optional)</label><input name="title" value="${esc(ctx.title || "")}">
        <label><input type="checkbox" name="include_wiki" checked style="width:auto"> Include product wiki as context</label>
        <details style="margin-top:10px"><summary class="muted" style="cursor:pointer; font-size:12px">Preview full prompt</summary>
          <pre class="prompt-preview" id="prompt-preview">Click "Refresh preview"…</pre>
          <button class="btn btn-sm" type="button" id="refresh-preview">Refresh preview</button>
        </details>
        <div class="form-error"></div>
        <div class="actions"><button class="btn" type="button" data-close>Cancel</button>
          <button class="btn btn-devin" type="submit">◆ Launch session</button></div>
      </form>`, async (fd) => {
      const created = await api("/api/devin/sessions", { method: "POST", body: JSON.stringify(payload(fd)) });
      window.open(created.url, "_blank", "noopener");
    });
    const payload = (fd) => ({
      prompt: fd.get("prompt"), title: fd.get("title") || "",
      project_id: fd.get("project_id") || null,
      source_type: ctx.source_type || "manual", source_id: ctx.source_id || null,
      include_wiki: fd.get("include_wiki") === "on",
    });
    document.getElementById("refresh-preview").addEventListener("click", async () => {
      const fd = new FormData(document.getElementById("devin-form"));
      const pre = document.getElementById("prompt-preview");
      if (!fd.get("prompt")) { pre.textContent = "Write a task first."; return; }
      try {
        const pv = await api("/api/devin/preview", { method: "POST", body: JSON.stringify(payload(fd)) });
        pre.textContent = pv.prompt;
      } catch (ex) { pre.textContent = ex.message; }
    });
  };

  /* ── Devin page (all sessions) ── */
  V2.renderDevin = async function () {
    const [status, sessions] = await Promise.all([api("/api/devin/status"), api("/api/devin/sessions")]);
    $view.innerHTML = `
      <div class="page-head">
        <div><h1><span class="devin-mark">◆</span> Devin</h1>
          <div class="muted">Sessions launched from the cockpit. ${status.configured ? "Connected to the Devin API." : "<b>Mock mode</b> — set DEVIN_API_KEY to spawn real sessions."}</div></div>
        <button class="btn btn-devin" id="new-devin">◆ New session</button>
      </div>
      <div id="devin-list"></div>`;
    document.getElementById("new-devin").addEventListener("click", () => V2.devinModal({}));
    const list = document.getElementById("devin-list");
    list.innerHTML = sessions.map((s) => V2.sessionCard(s)).join("")
      || `<div class="empty">No sessions yet. Hit "Send to Devin" on any project, feature request or recommendation.</div>`;
    V2.bindSessionCards(list, V2.renderDevin);
  };

  /* ── project Devin tab ── */
  V2.tabs.devin = async function (id, p, root) {
    const sessions = await api(`/api/devin/sessions?project_id=${id}`);
    root.innerHTML = `
      <div class="section" style="margin-top:12px">
        <div class="section-head"><h2>Devin sessions</h2>
          <button class="btn btn-sm btn-devin" id="tab-new-devin">◆ New session</button></div>
        <div id="devin-list"></div>
      </div>`;
    document.getElementById("tab-new-devin").addEventListener("click", () => V2.devinModal({ project_id: id }));
    const list = document.getElementById("devin-list");
    list.innerHTML = sessions.map((s) => V2.sessionCard(s)).join("")
      || `<div class="empty">No sessions for ${esc(p.name)} yet.</div>`;
    V2.bindSessionCards(list, () => V2.tabs.devin(id, p, root));
  };
})();
