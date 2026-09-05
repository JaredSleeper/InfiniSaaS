/* InfiniSaaS v2 — project tabs: wiki, product, growth, analytics, finance, ops, agents */

window.V2 = window.V2 || { tabs: {} };

(function () {
  const FR_STATUSES = ["inbox", "considering", "planned", "building", "shipped", "declined"];
  const PRIORITIES = ["low", "medium", "high", "critical"];
  const FB_SOURCES = ["email", "in_app", "social", "interview", "support", "review", "other"];
  const SENTIMENTS = ["positive", "neutral", "negative"];
  const CONTENT_STATUSES = ["idea", "drafting", "scheduled", "published"];
  const COST_CATS = ["infra", "ads", "tools", "llm", "contractors", "other"];
  const AD_PLATFORMS = ["google", "meta", "reddit", "x", "tiktok", "linkedin", "other"];
  const ALERT_CONDS = ["below", "above", "drop_pct", "stale_days"];

  const money = (v) => v == null ? "—" : "$" + Number(v).toLocaleString(undefined, { maximumFractionDigits: 2 });
  const num = (v) => v == null ? "—" : Number(v).toLocaleString();
  const pct = (v) => v == null ? "—" : Number(v).toFixed(1) + "%";
  const dateInput = (iso) => iso ? iso.slice(0, 10) : "";
  const today = () => new Date().toISOString().slice(0, 10);

  function stat(label, value, sub = "") {
    return `<div class="stat"><div class="num">${value}</div><div class="lbl">${label}${sub ? ` <span class="muted">${sub}</span>` : ""}</div></div>`;
  }

  function actionsRow(extra = "") {
    return `<div class="form-error"></div>
      <div class="actions">${extra}<button class="btn" type="button" data-close>Cancel</button>
        <button class="btn btn-primary" type="submit">Save</button></div>`;
  }

  function deleteButton(id) {
    return `<button class="btn btn-danger" type="button" data-delete="${id}">Delete</button>`;
  }

  function bindDelete(path, after) {
    const b = $modal.querySelector("[data-delete]");
    if (!b) return;
    b.addEventListener("click", async () => {
      if (!confirm("Delete this item?")) return;
      await api(`${path}/${b.dataset.delete}`, { method: "DELETE" });
      closeModal();
      after();
    });
  }

  /* simple markdown-ish renderer: headings, bullets, bold, links, paragraphs */
  V2.md = function (src) {
    const lines = esc(src || "").split("\n");
    let html = "", inList = false;
    const inline = (t) => t
      .replace(/\*\*(.+?)\*\*/g, "<b>$1</b>")
      .replace(/`(.+?)`/g, "<code>$1</code>")
      .replace(/\[(.+?)\]\((https?:[^)\s]+)\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>');
    for (const raw of lines) {
      const l = raw.trimEnd();
      const li = l.match(/^\s*[-*]\s+(.*)/);
      if (li) { if (!inList) { html += "<ul>"; inList = true; } html += `<li>${inline(li[1])}</li>`; continue; }
      if (inList) { html += "</ul>"; inList = false; }
      const h = l.match(/^(#{1,4})\s+(.*)/);
      if (h) html += `<h${h[1].length + 1}>${inline(h[2])}</h${h[1].length + 1}>`;
      else if (l.trim()) html += `<p>${inline(l)}</p>`;
    }
    if (inList) html += "</ul>";
    return html || `<p class="muted">Empty — click Edit to fill this in.</p>`;
  };

  /* ═══════════════ WIKI ═══════════════ */
  V2.tabs.wiki = async function (id, p, root, activeSlug) {
    const pages = await api(`/api/projects/${id}/wiki`);
    const current = pages.find((w) => w.slug === activeSlug) || pages[0];
    root.innerHTML = `
      <div class="wiki section" style="margin-top:12px">
        <aside class="wiki-nav">
          ${pages.map((w) => `<a href="#/p/${id}/wiki/${esc(w.slug)}" class="${current && w.slug === current.slug ? "active" : ""}">${esc(w.title)}</a>`).join("")}
          <button class="btn btn-sm" id="wiki-add" style="margin-top:10px">+ Page</button>
        </aside>
        <article class="wiki-body card">
          ${current ? `
            <div class="card-row"><h2>${esc(current.title)}</h2>
              <span><span class="muted mono" style="font-size:11px">updated ${fmtDate(current.updated_at)}</span>
              <button class="btn btn-sm" id="wiki-edit">Edit</button></span></div>
            <div class="prose" id="wiki-prose">${V2.md(current.content)}</div>` : `<div class="empty">No pages.</div>`}
        </article>
      </div>`;
    if (current) document.getElementById("wiki-edit").addEventListener("click", () => {
      openModal(`
        <h2>Edit — ${esc(current.title)}</h2>
        <form>
          <label>Title</label><input name="title" value="${esc(current.title)}" required>
          <label>Content (markdown). Never paste credentials here — use Settings → Integrations.</label>
          <textarea name="content" rows="18" class="mono" style="font-size:12px">${esc(current.content)}</textarea>
          ${actionsRow(`<button class="btn btn-danger" type="button" id="wiki-del">Delete page</button>`)}
        </form>`, async (fd) => {
        await api(`/api/projects/${id}/wiki/${current.slug}`, {
          method: "PUT", body: JSON.stringify({ title: fd.get("title"), content: fd.get("content") }),
        });
      });
      $modal.classList.add("modal-wide");
      document.getElementById("wiki-del").addEventListener("click", async () => {
        if (!confirm(`Delete page "${current.title}"?`)) return;
        await api(`/api/projects/${id}/wiki/${current.slug}`, { method: "DELETE" });
        closeModal(); location.hash = `#/p/${id}/wiki`;
      });
    });
    document.getElementById("wiki-add").addEventListener("click", () => {
      openModal(`
        <h2>New wiki page</h2>
        <form>
          <label>Slug (kebab-case)</label><input name="slug" required pattern="[a-z0-9][a-z0-9-]*" placeholder="launch-checklist">
          <label>Title</label><input name="title" required>
          <label>Content (markdown)</label><textarea name="content" rows="10"></textarea>
          ${actionsRow()}
        </form>`, async (fd) => {
        await api(`/api/projects/${id}/wiki/${fd.get("slug")}`, {
          method: "PUT", body: JSON.stringify({ title: fd.get("title"), content: fd.get("content") }),
        });
      });
    });
  };

  /* ═══════════════ PRODUCT: feature requests, feedback, releases ═══════════════ */
  function frCard(f) {
    return `<div class="card" data-fr="${f.id}">
      <div class="card-row">
        <strong>${esc(f.title)}</strong>
        <span>${badge(f.priority)} ${badge(f.status)} <span class="mono muted" style="font-size:11px">▲ ${f.votes}</span></span>
      </div>
      ${f.description ? `<div class="muted clamp-2" style="font-size:12px; margin-top:4px">${esc(f.description)}</div>` : ""}
      <div class="card-row" style="margin-top:8px">
        <span class="mono muted" style="font-size:11px">${fmtDate(f.created_at)}</span>
        <span><button class="btn btn-sm" data-edit-fr="${f.id}">Edit</button>
          <button class="btn btn-sm btn-devin" data-devin-fr="${f.id}">◆ Devin</button></span>
      </div>
    </div>`;
  }

  function frModal(projectId, existing, after) {
    const f = existing || { title: "", description: "", status: "inbox", priority: "medium", votes: 0 };
    openModal(`
      <h2>${existing ? "Edit" : "New"} feature request</h2>
      <form>
        <label>Title</label><input name="title" value="${esc(f.title)}" required>
        <label>Description / user problem</label><textarea name="description">${esc(f.description)}</textarea>
        <div class="grid-3">
          <div><label>Status</label><select name="status">${options(FR_STATUSES, f.status)}</select></div>
          <div><label>Priority</label><select name="priority">${options(PRIORITIES, f.priority)}</select></div>
          <div><label>Votes</label><input name="votes" type="number" min="0" value="${f.votes}"></div>
        </div>
        ${actionsRow(existing ? deleteButton(f.id) : "")}
      </form>`, async (fd) => {
      const body = { title: fd.get("title"), description: fd.get("description"), status: fd.get("status"),
        priority: fd.get("priority"), votes: Number(fd.get("votes") || 0) };
      if (existing) await api(`/api/feature-requests/${f.id}`, { method: "PATCH", body: JSON.stringify(body) });
      else await api(`/api/feature-requests/projects/${projectId}`, { method: "POST", body: JSON.stringify(body) });
    });
    bindDelete("/api/feature-requests", after);
  }

  function fbCard(f, frs) {
    const linked = f.feature_request_id && frs.find((x) => x.id === f.feature_request_id);
    return `<div class="card">
      <div class="card-row"><span>${badge(f.sentiment)} ${badge(f.source)} ${f.author ? `<span class="muted" style="font-size:12px">${esc(f.author)}</span>` : ""}</span>
        <button class="btn btn-sm" data-edit-fb="${f.id}">Edit</button></div>
      <div style="margin-top:6px">${esc(f.content)}</div>
      <div class="mono muted" style="font-size:11px; margin-top:6px">${fmtDate(f.created_at)}${linked ? ` · ↳ ${esc(linked.title)}` : ""}</div>
    </div>`;
  }

  function fbModal(projectId, frs, existing, after) {
    const f = existing || { source: "other", author: "", content: "", sentiment: "neutral", feature_request_id: null };
    openModal(`
      <h2>${existing ? "Edit" : "Log"} feedback</h2>
      <form>
        <label>What did they say?</label><textarea name="content" required>${esc(f.content)}</textarea>
        <div class="grid-3">
          <div><label>Source</label><select name="source">${options(FB_SOURCES, f.source)}</select></div>
          <div><label>Sentiment</label><select name="sentiment">${options(SENTIMENTS, f.sentiment)}</select></div>
          <div><label>Author</label><input name="author" value="${esc(f.author)}" placeholder="email / handle"></div>
        </div>
        <label>Link to feature request</label>
        <select name="feature_request_id"><option value="">—</option>
          ${frs.map((x) => `<option value="${x.id}" ${x.id === f.feature_request_id ? "selected" : ""}>${esc(x.title)}</option>`).join("")}</select>
        ${actionsRow(existing ? deleteButton(f.id) : "")}
      </form>`, async (fd) => {
      const body = { content: fd.get("content"), source: fd.get("source"), sentiment: fd.get("sentiment"),
        author: fd.get("author"), feature_request_id: fd.get("feature_request_id") || null };
      if (existing) await api(`/api/feedback/${f.id}`, { method: "PATCH", body: JSON.stringify(body) });
      else await api(`/api/feedback/projects/${projectId}`, { method: "POST", body: JSON.stringify(body) });
    });
    bindDelete("/api/feedback", after);
  }

  function releaseModal(projectId, existing, after) {
    const r = existing || { title: "", body: "", url: "", released_at: null };
    openModal(`
      <h2>${existing ? "Edit" : "Log"} release</h2>
      <form>
        <label>Title</label><input name="title" value="${esc(r.title)}" required>
        <label>Notes</label><textarea name="body">${esc(r.body)}</textarea>
        <div class="grid-2"><div><label>URL</label><input name="url" value="${esc(r.url || "")}"></div>
          <div><label>Released on</label><input name="released_at" type="date" value="${dateInput(r.released_at) || today()}"></div></div>
        ${actionsRow(existing ? deleteButton(r.id) : "")}
      </form>`, async (fd) => {
      const body = { title: fd.get("title"), body: fd.get("body"), url: fd.get("url") || null,
        released_at: fd.get("released_at") ? new Date(fd.get("released_at") + "T12:00:00Z").toISOString() : null };
      if (existing) await api(`/api/releases/${r.id}`, { method: "PATCH", body: JSON.stringify(body) });
      else await api(`/api/releases/projects/${projectId}`, { method: "POST", body: JSON.stringify(body) });
    });
    bindDelete("/api/releases", after);
  }

  V2.tabs.product = async function (id, p, root) {
    const [frs, fbs, rels, integs] = await Promise.all([
      api(`/api/feature-requests?project_id=${id}`), api(`/api/feedback?project_id=${id}`),
      api(`/api/releases?project_id=${id}`), api(`/api/integrations`),
    ]);
    const gh = integs.find((i) => i.provider === "github" && i.project_id === id);
    const rerender = () => V2.tabs.product(id, p, root);
    const byStatus = FR_STATUSES.map((s) => [s, frs.filter((f) => f.status === s)]).filter(([, l]) => l.length);
    root.innerHTML = `
      <div class="grid-2 section" style="margin-top:12px">
        <div>
          <div class="section-head"><h2>Feature requests <span class="muted">(${frs.length})</span></h2>
            <button class="btn btn-sm" id="add-fr">+ Request</button></div>
          <div id="fr-list">${byStatus.map(([s, l]) => `<div class="group-label">${badge(s)} <span class="muted">${l.length}</span></div>${l.map(frCard).join("")}`).join("")
            || `<div class="empty">No feature requests yet. Capture asks here; send the good ones to Devin.</div>`}</div>
        </div>
        <div>
          <div class="section-head"><h2>Customer voice <span class="muted">(${fbs.length})</span></h2>
            <button class="btn btn-sm" id="add-fb">+ Feedback</button></div>
          <div id="fb-list">${fbs.map((f) => fbCard(f, frs)).join("") || `<div class="empty">No feedback logged. Emails, DMs, reviews, interview notes all go here.</div>`}</div>
          <div class="section-head" style="margin-top:28px"><h2>Releases</h2>
            <span>${gh ? `<button class="btn btn-sm" id="sync-gh">Sync GitHub</button>` : `<a class="btn btn-sm" href="#/settings">Connect GitHub</a>`}
            <button class="btn btn-sm" id="add-rel">+ Release</button></span></div>
          <div class="timeline">${rels.map((r) => `
            <div class="tl-item" data-rel="${r.id}">
              <div class="tl-date mono">${fmtDate(r.released_at)}</div>
              <div><strong>${r.url ? `<a href="${esc(r.url)}" target="_blank" rel="noopener">${esc(r.title)}</a>` : esc(r.title)}</strong> ${r.source !== "manual" ? badge(r.source) : ""}
                ${r.body ? `<div class="muted clamp-2" style="font-size:12px">${esc(r.body)}</div>` : ""}</div>
              <button class="btn btn-sm" data-edit-rel="${r.id}">Edit</button>
            </div>`).join("") || `<div class="empty">No releases yet.</div>`}</div>
        </div>
      </div>`;
    document.getElementById("add-fr").addEventListener("click", () => frModal(id, null, rerender));
    document.getElementById("add-fb").addEventListener("click", () => fbModal(id, frs, null, rerender));
    document.getElementById("add-rel").addEventListener("click", () => releaseModal(id, null, rerender));
    root.querySelectorAll("[data-edit-fr]").forEach((b) => b.addEventListener("click", () =>
      frModal(id, frs.find((f) => f.id === b.dataset.editFr), rerender)));
    root.querySelectorAll("[data-devin-fr]").forEach((b) => b.addEventListener("click", () => {
      const f = frs.find((x) => x.id === b.dataset.devinFr);
      V2.devinModal({ project_id: id, source_type: "feature_request", source_id: f.id, title: f.title,
        prompt: `Implement the feature request "${f.title}".${f.description ? "\n\n" + f.description : ""}\n\nOpen a PR when done.` });
    }));
    root.querySelectorAll("[data-edit-fb]").forEach((b) => b.addEventListener("click", () =>
      fbModal(id, frs, fbs.find((f) => f.id === b.dataset.editFb), rerender)));
    root.querySelectorAll("[data-edit-rel]").forEach((b) => b.addEventListener("click", () =>
      releaseModal(id, rels.find((r) => r.id === b.dataset.editRel), rerender)));
    const sync = document.getElementById("sync-gh");
    if (sync) sync.addEventListener("click", async () => {
      sync.textContent = "Syncing…";
      try { await api(`/api/integrations/${gh.id}/sync`, { method: "POST" }); rerender(); }
      catch (ex) { alert(ex.message); sync.textContent = "Sync GitHub"; }
    });
  };

  /* ═══════════════ GROWTH: content calendar + SEO cockpit ═══════════════ */
  function contentModal(projectId, camps, existing, after) {
    const c = existing || { title: "", channel: "content", status: "idea", publish_at: null, url: "", notes: "", campaign_id: null };
    openModal(`
      <h2>${existing ? "Edit" : "New"} content item</h2>
      <form>
        <label>Title / hook</label><input name="title" value="${esc(c.title)}" required>
        <div class="grid-3">
          <div><label>Channel</label><select name="channel">${options(CHANNELS, c.channel)}</select></div>
          <div><label>Status</label><select name="status">${options(CONTENT_STATUSES, c.status)}</select></div>
          <div><label>Publish date</label><input name="publish_at" type="date" value="${dateInput(c.publish_at)}"></div>
        </div>
        <label>URL (once live)</label><input name="url" value="${esc(c.url || "")}">
        <label>Campaign</label><select name="campaign_id"><option value="">—</option>
          ${camps.map((x) => `<option value="${x.id}" ${x.id === c.campaign_id ? "selected" : ""}>${esc(x.name)}</option>`).join("")}</select>
        <label>Notes / outline</label><textarea name="notes">${esc(c.notes)}</textarea>
        ${actionsRow(existing ? deleteButton(c.id) : "")}
      </form>`, async (fd) => {
      const body = { title: fd.get("title"), channel: fd.get("channel"), status: fd.get("status"),
        publish_at: fd.get("publish_at") ? new Date(fd.get("publish_at") + "T12:00:00Z").toISOString() : null,
        url: fd.get("url") || null, notes: fd.get("notes"), campaign_id: fd.get("campaign_id") || null };
      if (existing) await api(`/api/content/${c.id}`, { method: "PATCH", body: JSON.stringify(body) });
      else await api(`/api/content/projects/${projectId}`, { method: "POST", body: JSON.stringify(body) });
    });
    bindDelete("/api/content", after);
  }

  function kwModal(projectId, existing, after) {
    const k = existing || { keyword: "", target_url: "", position: null, notes: "" };
    openModal(`
      <h2>${existing ? "Edit" : "Track"} keyword</h2>
      <form>
        <label>Keyword</label><input name="keyword" value="${esc(k.keyword)}" required>
        <label>Target URL</label><input name="target_url" value="${esc(k.target_url || "")}">
        <label>Current position (manual)</label><input name="position" type="number" step="0.1" value="${k.position ?? ""}">
        <label>Notes</label><textarea name="notes">${esc(k.notes)}</textarea>
        ${actionsRow(existing ? deleteButton(k.id) : "")}
      </form>`, async (fd) => {
      const body = { keyword: fd.get("keyword"), target_url: fd.get("target_url") || null,
        position: fd.get("position") ? Number(fd.get("position")) : null, notes: fd.get("notes") };
      if (existing) await api(`/api/seo/keywords/${k.id}`, { method: "PATCH", body: JSON.stringify(body) });
      else await api(`/api/seo/keywords/projects/${projectId}`, { method: "POST", body: JSON.stringify(body) });
    });
    bindDelete("/api/seo/keywords", after);
  }

  function scoreColor(s) { return s >= 80 ? "var(--good)" : s >= 60 ? "var(--warn)" : "var(--bad)"; }

  V2.tabs.growth = async function (id, p, root) {
    const [items, kws, audits, camps, seoMetrics] = await Promise.all([
      api(`/api/content?project_id=${id}`), api(`/api/seo/keywords?project_id=${id}`),
      api(`/api/seo/audits?project_id=${id}&limit=5`), api(`/api/campaigns?project_id=${id}`),
      api(`/api/projects/${id}/metrics`),
    ]);
    const rerender = () => V2.tabs.growth(id, p, root);
    const audit = audits[0];
    const clicks = seoMetrics.find((m) => m.key === "seo_clicks");
    const clickPts = clicks ? await api(`/api/projects/${id}/metrics/${clicks.id}/points?days=90`) : [];
    root.innerHTML = `
      <div class="grid-2 section" style="margin-top:12px">
        <div>
          <div class="section-head"><h2>SEO cockpit</h2>
            <span><button class="btn btn-sm" id="run-audit">${audit ? "Re-audit" : "Run audit"}</button></span></div>
          ${audit ? `
            <div class="card">
              <div class="card-row">
                <div><div class="score" style="color:${scoreColor(audit.score)}">${audit.score}<span class="muted" style="font-size:14px">/100</span></div>
                  <div class="muted" style="font-size:12px">On-page audit of <a href="${esc(audit.url)}" target="_blank" rel="noopener">${esc(audit.url)}</a> · ${fmtDate(audit.ts)}</div></div>
                <div class="mono muted" style="font-size:11px; text-align:right">
                  ${audit.page.status ? `HTTP ${audit.page.status}` : ""} · ${audit.page.ttfb_ms ? `TTFB ${audit.page.ttfb_ms}ms` : ""}<br>
                  ${audit.page.word_count != null ? `${audit.page.word_count} words` : ""} · ${audit.page.internal_links != null ? `${audit.page.internal_links} internal links` : ""}</div>
              </div>
              <ul class="findings">${audit.findings.map((f) => `<li class="${esc(f.severity)}"><b>${esc(f.severity)}</b> ${esc(f.message)}</li>`).join("") || "<li class='muted'>No issues found.</li>"}</ul>
            </div>` : `<div class="empty">No audit yet. Run one to check title, meta, headings, canonical, OG, sitemap, robots, structured data, speed.</div>`}
          <div class="card">
            <div class="card-row"><strong>Search Console clicks (90d)</strong>
              ${clicks ? "" : `<a class="btn btn-sm" href="#/settings">Connect GSC</a>`}</div>
            ${clickPts.length ? bigChart(clickPts, p.accent_color, "counter", "clicks") : `<div class="muted" style="font-size:12px; margin-top:6px">Connect Google Search Console in Settings to pull clicks, impressions, CTR and position per query.</div>`}
          </div>
          <div class="section-head" style="margin-top:20px"><h2>Keywords <span class="muted">(${kws.length})</span></h2>
            <button class="btn btn-sm" id="add-kw">+ Keyword</button></div>
          ${kws.length ? `<div class="card" style="padding:0"><table>
            <thead><tr><th>Keyword</th><th>Pos</th><th>Clicks</th><th>Impr</th><th>CTR</th><th></th></tr></thead>
            <tbody>${kws.map((k) => `<tr>
              <td><div>${esc(k.keyword)}</div>${k.target_url ? `<div class="muted" style="font-size:11px">${esc(k.target_url)}</div>` : ""}</td>
              <td class="mono">${k.position != null ? Number(k.position).toFixed(1) : "—"}</td>
              <td class="mono">${num(k.clicks)}</td><td class="mono">${num(k.impressions)}</td>
              <td class="mono">${k.ctr != null ? pct(k.ctr * 100) : "—"}</td>
              <td><button class="btn btn-sm" data-edit-kw="${k.id}">Edit</button></td></tr>`).join("")}</tbody></table></div>`
            : `<div class="empty">Track target keywords here; GSC sync fills in real positions.</div>`}
        </div>
        <div>
          <div class="section-head"><h2>Content calendar <span class="muted">(${items.length})</span></h2>
            <button class="btn btn-sm" id="add-content">+ Content</button></div>
          ${CONTENT_STATUSES.map((s) => {
            const l = items.filter((i) => i.status === s);
            return l.length ? `<div class="group-label">${badge(s)} <span class="muted">${l.length}</span></div>${l.map((c) => `
              <div class="card">
                <div class="card-row"><strong>${c.url ? `<a href="${esc(c.url)}" target="_blank" rel="noopener">${esc(c.title)}</a>` : esc(c.title)}</strong>
                  <span>${badge(c.channel)} <button class="btn btn-sm" data-edit-content="${c.id}">Edit</button></span></div>
                <div class="mono muted" style="font-size:11px; margin-top:4px">${c.publish_at ? "📅 " + fmtDate(c.publish_at) : "unscheduled"}${c.notes ? " · " + esc(c.notes.slice(0, 80)) : ""}</div>
              </div>`).join("")}` : "";
          }).join("") || `<div class="empty">No content planned. Blog posts, threads, videos, newsletters, Reddit posts.</div>`}
        </div>
      </div>`;
    document.getElementById("add-content").addEventListener("click", () => contentModal(id, camps, null, rerender));
    document.getElementById("add-kw").addEventListener("click", () => kwModal(id, null, rerender));
    root.querySelectorAll("[data-edit-content]").forEach((b) => b.addEventListener("click", () =>
      contentModal(id, camps, items.find((i) => i.id === b.dataset.editContent), rerender)));
    root.querySelectorAll("[data-edit-kw]").forEach((b) => b.addEventListener("click", () =>
      kwModal(id, kws.find((k) => k.id === b.dataset.editKw), rerender)));
    document.getElementById("run-audit").addEventListener("click", async (e) => {
      if (!p.url) { alert("Set the project URL first (Edit)."); return; }
      e.target.textContent = "Auditing…"; e.target.disabled = true;
      try { await api(`/api/seo/audits/projects/${id}`, { method: "POST", body: JSON.stringify({}) }); rerender(); }
      catch (ex) { alert(ex.message); rerender(); }
    });
  };

  /* ═══════════════ ANALYTICS ═══════════════ */
  V2.tabs.analytics = async function (id, p, root, days) {
    days = Number(days) || 30;
    const [a, recent] = await Promise.all([
      api(`/api/analytics?project_id=${id}&days=${days}`), api(`/api/analytics/recent?project_id=${id}&limit=25`),
    ]);
    const max = Math.max(1, ...a.funnel.map((s) => s.users || s.count));
    root.innerHTML = `
      <div class="section" style="margin-top:12px">
        <div class="section-head"><h2>Product analytics</h2>
          <span class="seg">${[7, 30, 90].map((d) => `<button class="btn btn-sm ${d === days ? "btn-primary" : ""}" data-days="${d}">${d}d</button>`).join("")}
            <button class="btn btn-sm" id="edit-funnel">Funnel steps</button></span></div>
        <div class="stat-strip">
          ${stat("Events", num(a.total_events), `${days}d`)}
          ${stat("Distinct event types", a.events.length)}
          ${stat("Latest DAU", a.dau.length ? num(a.dau[a.dau.length - 1].value) : "—")}
          ${stat("Funnel conversion", a.funnel.length > 1 && (a.funnel[0].users || a.funnel[0].count) ? pct((a.funnel[a.funnel.length - 1].users || a.funnel[a.funnel.length - 1].count) / (a.funnel[0].users || a.funnel[0].count) * 100) : "—", "first → last")}
        </div>
        ${a.total_events === 0 ? `<div class="empty">No events yet. Push them from ${esc(p.name)} with the ingest token (see "Ingest token" above): <code>POST /api/v1/events</code> with names matching your funnel steps: <b>${a.funnel_steps.join(" → ")}</b>.</div>` : ""}
        <div class="grid-2">
          <div class="card">
            <strong>Funnel</strong> <span class="muted" style="font-size:12px">unique users, ${days}d</span>
            <div class="funnel">${a.funnel.map((s) => `
              <div class="funnel-row">
                <div class="funnel-label mono">${esc(s.step)}</div>
                <div class="funnel-bar"><div style="width:${((s.users || s.count) / max * 100).toFixed(1)}%; background:${esc(p.accent_color)}"></div></div>
                <div class="funnel-val mono">${num(s.users || s.count)}${s.rate != null ? ` <span class="muted">${pct(s.rate)}</span>` : ""}</div>
              </div>`).join("")}</div>
          </div>
          <div class="card">
            <strong>Daily active users</strong>
            ${a.dau.length ? bigChart(a.dau, p.accent_color, "counter", "users") : `<div class="muted" style="font-size:12px">Send <code>user_key</code> with events to get DAU.</div>`}
          </div>
        </div>
        <div class="grid-2" style="margin-top:16px">
          <div class="card" style="padding:0"><table>
            <thead><tr><th>Event</th><th>Count</th><th>Users</th></tr></thead>
            <tbody>${a.events.map((e) => `<tr><td class="mono">${esc(e.name)}</td><td class="mono">${num(e.count)}</td><td class="mono">${num(e.users)}</td></tr>`).join("") || `<tr><td colspan="3" class="muted">—</td></tr>`}</tbody></table></div>
          <div class="card" style="padding:0; max-height:360px; overflow:auto"><table>
            <thead><tr><th>Recent</th><th>User</th><th>Props</th></tr></thead>
            <tbody>${recent.map((e) => `<tr><td><span class="mono">${esc(e.name)}</span><div class="muted" style="font-size:11px">${fmtDate(e.ts)}</div></td>
              <td class="mono" style="font-size:11px">${esc(e.user_key || "")}</td>
              <td class="mono" style="font-size:11px">${esc(JSON.stringify(e.properties || {}))}</td></tr>`).join("") || `<tr><td colspan="3" class="muted">—</td></tr>`}</tbody></table></div>
        </div>
      </div>`;
    root.querySelectorAll("[data-days]").forEach((b) => b.addEventListener("click", () => V2.tabs.analytics(id, p, root, Number(b.dataset.days))));
    document.getElementById("edit-funnel").addEventListener("click", () => {
      openModal(`
        <h2>Funnel steps</h2>
        <p class="muted" style="font-size:12px">Comma-separated event names, in order.</p>
        <form>
          <label>Steps</label><input name="steps" value="${esc(a.funnel_steps.join(", "))}" required>
          ${actionsRow()}
        </form>`, async (fd) => {
        const steps = fd.get("steps").split(",").map((s) => s.trim()).filter(Boolean);
        await api(`/api/projects/${id}`, { method: "PATCH", body: JSON.stringify({ settings: { ...(p.settings || {}), funnel: steps } }) });
      });
    });
  };

  /* ═══════════════ FINANCE ═══════════════ */
  function costModal(projectId, existing, after) {
    const c = existing || { category: "infra", amount: "", period_start: today().slice(0, 8) + "01", period_end: today(), note: "" };
    openModal(`
      <h2>${existing ? "Edit" : "Add"} cost</h2>
      <form>
        <div class="grid-2"><div><label>Category</label><select name="category">${options(COST_CATS, c.category)}</select></div>
          <div><label>Amount ($)</label><input name="amount" type="number" step="0.01" value="${c.amount}" required></div></div>
        <div class="grid-2"><div><label>Period start</label><input name="period_start" type="date" value="${c.period_start}" required></div>
          <div><label>Period end</label><input name="period_end" type="date" value="${c.period_end}" required></div></div>
        <label>Note</label><input name="note" value="${esc(c.note)}" placeholder="Railway, Anthropic, domain…">
        ${actionsRow(existing ? deleteButton(c.id) : "")}
      </form>`, async (fd) => {
      const body = { category: fd.get("category"), amount: Number(fd.get("amount")), period_start: fd.get("period_start"),
        period_end: fd.get("period_end"), note: fd.get("note") };
      if (existing) await api(`/api/costs/${c.id}`, { method: "PATCH", body: JSON.stringify(body) });
      else await api(`/api/costs/projects/${projectId}`, { method: "POST", body: JSON.stringify(body) });
    });
    bindDelete("/api/costs", after);
  }

  function adModal(projectId, camps, after) {
    openModal(`
      <h2>Log ad spend (per day)</h2>
      <form>
        <div class="grid-2"><div><label>Platform</label><select name="platform">${options(AD_PLATFORMS, "google")}</select></div>
          <div><label>Day</label><input name="day" type="date" value="${today()}" required></div></div>
        <div class="grid-2"><div><label>Spend ($)</label><input name="spend" type="number" step="0.01" required></div>
          <div><label>Conversions</label><input name="conversions" type="number" value="0"></div></div>
        <div class="grid-2"><div><label>Impressions</label><input name="impressions" type="number" value="0"></div>
          <div><label>Clicks</label><input name="clicks" type="number" value="0"></div></div>
        <label>Campaign</label><select name="campaign_id"><option value="">—</option>
          ${camps.map((x) => `<option value="${x.id}">${esc(x.name)}</option>`).join("")}</select>
        ${actionsRow()}
      </form>`, async (fd) => {
      await api(`/api/ad-spend/projects/${projectId}`, { method: "POST", body: JSON.stringify({
        platform: fd.get("platform"), day: fd.get("day"), spend: Number(fd.get("spend")),
        conversions: Number(fd.get("conversions") || 0), impressions: Number(fd.get("impressions") || 0),
        clicks: Number(fd.get("clicks") || 0), campaign_id: fd.get("campaign_id") || null }) });
    });
    void after;
  }

  V2.tabs.finance = async function (id, p, root, days) {
    days = Number(days) || 30;
    const [f, costs, ads, camps, integs, metrics] = await Promise.all([
      api(`/api/finance?project_id=${id}&days=${days}`), api(`/api/costs?project_id=${id}`),
      api(`/api/ad-spend?project_id=${id}`), api(`/api/campaigns?project_id=${id}`), api(`/api/integrations`),
      api(`/api/projects/${id}/metrics`),
    ]);
    const stripe = integs.find((i) => i.provider === "stripe" && i.project_id === id);
    const rev = metrics.find((m) => m.key === "revenue");
    const revPts = rev ? await api(`/api/projects/${id}/metrics/${rev.id}/points?days=${days}`) : [];
    const delta = f.revenue_prev ? ((f.revenue - f.revenue_prev) / f.revenue_prev * 100) : null;
    const rerender = () => V2.tabs.finance(id, p, root, days);
    root.innerHTML = `
      <div class="section" style="margin-top:12px">
        <div class="section-head"><h2>Finance</h2>
          <span class="seg">${[30, 90, 365].map((d) => `<button class="btn btn-sm ${d === days ? "btn-primary" : ""}" data-days="${d}">${d}d</button>`).join("")}
            ${stripe ? `<button class="btn btn-sm" id="sync-stripe">Sync Stripe</button>` : `<a class="btn btn-sm" href="#/settings">Connect Stripe</a>`}</span></div>
        <div class="stat-strip">
          ${stat("Revenue", money(f.revenue), delta != null ? `<span style="color:${delta >= 0 ? "var(--good)" : "var(--bad)"}">${delta >= 0 ? "▲" : "▼"} ${Math.abs(delta).toFixed(0)}%</span>` : `${days}d`)}
          ${stat("MRR", money(f.mrr))}
          ${stat("Active subs", num(f.active_subscriptions), f.arpu != null ? `ARPU ${money(f.arpu)}` : "")}
          ${stat("Costs", money(f.total_costs), `ads ${money(f.ad_spend)}`)}
          ${stat("Net", `<span style="color:${f.net >= 0 ? "var(--good)" : "var(--bad)"}">${money(f.net)}</span>`, f.margin_pct != null ? `${pct(f.margin_pct)} margin` : "")}
          ${stat("CAC", money(f.cac), f.ad_conversions ? `${f.ad_conversions} conv` : "paid only")}
          ${stat("ROAS", f.roas != null ? f.roas + "×" : "—", f.cpc != null ? `CPC ${money(f.cpc)}` : "")}
        </div>
        <div class="grid-2">
          <div class="card"><strong>Revenue</strong> <span class="muted" style="font-size:12px">${stripe ? "from Stripe" : "manual / ingest — connect Stripe to automate"}</span>
            ${revPts.length ? bigChart(revPts, "var(--good)", "currency", "$") : `<div class="muted" style="font-size:12px; margin-top:6px">No revenue points in this window.</div>`}</div>
          <div class="card"><strong>Costs by category</strong> <span class="muted" style="font-size:12px">${days}d</span>
            <table style="margin-top:8px"><tbody>
              ${Object.entries(f.costs_by_category).map(([k, v]) => `<tr><td>${badge(k)}</td><td class="mono" style="text-align:right">${money(v)}</td></tr>`).join("")}
              <tr><td>${badge("ads")} <span class="muted" style="font-size:11px">from ad spend</span></td><td class="mono" style="text-align:right">${money(f.ad_spend)}</td></tr>
            </tbody></table></div>
        </div>
        <div class="grid-2" style="margin-top:16px">
          <div>
            <div class="section-head"><h3>Costs ledger</h3><button class="btn btn-sm" id="add-cost">+ Cost</button></div>
            <div class="card" style="padding:0"><table><thead><tr><th>Category</th><th>Period</th><th>Note</th><th style="text-align:right">Amount</th><th></th></tr></thead>
              <tbody>${costs.map((c) => `<tr><td>${badge(c.category)}</td><td class="mono" style="font-size:11px">${c.period_start} → ${c.period_end}</td>
                <td>${esc(c.note)}</td><td class="mono" style="text-align:right">${money(c.amount)}</td><td><button class="btn btn-sm" data-edit-cost="${c.id}">Edit</button></td></tr>`).join("")
                || `<tr><td colspan="5" class="muted">No costs logged. Railway, LLM APIs, domains, tools…</td></tr>`}</tbody></table></div>
          </div>
          <div>
            <div class="section-head"><h3>Paid ads cockpit</h3><button class="btn btn-sm" id="add-ad">+ Spend</button></div>
            <div class="stat-strip" style="margin-bottom:12px">
              ${stat("Spend", money(f.ad_spend), `${days}d`)}${stat("Clicks", num(f.ad_clicks))}${stat("Impr", num(f.ad_impressions))}
              ${stat("CTR", f.ad_impressions ? pct(f.ad_clicks / f.ad_impressions * 100) : "—")}${stat("CVR", f.ad_clicks ? pct(f.ad_conversions / f.ad_clicks * 100) : "—")}
            </div>
            <div class="card" style="padding:0; max-height:320px; overflow:auto"><table><thead><tr><th>Day</th><th>Platform</th><th style="text-align:right">Spend</th><th style="text-align:right">Clicks</th><th style="text-align:right">Conv</th><th></th></tr></thead>
              <tbody>${ads.slice(0, 60).map((a) => `<tr><td class="mono" style="font-size:11px">${a.day}</td><td>${badge(a.platform)}</td>
                <td class="mono" style="text-align:right">${money(a.spend)}</td><td class="mono" style="text-align:right">${num(a.clicks)}</td><td class="mono" style="text-align:right">${num(a.conversions)}</td>
                <td><button class="btn btn-sm btn-danger" data-del-ad="${a.id}">×</button></td></tr>`).join("")
                || `<tr><td colspan="6" class="muted">No ad spend logged. Log daily spend per platform to get CAC / ROAS / CPC; the ads agent reads this.</td></tr>`}</tbody></table></div>
          </div>
        </div>
      </div>`;
    root.querySelectorAll("[data-days]").forEach((b) => b.addEventListener("click", () => V2.tabs.finance(id, p, root, Number(b.dataset.days))));
    document.getElementById("add-cost").addEventListener("click", () => costModal(id, null, rerender));
    document.getElementById("add-ad").addEventListener("click", () => adModal(id, camps, rerender));
    root.querySelectorAll("[data-edit-cost]").forEach((b) => b.addEventListener("click", () =>
      costModal(id, costs.find((c) => c.id === b.dataset.editCost), rerender)));
    root.querySelectorAll("[data-del-ad]").forEach((b) => b.addEventListener("click", async () => {
      await api(`/api/ad-spend/${b.dataset.delAd}`, { method: "DELETE" }); rerender();
    }));
    const sync = document.getElementById("sync-stripe");
    if (sync) sync.addEventListener("click", async () => {
      sync.textContent = "Syncing…";
      try { await api(`/api/integrations/${stripe.id}/sync`, { method: "POST" }); rerender(); }
      catch (ex) { alert(ex.message); sync.textContent = "Sync Stripe"; }
    });
  };

  /* ═══════════════ OPS ═══════════════ */
  V2.tabs.ops = async function (id, p, root) {
    const [o, metrics, targets, alerts] = await Promise.all([
      api(`/api/ops?project_id=${id}`), api(`/api/projects/${id}/metrics`),
      api(`/api/targets?project_id=${id}`), api(`/api/alerts?project_id=${id}`),
    ]);
    const u = o.uptime;
    const rerender = () => V2.tabs.ops(id, p, root);
    const mName = (mid) => (metrics.find((m) => m.id === mid) || {}).name || "?";
    const rw = o.railway;
    root.innerHTML = `
      <div class="section" style="margin-top:12px">
        <div class="section-head"><h2>Ops</h2><button class="btn btn-sm" id="run-uptime">Probe now</button></div>
        <div class="stat-strip">
          ${stat("Uptime", u.uptime_pct != null ? pct(u.uptime_pct) : "—", "7d")}
          ${stat("Avg latency", u.avg_latency_ms != null ? u.avg_latency_ms + " ms" : "—")}
          ${stat("Last check", u.last ? `<span style="color:${u.last.ok ? "var(--good)" : "var(--bad)"}">${u.last.ok ? "UP" : "DOWN"}</span>` : "—", u.last ? `${u.last.status_code || ""} ${fmtDate(u.last.ts)}` : p.url ? "probes every 5 min" : "set a URL first")}
          ${stat("Checks", num(u.checks), "7d")}
        </div>
        <div class="card"><strong>Uptime history</strong> <span class="muted" style="font-size:12px">last ${u.recent.length} probes</span>
          <div class="uptime-bar">${u.recent.map((r) => `<span class="${r.ok ? "ok" : "bad"}" title="${fmtDate(r.ts)} · ${r.code || "err"} · ${r.ms}ms"></span>`).join("") || `<span class="muted" style="font-size:12px">No probes yet.</span>`}</div>
          ${u.last && u.last.error ? `<div class="muted mono" style="font-size:11px; margin-top:6px; color:var(--bad)">${esc(u.last.error)}</div>` : ""}</div>
        <div class="grid-2" style="margin-top:16px">
          <div class="card">
            <div class="card-row"><strong>Railway</strong>${rw ? "" : `<a class="btn btn-sm" href="#/settings">Connect</a>`}</div>
            ${rw && !rw.error ? `<div class="muted" style="font-size:12px">${esc(rw.name)}</div>
              <table style="margin-top:8px"><thead><tr><th>Service</th><th>Latest deploy</th><th>When</th></tr></thead><tbody>
              ${rw.services.map((s) => `<tr><td>${esc(s.name)}${s.url ? ` <a href="${esc(s.url)}" target="_blank" rel="noopener" class="muted" style="font-size:11px">↗</a>` : ""}</td>
                <td>${badge(s.status === "SUCCESS" ? "healthy" : ["FAILED", "CRASHED"].includes(s.status) ? "critical" : (s.status || "unknown").toLowerCase())}</td>
                <td class="mono muted" style="font-size:11px">${s.deployed_at ? fmtDate(s.deployed_at) : "—"}</td></tr>`).join("")}</tbody></table>`
              : rw && rw.error ? `<div class="muted" style="font-size:12px; color:var(--bad)">${esc(rw.error)}</div>`
              : `<div class="muted" style="font-size:12px">Link the Railway project id in Settings → Integrations to see services and deploy status here.</div>`}
          </div>
          <div>
            <div class="card">
              <div class="card-row"><strong>Targets</strong><button class="btn btn-sm" id="add-target">+ Target</button></div>
              ${targets.map((t) => `<div class="card-row" style="margin-top:6px; font-size:13px"><span>${esc(mName(t.metric_id))} → <b class="mono">${num(t.target_value)}</b> ${t.label ? `<span class="muted">${esc(t.label)}</span>` : ""}${t.due_date ? ` <span class="muted mono" style="font-size:11px">by ${t.due_date}</span>` : ""}</span>
                <button class="btn btn-sm btn-danger" data-del-target="${t.id}">×</button></div>`).join("") || `<div class="muted" style="font-size:12px; margin-top:6px">No targets. Set a goal per key metric to see progress.</div>`}
            </div>
            <div class="card">
              <div class="card-row"><strong>Alert rules</strong><button class="btn btn-sm" id="add-alert">+ Alert</button></div>
              ${alerts.map((a) => `<div class="card-row" style="margin-top:6px; font-size:13px"><span>${esc(mName(a.metric_id))} <span class="mono">${esc(a.condition)} ${a.threshold}</span> <span class="muted mono" style="font-size:11px">${a.window_days}d window${a.last_fired_at ? ` · fired ${fmtDate(a.last_fired_at)}` : ""}</span></span>
                <button class="btn btn-sm btn-danger" data-del-alert="${a.id}">×</button></div>`).join("") || `<div class="muted" style="font-size:12px; margin-top:6px">No alerts. Fires a recommendation (and Slack, if connected) when a metric drops, breaches or goes stale.</div>`}
            </div>
          </div>
        </div>
      </div>`;
    document.getElementById("run-uptime").addEventListener("click", async (e) => {
      e.target.textContent = "Probing…"; await api("/api/ops/uptime/run", { method: "POST" }); rerender();
    });
    const metricOpts = metrics.map((m) => `<option value="${m.id}">${esc(m.name)}</option>`).join("");
    document.getElementById("add-target").addEventListener("click", () => openModal(`
      <h2>New target</h2><form>
        <label>Metric</label><select name="metric_id" required>${metricOpts}</select>
        <div class="grid-2"><div><label>Target value</label><input name="target_value" type="number" step="any" required></div>
          <div><label>Due date</label><input name="due_date" type="date"></div></div>
        <label>Label</label><input name="label" placeholder="e.g. Q4 goal">
        ${actionsRow()}</form>`, async (fd) => {
      await api("/api/targets", { method: "POST", body: JSON.stringify({ metric_id: fd.get("metric_id"), target_value: Number(fd.get("target_value")),
        due_date: fd.get("due_date") || null, label: fd.get("label") }) });
    }));
    document.getElementById("add-alert").addEventListener("click", () => openModal(`
      <h2>New alert rule</h2><form>
        <label>Metric</label><select name="metric_id" required>${metricOpts}</select>
        <div class="grid-3"><div><label>Condition</label><select name="condition">${options(ALERT_CONDS, "drop_pct")}</select></div>
          <div><label>Threshold</label><input name="threshold" type="number" step="any" required value="20"></div>
          <div><label>Window (days)</label><input name="window_days" type="number" value="7"></div></div>
        <p class="muted" style="font-size:12px">below/above compare the latest value; drop_pct compares this window's sum to the previous; stale_days fires when no data for N days.</p>
        ${actionsRow()}</form>`, async (fd) => {
      await api("/api/alerts", { method: "POST", body: JSON.stringify({ metric_id: fd.get("metric_id"), condition: fd.get("condition"),
        threshold: Number(fd.get("threshold")), window_days: Number(fd.get("window_days") || 7) }) });
    }));
    root.querySelectorAll("[data-del-target]").forEach((b) => b.addEventListener("click", async () => {
      await api(`/api/targets/${b.dataset.delTarget}`, { method: "DELETE" }); rerender(); }));
    root.querySelectorAll("[data-del-alert]").forEach((b) => b.addEventListener("click", async () => {
      await api(`/api/alerts/${b.dataset.delAlert}`, { method: "DELETE" }); rerender(); }));
  };

  /* ═══════════════ AGENTS ═══════════════ */
  const KIND_BLURB = {
    weekly_brief: "Digest of metric deltas, experiments, feedback and what to do next. Posts to Slack if connected.",
    seo: "Runs an on-page audit + reads Search Console data, proposes content and technical fixes.",
    analytics: "Reads the event funnel, DAU and feature requests; flags drop-offs and activation gaps.",
    ads: "Reads ad spend, CAC, ROAS, CPC per platform and proposes budget shifts and creative tests.",
    custom: "Your own instructions on top of the project snapshot.",
  };

  V2.recCard = function (r, { showProject = false, projects = [] } = {}) {
    const proj = showProject && projects.find((p) => p.id === r.project_id);
    return `<div class="card rec ${r.status}" data-rec="${r.id}">
      <div class="card-row">
        <strong>${esc(r.title)}</strong>
        <span>${badge(r.kind)} <span class="badge impact-${r.impact}">${r.impact} impact</span> <span class="badge">${r.effort} effort</span></span>
      </div>
      <div style="font-size:13px; margin-top:6px">${esc(r.body)}</div>
      <div class="card-row" style="margin-top:8px">
        <span class="mono muted" style="font-size:11px">${proj ? `<span style="color:${esc(proj.accent_color)}">●</span> ${esc(proj.name)} · ` : ""}${fmtDate(r.created_at)}${r.status !== "open" ? " · " + badge(r.status) : ""}</span>
        ${r.status === "open" ? `<span>
          <button class="btn btn-sm btn-devin" data-rec-devin="${r.id}">◆ Devin</button>
          ${r.project_id ? `<button class="btn btn-sm" data-rec-exp="${r.id}">→ Experiment</button>` : ""}
          <button class="btn btn-sm" data-rec-status="${r.id}" data-to="done">Done</button>
          <button class="btn btn-sm" data-rec-status="${r.id}" data-to="dismissed">Dismiss</button></span>`
        : r.experiment_id ? `<a class="btn btn-sm" href="#/experiments">View experiment</a>` : r.devin_session_id ? `<a class="btn btn-sm" href="#/devin">View session</a>` : ""}
      </div>
    </div>`;
  };

  V2.bindRecCards = function (root, recs, rerender) {
    root.querySelectorAll("[data-rec-status]").forEach((b) => b.addEventListener("click", async () => {
      await api(`/api/recommendations/${b.dataset.recStatus}`, { method: "PATCH", body: JSON.stringify({ status: b.dataset.to }) }); rerender();
    }));
    root.querySelectorAll("[data-rec-exp]").forEach((b) => b.addEventListener("click", async () => {
      await api(`/api/recommendations/${b.dataset.recExp}/to-experiment`, { method: "POST" }); rerender();
    }));
    root.querySelectorAll("[data-rec-devin]").forEach((b) => b.addEventListener("click", () => {
      const r = recs.find((x) => x.id === b.dataset.recDevin);
      V2.devinModal({ project_id: r.project_id, source_type: "recommendation", source_id: r.id, title: r.title,
        prompt: `${r.title}\n\n${r.body}\n\nImplement this and open a PR.` });
    }));
  };

  function agentModal(projectId, existing, after) {
    const a = existing || { kind: "custom", name: "", instructions: "", schedule: "manual", enabled: true };
    openModal(`
      <h2>${existing ? "Edit" : "New"} agent</h2>
      <form>
        <label>Name</label><input name="name" value="${esc(a.name)}" required>
        <div class="grid-2">
          <div><label>Kind</label><select name="kind" ${existing ? "disabled" : ""}>${options(Object.keys(KIND_BLURB), a.kind)}</select></div>
          <div><label>Schedule</label><select name="schedule">${options(["manual", "daily", "weekly"], a.schedule)}</select></div>
        </div>
        <label>Extra instructions (focus areas, constraints)</label><textarea name="instructions">${esc(a.instructions)}</textarea>
        <label><input type="checkbox" name="enabled" ${a.enabled ? "checked" : ""} style="width:auto"> Enabled</label>
        ${actionsRow(existing ? deleteButton(a.id) : "")}
      </form>`, async (fd) => {
      const body = { name: fd.get("name"), schedule: fd.get("schedule"), instructions: fd.get("instructions"), enabled: fd.get("enabled") === "on" };
      if (existing) await api(`/api/agents/${a.id}`, { method: "PATCH", body: JSON.stringify(body) });
      else await api("/api/agents", { method: "POST", body: JSON.stringify({ ...body, kind: fd.get("kind"), project_id: projectId }) });
    });
    bindDelete("/api/agents", after);
  }

  V2.tabs.agents = async function (id, p, root) {
    const [agents, recs, runs, llm] = await Promise.all([
      api(`/api/agents?project_id=${id}`), api(`/api/recommendations?project_id=${id}&status=open`),
      api(`/api/agents/runs/recent?project_id=${id}&limit=10`), api("/api/agents/status"),
    ]);
    const mine = agents.filter((a) => a.project_id === id);
    const rerender = () => V2.tabs.agents(id, p, root);
    root.innerHTML = `
      <div class="section" style="margin-top:12px">
        ${llm.llm_configured ? "" : `<div class="notice">ANTHROPIC_API_KEY is not set — agents run in <b>mock mode</b> and return placeholder recommendations so you can test the loop.</div>`}
        <div class="grid-2">
          <div>
            <div class="section-head"><h2>Agents</h2>
              <span>${mine.length ? "" : `<button class="btn btn-sm" id="bootstrap">Add standard set</button>`}<button class="btn btn-sm" id="add-agent">+ Agent</button></span></div>
            ${mine.map((a) => `<div class="card">
              <div class="card-row"><strong>${esc(a.name)}</strong><span>${badge(a.kind.replace("_", " "))} ${badge(a.schedule)} ${a.enabled ? "" : badge("paused")}</span></div>
              <div class="muted" style="font-size:12px; margin-top:4px">${esc(KIND_BLURB[a.kind])}${a.instructions ? `<br><i>${esc(a.instructions)}</i>` : ""}</div>
              <div class="card-row" style="margin-top:8px"><span class="mono muted" style="font-size:11px">${a.last_run_at ? "last run " + fmtDate(a.last_run_at) : "never run"}</span>
                <span><button class="btn btn-sm" data-edit-agent="${a.id}">Edit</button> <button class="btn btn-sm btn-primary" data-run-agent="${a.id}">Run now</button></span></div>
            </div>`).join("") || `<div class="empty">No agents for ${esc(p.name)}. Add the standard set: weekly brief, SEO, analytics, ads.</div>`}
            <div class="section-head" style="margin-top:20px"><h3>Recent runs</h3></div>
            ${runs.map((r) => {
              const a = agents.find((x) => x.id === r.agent_id) || {};
              return `<div class="card" style="padding:10px 14px">
                <div class="card-row"><span><b>${esc(a.name || "agent")}</b> ${badge(r.status === "succeeded" ? "healthy" : r.status === "failed" ? "critical" : r.status)} <span class="muted" style="font-size:11px">${r.trigger}</span></span>
                  <span class="mono muted" style="font-size:11px">${fmtDate(r.created_at)}${r.input_tokens ? ` · ${num(r.input_tokens + r.output_tokens)} tok` : ""}</span></div>
                ${r.summary ? `<div style="font-size:13px; margin-top:6px">${esc(r.summary)}</div>` : ""}${r.error ? `<div class="mono" style="font-size:11px; color:var(--bad); margin-top:6px">${esc(r.error)}</div>` : ""}
              </div>`; }).join("") || `<div class="muted" style="font-size:12px">No runs yet.</div>`}
          </div>
          <div>
            <div class="section-head"><h2>Recommendations <span class="muted">(${recs.length} open)</span></h2><a href="#/inbox" class="muted" style="font-size:12px">portfolio inbox →</a></div>
            <div id="rec-list">${recs.map((r) => V2.recCard(r)).join("") || `<div class="empty">Nothing open. Run an agent to get recommendations; accept them into experiments or Devin sessions.</div>`}</div>
          </div>
        </div>
      </div>`;
    const bs = document.getElementById("bootstrap");
    if (bs) bs.addEventListener("click", async () => { await api(`/api/agents/bootstrap/${id}`, { method: "POST" }); rerender(); });
    document.getElementById("add-agent").addEventListener("click", () => agentModal(id, null, rerender));
    root.querySelectorAll("[data-edit-agent]").forEach((b) => b.addEventListener("click", () =>
      agentModal(id, mine.find((a) => a.id === b.dataset.editAgent), rerender)));
    root.querySelectorAll("[data-run-agent]").forEach((b) => b.addEventListener("click", async () => {
      b.textContent = "Running…"; b.disabled = true;
      try { await api(`/api/agents/${b.dataset.runAgent}/run`, { method: "POST" }); } catch (ex) { alert(ex.message); }
      rerender();
    }));
    V2.bindRecCards(root, recs, rerender);
  };
})();
