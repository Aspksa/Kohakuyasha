// Runs in <head> before first paint: applies cached appearance to avoid a flash of the wrong theme.
(() => {
  "use strict";
  const KEY = "kohakuyasha.theme";
  const root = document.documentElement;
  const dark = window.matchMedia ? window.matchMedia("(prefers-color-scheme: dark)") : null;
  let current = null;

  function apply(app) {
    if (!app) return;
    current = app;
    const theme = app.theme === "auto" ? (dark && !dark.matches ? "light" : "dark") : app.theme;
    root.dataset.theme = theme || "dark";
    root.dataset.accent = app.accent || "gold";
    root.dataset.bg = app.background || "glow";
    root.dataset.motion = app.animations === false ? "off" : "on";
    root.style.setProperty("--ui-zoom", String((app.ui_zoom || 100) / 100));
    root.style.setProperty("--dim", String((app.bg_dim ?? 45) / 100));
    root.style.setProperty("--bg-image", app.bg_image ? `url("/media/${app.bg_image}")` : "none");
    const meta = document.querySelector('meta[name="theme-color"]');
    if (meta) meta.content = theme === "light" ? "#f6f5f2" : theme === "black" ? "#000000" : "#101016";
    try { localStorage.setItem(KEY, JSON.stringify(app)); } catch {}
  }
  window.KohTheme = {apply};
  try { apply(JSON.parse(localStorage.getItem(KEY) || "null")); } catch {}
  if (dark && dark.addEventListener) dark.addEventListener("change", () => { if (current && current.theme === "auto") apply(current); });
})();
