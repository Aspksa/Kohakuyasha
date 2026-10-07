(() => {
  "use strict";
  const Koh = window.Koh; if (!Koh || !Koh.registerTab) return;
  const {el, ui} = Koh;
  const dateOf = (iso) => { try { return new Date(iso).toLocaleDateString("ru-RU"); } catch { return ""; } };
  const CATS = {personal: "Личное", preference: "Предпочтения", relation: "Близкие", project: "Проекты", schedule: "Планы", other: "Другое"};

  Koh.registerTab("memory", "Память", async () => {
    const data = await Koh.api("/api/memory"), m = data.settings, nodes = [], status = ui.statusLine();
    const saveSettings = Koh.debounce(async () => { try { await Koh.api("/api/settings/memory", {method: "PUT", body: JSON.stringify(m)}); Koh.settings.memory = {...m}; } catch { Koh.toast("Не удалось сохранить настройки памяти"); } }, 300);

    nodes.push(el("p", "hint", "Память — не дообучение модели. Kohakuyasha запоминает факты о вас, ведёт краткое содержание беседы, знает текущие дату и время и при каждом ответе подставляет нужное в запрос. Всё хранится локально."));

    // ---------- stats ----------
    const stats = el("div", "stat-grid");
    const statBox = (label, value) => { const d = el("div"); d.append(el("b", "", String(value)), el("span", "", label)); return d; };
    const drawStats = (st) => stats.replaceChildren(statBox("фактов о вас", st.facts ?? 0), statBox("диалогов загружено", st.dialogs), statBox("фрагментов из чата и импорта", (st.imported || 0) + (st.learned || 0)));
    drawStats(data.stats); nodes.push(stats);

    // ---------- facts ----------
    const facts = ui.section("ЧТО Я О ВАС ЗНАЮ"), list = el("div", "dlist"), filter = el("input"), add = el("input"), addCat = el("select");
    let all = [];
    filter.type = "text"; filter.placeholder = "Поиск по фактам…"; filter.maxLength = 100;
    add.type = "text"; add.placeholder = "Добавить факт вручную, например: «Любит чай с лимоном»"; add.maxLength = 300;
    Object.entries(CATS).forEach(([k, v]) => { const o = el("option", "", v); o.value = k; addCat.append(o); }); addCat.value = "other";
    const refreshAll = async () => { const [f, d] = await Promise.all([Koh.api("/api/memory/facts"), Koh.api("/api/memory")]); all = f.facts; drawFacts(); drawStats(d.stats); drawSummary(d.summary); drawDialogs(d.dialogs); };
    const patch = async (id, body) => { try { await Koh.api(`/api/memory/facts/${id}`, {method: "PUT", body: JSON.stringify(body)}); await refreshAll(); } catch { Koh.toast("Не удалось изменить факт"); } };
    function factRow(f) {
      const row = el("div", "ditem fact"), main = el("div", "fact-main"), tag = el("span", "chip", CATS[f.category] || "Другое");
      const text = el("span", "fact-text", f.text); text.title = "Нажмите, чтобы изменить"; text.tabIndex = 0;
      const edit = () => {
        const inp = el("input"); inp.type = "text"; inp.value = f.text; inp.maxLength = 300; inp.className = "fact-edit";
        const done = (save) => { if (save && inp.value.trim().length >= 3 && inp.value.trim() !== f.text) patch(f.id, {text: inp.value.trim()}); else inp.replaceWith(text); };
        inp.addEventListener("keydown", (e) => { if (e.key === "Enter") done(true); else if (e.key === "Escape") done(false); });
        inp.addEventListener("blur", () => done(true)); text.replaceWith(inp); inp.focus(); inp.select();
      };
      text.addEventListener("click", edit); text.addEventListener("keydown", (e) => { if (e.key === "Enter") edit(); });
      main.append(tag, text, el("small", "", `${f.source === "manual" ? "вручную" : "из разговоров"} · ${dateOf(f.updated_at)}${f.use_count ? ` · использован ${f.use_count}×` : ""}`));
      const acts = el("div", "fact-acts");
      const star = ui.btn("★".repeat(f.importance), "", () => patch(f.id, {importance: f.importance % 5 + 1})); star.title = "Важность (нажмите, чтобы изменить)"; star.classList.add("fact-star");
      const pin = ui.btn(f.pinned ? "📌" : "📍", "", () => patch(f.id, {pinned: !f.pinned})); pin.title = f.pinned ? "Закреплён: всегда в памяти" : "Закрепить: всегда в памяти";
      const del = ui.btn("×", "", async () => { try { await Koh.api(`/api/memory/facts/${f.id}`, {method: "DELETE"}); await refreshAll(); } catch { Koh.toast("Не удалось удалить"); } }); del.title = "Забыть";
      acts.append(star, pin, del); row.append(main, acts); return row;
    }
    function drawFacts() {
      const q = filter.value.trim().toLowerCase(), shown = all.filter(f => !q || f.text.toLowerCase().includes(q));
      list.replaceChildren(...(shown.length ? shown.map(factRow) : [el("p", "hint", all.length ? "Ничего не найдено." : "Пока нет фактов. Скажите в чате «Запомни: …» или нажмите «Извлечь из чата сейчас».")]));
    }
    filter.addEventListener("input", drawFacts);
    const addRow = el("div", "keyline"); addRow.append(add, addCat, ui.btn("Добавить", "primary", async () => {
      if (add.value.trim().length < 3) return;
      try { await Koh.api("/api/memory/facts", {method: "POST", body: JSON.stringify({text: add.value.trim(), category: addCat.value})}); add.value = ""; await refreshAll(); }
      catch (e) { Koh.toast(e.message || "Не удалось добавить"); }
    }));
    add.addEventListener("keydown", (e) => { if (e.key === "Enter") addRow.querySelector(".primary").click(); });
    const fa = el("div", "actions");
    fa.append(ui.btn("Извлечь из чата сейчас", "primary", async function () {
      try { ui.setStatus(status, true, "Анализирую разговор…"); const r = await Koh.api("/api/memory/extract", {method: "POST", body: "{}"}); ui.setStatus(status, true, r.added || r.updated ? `Новых фактов: ${r.added}, обновлено: ${r.updated}.` : "Новых фактов не нашлось."); await refreshAll(); }
      catch (e) { ui.setStatus(status, false, e.message || "Не удалось извлечь факты."); }
    }), ui.btn("Забыть автоматические факты", "danger", async () => {
      if (!confirm("Удалить все факты, найденные автоматически? Закреплённые и добавленные вручную останутся.")) return;
      try { const r = await Koh.api("/api/memory/facts?scope=auto", {method: "DELETE"}); Koh.toast(`Забыто фактов: ${r.removed}`); await refreshAll(); } catch { Koh.toast("Не удалось очистить"); }
    }));
    facts.append(ui.field("", filter), list, ui.field("", addRow), fa, status); facts.classList.add("cab-wide"); nodes.push(facts);

    // ---------- settings ----------
    const sets = ui.section("КАК ЭТО РАБОТАЕТ");
    const every = ui.range("", 1, 10, 1, m.extract_every, v => `Искать факты после каждых ${v} ваших сообщений`, v => { m.extract_every = v; saveSettings(); });
    sets.append(
      ui.toggle("Память включена", m.enabled, v => { m.enabled = v; saveSettings(); }, "Поиск по загруженным диалогам и прошлым разговорам"),
      ui.toggle("Знать факты обо мне", m.use_facts, v => { m.use_facts = v; saveSettings(); }, "Подставлять нужные факты в каждый запрос"),
      ui.toggle("Находить факты сама", m.auto_facts, v => { m.auto_facts = v; saveSettings(); }, "Отдельный короткий запрос к ИИ после нескольких сообщений"), every,
      ui.toggle("Помнить ход беседы", m.use_summary, v => { m.use_summary = v; saveSettings(); }, "Старые сообщения сжимаются в краткое содержание"),
      ui.toggle("Запоминать сообщения чата для поиска", m.learn_chat, v => { m.learn_chat = v; saveSettings(); }),
      ui.range("", 1, 12, 1, m.max_snippets, v => `Фрагментов из диалогов в запросе: ${v}`, v => { m.max_snippets = v; saveSettings(); }));
    nodes.push(sets);

    // ---------- summary ----------
    const sum = ui.section("КРАТКОЕ СОДЕРЖАНИЕ БЕСЕДЫ"), sumBox = el("div", "sum-box");
    const drawSummary = (text) => {
      sumBox.replaceChildren();
      if (!text) { sumBox.append(el("p", "hint", "Появится, когда беседа станет длинной: старые сообщения сожмутся в несколько предложений.")); return; }
      sumBox.append(el("p", "sum-text", text), ui.btn("Сбросить содержание", "", async () => { try { await Koh.api("/api/memory/summary", {method: "DELETE"}); drawSummary(""); } catch { Koh.toast("Не удалось сбросить"); } }));
    };
    drawSummary(data.summary); sum.append(sumBox); nodes.push(sum);

    // ---------- import ----------
    const imp = ui.section("ЗАГРУЗИТЬ ДИАЛОГИ И ЗНАНИЯ"), istatus = ui.statusLine();
    imp.append(el("p", "hint", "Подходит: экспорт ChatGPT (conversations.json), экспорт Claude, JSON/JSONL со списком {role, content}, текст вида «Пользователь: … / Ассистент: …» или обычные заметки."));
    const title = el("input"); title.type = "text"; title.maxLength = 120; title.placeholder = "Название (необязательно)";
    const text = el("textarea"); text.placeholder = "Вставьте диалог или текст сюда…"; text.style.minHeight = "120px";
    const file = el("input"); file.type = "file"; file.accept = ".json,.jsonl,.txt,.md,.csv,.log,application/json,text/plain"; file.multiple = true; file.hidden = true;
    const dlist = el("div", "dlist");
    const send = (name, body) => Koh.api("/api/memory/import", {method: "POST", body: JSON.stringify({filename: name, title: title.value.trim(), text: body})});
    const importText = ui.btn("Импортировать из текста", "primary", async () => {
      if (!text.value.trim()) { ui.setStatus(istatus, false, "Вставьте текст для импорта."); return; }
      try { const r = await send("", text.value); text.value = ""; title.value = ""; ui.setStatus(istatus, true, `Импортировано: диалогов ${r.dialogs}, сообщений ${r.messages}.`); await refreshAll(); }
      catch (e) { ui.setStatus(istatus, false, e.message || "Не удалось импортировать."); }
    });
    file.addEventListener("change", async () => {
      const files = [...file.files]; file.value = ""; let dialogs = 0, messages = 0, failed = [];
      for (const f of files) {
        if (f.size > 5_000_000) { failed.push(`${f.name}: больше 5 МБ`); continue; }
        try { const r = await send(f.name, await Koh.readText(f)); dialogs += r.dialogs; messages += r.messages; } catch (e) { failed.push(`${f.name}: ${e.message}`); }
      }
      ui.setStatus(istatus, !failed.length, `Импортировано: диалогов ${dialogs}, сообщений ${messages}.` + (failed.length ? ` Не удалось: ${failed.join("; ")}` : "")); await refreshAll();
    });
    const iacts = el("div", "actions"); iacts.append(importText, ui.btn("Загрузить файлы…", "", () => file.click()));
    imp.append(ui.field("", title), ui.field("", text), iacts, file, istatus);
    function drawDialogs(dialogs) {
      if (!dialogs.length) { dlist.replaceChildren(el("p", "hint", "Загруженных диалогов пока нет.")); return; }
      dlist.replaceChildren(...dialogs.map(d => {
        const row = el("div", "ditem"), info = el("div"), del = ui.btn("Удалить", "", async () => {
          if (!confirm(`Удалить «${d.title}» из памяти?`)) return;
          try { await Koh.api(`/api/memory/dialogs/${d.id}`, {method: "DELETE"}); await refreshAll(); } catch { Koh.toast("Не удалось удалить"); }
        });
        info.append(document.createTextNode(d.title), el("small", "", `${d.message_count} ${d.source === "text" ? "заметок" : "сообщений"} · ${dateOf(d.created_at)}`));
        row.append(info, del); return row;
      }));
    }
    drawDialogs(data.dialogs); imp.append(dlist); imp.classList.add("cab-wide"); nodes.push(imp);

    // ---------- search tester ----------
    const tools = ui.section("ПРОВЕРКА ПОИСКА И ОЧИСТКА"), q = el("input"), results = el("div", "dlist");
    q.type = "text"; q.placeholder = "Что найдётся в загруженных диалогах по запросу…"; q.maxLength = 300;
    q.addEventListener("input", Koh.debounce(async () => {
      if (q.value.trim().length < 3) { results.replaceChildren(); return; }
      try {
        const r = await Koh.api(`/api/memory/search?q=${encodeURIComponent(q.value.trim())}&limit=5`);
        results.replaceChildren(...(r.results.length ? r.results.map(x => { const row = el("div", "ditem"), info = el("div"); info.append(document.createTextNode(x.content.slice(0, 220)), el("small", "", `${x.title} · ${x.role === "user" ? "пользователь" : x.role === "assistant" ? "ассистент" : "заметка"}`)); row.append(info); return row; }) : [el("p", "hint", "Ничего не найдено.")]));
      } catch { results.replaceChildren(el("p", "hint", "Не удалось выполнить поиск.")); }
    }, 350));
    const clear = el("div", "actions");
    clear.append(ui.btn("Забыть сообщения чата в поиске", "danger", async () => {
      if (!confirm("Удалить из поиска всё, что было запомнено из чата? Импортированные диалоги и факты останутся.")) return;
      try { const r = await Koh.api("/api/memory/learned", {method: "DELETE"}); Koh.toast(`Забыто записей: ${r.removed}`); await refreshAll(); } catch { Koh.toast("Не удалось очистить"); }
    }));
    tools.append(ui.field("", q), results, clear); nodes.push(tools);

    const grid = el("div", "cab-grid");
    [nodes[0], nodes[1]].forEach(n => n.classList.add("cab-wide"));
    grid.append(...nodes);
    refreshAll();
    return [grid];
  }, 40, "❖");
})();
