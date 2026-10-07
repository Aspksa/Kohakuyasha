(() => {
  "use strict";
  const Koh = window.Koh; if (!Koh || !Koh.registerTab) return;
  const {el, ui} = Koh;
  const dateOf = (iso) => { try { return new Date(iso).toLocaleDateString("ru-RU"); } catch { return ""; } };

  Koh.registerTab("memory", "Память", async () => {
    const data = await Koh.api("/api/memory"), m = data.settings, nodes = [], status = ui.statusLine();
    const saveSettings = Koh.debounce(async () => { try { await Koh.api("/api/settings/memory", {method: "PUT", body: JSON.stringify(m)}); Koh.settings.memory = {...m}; } catch { Koh.toast("Не удалось сохранить настройки памяти"); } }, 300);

    nodes.push(el("p", "hint", "Память — не дообучение модели. Kohakuyasha хранит диалоги и заметки локально и при каждом ответе подставляет в запрос ИИ самые подходящие фрагменты. Работает с любым провайдером и не требует видеокарты."));
    const stats = el("div", "stat-grid");
    const statBox = (label, value) => { const d = el("div"); d.append(el("b", "", String(value)), el("span", "", label)); return d; };
    const drawStats = (st) => stats.replaceChildren(statBox("диалогов импортировано", st.dialogs), statBox("фрагментов из импорта", st.imported), statBox("запомнено из чата", st.learned));
    drawStats(data.stats); nodes.push(stats);

    const sets = ui.section("НАСТРОЙКИ");
    sets.append(ui.toggle("Использовать память в ответах", m.enabled, v => { m.enabled = v; saveSettings(); }, "Работает, когда выбран ИИ-провайдер"),
      ui.toggle("Запоминать новые сообщения чата", m.learn_chat, v => { m.learn_chat = v; saveSettings(); }, "Ваши сообщения и ответы попадают в память автоматически"),
      ui.range("", 1, 12, 1, m.max_snippets, v => `Фрагментов в запросе: ${v}`, v => { m.max_snippets = v; saveSettings(); }));
    nodes.push(sets);

    // ----- import -----
    const imp = ui.section("ЗАГРУЗИТЬ ДИАЛОГИ И ЗНАНИЯ");
    imp.append(el("p", "hint", "Подходит: экспорт ChatGPT (conversations.json), экспорт Claude, JSON/JSONL со списком {role, content}, текст вида «Пользователь: … / Ассистент: …» или обычные заметки."));
    const title = el("input"); title.type = "text"; title.maxLength = 120; title.placeholder = "Название (необязательно)";
    const text = el("textarea"); text.placeholder = "Вставьте диалог или текст сюда…"; text.style.minHeight = "140px";
    const file = el("input"); file.type = "file"; file.accept = ".json,.jsonl,.txt,.md,.csv,.log,application/json,text/plain"; file.multiple = true; file.hidden = true;
    const list = el("div", "dlist");
    async function send(name, body) {
      const r = await Koh.api("/api/memory/import", {method: "POST", body: JSON.stringify({filename: name, title: title.value.trim(), text: body})});
      return r;
    }
    async function refresh() {
      const d = await Koh.api("/api/memory"); drawStats(d.stats); drawList(d.dialogs);
    }
    const importText = ui.btn("Импортировать из текста", "primary", async () => {
      if (!text.value.trim()) { ui.setStatus(status, false, "Вставьте текст для импорта."); return; }
      try { const r = await send("", text.value); text.value = ""; title.value = ""; ui.setStatus(status, true, `Импортировано: диалогов ${r.dialogs}, сообщений ${r.messages}.`); await refresh(); }
      catch (e) { ui.setStatus(status, false, e.message || "Не удалось импортировать."); }
    });
    const pick = ui.btn("Загрузить файлы…", "", () => file.click());
    file.addEventListener("change", async () => {
      const files = [...file.files]; file.value = ""; let dialogs = 0, messages = 0, failed = [];
      for (const f of files) {
        if (f.size > 5_000_000) { failed.push(`${f.name}: больше 5 МБ`); continue; }
        try { const r = await send(f.name, await Koh.readText(f)); dialogs += r.dialogs; messages += r.messages; }
        catch (e) { failed.push(`${f.name}: ${e.message}`); }
      }
      ui.setStatus(status, !failed.length, `Импортировано: диалогов ${dialogs}, сообщений ${messages}.` + (failed.length ? ` Не удалось: ${failed.join("; ")}` : ""));
      await refresh();
    });
    const acts = el("div", "actions"); acts.append(importText, pick);
    imp.append(ui.field("", title), ui.field("", text), acts, file, status);
    nodes.push(imp);

    // ----- dialogs list -----
    const lst = ui.section("ЗАГРУЖЕННОЕ");
    function drawList(dialogs) {
      if (!dialogs.length) { list.replaceChildren(el("p", "hint", "Пока ничего не загружено.")); return; }
      list.replaceChildren(...dialogs.map(d => {
        const row = el("div", "ditem"), info = el("div"), del = ui.btn("Удалить", "", async () => {
          if (!confirm(`Удалить «${d.title}» из памяти?`)) return;
          try { await Koh.api(`/api/memory/dialogs/${d.id}`, {method: "DELETE"}); await refresh(); } catch { Koh.toast("Не удалось удалить"); }
        });
        info.append(document.createTextNode(d.title), el("small", "", `${d.message_count} ${d.source === "text" ? "заметок" : "сообщений"} · ${dateOf(d.created_at)}`));
        row.append(info, del); return row;
      }));
    }
    drawList(data.dialogs); lst.append(list); nodes.push(lst);

    // ----- search + cleanup -----
    const tools = ui.section("ПРОВЕРКА И ОЧИСТКА");
    const q = el("input"); q.type = "text"; q.placeholder = "Проверить поиск по памяти: введите вопрос…"; q.maxLength = 300;
    const results = el("div", "dlist");
    q.addEventListener("input", Koh.debounce(async () => {
      if (q.value.trim().length < 3) { results.replaceChildren(); return; }
      try {
        const r = await Koh.api(`/api/memory/search?q=${encodeURIComponent(q.value.trim())}&limit=5`);
        results.replaceChildren(...(r.results.length ? r.results.map(x => { const row = el("div", "ditem"), info = el("div"); info.append(document.createTextNode(x.content.slice(0, 220)), el("small", "", `${x.title} · ${x.role === "user" ? "пользователь" : x.role === "assistant" ? "ассистент" : "заметка"}`)); row.append(info); return row; }) : [el("p", "hint", "Ничего не найдено.")]));
      } catch { results.replaceChildren(el("p", "hint", "Не удалось выполнить поиск.")); }
    }, 350));
    const clear = el("div", "actions");
    clear.append(ui.btn("Забыть всё, что запомнено из чата", "danger", async () => {
      if (!confirm("Удалить из памяти всё, что было запомнено из чата? Импортированные диалоги останутся.")) return;
      try { const r = await Koh.api("/api/memory/learned", {method: "DELETE"}); Koh.toast(`Забыто записей: ${r.removed}`); await refresh(); } catch { Koh.toast("Не удалось очистить"); }
    }));
    tools.append(ui.field("", q), results, clear); nodes.push(tools);
    const grid = el("div", "cab-grid");
    [nodes[0], nodes[1], imp].forEach(n => n.classList.add("cab-wide"));
    grid.append(...nodes);
    return [grid];
  }, 40, "❖");
})();
