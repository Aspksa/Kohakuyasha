"""Assistant 'brain': long-term facts, rolling summary, time awareness and prompt context assembly.

Memory here is retrieval + distillation, not model training: the provider is asked to distil durable facts and
a rolling summary, everything is stored locally in SQLite, and the relevant parts are injected into each request.
"""
from __future__ import annotations

import dataclasses
import json
import re
import threading
from datetime import datetime
from typing import Any, Callable

from . import ai
from .database import Database
from .prefs import MemorySettings

WORD_RE = re.compile(r"\w+", re.UNICODE)
REMEMBER_RE = re.compile(r"^\s*(запомни|запиши|не забудь|remember)\b[\s:,.-]*(.*)$", re.IGNORECASE | re.DOTALL)
WEEKDAYS = ["понедельник", "вторник", "среда", "четверг", "пятница", "суббота", "воскресенье"]
MONTHS = ["января", "февраля", "марта", "апреля", "мая", "июня", "июля", "августа", "сентября", "октября", "ноября", "декабря"]
MAX_FACTS = 500
SUMMARY_TRIGGER = 40      # unsummarised messages before the older ones are folded into the summary
SUMMARY_KEEP = 20         # most recent messages always kept verbatim
HISTORY_WINDOW = 30
SUMMARY_LIMIT = 1500
_lock = threading.Lock()


# ---------- text helpers ----------
def tokens(text: str) -> set[str]:
    """Words of 3+ letters reduced to a 5-letter stem (crude but good enough for Russian inflection)."""
    return {w[:5] for w in (m.lower() for m in WORD_RE.findall(text or "")) if len(w) >= 3}


def similarity(a: str, b: str) -> float:
    """Token overlap; a short fact fully contained in a longer one (>= 2 words) counts as the same fact."""
    ta, tb = tokens(a), tokens(b)
    if not ta or not tb:
        return 0.0
    inter = len(ta & tb)
    containment = inter / min(len(ta), len(tb)) if min(len(ta), len(tb)) >= 2 else 0.0
    return max(inter / len(ta | tb), containment * 0.9)


def explicit_remember(text: str) -> str | None:
    """'Запомни: я живу в Казани' -> 'я живу в Казани'. None when the message is not such a command."""
    m = REMEMBER_RE.match(text or "")
    return m.group(2).strip() if m and m.group(2).strip() else None


DEEP_MARKERS = (
    "проанализ", "сравни", "разбер", "архитект", "спроект", "план", "стратег", "почему", "докажи",
    "исправ", "ошиб", "баг", "код", "рефактор", "оптимиз", "безопас", "алгоритм", "математ",
    "analy", "compare", "debug", "architect", "refactor", "optimiz", "strategy", "prove", "algorithm",
)
COGNITION_FAST = (
    "Режим мышления: быстрый. Сначала определи реальную цель пользователя, затем дай прямой ответ. "
    "Не повторяй очевидный контекст и не перегружай ответ лишними оговорками."
)
COGNITION_DEEP = (
    "Режим мышления: глубокий. Перед ответом молча разложи задачу на части, проверь ограничения, зависимости, "
    "противоречия и граничные случаи. Для технических задач сначала найди первопричину, затем предложи минимально "
    "достаточное и проверяемое решение. Отделяй известное от предположений, не выдумывай факты. "
    "Не показывай скрытую цепочку рассуждений: пользователю дай выводы, ключевые причины и конкретные действия."
)
REVIEW_SYSTEM = (
    "Ты финальный редактор ответа Kohakuyasha. Проверь черновик на фактические ошибки, пропущенные ограничения, "
    "внутренние противоречия и неисполненные части запроса. Сохрани правильные части и стиль. "
    "Верни только улучшенный финальный ответ без анализа процесса, без упоминания черновика и без скрытой цепочки рассуждений."
)


CONSTRAINT_MARKERS = (
    "долж", "нужно", "надо", "обяз", "только", "не ", "без ", "нельзя", "миним", "максим",
    "must", "need", "only", "without", "never", "do not", "don't", "minimum", "maximum",
)
NEGATION_MARKERS = ("не ", "нет ", "никогда", "перестал", "перестала", "не любит", "не хочет")


