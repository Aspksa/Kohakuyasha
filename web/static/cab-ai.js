(() => {
  "use strict";
  const Koh = window.Koh; if (!Koh || !Koh.registerTab) return;
  const {el, ui} = Koh;

  Koh.registerTab("ai", "ИИ", () => {
    const s = Object.assign({}, Koh.settings.ai), d = s.defaults || {suggestions: [], model: "", base_url: ""};
    const status = ui.statusLine(), grid = el("div", "cab-grid");
    let modelId = s.model || d.model, enabled = s.provider !== "none";

    // ----- status banner -----
    const banner = el("div", "banner");
    const drawBanner = () => {
      const ready = enabled && s.has_key, name = (modelId || d.model).split("/").pop();
      banner.className = "banner " + (!enabled ? "" : ready ? "ok" : "warn");
      const t = el("div"); t.append(el("b", "", !enabled ? "ИИ отключён" : ready ? `Подключено · ${name}` : "Нужен API-ключ Cloud.ru"),
        el("small", "", !enabled ? "Чат сохраняет сообщения, но не отвечает." : ready ? "Ответы приходят от Cloud.ru Foundation Models." : "Вставьте ключ ниже: он хранится только на этом компьютере."));
      banner.replaceChildren(el("i", "dot" + (ready ? " on" : "")), t);
    };

    // ----- connection card -----
    const conn = ui.section("ПОДКЛЮЧЕНИЕ · CLOUD.RU"); conn.classList.add("cab-wide");
    conn.append(ui.toggle("ИИ включён", enabled, v => { enabled = v; drawBanner(); }));
    const models = el("div", "models"), custom = el("input");
    custom.type = "text"; custom.maxLength = 120; custom.placeholder = "или впишите id другой модели Cloud.ru";
    const known = (d.suggestions || []).map(m => m.id);
    custom.value = known.includes(modelId) ? "" : modelId;
    const drawModels = () => models.replaceChildren(...(d.suggestions || []).map(m => {
      const b = el("button", "model" + (m.id === modelId ? " on" : "")); b.type = "button";
      b.append(el("b", "", m.name), el("small", "", m.hint));
      b.addEventListener("click", () => { modelId = m.id; custom.value = ""; drawModels(); drawBanner(); }); return b;
    }));
    custom.addEventListener("input", () => { modelId = custom.value.trim() || d.model; drawModels(); drawBanner(); });
    drawModels();
    conn.append(ui.field("Модель", models), ui.field("", custom));
    const key = el("input"); key.type = "password"; key.autocomplete = "off"; key.placeholder = "Вставьте API-ключ Cloud.ru"; key.maxLength = 500;
    const keyInfo = el("p", "hint"), keyBtns = el("div", "actions");
    const delKey = ui.btn("Удалить ключ", "danger", async () => {
      if (!confirm("Удалить сохранённый API-ключ?")) return;
      try { await Koh.api("/api/ai/key", {method: "DELETE"}); s.has_key = false; s.key_hint = ""; Koh.settings.ai.has_key = false; Koh.notify(); showKey(); drawBanner(); ui.setStatus(status, true, "Ключ удалён."); }
      catch { ui.setStatus(status, false, "Не удалось удалить ключ."); }
    });
    const saveKey = ui.btn("Сохранить ключ", "primary", async () => {
      if (!key.value.trim()) return;
      try { const r = await Koh.api("/api/ai/key", {method: "PUT", body: JSON.stringify({key: key.value})}); s.has_key = r.has_key; s.key_hint = r.key_hint; Koh.settings.ai.has_key = true; Koh.settings.ai.key_hint = r.key_hint; Koh.notify(); key.value = ""; showKey(); drawBanner(); ui.setStatus(status, true, "Ключ сохранён."); }
      catch { ui.setStatus(status, false, "Не удалось сохранить ключ."); }
    });
    const showKey = () => { keyInfo.textContent = s.has_key ? `Ключ сохранён (${s.key_hint}). Хранится только в data/secrets.json на этом компьютере и никогда не показывается обратно.` : "Ключ не задан. Он будет храниться только в data/secrets.json на этом компьютере."; delKey.hidden = !s.has_key; };
    keyBtns.append(saveKey, delKey);
    conn.append(ui.field("API-ключ", key), keyInfo, keyBtns);
    const baseUrl = el("input"); baseUrl.type = "text"; baseUrl.value = s.base_url || ""; baseUrl.maxLength = 300; baseUrl.placeholder = d.base_url || "";
    conn.append(ui.field("Адрес API (менять не нужно)", baseUrl, "Если адрес Cloud.ru изменится, впишите актуальный из их документации."));

    // ----- generation -----
    const gen = ui.section("ГЕНЕРАЦИЯ");
    const autoRow = ui.toggle("Температура: авто (рекомендуется)", s.temperature === null || s.temperature === undefined, () => syncTemp());
    const autoBox = autoRow.querySelector("input"), temp = el("input"), tempLabel = el("label", "");
    temp.type = "range"; temp.min = 0; temp.max = 1; temp.step = 0.05; temp.value = s.temperature ?? 0.7;
    const syncTemp = () => { temp.disabled = autoBox.checked; tempLabel.textContent = autoBox.checked ? "Температура: по умолчанию модели" : `Температура: ${Number(temp.value).toFixed(2)}`; };
    temp.addEventListener("input", syncTemp);
    const tf = el("div", "field"); tf.append(autoRow, tempLabel, temp);
    const maxTokens = el("input"); maxTokens.type = "number"; maxTokens.min = 64; maxTokens.max = 8192; maxTokens.value = s.max_tokens || 1024;
    gen.append(tf, ui.field("Максимальная длина ответа (токены)", maxTokens));

    // ----- character -----
    const chr = ui.section("ХАРАКТЕР И ИНСТРУКЦИЯ");
    const charRow = ui.toggle("Играть роль из профиля персонажа", s.use_character !== false, () => {}, "Образ Kohakuyasha добавляется к каждому запросу");
    const prompt = el("textarea"); prompt.value = s.system_prompt || ""; prompt.maxLength = 8000; prompt.placeholder = "Например: отвечай кратко, обращайся ко мне «господин»…";
    chr.append(charRow, ui.field("Дополнительная инструкция", prompt));

    const collect = () => ({provider: enabled ? "cloudru" : "none", model: modelId === d.model ? "" : modelId, base_url: baseUrl.value.trim(), temperature: autoBox.checked ? null : Number(temp.value), max_tokens: Number(maxTokens.value) || 1024, system_prompt: prompt.value, use_character: charRow.querySelector("input").checked});
    const persist = async () => { const r = await Koh.api("/api/settings/ai", {method: "PUT", body: JSON.stringify(collect())}); Koh.settings.ai = r; Object.assign(s, r); Koh.notify(); };
    const act = el("div", "actions sticky");
    const test = ui.btn("Проверить подключение", "", async () => {
      test.disabled = true; ui.setStatus(status, true, "Проверяю подключение…");
      try { await persist(); const r = await Koh.api("/api/ai/test", {method: "POST", body: "{}"}); ui.setStatus(status, r.ok, r.ok ? `Подключение работает. Ответ: ${r.detail}` : r.detail); }
      catch { ui.setStatus(status, false, "Не удалось выполнить проверку."); } finally { test.disabled = false; }
    });
    act.append(ui.btn("Сохранить настройки", "primary", async () => { try { await persist(); drawBanner(); ui.setStatus(status, true, "Настройки сохранены."); } catch { ui.setStatus(status, false, "Не удалось сохранить настройки."); } }), test);
    grid.append(conn, gen, chr);
    drawBanner(); syncTemp(); showKey();
    return [banner, grid, status, act];
  }, 30, "✦");
})();
