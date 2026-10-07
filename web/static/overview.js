(() => {
  "use strict";
  const Koh = window.Koh;
  const $ = (q) => document.querySelector(q);

  async function refreshOverview() {
    try {
      const [mem, ch] = await Promise.all([Koh.api("/api/memory"), Koh.api("/api/character")]);
      $("#ov-facts").textContent = mem.stats.facts ?? 0;
      $("#ov-messages").textContent = (ch.stats && ch.stats.messages) ?? 0;
    } catch {}
    drawAssistant();
  }
  function drawAssistant() {
    const ai = Koh.settings.ai || {}, on = ai.provider === "cloudru" && ai.has_key;
    const chip = $("#ai-chip");
    chip.textContent = on ? "ПОДКЛЮЧЕНА" : ai.provider === "none" ? "ВЫКЛЮЧЕНА" : "НУЖЕН КЛЮЧ";
    $("#ov-model").textContent = ((ai.model || (ai.defaults && ai.defaults.model) || "—").split("/").pop());
  }
  function drawUpdate() {
    const u = Koh.updateInfo || {}, chip = $("#up-chip");
    $("#ov-version").textContent = u.local ? "v" + u.local : (Koh.status && Koh.status.runtime ? "v" + Koh.status.runtime.version : "—");
    $("#ov-remote").textContent = u.remote ? "v" + u.remote : "—";
    chip.textContent = u.error ? "НЕТ СВЯЗИ" : u.newer ? "ЕСТЬ ОБНОВЛЕНИЕ" : u.remote ? "АКТУАЛЬНО" : "НЕ ПРОВЕРЕНО";
    chip.style.color = u.newer ? "var(--accent-text)" : "";
  }
  $("#ov-chat").addEventListener("click", () => Koh.open("chat"));
  $("#ov-cabinet").addEventListener("click", () => Koh.open("cabinet"));
  $("#ov-update").addEventListener("click", () => Koh.go("update"));
  Koh.onSettings(drawAssistant);
  Koh.onUpdateInfo = drawUpdate;
  Koh.refreshOverview = refreshOverview;
  refreshOverview(); drawUpdate();
})();
