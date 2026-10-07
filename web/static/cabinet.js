(() => {
  "use strict";
  const Koh = window.Koh; if (!Koh || !Koh.panels) return;
  const el = Koh.el;
  const body = document.getElementById("cabinet-body");
  const tabsEl = document.getElementById("cabinet-tabs");
  const TRAITS = {"devoted to her master": "предана господину", "elegant": "элегантна", "mature": "зрелая", "protective": "защищает", "calm": "спокойна", "extremely powerful": "невероятно сильна"};
  const COLORS = {white: "белые", golden: "золотые"};
  let current = "profile", token = 0;

  // ---------- shared UI helpers for all cabinet tabs ----------
  const ui = Koh.ui = {
    row: (k, v) => { const r = el("div", "cab-row"); r.append(el("span", "", k), el("b", "", String(v))); return r; },
    section: (title) => { const s = el("div", "cab-sec"); s.append(el("h4", "", title)); return s; },
    field: (label, control, hint) => { const f = el("div", "field"); if (label) f.append(el("label", "", label)); f.append(control); if (hint) f.append(el("p", "hint", hint)); return f; },
    seg: (options, value, onPick) => {
      const wrap = el("div", "seg");
      options.forEach(([val, label]) => {
        const b = el("button", val === value ? "on" : "", label); b.type = "button";
        b.addEventListener("click", () => { wrap.querySelectorAll("button").forEach(x => x.classList.remove("on")); b.classList.add("on"); onPick(val); });
        wrap.append(b);
      });
      return wrap;
    },
    toggle: (label, checked, onChange, hint) => {
      const r = el("div", "toggle-row"), t = el("div"), sw = el("label", "switch"), inp = el("input");
      t.append(document.createTextNode(label)); if (hint) t.append(el("small", "", hint));
      inp.type = "checkbox"; inp.checked = !!checked; inp.addEventListener("change", () => onChange(inp.checked));
      sw.append(inp, el("span")); r.append(t, sw); return r;
    },
    range: (label, min, max, step, value, fmt, onInput) => {
      const f = el("div", "field"), lab = el("label", "", fmt(value)), inp = el("input");
      inp.type = "range"; inp.min = min; inp.max = max; inp.step = step; inp.value = value;
      inp.addEventListener("input", () => { lab.textContent = fmt(Number(inp.value)); onInput(Number(inp.value)); });
      f.append(lab, inp); return f;
    },
    statusLine: () => el("div", "status-line"),
    setStatus: (node, ok, text) => { node.className = `status-line ${ok ? "ok" : "bad"}`; node.textContent = text; },
    btn: (text, cls, fn) => { const b = el("button", cls || "", text); b.type = "button"; b.addEventListener("click", fn); return b; },
  };

  // ---------- tab registry ----------
  Koh.registerTab = (id, label, render, order, icon = "•") => {
    Koh.tabs = Koh.tabs.filter(t => t.id !== id); Koh.tabs.push({id, label, render, order, icon});
    Koh.tabs.sort((a, b) => a.order - b.order); renderTabs();
  };
  function renderTabs() {
    tabsEl.replaceChildren(...Koh.tabs.map(t => {
      const b = el("button", "tab" + (t.id === current ? " active" : "")); b.append(el("i", "", t.icon), document.createTextNode(t.label)); b.type = "button"; b.setAttribute("role", "tab"); b.dataset.tab = t.id;
      b.addEventListener("click", () => selectTab(t.id)); return b;
    }));
  }
  async function selectTab(id) {
    const tab = Koh.tabs.find(t => t.id === id) || Koh.tabs[0]; if (!tab) return;
    current = tab.id; const mine = ++token; renderTabs();
    try { const nodes = await tab.render(); if (mine === token && nodes) { body.replaceChildren(...nodes); body.scrollTop = 0; } }
    catch { if (mine === token) body.replaceChildren(el("p", "hint", "Не удалось загрузить раздел.")); }
  }
  Koh.hooks.cabinet = () => selectTab(current);
  Koh.hooks.cabinetTab = (id) => selectTab(id);

  // ---------- rail identity + responsive layout ----------
  const railStatus = document.getElementById("rail-status"), cabPanel = Koh.panels.cabinet;
  function drawRailStatus() {
    const ai = Koh.settings.ai || {}, on = ai.provider === "cloudru" && ai.has_key;
    railStatus.replaceChildren(el("i", on ? "dot on" : "dot"), document.createTextNode(on ? "ИИ подключён" : "ИИ не подключён"));
  }
  Koh.onSettings(drawRailStatus); drawRailStatus();
  if (window.ResizeObserver) new ResizeObserver(() => cabPanel.classList.toggle("cab-narrow", cabPanel.offsetWidth < 640)).observe(cabPanel);

  // ---------- Profile ----------
  Koh.registerTab("profile", "Профиль", async () => {
    const [c, s] = await Promise.all([Koh.api("/api/character"), Koh.api("/api/status")]);
    const ch = c.character || {}, rt = s.runtime || {}, grid = el("div", "cab-grid");
    const hero = ui.section("О ЧЁМ ОНА"), heroRow = el("div", "cab-hero"), t = el("div");
    t.append(el("h3", "", ch.name || "Kohakuyasha"), el("p", "", `${ch.role === "personal assistant" ? "личный помощник" : (ch.role || "помощник")} · мифическая лиса`));
    heroRow.append(Koh.faceImg("", "big"), t); hero.append(heroRow);
    const chips = el("div", "chips"); chips.style.marginTop = "12px";
    (Array.isArray(ch.traits) ? ch.traits : []).forEach(x => chips.append(el("span", "chip", TRAITS[x] || String(x))));
    hero.append(chips);
    const looks = ui.section("ОБЛИК"), ap = ch.appearance || {};
    if (ch.apparent_age) looks.append(ui.row("Возраст на вид", ch.apparent_age));
    if (Array.isArray(ap.hair)) looks.append(ui.row("Волосы", ap.hair.map(h => COLORS[h] || h).join(", ")));
    if (ap.fox_ears) looks.append(ui.row("Лисьи уши", "да"));
    if (ap.multiple_fox_tails) looks.append(ui.row("Хвосты", "несколько"));
    if (ch.power) looks.append(ui.row("Сила", ch.power.type === "magic" ? "магия, способная разрушить мир" : String(ch.power.type)));
    const st = ui.section("СОСТОЯНИЕ");
    st.append(ui.row("Статус", rt.status || "—"), ui.row("Сообщений в чате", (c.stats || {}).messages ?? 0), ui.row("Версия", rt.version ? "v" + rt.version : "—"));
    grid.append(hero, looks, st);
    return [grid];
  }, 10, "✿");

  // ---------- System ----------
  Koh.registerTab("system", "Система", async () => {
    const s = await Koh.api("/api/status"), rt = s.runtime || {}, grid = el("div", "cab-grid"), sec = ui.section("РАБОТА");
    sec.append(ui.row("Статус", rt.status || "—"), ui.row("Действие", rt.current_action || "—"), ui.row("Версия", rt.version ? "v" + rt.version : "—"), ui.row("Порт", rt.port ?? "—"),
      ui.row("CPU", `${Math.round(rt.cpu_percent || 0)}%`), ui.row("Память процесса", `${rt.memory_mb ?? 0} MB`), ui.row("Python", rt.python || "—"));
    const svc = ui.section("СЛУЖБЫ"); Object.entries(s.services || {}).forEach(([k, v]) => svc.append(ui.row(k, v)));
    grid.append(sec, svc);
    return [grid];
  }, 90, "⚙");
})();
