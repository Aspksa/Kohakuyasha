(() => {
  "use strict";
  const Koh = window.Koh; if (!Koh) return;
  const avatar = document.getElementById("avatar");
  const MOODS = {
    wiggle: ["игривость", "смущение"],
    rise: ["величие", "золотое появление", "поклон", "лунное сияние", "тайна", "вечер"],
    pulse: ["защита", "работа"],
  };  // everything else: a soft breathing glow
  const moodOf = (category) => Object.keys(MOODS).find(m => MOODS[m].includes(category)) || "soft";
  const enabled = () => { const j = Koh.settings.juunibi; return !!(j && j.available); };
  let lastReason = "";

  async function post(url, body) {
    try { return await Koh.api(url, {method: "POST", body: JSON.stringify(body || {})}); } catch { return null; }
  }
  // Returns {id, text, category, duration_seconds, ...} or null (disabled, exhausted without AI, offline). Never repeats.
  async function action(category, context) {
    if (!enabled() || !Koh.settings.juunibi.actions) return null;
    const r = await post("/api/juunibi/action", {category, context});
    lastReason = r && !r.action ? (r.reason || "") : "";
    return r && r.action ? r.action : null;
  }
  async function phrase(category) {
    if (!enabled() || !Koh.settings.juunibi.phrases) return null;
    const r = await post("/api/juunibi/phrase", {category});
    return r && r.phrase ? r.phrase : null;
  }
  // The avatar reacts to the stage direction: a short transform-only animation (cheap, no filters).
  function perform(a) {
    if (!avatar || !a || Koh.settings.app.animations === false) return;
    const mood = moodOf(a.category), sec = Math.min(Math.max(Number(a.duration_seconds) || 4, 2.5), 8);
    avatar.classList.remove("act-soft", "act-wiggle", "act-rise", "act-pulse");
    void avatar.offsetWidth;  // restart the animation if one was running
    avatar.style.setProperty("--act-dur", sec + "s");
    avatar.classList.add("act-" + mood);
    clearTimeout(perform.timer);
    perform.timer = setTimeout(() => avatar.classList.remove("act-" + mood), sec * 1000 + 100);
  }
  const plain = (text) => String(text || "").replace(/^\*+|\*+$/g, "").trim();

  // Occasional unprompted phrase (off by default): only while the tab is visible and nothing else is open.
  function scheduleAmbient() {
    setTimeout(async () => {
      const j = Koh.settings.juunibi;
      if (j && j.available && j.phrases && j.ambient && !document.hidden && Koh.panels && Koh.panels.chat.hidden && Koh.panels.cabinet.hidden) {
        const p = await phrase("ambient"); if (p && Koh.say) Koh.say(p.text, 10000);
      }
      scheduleAmbient();
    }, (9 + Math.random() * 6) * 60 * 1000);
  }
  scheduleAmbient();

  Koh.juunibi = {action, phrase, perform, plain, moodOf, lastReason: () => lastReason};
})();
