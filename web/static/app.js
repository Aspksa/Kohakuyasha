const $ = q => document.querySelector(q);
const $$ = q => [...document.querySelectorAll(q)];
const actionHeaders = {"X-Kohakuyasha-Request":"1","Content-Type":"application/json"};
let lastEvents = [];
let autostartPending = false;

function toast(message){const el=$("#toast");el.textContent=message;el.classList.add("show");setTimeout(()=>el.classList.remove("show"),2400)}
function escapeHtml(s){return String(s).replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]))}
function formatUptime(s){s=Math.max(0,Number(s)||0);const h=Math.floor(s/3600),m=Math.floor((s%3600)/60),sec=Math.floor(s%60);return h?`${String(h).padStart(2,"0")}:${String(m).padStart(2,"0")}:${String(sec).padStart(2,"0")}`:`${String(m).padStart(2,"0")}:${String(sec).padStart(2,"0")}`}
function timeOf(value){try{return new Date(value).toLocaleTimeString("ru-RU",{hour:"2-digit",minute:"2-digit",second:"2-digit"})}catch{return "—"}}
function eventHtml(e){return `<div class="event"><time>${timeOf(e.created_at)}</time><span>${escapeHtml(e.message||"Событие")}</span><b>${escapeHtml(e.event_type||"EVENT")}</b></div>`}
async function apiFetch(url,options={}){const r=await fetch(url,{credentials:"same-origin",...options});if(r.status===401){location.reload();throw new Error("session expired")}return r}
function setService(id,value){$("#svc-"+id).textContent=value;const led=$("#led-"+id);led.classList.toggle("ok",["ONLINE","READY","LOCAL","ACTIVE"].includes(value))}

async function refreshStatus(){
  try{
    const r=await apiFetch("/api/status");if(!r.ok)throw new Error("status");const d=await r.json(),x=d.runtime;
    $("#side-status").textContent=x.status;$("#side-action").textContent=x.current_action;$("#hero-status").textContent=x.status;$("#current-action").textContent=x.current_action;$("#observe-action").textContent=x.current_action;
    $("#version").textContent=`v${x.version}`;$("#cpu").textContent=`${Math.round(x.cpu_percent)}%`;$("#obs-cpu").textContent=`${Math.round(x.cpu_percent)}%`;$("#memory").textContent=`${x.memory_mb} MB`;$("#obs-ram").textContent=`${x.memory_mb} MB`;$("#uptime").textContent=formatUptime(x.uptime_seconds);$("#port").textContent=x.port;$("#python").textContent=x.python;$("#pid").textContent=x.pid;
    setService("core",d.services.core);setService("db",d.services.database);setService("web",d.services.web);setService("watchdog",d.services.watchdog);$("#overall-state").textContent=d.services.core==="ONLINE"?"ONLINE":"ПРОВЕРКА";
    if(!autostartPending)$("#autostart").checked=!!d.settings.autostart;
  }catch{$("#side-status").textContent="Нет связи";$("#side-action").textContent="Ожидание ядра";$("#overall-state").textContent="OFFLINE"}
}
function renderEvents(){
  $("#mini-events").innerHTML=lastEvents.slice(-5).reverse().map(eventHtml).join("")||'<div class="empty">Событий пока нет.</div>';
  $("#journal-events").innerHTML=lastEvents.slice().reverse().map(eventHtml).join("")||'<div class="empty">Событий пока нет.</div>';
  $("#live-events").innerHTML=lastEvents.slice(-30).reverse().map(eventHtml).join("")||'<div class="empty">Ожидание событий…</div>';
}
async function refreshEvents(){try{const r=await apiFetch("/api/events?limit=120");if(!r.ok)return;lastEvents=(await r.json()).events||[];renderEvents()}catch{}}
function renderTests(d){$("#test-score").textContent=`${d.passed} / ${d.total} успешно`;$("#test-time").textContent=d.ok?"Система готова к работе.":"Есть проверки, требующие внимания.";const pct=d.total?Math.round(d.passed/d.total*100):0;$("#score-ring").style.background=`conic-gradient(var(--gold) ${pct}%,rgba(255,255,255,.06) 0)`;$("#score-ring span").textContent=`${pct}%`;$("#test-results").innerHTML=d.checks.map(c=>`<div class="test-row ${c.ok?"":"fail"}"><span class="check">${c.ok?"✓":"!"}</span><div><b>${escapeHtml(c.name)}</b><small>${escapeHtml(c.detail)}</small></div><span>${c.duration_ms} ms</span></div>`).join("")}
async function runTests(mode){$("#test-score").textContent="Выполняется…";toast(mode==="full"?"Полная диагностика запущена":"Быстрый тест запущен");try{const r=await apiFetch(`/api/tests/run?mode=${mode}`,{method:"POST",headers:actionHeaders,body:"{}"});renderTests(await r.json())}catch{toast("Не удалось запустить диагностику")}}
async function post(url,body={}){const r=await apiFetch(url,{method:"POST",headers:actionHeaders,body:JSON.stringify(body)});if(!r.ok)throw new Error(await r.text());return r.json()}
function go(page){$$('.nav').forEach(x=>x.classList.toggle("active",x.dataset.page===page));$$('.page').forEach(x=>x.classList.toggle("active",x.id===`page-${page}`));if(location.hash.slice(1)!==page)history.replaceState(null,"",page==="overview"?location.pathname:`#${page}`)}
$$('.nav').forEach(x=>x.addEventListener("click",()=>go(x.dataset.page)));$$('[data-goto]').forEach(x=>x.addEventListener("click",()=>go(x.dataset.goto)));
$("#refresh").onclick=()=>{refreshStatus();refreshEvents();toast("Обновлено")};$("#quick-test").onclick=()=>{go("tests");runTests("quick")};$("#run-quick").onclick=()=>runTests("quick");$("#run-full").onclick=()=>runTests("full");$("#export-diagnostics").onclick=()=>{location.href="/api/diagnostics/export"};$("#journal-refresh").onclick=refreshEvents;
$("#autostart").onchange=async e=>{const wanted=e.target.checked;autostartPending=true;e.target.disabled=true;try{const d=await post("/api/autostart",{enabled:wanted});e.target.checked=d.enabled;toast(d.enabled?"Автозапуск включён":"Автозапуск отключён")}catch{e.target.checked=!wanted;toast("Не удалось изменить автозапуск")}finally{autostartPending=false;e.target.disabled=false;refreshStatus()}};
$("#restart-core").onclick=async()=>{try{await post("/api/system/restart");toast("Перезапуск запрошен")}catch{toast("Ошибка перезапуска")}};$("#shutdown").onclick=async()=>{if(confirm("Полностью завершить Kohakuyasha?")){try{await post("/api/system/shutdown");toast("Завершение работы…")}catch{}}};
function connectEvents(){const scheme=location.protocol==="https:"?"wss":"ws",ws=new WebSocket(`${scheme}://${location.host}/ws/events`);ws.onmessage=e=>{try{const item=JSON.parse(e.data);lastEvents.push(item);if(lastEvents.length>200)lastEvents.shift();renderEvents()}catch{}};ws.onclose=()=>setTimeout(connectEvents,2500)}
function routeFromHash(){const page=(location.hash||"#overview").slice(1);go(["overview","observe","tests","journal","settings"].includes(page)?page:"overview")}
window.addEventListener("hashchange",routeFromHash);routeFromHash();refreshStatus();refreshEvents();connectEvents();setInterval(refreshStatus,3000);setInterval(refreshEvents,30000);
