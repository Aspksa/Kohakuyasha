(() => {
  "use strict";
  const KEY = "kohakuyasha.avatar.pos";
  const DRAG_PX = 6, LONG_PRESS_MS = 550, MARGIN = 8;
  const avatar = document.getElementById("avatar");
  const chat = document.getElementById("chat-panel");
  const cabinet = document.getElementById("cabinet-panel");
  if (!avatar || !chat || !cabinet) return;
  const img = document.getElementById("avatar-img");

  // Shared helpers/state for chat.js and cabinet.js.
  const Koh = window.Koh = {
    panels: {chat, cabinet},
    hooks: {},
    settings: {avatar: {crop: "face", shape: "soft", size: 96, ring: false, glow: true, status_dot: true}, ai: {provider: "none"}},
    listeners: [],
    api: async (url, options = {}) => {
      const headers = {"X-Kohakuyasha-Request": "1", ...(options.body ? {"Content-Type": "application/json"} : {})};
      const r = await fetch(url, {credentials: "same-origin", ...options, headers});
      if (r.status === 401) { location.reload(); throw new Error("session expired"); }
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      return r.json();
    },
    el: (tag, cls, text) => { const n = document.createElement(tag); if (cls) n.className = cls; if (text !== undefined) n.textContent = text; return n; },
    faceSrc: "/static/avatar-small.png",
    onSettings: (fn) => Koh.listeners.push(fn),
    notify: () => Koh.listeners.forEach(fn => { try { fn(Koh.settings); } catch {} }),
    show: (panel) => show(panel),
    close: () => closeAll(),
    applyAvatar: (el = avatar, image = img) => applyAvatarTo(el, image),
    resetPos: () => { pos = {x: null, y: null}; applyPos(); savePos(); },
  };

  let pos = {x: null, y: null};
  const clamp = (v, lo, hi) => Math.min(Math.max(v, lo), Math.max(lo, hi));
  const size = () => avatar.offsetWidth || 96;

  function applyAvatarTo(el, image) {
    const a = Koh.settings.avatar;
    el.classList.remove("shape-soft", "shape-rounded", "shape-circle");
    el.classList.add(`shape-${a.shape}`);
    el.classList.toggle("ring", !!a.ring);
    el.classList.toggle("glow", !!a.glow);
    el.classList.toggle("nodot", !a.status_dot);
    image.src = a.crop === "full" ? "/static/avatar-full.jpg" : "/static/avatar-small.png";
    if (el === avatar) { el.style.width = a.size + "px"; el.style.height = a.size + "px"; }
  }

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
    if (panel.hidden || panel.classList.contains("max")) return;
    if (innerWidth <= 640) { panel.style.left = ""; panel.style.top = ""; return; }
    const s = size(), w = panel.offsetWidth, h = panel.offsetHeight;
    const x = pos.x + s / 2 > innerWidth / 2 ? pos.x - w - 12 : pos.x + s + 12;
    const y = pos.y + s - h;
    panel.style.left = clamp(x, MARGIN, innerWidth - w - MARGIN) + "px";
    panel.style.top = clamp(y, MARGIN, innerHeight - h - MARGIN) + "px";
  }
  function placePanels() { placePanel(chat); placePanel(cabinet); }

  const syncBody = () => document.body.classList.toggle("panel-open", !chat.hidden || !cabinet.hidden);
  function closeAll() { chat.hidden = true; cabinet.hidden = true; syncBody(); }
  function show(panel, forceOpen = false) {
    for (const p of [chat, cabinet]) p.hidden = p !== panel ? true : (forceOpen ? false : !p.hidden);
    syncBody(); placePanels();
    const name = panel === chat ? "chat" : "cabinet";
    if (!panel.hidden && Koh.hooks[name]) Koh.hooks[name]();
  }
  Koh.open = (name) => show(name === "chat" ? chat : cabinet, true);

  // Panel chrome: close, maximize.
  document.querySelectorAll("[data-close]").forEach(b => b.addEventListener("click", () => { closeAll(); avatar.focus(); }));
  document.querySelectorAll('[data-act="max"]').forEach(b => b.addEventListener("click", () => {
    const panel = b.closest(".float-panel");
    panel.classList.toggle("max");
    if (!panel.classList.contains("max")) { panel.style.left = ""; panel.style.top = ""; }
    placePanels();
  }));
  document.addEventListener("keydown", (e) => { if (e.key === "Escape" && (!chat.hidden || !cabinet.hidden)) closeAll(); });

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
  addEventListener("resize", applyPos);

  Koh.onSettings(() => { applyAvatarTo(avatar, img); applyPos(); });
  Koh.reloadSettings = async () => {
    try { const d = await Koh.api("/api/settings"); Koh.settings.avatar = d.avatar; Koh.settings.ai = d.ai; Koh.notify(); } catch {}
  };

  loadPos(); applyAvatarTo(avatar, img); applyPos();
  Koh.reloadSettings();
})();
