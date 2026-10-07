(() => {
  "use strict";
  const KEY = "kohakuyasha.avatar.pos";
  const DRAG_PX = 6, LONG_PRESS_MS = 550, MARGIN = 8;
  const avatar = document.getElementById("avatar");
  const chat = document.getElementById("chat-panel");
  const cabinet = document.getElementById("cabinet-panel");
  if (!avatar || !chat || !cabinet) return;
  const log = document.getElementById("chat-log");
  const form = document.getElementById("chat-form");
  const input = document.getElementById("chat-input");
  const cabBody = document.getElementById("cabinet-body");

  const TRAITS = {"devoted to her master":"предана господину","elegant":"элегантна","mature":"зрелая","protective":"защищает","calm":"спокойна","extremely powerful":"невероятно сильна"};
  const COLORS = {white:"белые",golden:"золотые"};
  let pos = {x: null, y: null}, chatLoaded = false, sending = false;

  const api = async (url, options = {}) => {
    const headers = {"X-Kohakuyasha-Request": "1", ...(options.body ? {"Content-Type": "application/json"} : {})};
    const r = await fetch(url, {credentials: "same-origin", ...options, headers});
    if (r.status === 401) { location.reload(); throw new Error("session expired"); }
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    return r.json();
  };
  const el = (tag, cls, text) => { const n = document.createElement(tag); if (cls) n.className = cls; if (text !== undefined) n.textContent = text; return n; };
  const clamp = (v, lo, hi) => Math.min(Math.max(v, lo), Math.max(lo, hi));
  const size = () => avatar.offsetWidth || 88;

  function applyPos() {
    const s = size();
    if (pos.x === null) { pos.x = innerWidth - s - 24; pos.y = innerHeight - s - 24; }
    pos.x = clamp(pos.x, MARGIN, innerWidth - s - MARGIN);
    pos.y = clamp(pos.y, MARGIN, innerHeight - s - MARGIN);
    avatar.style.left = pos.x + "px"; avatar.style.top = pos.y + "px";
    placePanels();
  }
  function savePos() { try { localStorage.setItem(KEY, JSON.stringify(pos)); } catch {} }
  function loadPos() {
    try { const v = JSON.parse(localStorage.getItem(KEY) || "null"); if (v && Number.isFinite(v.x) && Number.isFinite(v.y)) pos = {x: v.x, y: v.y}; } catch {}
  }

  function placePanel(panel) {
    if (panel.hidden) return;
    if (innerWidth <= 640) { panel.style.left = ""; panel.style.top = ""; return; }
    const s = size(), w = panel.offsetWidth, h = panel.offsetHeight;
    let x = pos.x + s / 2 > innerWidth / 2 ? pos.x - w - 12 : pos.x + s + 12;
    let y = pos.y + s - h;
    panel.style.left = clamp(x, MARGIN, innerWidth - w - MARGIN) + "px";
    panel.style.top = clamp(y, MARGIN, innerHeight - h - MARGIN) + "px";
  }
  function placePanels() { placePanel(chat); placePanel(cabinet); }

  function show(panel) {
    for (const p of [chat, cabinet]) p.hidden = p !== panel ? true : !p.hidden;
    placePanels();
    if (!chat.hidden) openChat();
    if (!cabinet.hidden) openCabinet();
  }

  function addMessage(m) {
    const empty = log.querySelector(".chat-empty"); if (empty) empty.remove();
    const b = el("div", `msg ${m.role}`, m.content);
    let time = "";
    try { time = new Date(m.created_at).toLocaleTimeString("ru-RU", {hour: "2-digit", minute: "2-digit"}); } catch {}
    if (time) b.append(el("small", "", time));
    log.append(b); log.scrollTop = log.scrollHeight;
  }
  async function openChat() {
    setTimeout(() => input.focus(), 0);
    if (chatLoaded) return;
    try {
      const d = await api("/api/chat?limit=100");
      chatLoaded = true; log.replaceChildren();
      if (!d.messages.length) log.append(el("div", "chat-empty", "Здесь пока тихо. Напишите мне, господин."));
      d.messages.forEach(addMessage);
    } catch { log.replaceChildren(el("div", "chat-empty", "Не удалось загрузить историю чата.")); }
  }
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const text = input.value.trim();
    if (!text || sending) return;
    sending = true; input.value = ""; input.disabled = true;
    try {
      const d = await api("/api/chat", {method: "POST", body: JSON.stringify({text})});
      chatLoaded = true; d.messages.forEach(addMessage);
    } catch { input.value = text; log.append(el("div", "chat-empty", "Не удалось отправить сообщение.")); }
    finally { sending = false; input.disabled = false; input.focus(); }
  });

  async function openCabinet() {
    try {
      const [c, s] = await Promise.all([api("/api/character"), api("/api/status")]);
      renderCabinet(c.character || {}, c.stats || {}, s.runtime || {});
    } catch { cabBody.replaceChildren(el("div", "chat-empty", "Не удалось загрузить данные кабинета.")); }
  }
  function section(title) { const s = el("div", "cab-sec"); s.append(el("h4", "", title)); return s; }
  function row(k, v) { const r = el("div", "cab-row"); r.append(el("span", "", k), el("b", "", String(v))); return r; }
  function renderCabinet(ch, stats, rt) {
    const hero = el("div", "cab-hero"), img = el("img"); img.src = "/static/avatar.png"; img.alt = "";
    const t = el("div"); t.append(el("h3", "", ch.name || "Kohakuyasha"), el("p", "", "личный помощник · мифическая лиса"));
    hero.append(img, t);
    const nodes = [hero];
    const traits = section("ХАРАКТЕР"), chips = el("div", "chips");
    (Array.isArray(ch.traits) ? ch.traits : []).forEach(x => chips.append(el("span", "chip", TRAITS[x] || String(x))));
    traits.append(chips); nodes.push(traits);
    const looks = section("ОБЛИК");
    if (ch.apparent_age) looks.append(row("Возраст на вид", ch.apparent_age));
    const hair = ch.appearance && ch.appearance.hair;
    if (Array.isArray(hair)) looks.append(row("Волосы", hair.map(h => COLORS[h] || h).join(", ")));
    if (ch.appearance && ch.appearance.multiple_fox_tails) looks.append(row("Хвосты", "несколько"));
    if (ch.appearance && ch.appearance.fox_ears) looks.append(row("Лисьи уши", "да"));
    nodes.push(looks);
    const state = section("СОСТОЯНИЕ");
    state.append(row("Статус", rt.status || "—"), row("Действие", rt.current_action || "—"), row("Сообщений в чате", stats.messages ?? 0), row("Версия", rt.version ? "v" + rt.version : "—"));
    nodes.push(state);
    cabBody.replaceChildren(...nodes);
  }

  // Drag: left button / touch moves the avatar anywhere; a click without movement opens the chat,
  // the context menu (right click, or long press on touch) opens the cabinet.
  let drag = null, longTimer = 0, suppressClick = false;
  avatar.addEventListener("pointerdown", (e) => {
    if (e.button !== 0) return;
    suppressClick = false;
    avatar.setPointerCapture(e.pointerId);
    drag = {id: e.pointerId, sx: e.clientX, sy: e.clientY, ox: pos.x, oy: pos.y, moved: false, touch: e.pointerType !== "mouse"};
    if (drag.touch) longTimer = setTimeout(() => { if (drag && !drag.moved) { suppressClick = true; show(cabinet); drag = null; } }, LONG_PRESS_MS);
  });
  avatar.addEventListener("pointermove", (e) => {
    if (!drag || e.pointerId !== drag.id) return;
    const dx = e.clientX - drag.sx, dy = e.clientY - drag.sy;
    if (!drag.moved && Math.hypot(dx, dy) < DRAG_PX) return;
    if (!drag.moved) { drag.moved = true; clearTimeout(longTimer); avatar.classList.add("dragging"); }
    pos.x = drag.ox + dx; pos.y = drag.oy + dy; applyPos();
  });
  const endDrag = (e) => {
    clearTimeout(longTimer);
    if (!drag || e.pointerId !== drag.id) return;
    const wasMoved = drag.moved; drag = null; avatar.classList.remove("dragging");
    if (wasMoved) savePos();
    else if (e.type === "pointerup") show(chat);
  };
  avatar.addEventListener("pointerup", endDrag);
  avatar.addEventListener("pointercancel", endDrag);
  avatar.addEventListener("contextmenu", (e) => { e.preventDefault(); if (suppressClick) { suppressClick = false; return; } show(cabinet); });
  avatar.addEventListener("keydown", (e) => {
    if (e.key === "Enter" || e.key === " ") { e.preventDefault(); show(chat); }
    else if (e.key === "ContextMenu" || (e.shiftKey && e.key === "F10")) { e.preventDefault(); show(cabinet); }
  });
  document.querySelectorAll("[data-close]").forEach(b => b.addEventListener("click", () => { chat.hidden = true; cabinet.hidden = true; avatar.focus(); }));
  document.addEventListener("keydown", (e) => { if (e.key === "Escape" && (!chat.hidden || !cabinet.hidden)) { chat.hidden = true; cabinet.hidden = true; } });
  addEventListener("resize", applyPos);

  loadPos(); applyPos();
})();
