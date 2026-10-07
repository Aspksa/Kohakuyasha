(() => {
  "use strict";
  const Koh = window.Koh; if (!Koh) return;
  const {api, el} = Koh;
  const panel = Koh.panels.chat;
  const scroller = document.getElementById("chat-scroll");
  const log = document.getElementById("chat-log");
  const form = document.getElementById("chat-form");
  const input = document.getElementById("chat-input");
  const sendBtn = document.getElementById("chat-send");
  const downBtn = document.getElementById("chat-down");
  const statusEl = document.getElementById("chat-status");
  const SUGGESTIONS = ["Расскажи о себе", "Составь план на день", "Объясни, как ты работаешь", "Придумай идею проекта"];
  let loaded = false, sending = false, typingRow = null;

  // ---------- safe Markdown-lite renderer (DOM nodes only) ----------
  function safeUrl(text) {
    try { const u = new URL(text); return u.protocol === "http:" || u.protocol === "https:" ? u.href : null; } catch { return null; }
  }
  function inline(text, parent) {
    const re = /(`[^`\n]+`)|(\*\*[^*\n]+\*\*)|(\*[^*\n]+\*)|(https?:\/\/[^\s<)]+)/g;
    let last = 0, m;
    while ((m = re.exec(text))) {
      if (m.index > last) parent.append(document.createTextNode(text.slice(last, m.index)));
      const t = m[0];
      if (m[1]) parent.append(el("code", "", t.slice(1, -1)));
      else if (m[2]) parent.append(el("strong", "", t.slice(2, -2)));
      else if (m[3]) parent.append(el("em", "", t.slice(1, -1)));
      else {
        const href = safeUrl(t);
        if (href) { const a = el("a", "", t); a.href = href; a.target = "_blank"; a.rel = "noopener noreferrer"; parent.append(a); }
        else parent.append(document.createTextNode(t));
      }
      last = m.index + t.length;
    }
    if (last < text.length) parent.append(document.createTextNode(text.slice(last)));
  }
  function textBlocks(text, out) {
    for (const block of text.split(/\n{2,}/)) {
      const lines = block.split("\n").filter(l => l.trim() !== "");
      if (!lines.length) continue;
      if (lines.every(l => /^\s*[-*•]\s+/.test(l))) {
        const ul = el("ul"); lines.forEach(l => { const li = el("li"); inline(l.replace(/^\s*[-*•]\s+/, ""), li); ul.append(li); }); out.append(ul);
      } else if (lines.every(l => /^\s*\d+[.)]\s+/.test(l))) {
        const ol = el("ol"); lines.forEach(l => { const li = el("li"); inline(l.replace(/^\s*\d+[.)]\s+/, ""), li); ol.append(li); }); out.append(ol);
      } else if (/^#{1,4}\s+/.test(lines[0])) {
        const h = el("h4"); inline(lines[0].replace(/^#{1,4}\s+/, ""), h); out.append(h);
        if (lines.length > 1) textBlocks(lines.slice(1).join("\n"), out);
      } else {
        const p = el("p");
        lines.forEach((l, i) => { if (i) p.append(document.createElement("br")); inline(l, p); });
        out.append(p);
      }
    }
  }
  function copyText(text, button) {
    const done = () => { const old = button.textContent; button.textContent = "Скопировано"; setTimeout(() => { button.textContent = old; }, 1400); };
    if (navigator.clipboard && navigator.clipboard.writeText) navigator.clipboard.writeText(text).then(done, () => {});
  }
  function renderMarkdown(text) {
    const out = document.createDocumentFragment();
    const re = /```([\w+-]*)\n?([\s\S]*?)```/g;
    let last = 0, m;
    while ((m = re.exec(text))) {
      textBlocks(text.slice(last, m.index), out);
      const code = m[2].replace(/\n$/, "");
      const box = el("div", "code"), head = el("div", "code-head"), copy = el("button", "", "Копировать");
      copy.type = "button"; copy.addEventListener("click", () => copyText(code, copy));
      head.append(el("span", "", m[1] || "код"), copy);
      const pre = el("pre"); pre.append(el("code", "", code));
      box.append(head, pre); out.append(box);
      last = m.index + m[0].length;
    }
    textBlocks(text.slice(last), out);
    return out;
  }

  // ---------- rendering ----------
  const nearBottom = () => scroller.scrollHeight - scroller.scrollTop - scroller.clientHeight < 80;
  function toBottom(force) { if (force || nearBottom()) scroller.scrollTop = scroller.scrollHeight; }
  function timeOf(iso) { try { return new Date(iso).toLocaleTimeString("ru-RU", {hour: "2-digit", minute: "2-digit"}); } catch { return ""; } }
  function removeEmpty() { const e = log.querySelector(".chat-empty"); if (e) e.remove(); }

  function addMessage(m, force) {
    removeEmpty();
    const stick = force || nearBottom();
    const row = el("div", `row ${m.role}`);
    if (m.role === "user") {
      row.append(el("div", "bubble", m.content));
    } else {
      const ava = Koh.faceImg("ava-mini");
      const body = el("div", "body"), content = el("div"), meta = el("div", "meta");
      content.append(renderMarkdown(m.content));
      const copy = el("button", "", "Копировать"); copy.type = "button"; copy.addEventListener("click", () => copyText(m.content, copy));
      meta.append(el("span", "", timeOf(m.created_at)), copy);
      body.append(content, meta); row.append(ava, body);
    }
    log.append(row); if (stick) toBottom(true);
  }
  function addError(message) {
    removeEmpty();
    const row = el("div", "row error"), ava = Koh.faceImg("ava-mini"), body = el("div", "body");
    body.append(el("div", "", message));
    const btn = el("button", "", "Открыть настройки ИИ"); btn.type = "button";
    btn.addEventListener("click", () => { Koh.open("cabinet"); if (Koh.hooks.cabinetTab) Koh.hooks.cabinetTab("ai"); });
    body.append(btn); row.append(ava, body); log.append(row); toBottom(true);
  }
  function setTyping(on) {
    if (on && !typingRow) {
      typingRow = el("div", "row assistant"); const ava = Koh.faceImg("ava-mini");
      const body = el("div", "body"), t = el("div", "typing"); t.append(el("i"), el("i"), el("i")); body.append(t);
      typingRow.append(ava, body); log.append(typingRow); toBottom(true);
    } else if (!on && typingRow) { typingRow.remove(); typingRow = null; }
  }
  function renderEmpty() {
    const box = el("div", "chat-empty"), im = Koh.faceImg("", "big");
    const grid = el("div", "suggest");
    SUGGESTIONS.forEach(s => { const b = el("button", "", s); b.type = "button"; b.addEventListener("click", () => { input.value = s; autosize(); submit(); }); grid.append(b); });
    box.append(im, el("h2", "", "Чем могу помочь, господин?"), el("p", "", "Спросите о чём угодно или выберите подсказку."), grid);
    log.replaceChildren(box);
  }

  // ---------- data flow ----------
  async function load() {
    try {
      const d = await api("/api/chat?limit=200");
      loaded = true; log.replaceChildren();
      if (!d.messages.length) renderEmpty(); else { d.messages.forEach(m => addMessage(m, true)); toBottom(true); }
    } catch { log.replaceChildren(); addError("Не удалось загрузить историю чата."); }
  }
  async function submit() {
    const text = input.value.trim();
    if (!text || sending) return;
    sending = true; input.value = ""; autosize(); updateSend();
    addMessage({role: "user", content: text, created_at: new Date().toISOString()}, true);
    setTyping(true);
    try {
      const d = await api("/api/chat", {method: "POST", body: JSON.stringify({text})});
      setTyping(false);
      d.messages.filter(m => m.role === "assistant").forEach(m => addMessage(m, true));
      if (d.error) addError(d.error);
    } catch { setTyping(false); addError("Не удалось отправить сообщение. Проверьте, что Kohakuyasha запущена."); }
    finally { sending = false; updateSend(); input.focus(); }
  }
  async function newChat() {
    if (!confirm("Начать новый чат? Текущая история будет удалена.")) return;
    try { await api("/api/chat", {method: "DELETE"}); renderEmpty(); } catch { addError("Не удалось очистить чат."); }
  }

  // ---------- composer ----------
  function autosize() { input.style.height = "auto"; input.style.height = Math.min(input.scrollHeight, 200) + "px"; }
  function updateSend() { sendBtn.disabled = sending || !input.value.trim(); }
  input.addEventListener("input", () => { autosize(); updateSend(); });
  input.addEventListener("keydown", (e) => { if (e.key === "Enter" && !e.shiftKey && !e.isComposing) { e.preventDefault(); submit(); } });
  form.addEventListener("submit", (e) => { e.preventDefault(); submit(); });
  scroller.addEventListener("scroll", () => { downBtn.hidden = nearBottom(); });
  downBtn.addEventListener("click", () => toBottom(true));
  panel.querySelector('[data-act="new"]').addEventListener("click", newChat);

  function renderStatus() {
    const ai = Koh.settings.ai || {}, on = ai.provider && ai.provider !== "none";
    statusEl.replaceChildren(el("i", on ? "dot on" : "dot"), document.createTextNode(on ? `онлайн · ${ai.model || (ai.defaults && ai.defaults.models[ai.provider]) || ai.provider}` : "ИИ не подключён"));
  }
  Koh.onSettings(renderStatus);
  Koh.hooks.chatReset = () => { if (loaded) renderEmpty(); };
  Koh.hooks.chat = () => { renderStatus(); setTimeout(() => input.focus(), 0); if (!loaded) load(); else toBottom(true); };
  renderStatus();
})();
