(() => {
  "use strict";
  const Koh = window.Koh; if (!Koh || !Koh.registerTab) return;
  const {el, ui} = Koh;
  const HINTS = {
    none: "ИИ отключён: чат сохраняет сообщения, но не отвечает.",
    anthropic: "Claude через API Anthropic. Ключ создаётся в консоли Anthropic.",
    openai: "OpenAI или любой OpenAI-совместимый сервер, в том числе локальный (Ollama, LM Studio). Для локального сервера ключ не нужен.",
    cloudru: "Cloud.ru Evolution Foundation Models (OpenAI-совместимый API). Ключ создаётся в консоли Cloud.ru. Адрес API и названия моделей возьмите из документации Cloud.ru: если адрес по умолчанию устарел, впишите актуальный.",
  };

  Koh.registerTab("ai", "ИИ", () => {
    const s = Object.assign({}, Koh.settings.ai), d = s.defaults || {models: {}, base_urls: {}, suggestions: {}};
    const nodes = [], status = ui.statusLine();
    const provider = el("select");
    [["none", "Не подключён"], ["anthropic", "Anthropic (Claude)"], ["cloudru", "Cloud.ru (Foundation Models)"], ["openai", "OpenAI или совместимый (в т. ч. локальный)"]].forEach(([v, l]) => { const o = el("option", "", l); o.value = v; provider.append(o); });
    provider.value = s.provider || "none";
    const hint = el("p", "hint");
    const model = el("input"); model.type = "text"; model.value = s.model || ""; model.maxLength = 120; model.setAttribute("list", "model-suggest");
    const datalist = el("datalist"); datalist.id = "model-suggest";
    const baseUrl = el("input"); baseUrl.type = "text"; baseUrl.value = s.base_url || ""; baseUrl.maxLength = 300;
    const baseField = ui.field("Адрес API (необязательно)", baseUrl, "Для локальной модели: http://127.0.0.1:11434/v1");
    const modelField = ui.field("Модель", model);
    const sync = () => {
      const p = provider.value;
      model.placeholder = d.models[p] || ""; baseUrl.placeholder = d.base_urls[p] || "";
      datalist.replaceChildren(...((d.suggestions || {})[p] || []).map(m => { const o = el("option"); o.value = m; return o; }));
      baseField.hidden = !(p === "openai" || p === "cloudru"); modelField.hidden = p === "none"; hint.textContent = HINTS[p] || "";
    };
    provider.addEventListener("change", sync);
    const secConn = ui.section("ПОДКЛЮЧЕНИЕ"), secGen = ui.section("ГЕНЕРАЦИЯ"), secChar = ui.section("ХАРАКТЕР И ИНСТРУКЦИЯ");
    secConn.append(ui.field("Провайдер", provider), hint, modelField, datalist, baseField);

    const key = el("input"); key.type = "password"; key.autocomplete = "off"; key.placeholder = "Вставьте API-ключ"; key.maxLength = 500;
    const keyInfo = el("p", "hint"), keyBtns = el("div", "actions");
    const delKey = ui.btn("Удалить ключ", "danger", async () => {
      if (!confirm("Удалить сохранённый API-ключ?")) return;
      try { await Koh.api("/api/ai/key", {method: "DELETE"}); s.has_key = false; s.key_hint = ""; Koh.settings.ai.has_key = false; showKey(); ui.setStatus(status, true, "Ключ удалён."); }
      catch { ui.setStatus(status, false, "Не удалось удалить ключ."); }
    });
    const saveKey = ui.btn("Сохранить ключ", "primary", async () => {
      if (!key.value.trim()) return;
      try { const r = await Koh.api("/api/ai/key", {method: "PUT", body: JSON.stringify({key: key.value})}); s.has_key = r.has_key; s.key_hint = r.key_hint; Koh.settings.ai.has_key = true; Koh.settings.ai.key_hint = r.key_hint; key.value = ""; showKey(); ui.setStatus(status, true, "Ключ сохранён."); }
      catch { ui.setStatus(status, false, "Не удалось сохранить ключ."); }
    });
    const showKey = () => { keyInfo.textContent = s.has_key ? `Ключ сохранён (${s.key_hint}). Он хранится только в data/secrets.json на этом компьютере и никогда не показывается обратно.` : "Ключ не задан. Он будет храниться только в data/secrets.json на этом компьютере."; delKey.hidden = !s.has_key; };
    keyBtns.append(saveKey, delKey);
    secConn.append(ui.field("API-ключ", key), keyInfo, keyBtns);

    const autoRow = ui.toggle("Температура: авто (рекомендуется)", s.temperature === null || s.temperature === undefined, () => syncTemp());
    const autoBox = autoRow.querySelector("input"), temp = el("input"), tempLabel = el("label", "");
    temp.type = "range"; temp.min = 0; temp.max = 1; temp.step = 0.05; temp.value = s.temperature ?? 0.7;
    const syncTemp = () => { temp.disabled = autoBox.checked; tempLabel.textContent = autoBox.checked ? "Температура: по умолчанию провайдера" : `Температура: ${Number(temp.value).toFixed(2)}`; };
    temp.addEventListener("input", syncTemp);
    const tf = el("div", "field"); tf.append(autoRow, tempLabel, temp); secGen.append(tf);
    const maxTokens = el("input"); maxTokens.type = "number"; maxTokens.min = 64; maxTokens.max = 8192; maxTokens.value = s.max_tokens || 1024;
    secGen.append(ui.field("Максимальная длина ответа (токены)", maxTokens));
    const charRow = ui.toggle("Играть роль из профиля персонажа", s.use_character !== false, () => {}); secChar.append(charRow);
    const prompt = el("textarea"); prompt.value = s.system_prompt || ""; prompt.maxLength = 8000; prompt.placeholder = "Например: отвечай кратко, обращайся ко мне «господин»…";
    secChar.append(ui.field("Дополнительная инструкция", prompt, "Добавляется к образу персонажа и отправляется провайдеру в каждом запросе."));

    const collect = () => ({provider: provider.value, model: model.value.trim(), base_url: baseUrl.value.trim(), temperature: autoBox.checked ? null : Number(temp.value), max_tokens: Number(maxTokens.value) || 1024, system_prompt: prompt.value, use_character: charRow.querySelector("input").checked});
    const persist = async () => { const r = await Koh.api("/api/settings/ai", {method: "PUT", body: JSON.stringify(collect())}); Koh.settings.ai = r; Object.assign(s, r); Koh.notify(); };
    const act = el("div", "actions sticky");
    const test = ui.btn("Проверить подключение", "", async () => {
      test.disabled = true; ui.setStatus(status, true, "Проверяю подключение…");
      try { await persist(); const r = await Koh.api("/api/ai/test", {method: "POST", body: "{}"}); ui.setStatus(status, r.ok, r.ok ? `Подключение работает. Ответ: ${r.detail}` : r.detail); }
      catch { ui.setStatus(status, false, "Не удалось выполнить проверку."); } finally { test.disabled = false; }
    });
    act.append(ui.btn("Сохранить настройки", "primary", async () => { try { await persist(); ui.setStatus(status, true, "Настройки сохранены."); } catch { ui.setStatus(status, false, "Не удалось сохранить настройки."); } }), test);
    nodes.push(secConn, secGen, secChar, status, act);
    sync(); syncTemp(); showKey();
    return nodes;
  }, 30);
})();
