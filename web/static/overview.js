(() => {
  "use strict";
  const Koh = window.Koh;
  const $ = (q) => document.querySelector(q);
  const el = Koh.el;
  const cap = (s) => s.charAt(0).toUpperCase() + s.slice(1);
  const pad = (n) => String(n).padStart(2, "0");
  const ymd = (d) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
  const fromYmd = (s) => { const [y, m, d] = s.split("-").map(Number); return new Date(y, m - 1, d); };
  const cfg = () => Koh.settings.app || {};

  // ---------------- clock ----------------
  const timeFmt = {};
  function formatTime(now) {
    const c = cfg(), key = `${c.clock_24h}|${c.clock_seconds}`;
    if (!timeFmt[key]) timeFmt[key] = new Intl.DateTimeFormat("ru-RU", {hour: "2-digit", minute: "2-digit", second: c.clock_seconds ? "2-digit" : undefined, hour12: c.clock_24h === false});
    return timeFmt[key].formatToParts(now);
  }
  const dateFmt = new Intl.DateTimeFormat("ru-RU", {weekday: "long", day: "numeric", month: "long", year: "numeric"});
  const monthFmt = new Intl.DateTimeFormat("ru-RU", {month: "long", year: "numeric"});
  const dayFmt = new Intl.DateTimeFormat("ru-RU", {day: "numeric", month: "long", weekday: "long"});
  const stripYear = (s) => s.replace(/\s*г\.?$/, "");

  function isoWeek(d) {
    const t = new Date(Date.UTC(d.getFullYear(), d.getMonth(), d.getDate())), day = t.getUTCDay() || 7;
    t.setUTCDate(t.getUTCDate() + 4 - day);
    return Math.ceil(((t - new Date(Date.UTC(t.getUTCFullYear(), 0, 1))) / 86400000 + 1) / 7);
  }
  function tzLabel(now) {
    const off = -now.getTimezoneOffset(), sign = off >= 0 ? "+" : "−", a = Math.abs(off);
    let name = ""; try { name = Intl.DateTimeFormat().resolvedOptions().timeZone || ""; } catch {}
    return `UTC${sign}${Math.floor(a / 60)}${a % 60 ? ":" + pad(a % 60) : ""}${name ? " · " + name : ""}`;
  }
  let lastClockKey = "", lastToday = ymd(new Date());
  function tick() {
    const now = new Date();
    const parts = formatTime(now);
    const main = parts.filter(p => p.type === "hour" || p.type === "minute" || (p.type === "literal" && parts.indexOf(p) < 3)).map(p => p.value).join("").trim();
    const sec = parts.find(p => p.type === "second"), ampm = parts.find(p => p.type === "dayPeriod");
    const key = `${main}|${sec ? sec.value : ""}|${ampm ? ampm.value : ""}`;
    if (key !== lastClockKey) {
      lastClockKey = key;
      const box = $("#clock-time"); box.replaceChildren(document.createTextNode(main));
      if (sec || ampm) box.append(el("small", "", [sec ? ":" + sec.value : "", ampm ? " " + ampm.value : ""].join("")));
    }
    $("#clock-date").textContent = cap(stripYear(dateFmt.format(now)));
    $("#clock-greet").textContent = Koh.greeting();
    $("#clock-tz").textContent = tzLabel(now);
    $("#clock-week").textContent = `Неделя ${isoWeek(now)}`;
    $("#clock-doy").textContent = `День ${Math.floor((now - new Date(now.getFullYear(), 0, 0)) / 86400000)}`;
    const start = new Date(now.getFullYear(), now.getMonth(), now.getDate()), pct = Math.min(100, Math.max(0, (now - start) / 864000));
    $("#daybar").style.width = pct.toFixed(1) + "%"; $("#daybar-pct").textContent = Math.floor(pct) + "%";
    const today = ymd(now);
    if (today !== lastToday) { lastToday = today; renderCalendar(); }
  }

  // ---------------- calendar ----------------
  const today0 = new Date();
  const state = {year: today0.getFullYear(), month: today0.getMonth(), selected: ymd(today0), notes: {}};
  const weekStart = () => (cfg().week_start === 0 ? 0 : 1);
  const DOW = ["Вс", "Пн", "Вт", "Ср", "Чт", "Пт", "Сб"];

  function gridRange() {
    const first = new Date(state.year, state.month, 1), shift = (first.getDay() - weekStart() + 7) % 7;
    const start = new Date(state.year, state.month, 1 - shift), end = new Date(start.getFullYear(), start.getMonth(), start.getDate() + 41);
    return {start, end};
  }
  async function loadNotes() {
    const {start, end} = gridRange();
    try {
      const d = await Koh.api(`/api/calendar?start=${ymd(start)}&end=${ymd(end)}`);
      state.notes = {}; (d.notes || []).forEach(n => { (state.notes[n.day] = state.notes[n.day] || []).push(n); });
    } catch { state.notes = {}; }
    renderCalendar(); renderNotes();
  }
  function renderCalendar() {
    const grid = $("#cal-grid"), {start} = gridRange(), todayStr = ymd(new Date()), nodes = [];
    $("#cal-title").textContent = cap(stripYear(monthFmt.format(new Date(state.year, state.month, 1))));
    for (let i = 0; i < 7; i++) { const dow = (weekStart() + i) % 7; nodes.push(el("div", "cal-dow" + (dow === 0 || dow === 6 ? " we" : ""), DOW[dow])); }
    for (let i = 0; i < 42; i++) {
      const d = new Date(start.getFullYear(), start.getMonth(), start.getDate() + i), s = ymd(d), dow = d.getDay();
      const cls = ["cal-day", d.getMonth() !== state.month ? "out" : "", dow === 0 || dow === 6 ? "we" : "", s === todayStr ? "today" : "", s === state.selected ? "sel" : ""].filter(Boolean).join(" ");
      const b = el("button", cls, String(d.getDate())); b.type = "button"; b.setAttribute("aria-label", cap(dateFmt.format(d)));
      if (state.notes[s]) b.append(el("i"));
      b.addEventListener("click", () => {
        state.selected = s;
        if (d.getMonth() !== state.month || d.getFullYear() !== state.year) { state.year = d.getFullYear(); state.month = d.getMonth(); loadNotes(); } else { renderCalendar(); renderNotes(); }
      });
      nodes.push(b);
    }
    grid.replaceChildren(...nodes);
  }
  function renderNotes() {
    $("#notes-title").textContent = cap(dayFmt.format(fromYmd(state.selected)));
    const list = $("#notes-list"), notes = state.notes[state.selected] || [];
    if (!notes.length) { list.replaceChildren(el("div", "notes-empty", "На этот день заметок нет.")); return; }
    list.replaceChildren(...notes.map(n => {
      const row = el("div", "note"), del = el("button", "", "×"); del.type = "button"; del.title = "Удалить"; del.setAttribute("aria-label", "Удалить заметку");
      del.addEventListener("click", async () => { try { await Koh.api(`/api/calendar/${n.id}`, {method: "DELETE"}); await loadNotes(); } catch { Koh.toast("Не удалось удалить заметку"); } });
      row.append(el("span", "", n.text), del); return row;
    }));
  }
  function shiftMonth(delta) {
    const d = new Date(state.year, state.month + delta, 1);
    state.year = d.getFullYear(); state.month = d.getMonth(); loadNotes();
  }
  $("#cal-prev").addEventListener("click", () => shiftMonth(-1));
  $("#cal-next").addEventListener("click", () => shiftMonth(1));
  $("#cal-today").addEventListener("click", () => { const n = new Date(); state.year = n.getFullYear(); state.month = n.getMonth(); state.selected = ymd(n); loadNotes(); });
  $("#note-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const input = $("#note-input"), text = input.value.trim();
    if (!text) return;
    try { await Koh.api("/api/calendar", {method: "POST", body: JSON.stringify({day: state.selected, text})}); input.value = ""; await loadNotes(); }
    catch (err) { Koh.toast(err.message || "Не удалось добавить заметку"); }
  });

  let lastWeekStart = weekStart(), lastClockCfg = "";
  Koh.onSettings(() => {
    if (weekStart() !== lastWeekStart) { lastWeekStart = weekStart(); loadNotes(); }
    const c = `${cfg().clock_24h}|${cfg().clock_seconds}`;
    if (c !== lastClockCfg) { lastClockCfg = c; lastClockKey = ""; tick(); }
  });
  Koh.refreshOverview = loadNotes;
  tick(); setInterval(tick, 1000); renderCalendar(); renderNotes(); loadNotes();
})();
