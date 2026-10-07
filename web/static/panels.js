// Floating panel chrome: drag by the header, resize from any edge/corner, maximize, reset. Position/size persist per panel.
(() => {
  "use strict";
  const Koh = window.Koh;
  if (!Koh || !Koh.panels) return;
  const MIN_W = 320, MIN_H = 360, M = 8;
  const key = (name) => `kohakuyasha.panel.${name}`;
  const clamp = (v, lo, hi) => Math.min(Math.max(v, lo), Math.max(lo, hi));
  const mobile = () => innerWidth <= 640;
  const names = {chat: Koh.panels.chat, cabinet: Koh.panels.cabinet};

  const load = (name) => { try { return JSON.parse(localStorage.getItem(key(name)) || "null"); } catch { return null; } };
  const store = (name, panel) => {
    const r = panel.getBoundingClientRect();
    try { localStorage.setItem(key(name), JSON.stringify({x: Math.round(r.left), y: Math.round(r.top), w: Math.round(r.width), h: Math.round(r.height), free: true})); } catch {}
  };
  function apply(panel, r) {
    const w = clamp(r.w, MIN_W, innerWidth - 2 * M), h = clamp(r.h, MIN_H, innerHeight - 2 * M);
    panel.style.width = w + "px"; panel.style.height = h + "px";
    panel.style.left = clamp(r.x, M, innerWidth - w - M) + "px"; panel.style.top = clamp(r.y, M, innerHeight - h - M) + "px";
  }
  const rectOf = (panel) => { const r = panel.getBoundingClientRect(); return {x: r.left, y: r.top, w: r.width, h: r.height}; };

  Koh.restorePanel = (panel, name) => {
    if (panel.dataset.restored === "1" || mobile()) return;
    panel.dataset.restored = "1";
    const s = load(name);
    if (s && s.free && [s.x, s.y, s.w, s.h].every(Number.isFinite)) { panel.dataset.free = "1"; apply(panel, s); }
  };
  Koh.clampFree = () => {
    if (mobile()) return;
    for (const p of Object.values(names)) if (!p.hidden && p.dataset.free === "1" && !p.classList.contains("max")) apply(p, rectOf(p));
  };

  function begin(panel, name, e, dir) {
    if (mobile() || panel.classList.contains("max") || e.button !== 0) return;
    e.preventDefault();
    const target = e.currentTarget, start = rectOf(panel), sx = e.clientX, sy = e.clientY;
    target.setPointerCapture(e.pointerId);
    panel.classList.add("moving");
    const move = (ev) => {
      const dx = ev.clientX - sx, dy = ev.clientY - sy;
      let {x, y, w, h} = start;
      if (dir === "move") { x += dx; y += dy; }
      else {
        if (dir.includes("e")) w = start.w + dx;
        if (dir.includes("s")) h = start.h + dy;
        if (dir.includes("w")) { w = start.w - dx; x = start.x + dx; }
        if (dir.includes("n")) { h = start.h - dy; y = start.y + dy; }
        if (w < MIN_W) { if (dir.includes("w")) x = start.x + start.w - MIN_W; w = MIN_W; }
        if (h < MIN_H) { if (dir.includes("n")) y = start.y + start.h - MIN_H; h = MIN_H; }
        if (x < M) { w -= M - x; x = M; }
        if (y < M) { h -= M - y; y = M; }
        w = Math.min(w, innerWidth - M - x); h = Math.min(h, innerHeight - M - y);
      }
      panel.dataset.free = "1"; apply(panel, {x, y, w, h});
    };
    const up = () => {
      target.removeEventListener("pointermove", move); target.removeEventListener("pointerup", up); target.removeEventListener("pointercancel", up);
      panel.classList.remove("moving"); store(name, panel);
    };
    target.addEventListener("pointermove", move); target.addEventListener("pointerup", up); target.addEventListener("pointercancel", up);
  }

  for (const [name, panel] of Object.entries(names)) {
    ["n", "s", "e", "w", "ne", "nw", "se", "sw"].forEach(dir => {
      const h = document.createElement("div"); h.className = `rz rz-${dir}`; h.setAttribute("aria-hidden", "true");
      h.addEventListener("pointerdown", (e) => begin(panel, name, e, dir)); panel.append(h);
    });
    const head = panel.querySelector(".fp-head");
    head.addEventListener("pointerdown", (e) => { if (!e.target.closest("button")) begin(panel, name, e, "move"); });
    head.addEventListener("dblclick", (e) => { if (!e.target.closest("button")) panel.querySelector('[data-act="max"]').click(); });
    panel.querySelector('[data-act="max"]').addEventListener("click", () => {
      panel.classList.toggle("max"); Koh.placePanels();
    });
    panel.querySelector('[data-act="reset"]').addEventListener("click", () => {
      try { localStorage.removeItem(key(name)); } catch {}
      panel.classList.remove("max"); panel.dataset.free = "0";
      panel.style.width = ""; panel.style.height = ""; panel.style.left = ""; panel.style.top = "";
      Koh.placePanels(); Koh.toast("Размер и положение окна сброшены");
    });
  }
  addEventListener("resize", () => Koh.clampFree());
})();
