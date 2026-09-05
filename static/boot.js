/* InfiniSaaS boot — optional Clerk auth, then first render */

(function () {
  const cfg = window.INFINI || {};

  function showSignIn() {
    $view.innerHTML = `<div class="signin">
      <h1 style="margin-bottom:6px">Infini<span style="color:var(--primary)">SaaS</span></h1>
      <p class="muted">Sign in to open the cockpit.</p><div id="clerk-signin"></div></div>`;
    window.Clerk.mountSignIn(document.getElementById("clerk-signin"), {
      appearance: {
        baseTheme: undefined,
        elements: { rootBox: { width: "100%", maxWidth: "25rem" }, cardBox: { width: "100%", maxWidth: "100%" } },
      },
    });
  }

  async function bootWithClerk() {
    await window.Clerk.load();
    window.__getAuthToken = async () => (window.Clerk.session ? window.Clerk.session.getToken() : null);
    window.__signIn = showSignIn;
    if (!window.Clerk.user) { showSignIn(); return; }
    window.Clerk.mountUserButton(document.getElementById("user-button"));
    window.Clerk.addListener(({ user }) => { if (!user) location.reload(); });
    render();
  }

  if (cfg.authEnabled) {
    document.body.classList.add("auth");
    if (window.Clerk) bootWithClerk();
    else window.addEventListener("clerk-ready", bootWithClerk, { once: true });
    setTimeout(() => {
      if (!window.Clerk) $view.innerHTML = `<div class="empty">Auth script failed to load. Check CLERK_PUBLISHABLE_KEY / network.</div>`;
    }, 8000);
  } else {
    render();
  }
})();
