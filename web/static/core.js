(() => {
  "use strict";
  const DEFAULT_FACE = {id: "default", name: "Kohakuyasha", builtin: true, url: "/static/avatar.png", small: "/static/avatar-small.png", full: "/static/avatar-full.jpg"};
  const Koh = window.Koh = {
    settings: {
      avatar: {active_face: "default", crop: "face", shape: "soft", size: 96, opacity: 100, ring: false, ring_color: "#e8be56", glow: true, glow_color: "#e8be56", status_dot: true, animation: "none", snap_edges: false, idle_dim: false, hide_on_open: false, greeting: true, left_action: "chat", right_action: "cabinet", replace_logo: true},
      faces: [DEFAULT_FACE], ai: {provider: "none"}, app: {clock_24h: true, clock_seconds: true, week_start: 1}, memory: {enabled: true, learn_chat: true, max_snippets: 6},
    },
    listeners: [],
    hooks: {},
    tabs: [],
    DEFAULT_FACE,
    api: async (url, options = {}) => {
      const headers = {"X-Kohakuyasha-Request": "1", ...(options.body ? {"Content-Type": "application/json"} : {})};
      const r = await fetch(url, {credentials: "same-origin", ...options, headers});
      if (r.status === 401) { location.reload(); throw new Error("session expired"); }
      let data = null;
      try { data = await r.json(); } catch {}
      if (!r.ok) { const e = new Error((data && data.detail) || `HTTP ${r.status}`); e.status = r.status; throw e; }
      return data;
    },
    el: (tag, cls, text) => { const n = document.createElement(tag); if (cls) n.className = cls; if (text !== undefined) n.textContent = text; return n; },
    toast: (message) => {
      const t = document.getElementById("toast"); if (!t) return;
      t.textContent = message; t.classList.add("show");
      clearTimeout(Koh._toastTimer); Koh._toastTimer = setTimeout(() => t.classList.remove("show"), 2600);
    },
    onSettings: (fn) => { Koh.listeners.push(fn); },
    notify: () => { Koh.listeners.forEach(fn => { try { fn(Koh.settings); } catch (e) { console.error(e); } }); },
    // Accepts the full settings object returned by /api/settings and by endpoints that change it.
    setAll: (d) => {
      if (!d) return;
      for (const k of ["avatar", "faces", "ai", "app", "memory"]) if (d[k]) Koh.settings[k] = d[k];
      Koh.loadedOnce = true;
      if (window.KohTheme) window.KohTheme.apply(Koh.settings.app);
      Koh.notify();
    },
    reload: async () => { try { Koh.setAll(await Koh.api("/api/settings")); } catch {} },
    activeFace: () => {
      const s = Koh.settings;
      return s.faces.find(f => f.id === s.avatar.active_face) || s.faces[0] || DEFAULT_FACE;
    },
    faceImg: (cls, kind = "small") => {
      const img = document.createElement("img"); img.className = cls || ""; img.alt = ""; img.draggable = false;
      img.dataset.face = kind; img.src = Koh.activeFace()[kind === "big" ? "url" : "small"];
      return img;
    },
    applyFaces: () => {
      const f = Koh.activeFace();
      document.querySelectorAll("img[data-face]").forEach(img => { img.src = img.dataset.face === "big" ? f.url : f.small; });
      document.querySelectorAll("img[data-logo]").forEach(img => { img.src = Koh.settings.avatar.replace_logo ? f.url : "/static/logo.svg"; });
    },
    greeting: () => {
      const h = new Date().getHours();
      return h < 5 ? "Не спите, господин?" : h < 12 ? "Доброе утро, господин." : h < 18 ? "Добрый день, господин." : "Добрый вечер, господин.";
    },
    debounce: (fn, ms) => { let t = 0; return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); }; },
    fileToBase64: (file) => new Promise((resolve, reject) => {
      const r = new FileReader(); r.onload = () => resolve(String(r.result)); r.onerror = () => reject(new Error("read")); r.readAsDataURL(file);
    }),
    readText: (file) => new Promise((resolve, reject) => {
      const r = new FileReader(); r.onload = () => resolve(String(r.result)); r.onerror = () => reject(new Error("read")); r.readAsText(file, "utf-8");
    }),
  };
  Koh.onSettings(Koh.applyFaces);
})();
