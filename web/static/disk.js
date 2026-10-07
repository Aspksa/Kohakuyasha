(() => {
  "use strict";
  const Koh = window.Koh, el = Koh.el;
  const root = document.getElementById("disk-root");
  if (!root) return;
  const ICONS = {folder: "📁", image: "🖼️", text: "📄", audio: "🎵", video: "🎬", pdf: "📕", archive: "🗜️", doc: "📘", file: "📎"};
  const PREFS = "kohakuyasha.disk.view";
  let path = "", view = "grid", mode = "files", data = null, info = null, trash = null, query = "", loadId = 0;
  try { view = localStorage.getItem(PREFS) === "list" ? "list" : "grid"; } catch {}

  const btn = (text, cls, fn, title) => { const b = el("button", cls || "", text); b.type = "button"; if (title) { b.title = title; b.setAttribute("aria-label", title); } b.addEventListener("click", fn); return b; };
  const fmtSize = (n) => { n = Number(n) || 0; const u = ["Б", "КБ", "МБ", "ГБ", "ТБ"]; let i = 0; while (n >= 1024 && i < u.length - 1) { n /= 1024; i++; } return `${n >= 10 || i === 0 ? Math.round(n) : n.toFixed(1)} ${u[i]}`; };
  const fmtDate = (iso) => { try { return new Date(iso).toLocaleString("ru-RU", {day: "numeric", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit"}); } catch { return ""; } };
  const join = (a, b) => (a ? a + "/" : "") + b;
  const fileUrl = (p, dl) => `/api/disk/file?path=${encodeURIComponent(p)}${dl ? "&download=1" : ""}`;
  const fail = (e) => Koh.toast((e && e.message) || "Не удалось выполнить действие");

  // ---------- skeleton ----------
  const head = el("div", "disk-bar"), crumbs = el("div", "disk-crumbs"), tools = el("div", "disk-tools");
  const search = el("input", "disk-search"); search.type = "search"; search.placeholder = "Поиск по диску…"; search.maxLength = 80; search.setAttribute("aria-label", "Поиск");
  const picker = el("input"); picker.type = "file"; picker.multiple = true; picker.hidden = true;
  const list = el("div", "disk-list"), foot = el("div", "disk-foot"), uploads = el("div", "disk-uploads");
  const drop = el("div", "disk-drop", "Отпустите файлы, чтобы загрузить сюда");
  tools.append(search, btn("⭱ Загрузить", "primary", () => picker.click()), btn("＋ Папка", "", newFolder), btn("☰", "", toggleView, "Вид: сетка / список"), btn("🗑 Корзина", "", () => { mode = mode === "trash" ? "files" : "trash"; refresh(); }));
  head.append(crumbs, tools);
  const panel = el("section", "panel disk"); panel.append(head, list, uploads, foot, drop, picker);
  root.append(panel);

  // ---------- data ----------
  async function refresh() {
    const my = ++loadId;
    try {
      if (mode === "trash") trash = await Koh.api("/api/disk/trash");
      else if (query) data = {path: "", crumbs: [], items: (await Koh.api("/api/disk/search?q=" + encodeURIComponent(query))).items, search: true};
      else data = await Koh.api("/api/disk/list?path=" + encodeURIComponent(path));
      info = await Koh.api("/api/disk");
    } catch (e) { if (my === loadId) { list.replaceChildren(el("p", "hint", (e && e.message) || "Диск недоступен.")); } return; }
    if (my === loadId) draw();
  }
  function go(p) { path = p; query = ""; search.value = ""; mode = "files"; refresh(); }

  // ---------- drawing ----------
  function drawCrumbs() {
    const nodes = [];
    const part = (name, p, last) => { const b = btn(name, "crumb" + (last ? " last" : ""), () => go(p)); return b; };
    if (mode === "trash") { nodes.push(part("Диск", "", false), el("span", "sep", "›"), el("b", "", "Корзина")); }
    else if (query) nodes.push(part("Диск", "", false), el("span", "sep", "›"), el("b", "", `Поиск: ${query}`));
    else {
      const cs = data ? data.crumbs : [];
      nodes.push(part("Диск Kohakuyasha", "", !cs.length));
      cs.forEach((c, i) => { nodes.push(el("span", "sep", "›"), part(c.name, c.path, i === cs.length - 1)); });
    }
    crumbs.replaceChildren(...nodes);
  }
  function itemActions(it) {
    const box = el("div", "disk-acts");
    box.append(btn("✎", "", (e) => { e.stopPropagation(); rename(it); }, "Переименовать"), btn("⇄", "", (e) => { e.stopPropagation(); moveTo(it); }, "Переместить"));
    if (!it.dir) box.append(btn("⭳", "", (e) => { e.stopPropagation(); location.href = fileUrl(it.path, true); }, "Скачать"));
    box.append(btn("🗑", "danger-btn", (e) => { e.stopPropagation(); remove(it); }, "В корзину"));
    return box;
  }
  function drawFiles() {
    const items = data.items;
    list.className = `disk-list ${view}`;
    if (!items.length) { list.replaceChildren(emptyBox(data.search ? "Ничего не найдено." : "Здесь пока пусто. Перетащите файлы сюда или нажмите «Загрузить».")); return; }
    list.replaceChildren(...items.map(it => {
      const row = el("div", "disk-item" + (it.dir ? " dir" : "")); row.tabIndex = 0;
      const ico = el("div", "ico");
      if (it.kind === "image" && it.inline) { const im = el("img"); im.loading = "lazy"; im.alt = ""; im.src = fileUrl(it.path); ico.append(im); }
      else ico.textContent = ICONS[it.kind] || ICONS.file;
      const meta = el("div", "dmeta"), name = el("b", "", it.name); name.title = it.name;
      meta.append(name, el("small", "", it.dir ? (data.search ? `Папка · ${it.path}` : "Папка") : `${fmtSize(it.size)} · ${fmtDate(it.modified)}${data.search ? " · " + it.path : ""}`));
      row.append(ico, meta, itemActions(it));
      const open = () => it.dir ? go(it.path) : preview(it);
      row.addEventListener("click", open);
      row.addEventListener("keydown", (e) => { if (e.key === "Enter") open(); else if (e.key === "Delete") remove(it); else if (e.key === "F2") rename(it); });
      return row;
    }));
  }
  function emptyBox(text) { const b = el("div", "disk-empty"); b.append(el("div", "big", "☁"), el("p", "", text)); return b; }
  function drawTrash() {
    list.className = "disk-list list";
    const items = trash.items;
    const bar = [];
    if (items.length) { const top = el("div", "disk-trashbar"); top.append(el("span", "hint", `Файлы хранятся ${trash.days} дн., потом удаляются навсегда.`), btn("Очистить корзину", "danger-btn", emptyTrash)); bar.push(top); }
    if (!items.length) { list.replaceChildren(emptyBox("Корзина пуста.")); return; }
    list.replaceChildren(...bar, ...items.map(it => {
      const row = el("div", "disk-item"), ico = el("div", "ico", it.dir ? ICONS.folder : ICONS.file), meta = el("div", "dmeta");
      meta.append(el("b", "", it.name), el("small", "", `Из «/${it.path}» · удалено ${fmtDate(it.deleted_at)}${it.dir ? "" : " · " + fmtSize(it.size)}`));
      const acts = el("div", "disk-acts");
      acts.append(btn("Восстановить", "", async () => { try { await Koh.api("/api/disk/restore", {method: "POST", body: JSON.stringify({id: it.id})}); Koh.toast("Восстановлено"); refresh(); } catch (e) { fail(e); } }),
        btn("Удалить навсегда", "danger-btn", async () => { if (!confirm(`Удалить «${it.name}» навсегда?`)) return; try { await Koh.api("/api/disk/trash/" + it.id, {method: "DELETE"}); refresh(); } catch (e) { fail(e); } }));
      row.append(ico, meta, acts); return row;
    }));
  }
  function drawFoot() {
    const u = info.usage;
    foot.replaceChildren(el("span", "", `Занято: ${fmtSize(u.bytes)} · файлов: ${u.files} · в корзине: ${fmtSize(u.trash_bytes)} · свободно на диске: ${fmtSize(u.free)}`),
      btn("Настройки", "link-btn", settings));
  }
  function draw() { drawCrumbs(); if (mode === "trash") drawTrash(); else drawFiles(); drawFoot(); }

  // ---------- actions ----------
  function toggleView() { view = view === "grid" ? "list" : "grid"; try { localStorage.setItem(PREFS, view); } catch {} draw(); }
  async function newFolder() {
    if (mode === "trash" || query) return;
    const name = prompt("Название папки"); if (!name) return;
    try { await Koh.api("/api/disk/folder", {method: "POST", body: JSON.stringify({path: join(path, name.trim())})}); refresh(); } catch (e) { fail(e); }
  }
  async function rename(it) {
    const name = prompt("Новое имя", it.name); if (!name || name === it.name) return;
    const parent = it.path.split("/").slice(0, -1).join("/");
    try { await Koh.api("/api/disk/move", {method: "POST", body: JSON.stringify({from: it.path, to: join(parent, name.trim())})}); refresh(); } catch (e) { fail(e); }
  }
  async function moveTo(it) {
    const dest = prompt("Переместить в папку (путь от корня диска; пусто — корень)", it.path.split("/").slice(0, -1).join("/")); if (dest === null) return;
    try { await Koh.api("/api/disk/move", {method: "POST", body: JSON.stringify({from: it.path, to: join(dest.trim().replace(/^\/+|\/+$/g, ""), it.name)})}); Koh.toast("Перемещено"); refresh(); } catch (e) { fail(e); }
  }
  async function remove(it) {
    try { await Koh.api("/api/disk/delete", {method: "POST", body: JSON.stringify({path: it.path})}); Koh.toast(`«${it.name}» в корзине`); refresh(); } catch (e) { fail(e); }
  }
  async function emptyTrash() {
    if (!confirm("Удалить всё из корзины навсегда?")) return;
    try { await Koh.api("/api/disk/trash", {method: "DELETE"}); refresh(); } catch (e) { fail(e); }
  }
  function settings() {
    const mb = prompt("Максимальный размер одного файла, МБ (1–8192)", String(info.settings.max_file_mb)); if (mb === null) return;
    const days = prompt("Сколько дней хранить удалённое в корзине (1–365)", String(info.settings.trash_days)); if (days === null) return;
    Koh.api("/api/disk/settings", {method: "PUT", body: JSON.stringify({max_file_mb: parseInt(mb, 10), trash_days: parseInt(days, 10)})}).then(() => { Koh.toast("Сохранено"); refresh(); }, fail);
  }

  // ---------- preview ----------
  function preview(it) {
    if (it.kind === "pdf") { window.open(fileUrl(it.path), "_blank", "noopener"); return; }
    if (!it.inline) { location.href = fileUrl(it.path, true); return; }
    const overlay = el("div", "disk-modal"), card = el("div", "disk-modal-card"), top = el("div", "disk-modal-head"), body = el("div", "disk-modal-body");
    const close = () => { overlay.remove(); document.removeEventListener("keydown", onKey, true); };
    const onKey = (e) => { if (e.key === "Escape") { e.stopPropagation(); close(); } };
    top.append(el("b", "", it.name), el("span", "grow"), btn("⭳ Скачать", "", () => { location.href = fileUrl(it.path, true); }), btn("×", "", close, "Закрыть"));
    if (it.kind === "image") { const im = el("img"); im.alt = it.name; im.src = fileUrl(it.path); body.append(im); }
    else if (it.kind === "audio") { const a = el("audio"); a.controls = true; a.src = fileUrl(it.path); body.append(a); }
    else if (it.kind === "video") { const v = el("video"); v.controls = true; v.src = fileUrl(it.path); body.append(v); }
    else {
      const pre = el("pre", "", "Загрузка…"); body.append(pre);
      fetch(fileUrl(it.path), {credentials: "same-origin"}).then(r => r.text()).then(t => { pre.textContent = t.length > 200000 ? t.slice(0, 200000) + "\n… (показано 200 000 знаков, остальное — в скачанном файле)" : t; }, () => { pre.textContent = "Не удалось открыть файл."; });
    }
    card.append(top, body); overlay.append(card);
    overlay.addEventListener("click", (e) => { if (e.target === overlay) close(); });
    document.addEventListener("keydown", onKey, true);
    document.body.append(overlay);
  }

  // ---------- upload (raw PUT with progress; files are streamed to disk by the server) ----------
  const queue = [];
  let running = false;
  function uploadOne(file, folder) {
    return new Promise((resolve) => {
      const row = el("div", "up-row"), name = el("span", "up-name", file.name), bar = el("div", "up-bar"), fill = el("i"), state = el("small", "", "в очереди");
      bar.append(fill); row.append(name, bar, state); uploads.append(row);
      const xhr = new XMLHttpRequest();
      xhr.open("PUT", `/api/disk/upload?path=${encodeURIComponent(folder)}&name=${encodeURIComponent(file.name)}`);
      xhr.setRequestHeader("X-Kohakuyasha-Request", "1");
      xhr.upload.onprogress = (e) => { if (e.lengthComputable) { const pc = Math.round(e.loaded / e.total * 100); fill.style.width = pc + "%"; state.textContent = pc + "%"; } };
      const done = (ok, msg) => { row.classList.add(ok ? "ok" : "bad"); fill.style.width = "100%"; state.textContent = ok ? "готово" : msg; setTimeout(() => row.remove(), ok ? 2500 : 9000); resolve(ok); };
      xhr.onload = () => { let m = ""; try { m = JSON.parse(xhr.responseText).detail || ""; } catch {} done(xhr.status === 200, m || `Ошибка ${xhr.status}`); };
      xhr.onerror = () => done(false, "нет связи");
      xhr.send(file);
    });
  }
  async function pump() {
    if (running) return; running = true;
    let any = false;
    while (queue.length) { const [file, folder] = queue.shift(); any = (await uploadOne(file, folder)) || any; }
    running = false;
    if (any) refresh();
  }
  // Public: other modules (e.g. chat attachments) can store files on the disk.
  Koh.disk = {upload: (files, folder) => { [...files].forEach(f => queue.push([f, folder || ""])); pump(); }};
  picker.addEventListener("change", () => { if (mode === "files" && !query) Koh.disk.upload(picker.files, path); else Koh.toast("Откройте папку, чтобы загрузить файлы"); picker.value = ""; });
  let dragDepth = 0;
  const hasFiles = (e) => e.dataTransfer && [...e.dataTransfer.types].includes("Files");
  const active = () => document.getElementById("page-disk").classList.contains("active");
  document.addEventListener("dragenter", (e) => { if (active() && hasFiles(e)) { dragDepth++; drop.classList.add("show"); } });
  document.addEventListener("dragleave", (e) => { if (active() && hasFiles(e) && --dragDepth <= 0) { dragDepth = 0; drop.classList.remove("show"); } });
  document.addEventListener("dragover", (e) => { if (active() && hasFiles(e)) e.preventDefault(); });
  document.addEventListener("drop", (e) => {
    if (!active() || !hasFiles(e)) return;
    e.preventDefault(); dragDepth = 0; drop.classList.remove("show");
    if (mode === "files" && !query) Koh.disk.upload(e.dataTransfer.files, path); else Koh.toast("Откройте папку, чтобы загрузить файлы");
  });
  search.addEventListener("input", Koh.debounce(() => { query = search.value.trim(); mode = "files"; refresh(); }, 300));
  Koh.refreshDisk = refresh;
})();
