(() => {
  "use strict";
  const $ = (q) => document.querySelector(q);
  const $$ = (q) => [...document.querySelectorAll(q)];
  const Koh = window.Koh;
  const PAGES = ["overview", "update", "settings"];

  function formatUptime(s) {
    s = Math.max(0, Number(s) || 0);
    const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), sec = Math.floor(s % 60), p = (n) => String(n).padStart(2, "0");
    return h ? `${p(h)}:${p(m)}:${p(sec)}` : `${p(m)}:${p(sec)}`;
  }
  function setService(id, value) {
    $("#svc-" + id).textContent = value;
    $("#led-" + id).classList.toggle("ok", ["ONLINE", "READY", "LOCAL", "ACTIVE"].includes(value));
  }
  async function refreshStatus() {
    try {
      const d = await Koh.api("/api/status"), x = d.runtime;
      $("#side-status").textContent = x.status; $("#side-action").textContent = x.current_action;
      $("#hero-status").textContent = x.status; $("#current-action").textContent = x.current_action;
      $("#version").textContent = `v${x.version}`;
      $("#cpu").textContent = `${Math.round(x.cpu_percent)}%`; $("#memory").textContent = `${x.memory_mb} MB`;
      $("#uptime").textContent = formatUptime(x.uptime_seconds); $("#port").textContent = x.port;
      setService("core", d.services.core); setService("db", d.services.database); setService("web", d.services.web); setService("watchdog", d.services.watchdog);
      $("#overall-state").textContent = d.services.core === "ONLINE" ? "ONLINE" : "ПРОВЕРКА";
      Koh.status = d;
      if (Koh.onStatus) Koh.onStatus(d);
      Koh.statusHooks.forEach(fn => { try { fn(d); } catch (e) { console.error(e); } });
    } catch {
      $("#side-status").textContent = "Нет связи"; $("#side-action").textContent = "Ожидание ядра"; $("#overall-state").textContent = "OFFLINE";
    }
  }
  function go(page) {
    if (!PAGES.includes(page)) page = "overview";
    $$(".nav").forEach(x => x.classList.toggle("active", x.dataset.page === page));
    $$(".page").forEach(x => x.classList.toggle("active", x.id === `page-${page}`));
    if (location.hash.slice(1) !== page) history.replaceState(null, "", page === "overview" ? location.pathname : `#${page}`);
  }
  $$(".nav").forEach(x => x.addEventListener("click", () => go(x.dataset.page)));
  $("#refresh").addEventListener("click", () => { refreshStatus(); if (Koh.refreshOverview) Koh.refreshOverview(); Koh.toast("Обновлено"); });
  window.addEventListener("hashchange", () => go((location.hash || "#overview").slice(1)));
  // drifting sakura petals (purely decorative; hidden by the Petals/Animations settings)
  const petals = $("#petals");
  if (petals) for (let i = 0; i < 12; i++) {
    const p = document.createElement("i"); p.className = "petal";
    p.style.left = (Math.random() * 100).toFixed(1) + "%"; p.style.animationDuration = (16 + Math.random() * 16).toFixed(1) + "s";
    p.style.animationDelay = (-Math.random() * 30).toFixed(1) + "s"; p.style.scale = (0.7 + Math.random() * 0.8).toFixed(2);
    petals.append(p);
  }
  Koh.refreshStatus = refreshStatus;
  Koh.go = go;
  go((location.hash || "#overview").slice(1));
  $("#greeting").textContent = Koh.greeting().replace(",", ",").replace(".", ".");
  refreshStatus();
  // Poll only while the tab is visible: a hidden page should cost nothing.
  setInterval(() => { if (!document.hidden) refreshStatus(); }, 3000);
  document.addEventListener("visibilitychange", () => { if (!document.hidden) refreshStatus(); });
  Koh.reload();
})();
