const $ = (q) => document.querySelector(q);
const $$ = (q) => [...document.querySelectorAll(q)];
const actionHeaders = {"X-Kohakuyasha-Request":"1","Content-Type":"application/json"};
let lastEvents = [];

function toast(message){
  const el=$("#toast"); el.textContent=message; el.classList.add("show");
  setTimeout(()=>el.classList.remove("show"),2400);
}
function formatUptime(s){
  s=Math.max(0,Number(s)||0); const h=Math.floor(s/3600),m=Math.floor((s%3600)/60),sec=Math.floor(s%60);
  return h?`${String(h).padStart(2,"0")}:${String(m).padStart(2,"0")}:${String(sec).padStart(2,"0")}`:`${String(m).padStart(2,"0")}:${String(sec).padStart(2,"0")}`;
}
function timeOf(value){
  try{return new Date(value).toLocaleTimeString("ru-RU",{hour:"2-digit",minute:"2-digit",second:"2-digit"})}catch{return "—"}
}
function eventHtml(e){
  const t=e.created_at?timeOf(e.created_at):new Date().toLocaleTimeString("ru-RU");
  return `<div class="event"><time>${t}</time><span>${escapeHtml(e.message||"Событие")}</span><b>${escapeHtml(e.event_type||"EVENT")}</b></div>`;
}
function escapeHtml(s){return String(s).replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]))}

async function refreshStatus(){
  try{
    const r=await fetch("/api/status"); const d=await r.json(); const x=d.runtime;
    $("#side-status").textContent=x.status; $("#side-action").textContent=x.current_action;
    $("#hero-status").textContent=x.status; $("#current-action").textContent=x.current_action;
    $("#observe-action").textContent=x.current_action; $("#version").textContent=`v${x.version}`;
    $("#cpu").textContent=`${Math.round(x.cpu_percent)}%`; $("#obs-cpu").textContent=`${Math.round(x.cpu_percent)}%`;
    $("#memory").textContent=`${x.memory_mb} MB`; $("#obs-ram").textContent=`${x.memory_mb} MB`;
    $("#uptime").textContent=formatUptime(x.uptime_seconds); $("#port").textContent=x.port;
    $("#python").textContent=x.python; $("#pid").textContent=x.pid;
    $("#db-state").textContent=d.database.exists?"READY":"INIT";
    $("#autostart").checked=!!d.settings.autostart;
  }catch(e){$("#side-status").textContent="Нет связи";$("#side-action").textContent="Ожидание ядра";}
}
async function refreshEvents(){
  try{
    const r=await fetch("/api/events?limit=160"); const d=await r.json(); lastEvents=d.events||[];
    $("#mini-events").innerHTML=lastEvents.slice(-5).reverse().map(eventHtml).join("")||'<div class="empty">Событий пока нет.</div>';
    $("#journal-events").innerHTML=lastEvents.slice().reverse().map(eventHtml).join("")||'<div class="empty">Событий пока нет.</div>';
    $("#live-events").innerHTML=lastEvents.slice(-30).reverse().map(eventHtml).join("")||'<div class="empty">Ожидание событий…</div>';
  }catch{}
}
function renderTests(d){
  $("#test-score").textContent=`${d.passed} / ${d.total} успешно`;
  $("#test-time").textContent=d.ok?"Система готова к работе.":"Есть проверки, требующие внимания.";
  const pct=d.total?Math.round(d.passed/d.total*100):0;
  $("#score-ring").style.background=`conic-gradient(var(--gold) ${pct}%,rgba(255,255,255,.06) 0)`;
  $("#score-ring span").textContent=`${pct}%`;
  $("#test-results").innerHTML=d.checks.map(c=>`<div class="test-row ${c.ok?"":"fail"}"><span class="check">${c.ok?"✓":"!"}</span><div><b>${escapeHtml(c.name)}</b><small>${escapeHtml(c.detail)}</small></div><span>${c.duration_ms} ms</span></div>`).join("");
}
async function runTests(mode){
  $("#test-score").textContent="Выполняется…"; toast(mode==="full"?"Полная диагностика запущена":"Быстрый тест запущен");
  try{
    const r=await fetch(`/api/tests/run?mode=${mode}`,{method:"POST",headers:actionHeaders,body:"{}"});
    renderTests(await r.json());
  }catch{toast("Не удалось запустить диагностику")}
}
async function post(url,body={}){
  const r=await fetch(url,{method:"POST",headers:actionHeaders,body:JSON.stringify(body)});
  if(!r.ok) throw new Error(await r.text()); return r.json();
}
function go(page){
  $$(".nav").forEach(x=>x.classList.toggle("active",x.dataset.page===page));
  $$(".page").forEach(x=>x.classList.toggle("active",x.id===`page-${page}`));
  history.replaceState(null,"",page==="overview"?location.pathname:`#${page}`);
}
$$(".nav").forEach(x=>x.addEventListener("click",()=>go(x.dataset.page)));
$$("[data-goto]").forEach(x=>x.addEventListener("click",()=>go(x.dataset.goto)));
$("#refresh").onclick=()=>{refreshStatus();refreshEvents();toast("Обновлено")};
$("#quick-test").onclick=()=>{go("tests");runTests("quick")};
$("#run-quick").onclick=()=>runTests("quick");
$("#run-full").onclick=()=>runTests("full");
$("#export-diagnostics").onclick=()=>{location.href="/api/diagnostics/export";toast("Диагностика экспортируется")};
$("#journal-refresh").onclick=refreshEvents;
$("#autostart").onchange=async e=>{try{const d=await post("/api/autostart",{enabled:e.target.checked});e.target.checked=d.enabled;toast(d.enabled?"Автозапуск включён":"Автозапуск отключён")}catch{e.target.checked=!e.target.checked;toast("Не удалось изменить автозапуск")}};
$("#restart-core").onclick=async()=>{try{await post("/api/system/restart");toast("Перезапуск запрошен")}catch{toast("Ошибка перезапуска")}};
$("#shutdown").onclick=async()=>{if(confirm("Полностью завершить Kohakuyasha?")){try{await post("/api/system/shutdown");toast("Завершение работы…")}catch{}}};

function connectEvents(){
  const scheme=location.protocol==="https:"?"wss":"ws"; const ws=new WebSocket(`${scheme}://${location.host}/ws/events`);
  ws.onmessage=e=>{try{const item=JSON.parse(e.data);lastEvents.push(item);if(lastEvents.length>200)lastEvents.shift();refreshEvents();refreshStatus()}catch{}};
  ws.onclose=()=>setTimeout(connectEvents,2000);
}
const initial=(location.hash||"#overview").slice(1); if(["overview","observe","tests","journal","settings"].includes(initial))go(initial);
refreshStatus();refreshEvents();connectEvents();setInterval(refreshStatus,1200);setInterval(refreshEvents,7000);
