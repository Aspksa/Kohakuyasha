(() => {
  "use strict";
  const Koh = window.Koh, el = Koh.el;
  const root = document.getElementById("update-root");
  if (!root) return;
  const dot = document.getElementById("update-dot");
  let state = null, busy = false;
  const AUTO_CHECK_MS = 6 * 3600 * 1000;

  const card = (title, desc, wide) => { const c = el("section", "panel set-card" + (wide ? " wide" : "")); c.append(el("h3", "", title)); if (desc) c.append(el("p", "", desc)); return c; };
  const row = (k, v) => { const r = el("div", "srow"), t = el("div", "", k), b = el("b", "", v); r.append(t, b); return r; };
  const btn = (text, cls, fn) => { const b = el("button", cls || "", text); b.type = "button"; b.addEventListener("click", fn); return b; };
  const toggle = (checked, onChange) => { const l = el("label", "switch"), i = el("input"); i.type = "checkbox"; i.checked = !!checked; i.addEventListener("change", () => onChange(i.checked)); l.append(i, el("span")); return l; };
  const fmtDate = (iso) => { try { return new Date(iso).toLocaleString("ru-RU", {day: "numeric", month: "long", hour: "2-digit", minute: "2-digit"}); } catch { return ""; } };
  const status = (kind, text) => { const s = el("div", `status-line ${kind}`, text); return s; };

  function publish() {
    const info = state && state.info;
    Koh.updateInfo = info || null;
    if (dot) dot.hidden = !(info && info.newer);
  }
  async function load() {
    try { state = await Koh.api("/api/update"); } catch { return; }
    publish(); draw();
    const info = state.info, stale = !info || !info.checked_at || Date.now() - new Date(info.checked_at).getTime() > AUTO_CHECK_MS;
    if (state.settings.auto_check && stale) check(true);
  }
  async function check(silent) {
    if (busy) return; busy = true; draw(silent ? null : "Проверяю GitHub…");
    try { state = await Koh.api("/api/update/check", {method: "POST", body: "{}"}); busy = false; publish(); draw(); if (!silent) Koh.toast(state.info && state.info.newer ? `Доступна версия v${state.info.remote}` : "У вас последняя версия"); }
    catch (e) { busy = false; if (state) state.info = {...(state.info || {}), error: e.message}; draw(silent ? null : e.message, true); Koh.updateInfo = {error: e.message}; }
  }
  async function install() {
    if (busy) return; if (!confirm(`Установить v${state.info.remote}? Данные, настройки и ключи сохранятся, перед заменой будет создана резервная копия.`)) return;
    busy = true; draw("Скачиваю и устанавливаю обновление…");
    try { const r = await Koh.api("/api/update/install", {method: "POST", body: "{}"}); state = r.state; busy = false; publish(); draw(`Установлена v${r.result.version}: изменено файлов ${r.result.changed}, добавлено ${r.result.added}, удалено ${r.result.removed}.`); }
    catch (e) { busy = false; draw(e.message, true); }
  }
  async function rollback() {
    const b = state.backups[0]; if (busy || !b) return;
    if (!confirm(`Вернуть файлы проекта к версии v${b.from}? Данные и настройки не затрагиваются.`)) return;
    busy = true; draw("Откатываю…");
    try { const r = await Koh.api("/api/update/rollback", {method: "POST", body: "{}"}); state = r.state; busy = false; publish(); draw(`Файлы возвращены к v${r.result.version}.`); }
    catch (e) { busy = false; draw(e.message, true); }
  }
  const sleep = (ms) => new Promise(r => setTimeout(r, ms));
  // After a relaunch the old server goes away and a new one appears: reload as soon as the new one answers.
  async function waitForRestart(oldPid) {
    const started = Date.now(); let sawDown = false;
    while (Date.now() - started < 120000) {
      await sleep(1500);
      try {
        const r = await fetch("/api/status", {credentials: "same-origin", cache: "no-store"});
        if (r.ok) {
          const d = await r.json();
          if (sawDown || (oldPid && d.runtime && d.runtime.pid !== oldPid)) { location.reload(); return; }
        } else sawDown = true;
      } catch { sawDown = true; }
      busy = true; draw(sawDown ? "Запускаю новую версию… это занимает несколько секунд." : "Останавливаю текущую версию…");
    }
    busy = false;
    draw("Kohakuyasha не запустилась автоматически. Откройте Kohakuyasha.bat вручную; если не получится, пришлите файлы logs/relaunch.log и logs/launcher-crash.log.", true);
  }
  async function restart() {
    const oldPid = Koh.status && Koh.status.runtime ? Koh.status.runtime.pid : 0;
    try {
      const r = await Koh.api("/api/update/restart", {method: "POST", body: "{}"});
      if (r.relaunched) waitForRestart(oldPid);
      else alert("Автоматический перезапуск доступен только в Windows. Закройте Kohakuyasha (Настройки → Выход) и запустите Kohakuyasha.bat снова.");
    } catch { Koh.toast("Не удалось перезапустить"); }
  }

  function draw(message, isError) {
    if (!state) return;
    const info = state.info || {}, newer = !!info.newer, nodes = [];

    // ----- version card -----
    const v = card("Версия проекта", "Проект обновляется из репозитория GitHub одним нажатием.", true);
    v.append(row("Установлено", "v" + state.installed), row("Доступно на GitHub", info.remote ? `v${info.remote}${info.sha ? " · " + info.sha : ""}` : "ещё не проверялось"),
      row("Источник", `${state.settings.repo} · ${state.settings.branch}`), row("Последняя проверка", info.checked_at ? fmtDate(info.checked_at) : "—"));
    if (state.restart_needed) v.append(status("ok", `Файлы обновлены до v${state.disk_version}. Перезапустите Kohakuyasha, чтобы начать использовать новую версию.`));
    else if (message) v.append(status(isError ? "bad" : "ok", message));
    else if (info.error) v.append(status("bad", info.error));
    else if (newer) v.append(status("ok", `Доступна новая версия: v${info.remote}.`));
    else if (info.remote) v.append(status("ok", "Установлена последняя версия."));
    const actions = el("div", "btns");
    if (state.restart_needed) actions.append(btn(state.can_relaunch ? "Перезапустить сейчас" : "Как перезапустить", "primary", restart));
    else if (newer) actions.append(btn(`Обновить до v${info.remote}`, "primary", install));
    actions.append(btn(busy ? "Подождите…" : "Проверить обновления", newer || state.restart_needed ? "" : "primary", () => check(false)));
    if (state.backups.length) actions.append(btn(`Откатить к v${state.backups[0].from}`, "danger-btn", rollback));
    actions.querySelectorAll("button").forEach(b => { b.disabled = busy; });
    v.append(actions); nodes.push(v);

    // ----- what's new -----
    const news = card("Что нового", newer ? "Изменения, которые принесёт обновление." : "Здесь появятся изменения новой версии.");
    if (newer && info.notes && info.notes.length) info.notes.forEach(n => { const r = el("div", "srow"), t = el("div"); t.append(el("b", "", "v" + n.version), el("small", "", n.summary)); r.append(t); news.append(r); });
    else news.append(el("p", "hint", newer ? "Описание изменений недоступно." : "Новых версий нет."));
    nodes.push(news);

    // ----- backups -----
    const safe = card("Данные и резервные копии", "Обновление не трогает: " + state.protected.join(", ") + ". Ключи и память остаются на месте.");
    if (state.backups.length) state.backups.forEach(b => safe.append(row(`v${b.from} → v${b.to}`, b.created.replace(/^(\d{4})(\d{2})(\d{2})-(\d{2})(\d{2}).*/, "$3.$2.$1 $4:$5"))));
    else safe.append(el("p", "hint", "Копий пока нет: они создаются автоматически перед каждым обновлением (хранятся последние 3)."));
    nodes.push(safe);

    // ----- source -----
    const src = card("Источник обновлений", "По умолчанию официальный репозиторий проекта.", true);
    const repo = el("input"), branch = el("input"), token = el("input");
    repo.type = branch.type = "text"; token.type = "password"; token.autocomplete = "off"; token.maxLength = 300;
    repo.value = state.settings.repo; branch.value = state.settings.branch; token.placeholder = state.has_token ? `Токен сохранён (${state.token_hint})` : "Токен GitHub (нужен только для приватного репозитория)";
    const f = (label, control, hint) => { const d = el("div", "sfield"); d.append(el("label", "", label), control); if (hint) d.append(el("p", "hint", hint)); return d; };
    src.append(f("Репозиторий (владелец/имя)", repo), f("Ветка", branch), f("Токен GitHub", token, "Fine-grained токен с доступом только к этому репозиторию и правом «Contents: Read-only». Хранится только в data/secrets.json и никогда не показывается обратно."));
    const sbtns = el("div", "btns");
    sbtns.append(btn("Сохранить источник", "primary", async () => {
      try { state = await Koh.api("/api/update/settings", {method: "PUT", body: JSON.stringify({repo: repo.value.trim(), branch: branch.value.trim(), auto_check: state.settings.auto_check})}); Koh.toast("Источник сохранён"); draw(); }
      catch { Koh.toast("Не удалось сохранить"); }
    }), btn("Сохранить токен", "", async () => {
      if (!token.value.trim()) return;
      try { state = await Koh.api("/api/update/token", {method: "PUT", body: JSON.stringify({token: token.value})}); Koh.toast("Токен сохранён"); draw(); } catch (e) { Koh.toast(e.message || "Не удалось сохранить токен"); }
    }));
    if (state.has_token) sbtns.append(btn("Удалить токен", "danger-btn", async () => { try { state = await Koh.api("/api/update/token", {method: "DELETE"}); draw(); } catch { Koh.toast("Не удалось удалить"); } }));
    src.append(sbtns);
    const auto = el("div", "srow"), at = el("div", "", "Проверять автоматически"); at.append(el("small", "", "При открытии страницы, не чаще раза в 6 часов; ничего не устанавливается без вашего нажатия"));
    auto.append(at, toggle(state.settings.auto_check, async (v) => { state.settings.auto_check = v; try { await Koh.api("/api/update/settings", {method: "PUT", body: JSON.stringify(state.settings)}); } catch { Koh.toast("Не удалось сохранить"); } }));
    src.append(auto); nodes.push(src);
    root.replaceChildren(...nodes);
  }
  Koh.refreshUpdate = load;
  Koh.restartProject = restart;
  Koh.installUpdate = async () => {
    const r = await Koh.api("/api/update/install", {method: "POST", body: "{}"});
    if (r.state) { state = r.state; publish(); draw(`Установлена v${r.result.version}: изменено файлов ${r.result.changed}, добавлено ${r.result.added}, удалено ${r.result.removed}.`); }
    return r;
  };
  load();
})();
