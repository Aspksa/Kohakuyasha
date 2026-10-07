(() => {
  "use strict";
  const Koh = window.Koh; if (!Koh) return;
  const {api, el} = Koh;
  const panel = Koh.panels.cabinet;
  const body = document.getElementById("cabinet-body");
  const tabs = [...panel.querySelectorAll(".tab")];
  const TRAITS = {"devoted to her master": "предана господину", "elegant": "элегантна", "mature": "зрелая", "protective": "защищает", "calm": "спокойна", "extremely powerful": "невероятно сильна"};
  const COLORS = {white: "белые", golden: "золотые"};
  let current = "profile", saveTimer = 0;

  const row = (k, v) => { const r = el("div", "cab-row"); r.append(el("span", "", k), el("b", "", String(v))); return r; };
  const section = (title) => { const s = el("div", "cab-sec"); s.append(el("h4", "", title)); return s; };
  const field = (label, control, hint) => { const f = el("div", "field"); if (label) f.append(el("label", "", label)); f.append(control); if (hint) f.append(el("p", "hint", hint)); return f; };
  function seg(options, value, onPick) {
    const wrap = el("div", "seg");
    options.forEach(([val, label]) => {
      const b = el("button", val === value ? "on" : "", label); b.type = "button";
      b.addEventListener("click", () => { wrap.querySelectorAll("button").forEach(x => x.classList.remove("on")); b.classList.add("on"); onPick(val); });
      wrap.append(b);
    });
    return wrap;
  }
  function toggle(label, checked, onChange) {
    const r = el("div", "toggle-row"), sw = el("label", "switch"), inp = el("input"), knob = el("span");
    inp.type = "checkbox"; inp.checked = !!checked; inp.addEventListener("change", () => onChange(inp.checked));
    sw.append(inp, knob); r.append(el("span", "", label), sw); return r;
  }
  const statusLine = () => el("div", "status-line");
  function setStatus(node, ok, text) { node.className = `status-line ${ok ? "ok" : "bad"}`; node.textContent = text; }

  // ---------- Profile ----------
  async function renderProfile() {
    const [c, s] = await Promise.all([api("/api/character"), api("/api/status")]);
    const ch = c.character || {}, nodes = [];
    const hero = el("div", "cab-hero"), im = el("img"), t = el("div");
    im.src = "/static/avatar.png"; im.alt = "";
    t.append(el("h3", "", ch.name || "Kohakuyasha"), el("p", "", `${ch.role === "personal assistant" ? "личный помощник" : (ch.role || "помощник")} · мифическая лиса`));
    hero.append(im, t); nodes.push(hero);
    const traits = section("ХАРАКТЕР"), chips = el("div", "chips");
    (Array.isArray(ch.traits) ? ch.traits : []).forEach(x => chips.append(el("span", "chip", TRAITS[x] || String(x))));
    traits.append(chips); nodes.push(traits);
    const looks = section("ОБЛИК");
    if (ch.apparent_age) looks.append(row("Возраст на вид", ch.apparent_age));
    const ap = ch.appearance || {};
    if (Array.isArray(ap.hair)) looks.append(row("Волосы", ap.hair.map(h => COLORS[h] || h).join(", ")));
    if (ap.fox_ears) looks.append(row("Лисьи уши", "да"));
    if (ap.multiple_fox_tails) looks.append(row("Хвосты", "несколько"));
    if (ch.power) looks.append(row("Сила", ch.power.type === "magic" ? "магия, способная разрушить мир" : String(ch.power.type)));
    nodes.push(looks);
    const rt = s.runtime || {}, st = section("СОСТОЯНИЕ");
    st.append(row("Статус", rt.status || "—"), row("Сообщений в чате", (c.stats || {}).messages ?? 0), row("Версия", rt.version ? "v" + rt.version : "—"));
    nodes.push(st);
    body.replaceChildren(...nodes);
  }

  // ---------- Avatar visualisation ----------
  function renderAvatar() {
    const a = Koh.settings.avatar, nodes = [];
    const prev = el("div", "preview"), pv = el("div", "avatar"), pimg = el("img");
    pimg.alt = ""; pimg.draggable = false; pv.append(pimg, el("span", "avatar-dot")); prev.append(pv);
    const refresh = () => { Koh.applyAvatar(pv, pimg); pv.style.width = a.size + "px"; pv.style.height = a.size + "px"; };
    const change = (patch) => { Object.assign(a, patch); refresh(); Koh.notify(); clearTimeout(saveTimer); saveTimer = setTimeout(save, 350); };
    const save = async () => { try { await api("/api/settings/avatar", {method: "PUT", body: JSON.stringify(a)}); } catch {} };
    refresh(); nodes.push(prev);
    nodes.push(field("Что показывать", seg([["face", "Только лицо"], ["full", "Вся картинка"]], a.crop, v => change({crop: v}))));
    nodes.push(field("Форма", seg([["soft", "Мягкие края"], ["rounded", "Скруглённый"], ["circle", "Круг"]], a.shape, v => change({shape: v}))));
    const size = el("input"); size.type = "range"; size.min = 48; size.max = 200; size.step = 4; size.value = a.size;
    const sizeLabel = el("label", "", `Размер: ${a.size} px`);
    size.addEventListener("input", () => { sizeLabel.textContent = `Размер: ${size.value} px`; change({size: Number(size.value)}); });
    const sf = el("div", "field"); sf.append(sizeLabel, size); nodes.push(sf);
    const tg = el("div", "field");
    tg.append(toggle("Рамка", a.ring, v => change({ring: v})), toggle("Свечение", a.glow, v => change({glow: v})), toggle("Индикатор статуса", a.status_dot, v => change({status_dot: v})));
    nodes.push(tg);
    const act = el("div", "actions"), reset = el("button", "", "Вернуть в правый нижний угол"); reset.type = "button";
    reset.addEventListener("click", () => Koh.resetPos());
    act.append(reset); nodes.push(act);
    nodes.push(el("p", "hint", "Аватар можно перетаскивать по любой странице: положение запоминается."));
    body.replaceChildren(...nodes);
  }

  // ---------- AI settings ----------
  function renderAI() {
    const s = Object.assign({}, Koh.settings.ai), d = s.defaults || {models: {}, base_urls: {}};
    const nodes = [], status = statusLine();
    const provider = el("select");
    [["none", "Не подключён"], ["anthropic", "Anthropic (Claude)"], ["openai", "OpenAI или совместимый (в т. ч. локальный Ollama)"]].forEach(([v, l]) => { const o = el("option", "", l); o.value = v; provider.append(o); });
    provider.value = s.provider || "none";
    const model = el("input"); model.type = "text"; model.value = s.model || ""; model.maxLength = 120;
    const baseUrl = el("input"); baseUrl.type = "text"; baseUrl.value = s.base_url || ""; baseUrl.maxLength = 300;
    const baseField = field("Адрес API (необязательно)", baseUrl, "Для локальной модели: http://127.0.0.1:11434/v1");
    const modelField = field("Модель", model);
    const syncProvider = () => {
      model.placeholder = d.models[provider.value] || "";
      baseUrl.placeholder = d.base_urls[provider.value] || "";
      baseField.hidden = provider.value !== "openai"; modelField.hidden = provider.value === "none";
    };
    provider.addEventListener("change", syncProvider);
    nodes.push(field("Провайдер", provider), modelField, baseField);
    // API key
    const key = el("input"); key.type = "password"; key.autocomplete = "off"; key.placeholder = "Вставьте API-ключ"; key.maxLength = 500;
    const keyInfo = el("p", "hint");
    const keyBtns = el("div", "actions");
    const saveKey = el("button", "primary", "Сохранить ключ"), delKey = el("button", "danger", "Удалить ключ");
    saveKey.type = delKey.type = "button";
    const showKey = () => { keyInfo.textContent = s.has_key ? `Ключ сохранён (${s.key_hint}). Он хранится только в data/secrets.json на этом компьютере и никогда не показывается обратно.` : "Ключ не задан. Он будет храниться только в data/secrets.json на этом компьютере."; delKey.hidden = !s.has_key; };
    saveKey.addEventListener("click", async () => {
      if (!key.value.trim()) return;
      try { const r = await api("/api/ai/key", {method: "PUT", body: JSON.stringify({key: key.value})}); s.has_key = r.has_key; s.key_hint = r.key_hint; Koh.settings.ai.has_key = true; Koh.settings.ai.key_hint = r.key_hint; key.value = ""; showKey(); setStatus(status, true, "Ключ сохранён."); }
      catch { setStatus(status, false, "Не удалось сохранить ключ."); }
    });
    delKey.addEventListener("click", async () => {
      if (!confirm("Удалить сохранённый API-ключ?")) return;
      try { await api("/api/ai/key", {method: "DELETE"}); s.has_key = false; s.key_hint = ""; Koh.settings.ai.has_key = false; showKey(); setStatus(status, true, "Ключ удалён."); }
      catch { setStatus(status, false, "Не удалось удалить ключ."); }
    });
    keyBtns.append(saveKey, delKey);
    nodes.push(field("API-ключ", key), keyInfo, keyBtns);
    // generation
    const auto = toggle("Температура: авто (рекомендуется)", s.temperature === null || s.temperature === undefined, () => syncTemp());
    const temp = el("input"); temp.type = "range"; temp.min = 0; temp.max = 1; temp.step = 0.05; temp.value = s.temperature ?? 0.7;
    const tempLabel = el("label", "", "");
    const autoBox = auto.querySelector("input");
    const syncTemp = () => { temp.disabled = autoBox.checked; tempLabel.textContent = autoBox.checked ? "Температура: по умолчанию провайдера" : `Температура: ${Number(temp.value).toFixed(2)}`; };
    temp.addEventListener("input", syncTemp);
    const tf = el("div", "field"); tf.append(auto, tempLabel, temp); nodes.push(tf);
    const maxTokens = el("input"); maxTokens.type = "number"; maxTokens.min = 64; maxTokens.max = 8192; maxTokens.value = s.max_tokens || 1024;
    nodes.push(field("Максимальная длина ответа (токены)", maxTokens));
    const useChar = el("div", "field"); const ucBox = toggle("Играть роль из профиля персонажа", s.use_character !== false, () => {}); useChar.append(ucBox); nodes.push(useChar);
    const prompt = el("textarea"); prompt.value = s.system_prompt || ""; prompt.maxLength = 8000; prompt.placeholder = "Например: отвечай кратко, обращайся ко мне «господин»…";
    nodes.push(field("Дополнительная инструкция", prompt, "Добавляется к образу персонажа и отправляется провайдеру в каждом запросе."));
    // actions
    const act = el("div", "actions"), save = el("button", "primary", "Сохранить настройки"), test = el("button", "", "Проверить подключение");
    save.type = test.type = "button";
    const collect = () => ({provider: provider.value, model: model.value.trim(), base_url: baseUrl.value.trim(), temperature: autoBox.checked ? null : Number(temp.value), max_tokens: Number(maxTokens.value) || 1024, system_prompt: prompt.value, use_character: ucBox.querySelector("input").checked});
    const persist = async () => { const r = await api("/api/settings/ai", {method: "PUT", body: JSON.stringify(collect())}); Koh.settings.ai = r; Object.assign(s, r); Koh.notify(); };
    save.addEventListener("click", async () => { try { await persist(); setStatus(status, true, "Настройки сохранены."); } catch { setStatus(status, false, "Не удалось сохранить настройки."); } });
    test.addEventListener("click", async () => {
      test.disabled = true; setStatus(status, true, "Проверяю подключение…");
      try { await persist(); const r = await api("/api/ai/test", {method: "POST", body: "{}"}); setStatus(status, r.ok, r.ok ? `Подключение работает. Ответ: ${r.detail}` : r.detail); }
      catch { setStatus(status, false, "Не удалось выполнить проверку."); } finally { test.disabled = false; }
    });
    act.append(save, test); nodes.push(act, status);
    syncProvider(); syncTemp(); showKey();
    body.replaceChildren(...nodes);
  }

  // ---------- System ----------
  async function renderSystem() {
    const s = await api("/api/status"), rt = s.runtime || {}, nodes = [], sec = section("РАБОТА");
    sec.append(row("Статус", rt.status || "—"), row("Действие", rt.current_action || "—"), row("Версия", rt.version ? "v" + rt.version : "—"), row("Порт", rt.port ?? "—"), row("CPU", `${Math.round(rt.cpu_percent || 0)}%`), row("Память процесса", `${rt.memory_mb ?? 0} MB`), row("Python", rt.python || "—"));
    nodes.push(sec);
    const svc = section("СЛУЖБЫ"); Object.entries(s.services || {}).forEach(([k, v]) => svc.append(row(k, v))); nodes.push(svc);
    body.replaceChildren(...nodes);
  }

  const RENDER = {profile: renderProfile, avatar: renderAvatar, ai: renderAI, system: renderSystem};
  async function selectTab(name) {
    current = name; tabs.forEach(t => t.classList.toggle("active", t.dataset.tab === name));
    try { await RENDER[name](); } catch { body.replaceChildren(el("p", "hint", "Не удалось загрузить раздел.")); }
  }
  tabs.forEach(t => t.addEventListener("click", () => selectTab(t.dataset.tab)));
  Koh.hooks.cabinet = () => selectTab(current);
  Koh.hooks.cabinetTab = (name) => selectTab(name);
})();