def working_memory_block(query: str, history: list[dict[str, Any]] | None = None, limit_chars: int = 1400) -> str:
    """Keep the current goal and recent explicit constraints visible without another model call."""
    current = (query or "").strip()
    if not current:
        return ""
    lines = [f"Текущая цель пользователя: {current[:700]}"]
    seen = {current}
    constraints: list[str] = []
    for item in reversed(history or []):
        if item.get("role") != "user":
            continue
        text = str(item.get("content") or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        low = text.lower()
        if any(marker in low for marker in CONSTRAINT_MARKERS):
            constraints.append(text[:350])
        if len(constraints) >= 3:
            break
    if constraints:
        lines.append("Актуальные ограничения из недавних сообщений:")
        lines.extend(f"- {x}" for x in reversed(constraints))
    return "\n".join(lines)[:limit_chars]


def _strip_negation(text: str) -> str:
    out = " " + (text or "").lower().strip() + " "
    for marker in NEGATION_MARKERS:
        out = out.replace(" " + marker, " ")
    return " ".join(out.split())


def memory_conflicts(facts: list[dict[str, Any]], limit: int = 3) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    """Find likely contradictory near-duplicate facts so the model does not silently trust both."""
    pairs: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for i, a in enumerate(facts):
        atext = str(a.get("text", ""))
        aneg = any(m in atext.lower() for m in NEGATION_MARKERS)
        for b in facts[i + 1:]:
            if a.get("category") != b.get("category"):
                continue
            btext = str(b.get("text", ""))
            bneg = any(m in btext.lower() for m in NEGATION_MARKERS)
            if aneg == bneg:
                continue
            if similarity(_strip_negation(atext), _strip_negation(btext)) >= 0.6:
                pairs.append((a, b))
                if len(pairs) >= limit:
                    return pairs
    return pairs


def format_conflicts(pairs: list[tuple[dict[str, Any], dict[str, Any]]]) -> str:
    if not pairs:
        return ""
    lines = ["В памяти есть возможные противоречия. Не смешивай их и не угадывай; при необходимости опирайся на более свежую реплику пользователя:"]
    for a, b in pairs:
        lines.append(f"- «{a.get('text', '')}» ↔ «{b.get('text', '')}»")
    return "\n".join(lines)


def reasoning_mode(query: str) -> str:
    """Cheap local router: use deep mode only for genuinely complex requests."""
    text = (query or "").strip().lower()
    if not text:
        return "fast"
    score = 0
    if len(text) >= 220:
        score += 1
    if text.count("\n") >= 2 or (chr(96) * 3) in text:
        score += 1
    marker_hits = sum(1 for marker in DEEP_MARKERS if marker in text)
    score += min(marker_hits, 2)
    if len(text.split()) >= 14:
        score += 1
    if text.count("?") >= 2:
        score += 1
    if any(marker in text for marker in ("{", "}", "=>", "==", "::", "->")):
        score += 1
    return "deep" if score >= 2 else "fast"


def cognition_block(query: str) -> str:
    return COGNITION_DEEP if reasoning_mode(query) == "deep" else COGNITION_FAST


def contextual_query(query: str, history: list[dict[str, Any]] | None = None, limit_chars: int = 1200) -> str:
    """Expand only likely follow-ups; independent new topics must not inherit unrelated recent turns."""
    current = query.strip() if isinstance(query, str) else ""
    parts = [current] if current else []
    lowered = current.lower()
    followup_markers = ("а ", "и ", "но ", "она", "он ", "они", "это", "там", "тот ", "та ", "те ", "ещё", "теперь", "продолж")
    likely_followup = len(tokens(current)) <= 7 or any(lowered.startswith(marker) for marker in followup_markers)
    if not likely_followup:
        return current[:limit_chars]
    for item in reversed(history or []):
        if item.get("role") != "user":
            continue
        text = item.get("content")
        if not isinstance(text, str) or not text.strip() or text.strip() == current:
            continue
        parts.append(text.strip()[:400])
        if len(parts) >= 3:
            break
    return "\n".join(parts)[:limit_chars]


# ---------- selecting and formatting context ----------
def select_facts(facts: list[dict[str, Any]], query: str, limit: int = 12, now: datetime | None = None) -> list[dict[str, Any]]:
    """Rank memory by relevance first; pinned facts survive, unrelated facts stop flooding prompts."""
    q, now = tokens(query), now or datetime.now().astimezone()
    pinned: list[tuple[float, dict[str, Any]]] = []
    relevant: list[tuple[float, dict[str, Any]]] = []
    background: list[tuple[float, dict[str, Any]]] = []
    for f in facts:
        text = str(f.get("text", ""))
        ft = tokens(text)
        overlap = len(q & ft)
        coverage = overlap / max(1, len(q)) if q else 0.0
        related = similarity(query, text) if q else 0.0
        try:
            days = max(0.0, (now - datetime.fromisoformat(f["updated_at"])).total_seconds() / 86400)
        except (ValueError, KeyError, TypeError):
            days = 365.0
        recency = 1.0 / (1.0 + days / 30.0)
        use_bonus = min(int(f.get("use_count", 0) or 0), 20) * 0.04
        score = overlap * 4.0 + coverage * 3.0 + related * 4.0 + float(f.get("importance", 3)) * 0.7 + recency + use_bonus
        if f.get("pinned"):
            pinned.append((score + 20.0, f))
        elif not q or overlap or related >= 0.28:
            relevant.append((score, f))
        else:
            background.append((score, f))
    pinned.sort(key=lambda x: x[0], reverse=True)
    relevant.sort(key=lambda x: x[0], reverse=True)
    background.sort(key=lambda x: x[0], reverse=True)
    chosen = [f for _, f in pinned[:limit]]
    remaining = limit - len(chosen)
    chosen.extend(f for _, f in relevant[:remaining])
    remaining = limit - len(chosen)
    if remaining > 0:
        chosen.extend(f for _, f in background[:min(2, remaining)])
    return chosen


def format_facts(facts: list[dict[str, Any]], limit_chars: int = 1800) -> str:
    lines, used = [], 0
    for f in facts:
        line = f"- {f['text']}"
        if used + len(line) > limit_chars:
            break
        lines.append(line); used += len(line)
    return ("Что ты знаешь о пользователе (он сам это сообщал):\n" + "\n".join(lines)) if lines else ""


def format_now(now: datetime) -> str:
    return f"Сейчас: {WEEKDAYS[now.weekday()]}, {now.day} {MONTHS[now.month - 1]} {now.year}, {now:%H:%M}."


GUIDELINES = (
    "Используй сведения выше естественно, как помощник, который давно знает пользователя: не перечисляй их без нужды "
    "и не выдумывай того, чего в них нет. Если сказанное сейчас противоречит памяти, верь пользователю. "
    "Если он просит что-то запомнить, коротко подтверди."
)


def build_context(
    db: Database,
    mem: MemorySettings,
    query: str,
    now: datetime | None = None,
    history: list[dict[str, Any]] | None = None,
) -> tuple[list[str], list[int]]:
    """Compile the working context for one turn."""
    now = now or datetime.now()
    expanded_query = contextual_query(query, history)
    blocks = [format_now(now), cognition_block(query)]
    working = working_memory_block(query, history)
    if working:
        blocks.append(working)
    used: list[int] = []
    if mem.use_facts:
        all_facts = db.list_facts(MAX_FACTS)
        chosen = select_facts(all_facts, expanded_query)
        text = format_facts(chosen)
        if text:
            blocks.append(text)
            used = [f["id"] for f in chosen]
        conflicts = format_conflicts(memory_conflicts(chosen))
        if conflicts:
            blocks.append(conflicts)
    if mem.use_summary:
        summary = (db.get_setting("memory_state", {}) or {}).get("summary", "")
        if summary:
            blocks.append("Краткое содержание более ранней части вашего общения:\n" + summary)
    if len(blocks) > 2:
        blocks.append(GUIDELINES)
    return blocks, used


def history_window(db: Database, mem: MemorySettings) -> list[dict[str, Any]]:
    """Recent chat messages not yet folded into the summary."""
    state = db.get_setting("memory_state", {}) or {}
    after = int(state.get("summary_upto", 0)) if mem.use_summary and state.get("summary") else 0
    return db.chat_after(after, 1000)[-HISTORY_WINDOW:]


# ---------- extraction ----------
EXTRACT_SYSTEM = (
    "Ты модуль долговременной памяти личного помощника. По фрагменту диалога выпиши только устойчивые факты о ПОЛЬЗОВАТЕЛЕ, "
    "которые он сам сообщил: имя, семья и близкие, питомцы, место жительства, работа и проекты, предпочтения и привычки, "
    "планы и договорённости, важные даты. Не записывай болтовню, вопросы, слова ассистента и временные состояния. "
    "Каждый факт — одно короткое предложение на русском в третьем лице (например: «Любит чай с лимоном»). Не больше 5 фактов. "
    'Ответь СТРОГО JSON без пояснений: {"facts":[{"text":"...","category":"personal|preference|relation|project|schedule|other","importance":1-5}]}. '
    'Если запоминать нечего — {"facts":[]}.'
)


def transcript(messages: list[dict[str, Any]], per_message: int = 800, total: int = 6000) -> str:
    names = {"user": "Пользователь", "assistant": "Ассистент"}
    out, used = [], 0
    for m in messages:
        line = f"{names.get(m['role'], m['role'])}: {str(m['content'])[:per_message]}"
        if used + len(line) > total:
            break
        out.append(line); used += len(line)
    return "\n".join(out)


def parse_facts_json(text: str) -> list[dict[str, Any]]:
    """Tolerant parser: code fences, text around the JSON, a bare list or an object with 'facts'."""
    text = (text or "").strip()
    text = re.sub(r"^```(?:json)?|```$", "", text, flags=re.MULTILINE).strip()
    candidates = [text]
    first, last = text.find("{"), text.rfind("}")
    if 0 <= first < last:
        candidates.append(text[first:last + 1])
    first, last = text.find("["), text.rfind("]")
    if 0 <= first < last:
        candidates.append(text[first:last + 1])
    data: Any = None
    for c in candidates:
        try:
            data = json.loads(c); break
        except ValueError:
            continue
    items = data.get("facts") if isinstance(data, dict) else data
    out: list[dict[str, Any]] = []
    for it in items if isinstance(items, list) else []:
        raw = it if isinstance(it, str) else (it.get("text") if isinstance(it, dict) else None)
        if not isinstance(raw, str) or not 3 <= len(raw.strip()) <= 300:
            continue
        cat = it.get("category") if isinstance(it, dict) else "other"
        imp = it.get("importance") if isinstance(it, dict) else 3
        out.append({
            "text": raw.strip(),
            "category": cat if cat in Database.FACT_CATEGORIES else "other",
            "importance": imp if isinstance(imp, int) and not isinstance(imp, bool) and 1 <= imp <= 5 else 3,
        })
    return out[:5]


def _light(settings: ai.AISettings, tokens_limit: int) -> ai.AISettings:
    return dataclasses.replace(settings, max_tokens=tokens_limit, temperature=None)


def extract_facts(settings: ai.AISettings, key: str, messages: list[dict[str, Any]], existing: list[str], explicit: str | None = None) -> list[dict[str, Any]]:
    known = "\n".join(f"- {t}" for t in existing[:40]) or "(пока ничего)"
    hint = f"\nПользователь прямо просит запомнить: «{explicit}». Обязательно сохрани это с importance 5.\n" if explicit else ""
    prompt = f"Уже известные факты (не дублируй):\n{known}\n{hint}\nФрагмент диалога:\n{transcript(messages)}"
    answer = ai.complete(_light(settings, 700), key, EXTRACT_SYSTEM, [{"role": "user", "content": prompt}])
    return parse_facts_json(answer)


def store_facts(db: Database, facts: list[dict[str, Any]], source: str = "auto") -> tuple[int, int]:
    """Insert new facts; near-duplicates (token overlap >= 0.6) refresh the existing fact instead."""
    existing = db.list_facts(MAX_FACTS)
    added = updated = 0
    for f in facts:
        match = max(existing, key=lambda e: similarity(e["text"], f["text"]), default=None)
        if match is not None and similarity(match["text"], f["text"]) >= 0.6:
            changes: dict[str, Any] = {"importance": max(match["importance"], f["importance"])}
            if len(f["text"]) > len(match["text"]) and not match["pinned"] and match["source"] == "auto":
                changes["text"] = f["text"]
            db.update_fact(match["id"], **changes)
            updated += 1
        else:
            fid = db.add_fact(f["text"], f["category"], f["importance"], source)
            existing.append({"id": fid, "text": f["text"], "importance": f["importance"], "pinned": False, "source": source})
            added += 1
    db.trim_facts(MAX_FACTS)
    return added, updated


# ---------- summary ----------
SUMMARY_SYSTEM = (
    "Ты сжимаешь переписку помощника с пользователем в краткое содержание на русском (до 1200 символов). Сохрани имена, решения, "
    "договорённости, незавершённые дела и важные детали; убери болтовню. Верни только текст содержания, без вступлений."
)


def summarize(settings: ai.AISettings, key: str, previous: str, messages: list[dict[str, Any]]) -> str:
    prompt = (f"Предыдущее содержание:\n{previous}\n\n" if previous else "") + "Новые сообщения:\n" + transcript(messages, 600, 9000)
    return ai.complete(_light(settings, 700), key, SUMMARY_SYSTEM, [{"role": "user", "content": prompt}])[:SUMMARY_LIMIT]


# ---------- maintenance (runs after a reply, never blocks it) ----------
def run_maintenance(
    db: Database, settings: ai.AISettings, key: str, mem: MemorySettings,
    *, force: bool = False, explicit: str | None = None, notify: Callable[[str, str], None] | None = None,
) -> dict[str, Any]:
    result: dict[str, Any] = {"added": 0, "updated": 0, "summarized": False, "error": None, "busy": False, "texts": []}
    if not _lock.acquire(blocking=False):
        result["busy"] = True
        return result
    try:
        state = dict(db.get_setting("memory_state", {}) or {})
        try:
            pending = db.chat_after(int(state.get("extracted_upto", 0)), 200)
            users = [m for m in pending if m["role"] == "user"]
            if (mem.auto_facts or force or explicit) and pending and (force or explicit or len(users) >= mem.extract_every):
                found = extract_facts(settings, key, pending[-20:], [f["text"] for f in db.list_facts(40)], explicit)
                if not found and explicit:  # the model returned nothing for an explicit command: keep the user's words
                    found = [{"text": explicit[:300], "category": "other", "importance": 5}]
                result["added"], result["updated"] = store_facts(db, found)
                result["texts"] = [f["text"] for f in found]
                state["extracted_upto"] = pending[-1]["id"]
                if notify and (result["added"] or result["updated"]):
                    notify("INFO", f"Память: новых фактов {result['added']}, обновлено {result['updated']}")
            if mem.use_summary:
                after = int(state.get("summary_upto", 0))
                unsummarised = db.chat_after(after, 1000)
                if len(unsummarised) > SUMMARY_TRIGGER:
                    old = unsummarised[:-SUMMARY_KEEP]
                    state["summary"] = summarize(settings, key, state.get("summary", ""), old)
                    state["summary_upto"] = old[-1]["id"]
                    result["summarized"] = True
                    if notify:
                        notify("INFO", "Память: обновлено краткое содержание беседы")
        except ai.AIError as exc:
            result["error"] = str(exc)
            if notify:
                notify("WARNING", f"Память: не удалось обработать ({exc})")
        finally:
            db.set_setting("memory_state", state)
        return result
    finally:
        _lock.release()
