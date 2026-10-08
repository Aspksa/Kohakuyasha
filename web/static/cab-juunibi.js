(() => {
  "use strict";
  const Koh = window.Koh; if (!Koh || !Koh.registerTab) return;
  const {el, ui} = Koh;

  Koh.registerTab("juunibi", "JUUNIBI", async () => {
    let info = await Koh.api("/api/juunibi");
    const grid = el("div", "cab-grid"), status = ui.statusLine();
    const save = async (patch) => {
      Object.assign(info.settings, patch);
      try { Koh.setAll(await Koh.api("/api/settings/juunibi", {method: "PUT", body: JSON.stringify(info.settings)})); ui.setStatus(status, true, "Сохранено."); }
      catch { ui.setStatus(status, false, "Не удалось сохранить."); }
    };
    const draw = () => {
      const st = info.stats, s = info.settings, nodes = [];
      const lib = ui.section("БИБЛИОТЕКА"); lib.classList.add("cab-wide");
      if (!st.available) {
        lib.append(el("p", "hint", st.error || "Материалы JUUNIBI не найдены в папке content/juunibi."));
        nodes.push(lib); grid.replaceChildren(...nodes); return;
      }
      lib.append(ui.row("Действий всего", `${st.actions_total} (создано ИИ: ${st.generated})`), ui.row("Использовано", st.actions_used), ui.row("Осталось неиспользованных", st.actions_unused),
        ui.row("Реплик", `${st.phrases_total} в ${st.phrase_categories} категориях`));
      const bar = el("div", "ubar"), fill = el("i"); fill.style.width = Math.round(st.actions_used / Math.max(1, st.actions_total) * 100) + "%"; bar.append(fill); lib.append(bar);
      lib.append(el("p", "hint", "Действия и реплики не повторяются: история хранится в базе на этом компьютере. Когда неиспользованных действий не останется, ИИ создаст новое (ключ остаётся на сервере); если ИИ недоступен, повтора не будет."));
      if (st.last_error) lib.append(el("div", "status-line bad", st.last_error));
      nodes.push(lib);

      const opt = ui.section("ПОВЕДЕНИЕ");
      opt.append(
        ui.toggle("Действия перед ответом", s.actions, v => save({actions: v}), "Аватар «играет» ремарку, пока готовится ответ, и она остаётся в чате"),
        ui.toggle("Реплики аватара", s.phrases, v => save({phrases: v}), "Приветствие подбирается из библиотеки по времени суток"),
        ui.toggle("Иногда говорить самой", s.ambient, v => save({ambient: v}), "Редкие спокойные реплики над аватаром, пока вы заняты; не чаще раза в 9–15 минут"),
        ui.toggle("Создавать новые действия через ИИ", s.generate, v => save({generate: v}), info.ai_ready ? "Cloud.ru подключён" : "Нужен ключ Cloud.ru во вкладке «ИИ»"),
        ui.toggle("Характер JUUNIBI в ответах ИИ", s.persona, v => save({persona: v}), "Ассистент отвечает в образе JUUNIBI вместо профиля Kohakuyasha"),
      );
      nodes.push(opt);

      const tools = ui.section("ДЕЙСТВИЯ"), acts = el("div", "actions");
      const preview = el("p", "stage-line", "");
      acts.append(
        ui.btn("Показать действие", "", async () => {
          const a = await Koh.juunibi.action(); preview.textContent = a ? Koh.juunibi.plain(a.text) : (Koh.juunibi.lastReason() || "Действие недоступно."); if (a) { Koh.juunibi.perform(a); info = await Koh.api("/api/juunibi"); draw(); }
        }),
        ui.btn("Создать новое через ИИ", "", async () => {
          ui.setStatus(status, true, "Прошу ИИ придумать действие…");
          try { const r = await Koh.api("/api/juunibi/generate-action", {method: "POST", body: "{}"}); info.stats = r.stats; preview.textContent = Koh.juunibi.plain(r.action.text); ui.setStatus(status, true, "Новое действие добавлено в библиотеку."); draw(); }
          catch (e) { ui.setStatus(status, false, e.message); }
        }),
        ui.btn("Сбросить историю действий", "danger", async () => {
          if (!confirm("Все действия снова станут неиспользованными. Продолжить?")) return;
          try { const r = await Koh.api("/api/juunibi/reset", {method: "POST", body: JSON.stringify({scope: "actions"})}); info.stats = r.stats; draw(); ui.setStatus(status, true, "История действий сброшена."); } catch (e) { ui.setStatus(status, false, e.message); }
        }),
        ui.btn("Сбросить историю реплик", "danger", async () => {
          try { const r = await Koh.api("/api/juunibi/reset", {method: "POST", body: JSON.stringify({scope: "phrases"})}); info.stats = r.stats; ui.setStatus(status, true, "История реплик сброшена."); } catch (e) { ui.setStatus(status, false, e.message); }
        }),
      );
      tools.append(preview, acts); nodes.push(tools);
      grid.replaceChildren(...nodes);
    };
    draw();
    return [grid, status];
  }, 40, "❖");
})();
