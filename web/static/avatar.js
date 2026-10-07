(() => {
  "use strict";
  const KEY = "kohakuyasha.avatar.pos";
  const DRAG_PX = 6, LONG_PRESS_MS = 550, MARGIN = 8, IDLE_MS = 12000;
  const Koh = window.Koh;
  const avatar = document.getElementById("avatar");
  const chat = document.getElementById("chat-panel");
  const cabinet = document.getElementById("cabinet-panel");
  if (!Koh || !avatar || !chat || !cabinet) return;
  const img = document.getElementById("avatar-img");
  Koh.panels = {chat, cabinet};

  let pos = {x: null, y: null};
  const clamp = (v, lo, hi) => Math.min(Math.max(v, lo), Math.max(lo, hi));
  const size = () => avatar.offsetWidth || Koh.settings.avatar.size || 96;
  const A = () => Koh.settings.avatar;

  // ---------- appearance ----------
  function applyAvatarTo(el, image) {
    const a = A(), face = Koh.activeFace();
    el.classList.remove("shape-soft", "shape-rounded", "shape-circle", "anim-float", "anim-pulse", "anim-breathe");
    el.classList.add(`shape-${a.shape}`);
    if (a.animation !== "none" && el === avatar) el.classList.add(`anim-${a.animation}`);
    el.classList.toggle("ring", !!a.ring); el.classList.toggle("glow", !!a.glow); el.classList.toggle("nodot", !a.status_dot);
    el.style.setProperty("--av-ring", a.ring_color); el.style.setProperty("--av-glow", a.glow_color + "99");
    el.style.setProperty("--av-opacity", String(a.opacity / 100));
    const px = el === avatar ? a.size : Math.min(a.size, 150);
    el.style.width = px + "px"; el.style.height = px + "px";
    const src = a.crop === "full" ? face.full : face.small;
    if (image.getAttribute("src") !== src) image.src = src;
  }
  Koh.applyAvatar = (el, image) => applyAvatarTo(el, image);

  // ---------- position ----------
  function applyPos() {
    const s = size();
    if (pos.x === null) { pos.x = innerWidth - s - 24; pos.y = innerHeight - s - 24 - (innerWidth <= 640 ? 66 : 0); }
    pos.x = clamp(pos.x, MARGIN, innerWidth - s - MARGIN);
    pos.y = clamp(pos.y, MARGIN, innerHeight - s - MARGIN);
    avatar.style.left = pos.x + "px"; avatar.style.top = pos.y + "px";
    placePanels();
  }
  const savePos = () => { try { localStorage.setItem(KEY, JSON.stringify(pos)); } catch {} };
  function loadPos() {
    try { const v = JSON.parse(localStorage.getItem(KEY) || "null"); if (v && Number.isFinite(v.x) && Number.isFinite(v.y)) pos = {x: v.x, y: v.y}; } catch {}
  }
  Koh.resetPos = () => { pos = {x: null, y: null}; applyPos(); savePos(); };
  function snapToEdge() {
    if (!A().snap_edges) return;
    const s = size();
    pos.x = pos.x + s / 2 < innerWidth / 2 ? MARGIN : innerWidth - s - MARGIN;
    avatar.classList.add("snapping"); applyPos();
    setTimeout(() => avatar.classList.remove("snapping"), 260);
  }

  // ---------- panels ----------
  Koh.placePanel = (panel) => {
    if (panel.hidden || panel.classList.contains("max") || panel.dataset.free === "1") return;
    if (innerWidth <= 640) { panel.style.left = ""; panel.style.top = ""; return; }
    const s = size(), w = panel.offsetWidth, h = panel.offsetHeight;
    const x = pos.x + s / 2 > innerWidth / 2 ? pos.x - w - 12 : pos.x + s + 12;
    panel.style.left = clamp(x, MARGIN, innerWidth - w - MARGIN) + "px";
    panel.style.top = clamp(pos.y + s - h, MARGIN, innerHeight - h - MARGIN) + "px";
  };
  const placePanels = () => { Koh.placePanel(chat); Koh.placePanel(cabinet); if (Koh.clampFree) Koh.clampFree(); };
  Koh.placePanels = placePanels;

  function syncBody() {
    const open = !chat.hidden || !cabinet.hidden;
    document.body.classList.toggle("panel-open", open);
    avatar.classList.toggle("hide-open", open && A().hide_on_open);
    hideBubble(); wake();
  }
  function closeAll() { chat.hidden = true; cabinet.hidden = true; syncBody(); }
  function show(panel, forceOpen = false) {
    for (const p of [chat, cabinet]) p.hidden = p !== panel ? true : (forceOpen ? false : !p.hidden);
    const name = panel === chat ? "chat" : "cabinet";
    if (!panel.hidden && Koh.restorePanel) Koh.restorePanel(panel, name);
    syncBody(); placePanels();
    if (!panel.hidden && Koh.hooks[name]) Koh.hooks[name]();
  }
  Koh.open = (name) => show(name === "chat" ? chat : cabinet, true);
  Koh.close = closeAll;
  const act = (which) => {
    const a = A()[which === "left" ? "left_action" : "right_action"];
    if (a === "chat") show(chat); else if (a === "cabinet") show(cabinet);
  };

  document.querySelectorAll("[data-close]").forEach(b => b.addEventListener("click", () => { closeAll(); avatar.focus(); }));
  document.addEventListener("keydown", (e) => { if (e.key === "Escape" && (!chat.hidden || !cabinet.hidden)) closeAll(); });

  // ---------- idle dimming ----------
  let idleTimer = 0;
  function wake() {
    avatar.classList.remove("idle"); clearTimeout(idleTimer);
    if (A().idle_dim && chat.hidden && cabinet.hidden) idleTimer = setTimeout(() => avatar.classList.add("idle"), IDLE_MS);
  }
  ["pointermove", "pointerdown", "keydown"].forEach(ev => document.addEventListener(ev, wake, {passive: true}));

  // ---------- greeting bubble ----------
  let bubble = null, bubbleTimer = 0, greeted = false;
  function hideBubble() { clearTimeout(bubbleTimer); if (bubble) { bubble.remove(); bubble = null; } }
  function showGreeting() {
    if (greeted || !A().greeting || !chat.hidden || !cabinet.hidden) return;
    greeted = true; hideBubble();
    bubble = Koh.el("div", "av-bubble", Koh.greeting());
    document.body.append(bubble);
    const s = size(), bw = bubble.offsetWidth, bh = bubble.offsetHeight;
    bubble.style.left = clamp(pos.x + s / 2 - bw / 2, MARGIN, innerWidth - bw - MARGIN) + "px";
    bubble.style.top = (pos.y - bh - 10 >= MARGIN ? pos.y - bh - 10 : pos.y + s + 10) + "px";
    bubble.addEventListener("click", () => { hideBubble(); show(chat, true); });
    bubbleTimer = setTimeout(hideBubble, 6500);
  }

  // ---------- drag / click ----------
  let drag = null, longTimer = 0, suppress = false;
  avatar.addEventListener("pointerdown", (e) => {
    if (e.button !== 0) return;
    suppress = false; hideBubble();
    avatar.setPointerCapture(e.pointerId);
    drag = {id: e.pointerId, sx: e.clientX, sy: e.clientY, ox: pos.x, oy: pos.y, moved: false, touch: e.pointerType !== "mouse"};
    if (drag.touch) longTimer = setTimeout(() => { if (drag && !drag.moved) { suppress = true; act("right"); drag = null; } }, LONG_PRESS_MS);
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
    const moved = drag.moved; drag = null; avatar.classList.remove("dragging");
    if (moved) { snapToEdge(); savePos(); } else if (e.type === "pointerup") act("left");
  };
  avatar.addEventListener("pointerup", endDrag);
  avatar.addEventListener("pointercancel", endDrag);
  avatar.addEventListener("contextmenu", (e) => { e.preventDefault(); if (suppress) { suppress = false; return; } act("right"); });
  avatar.addEventListener("keydown", (e) => {
    if (e.key === "Enter" || e.key === " ") { e.preventDefault(); act("left"); }
    else if (e.key === "ContextMenu" || (e.shiftKey && e.key === "F10")) { e.preventDefault(); act("right"); }
  });
  addEventListener("resize", applyPos);

  Koh.onSettings(() => { applyAvatarTo(avatar, img); applyPos(); syncBody(); });
  loadPos(); applyAvatarTo(avatar, img); applyPos();
  const waitSettings = setInterval(() => { if (Koh.loadedOnce) { clearInterval(waitSettings); setTimeout(showGreeting, 700); } }, 150);
  setTimeout(() => clearInterval(waitSettings), 6000);
})();
