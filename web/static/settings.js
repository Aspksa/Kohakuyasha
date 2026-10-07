(() => {
  "use strict";
  const Koh = window.Koh, el = Koh.el;
  const root = document.getElementById("settings-root");
  if (!root) return;

  const card = (title, desc) => { const c = el("section", "panel set-card"); c.append(el("h3", "", title)); if (desc) c.append(el("p", "", desc)); return c; };
  function seg(options, value, onPick) {
    const wrap = el("div", "seg");
    options.forEach(([val, label]) => {
      const b = el("button", val === value ? "on" : "", label); b.type = "button";
      b.addEventListener("click", () => { wrap.querySelectorAll("button").forEach(x => x.classList.remove("on")); b.classList.add("on"); onPick(val); });
      wrap.append(b);
    });
    return wrap;
  }
  function row(label, hint, control) {
    const r = el("div", "srow"), t = el("div"); t.append(document.createTextNode(label)); if (hint) t.append(el("small", "", hint));
    r.append(t, control); return r;
  }
  function sw(checked, onChange) {
    const l = el("label", "switch"), i = el("input"); i.type = "checkbox"; i.checked = !!checked;
    i.addEventListener("change", () => onChange(i.checked)); l.append(i, el("span")); return l;
  }
  function field(label, control) { const f = el("div", "sfield"); if (label) f.append(el("label", "", label)); f.append(control); return f; }
  const btn = (text, cls, fn) => { const b = el("button", cls || "", text); b.type = "button"; b.addEventListener("click", fn); return b; };

  const saveApp = Koh.debounce(async () => {
    try { Koh.setAll(await Koh.api("/api/settings/app", {method: "PUT", body: JSON.stringify(Koh.settings.app)})); } catch { Koh.toast("Не удалось сохранить настройки"); }
  }, 350);
  const change = (patch) => { Object.assign(Koh.settings.app, patch); if (window.KohTheme) window.KohTheme.apply(Koh.settings.app); Koh.notify(); saveApp(); };

  function build() {
    const a = Koh.settings.app, nodes = [];

    // ----- appearance -----
    const look = card("Внешний вид", "Тема, цвет акцента, фон и масштаб применяются сразу.");
    look.append(field("Тема", seg([["dark", "Тёмная"], ["black", "Чёрная"], ["light", "Белая"], ["auto", "Как в системе"]], a.theme, v => change({theme: v}))));
    const sw1 = el("div", "swatches");
    [["gold", "#e8be56", "Золото"], ["rose", "#ec78a0", "Роза"], ["violet", "#a082f0", "Фиолет"], ["blue", "#5aa0f0", "Синий"], ["green", "#5ac896", "Зелёный"], ["red", "#f06e64", "Красный"]].forEach(([id, color, name]) => {
      const b = el("button", "swatch" + (a.accent === id ? " on" : "")); b.type = "button"; b.title = name; b.setAttribute("aria-label", name); b.style.background = color;
      b.addEventListener("click", () => { sw1.querySelectorAll(".swatch").forEach(x => x.classList.remove("on")); b.classList.add("on"); change({accent: id}); });
      sw1.append(b);
    });
    look.append(field("Цвет акцента", sw1));
    const bgBox = el("div"), dim = el("input"); dim.type = "range"; dim.min = 0; dim.max = 85; dim.value = a.bg_dim;
    const dimLabel = el("label", "", `Затемнение фона: ${a.bg_dim}%`);
    dim.addEventListener("input", () => { dimLabel.textContent = `Затемнение фона: ${dim.value}%`; change({bg_dim: Number(dim.value)}); });
    const file = el("input"); file.type = "file"; file.accept = "image/png,image/jpeg,image/webp,image/gif"; file.hidden = true;
    file.addEventListener("change", async () => {
      const f = file.files[0]; file.value = ""; if (!f) return;
      if (f.size > 6_000_000) { Koh.toast("Файл больше 6 МБ"); return; }
      try { Koh.setAll(await Koh.api("/api/background", {method: "POST", body: JSON.stringify({data: await Koh.fileToBase64(f)})})); Koh.toast("Фон загружен"); rebuild(); }
      catch (e) { Koh.toast(e.message || "Не удалось загрузить фон"); }
    });
    const bgBtns = el("div", "btns");
    bgBtns.append(btn("Загрузить изображение…", "", () => file.click()));
    if (a.bg_image) bgBtns.append(btn("Убрать изображение", "danger-btn", async () => { try { Koh.setAll(await Koh.api("/api/background", {method: "DELETE"})); rebuild(); } catch { Koh.toast("Не удалось убрать фон"); } }));
    bgBox.append(seg([["glow", "Свечение"], ["plain", "Однотонный"], ["image", "Своё изображение"]], a.background, v => {
      if (v === "image" && !Koh.settings.app.bg_image) { Koh.toast("Сначала загрузите изображение"); file.click(); return; }
      change({background: v});
    }), bgBtns, file);
    if (a.bg_image) { bgBox.append(dimLabel, dim); dimLabel.style.display = "block"; }
    look.append(field("Фон", bgBox));
    const zoom = el("input"); zoom.type = "range"; zoom.min = 85; zoom.max = 130; zoom.step = 5; zoom.value = a.ui_zoom;
    const zl = el("label", "", `Масштаб содержимого: ${a.ui_zoom}%`);
    zoom.addEventListener("input", () => { zl.textContent = `Масштаб содержимого: ${zoom.value}%`; change({ui_zoom: Number(zoom.value)}); });
    const zf = el("div", "sfield"); zf.append(zl, zoom); look.append(zf);
    look.append(row("Узор «волны»", "Едва заметный японский узор на фоне", sw(a.pattern, v => change({pattern: v}))));
    look.append(row("Лепестки сакуры", "Медленно падающие лепестки на фоне", sw(a.petals, v => change({petals: v}))));
    look.append(row("Анимации", "Отключите, если интерфейс кажется тяжёлым", sw(a.animations, v => change({animations: v}))));
    nodes.push(look);

    // ----- notifications -----
    const notes = card("Уведомления", "Новости (например, вышло обновление) приходят на аватар; нажмите на него — откроется чат с подробностями и кнопками.");
    notes.append(row("Значок и подсказка на аватаре", "Счётчик на аватаре и всплывающая подсказка", sw(a.notifications !== false, v => change({notifications: v}))));
    notes.append(row("Уведомления Windows", "Всплывающее сообщение из значка в трее; работает, когда запущен launcher", sw(a.toast !== false, v => change({toast: v}))));
    nodes.push(notes);

    // ----- startup -----
    const start = card("Запуск", "Поведение при включении компьютера и при запуске Kohakuyasha.");
    const auto = sw(false, () => {}), autoInput = auto.querySelector("input");
    autoInput.addEventListener("change", async () => {
      autoInput.disabled = true;
      try { const d = await Koh.api("/api/autostart", {method: "POST", body: JSON.stringify({enabled: autoInput.checked})}); autoInput.checked = d.enabled; Koh.toast(d.enabled ? "Автозапуск включён" : "Автозапуск отключён"); }
      catch { autoInput.checked = !autoInput.checked; Koh.toast("Не удалось изменить автозапуск"); }
      finally { autoInput.disabled = false; }
    });
    Koh.onStatus = (d) => { if (!autoInput.disabled) autoInput.checked = !!(d.settings && d.settings.autostart); };
    if (Koh.status) Koh.onStatus(Koh.status);
    start.append(row("Автозапуск Windows", "Находит этот экземпляр даже после смены буквы переносного диска", auto));
    start.append(row("Открывать браузер при старте", "Вступает в силу при следующем запуске", sw(a.open_browser !== false, v => change({open_browser: v}))));
    nodes.push(start);

    // ----- data -----
    const data = card("Данные", "Резервные копии и очистка. Всё хранится локально в папке data.");
    const dbtns = el("div", "btns");
    dbtns.append(
      btn("Экспорт чата (JSON)", "", () => { location.href = "/api/chat/export"; }),
      btn("Экспорт диагностики", "", () => { location.href = "/api/diagnostics/export"; }),
      btn("Открыть память ИИ", "", () => { Koh.open("cabinet"); Koh.hooks.cabinetTab("memory"); }),
      btn("Очистить историю чата", "danger-btn", async () => {
        if (!confirm("Удалить всю историю чата? Это действие нельзя отменить.")) return;
        try { await Koh.api("/api/chat", {method: "DELETE"}); Koh.toast("История чата очищена"); if (Koh.hooks.chatReset) Koh.hooks.chatReset(); } catch { Koh.toast("Не удалось очистить чат"); }
      }),
    );
    data.append(dbtns); nodes.push(data);

    // ----- system -----
    const sys = card("Система", "Локальная безопасность включена: веб-интерфейс слушает только 127.0.0.1, API защищён сессией, Host и Origin.");
    const sbtns = el("div", "btns");
    sbtns.append(
      btn("Перезапустить ядро", "", async () => { try { await Koh.api("/api/system/restart", {method: "POST", body: "{}"}); Koh.toast("Перезапуск запрошен"); } catch { Koh.toast("Ошибка перезапуска"); } }),
      btn("Выход", "danger-btn", async () => { if (confirm("Полностью завершить Kohakuyasha?")) { try { await Koh.api("/api/system/shutdown", {method: "POST", body: "{}"}); Koh.toast("Завершение работы…"); } catch {} } }),
    );
    sys.append(sbtns); nodes.push(sys);
    root.replaceChildren(...nodes);
  }
  function rebuild() { build(); }
  let rebuiltAfterLoad = false;
  Koh.onSettings(() => {
    // Rebuild once when the real server settings arrive; later changes come from this page itself.
    if (Koh.loadedOnce && !rebuiltAfterLoad) { rebuiltAfterLoad = true; build(); }
  });
  build();
  Koh.rebuildSettings = rebuild;
})();
