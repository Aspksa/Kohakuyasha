"""JUUNIBI: pre-speech actions and phrases that never repeat, with server-side generation of new actions.

The content pack lives in content/juunibi/ (data only). Used ids are stored in SQLite so a restart, a second
browser tab or a cleared browser cache cannot cause a repeat. When every action is used, a new one is requested
from the AI provider (key stays on the server), validated and saved; if that is impossible nothing is repeated.
"""
from __future__ import annotations

import json
import random
import re
import threading
import uuid
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path
from typing import Any

from . import ai
from .database import Database

ACTIONS_FILE = "JUUNIBI_365_cinematic_actions.json"
PHRASES_FILE = "JUUNIBI_452_phrases.json"
CHARACTER_FILE = "JUUNIBI_character_v1.json"
PHRASE_RECENT = 60
MAX_ATTEMPTS = 5
MIN_LEN, MAX_LEN = 55, 600
SIMILARITY_LIMIT = 0.42
# Calm categories that suit an unprompted remark; the rest (errors, alarms, work talk) only appear on demand.
AMBIENT_CATEGORIES = ("нежность", "забота", "игривость", "любопытство", "магия_хвосты", "покой_доверие", "похвала", "лисий юмор", "романтика дома")
GENERATION_TASK = (
    "Сгенерируй ОДНО новое короткое кинематографичное действие перед речью персонажа. Пиши по-русски от третьего лица, "
    "без имени персонажа, без реплик и прямой речи, без кавычек. Укажи жест, взгляд, ушки и хвосты, плавную кинематографичную "
    "динамику; 1–3 предложения, 150–350 знаков. Не повторяй идеи и формулировки примеров. Не описывай больше 12 хвостов. "
    "Верни только JSON с полями text, category, emotion, duration_seconds (число секунд от 3 до 7)."
)


class JuunibiError(Exception):
    """Russian, UI-safe reason why an action/phrase could not be produced."""


@dataclass(slots=True)
class JuunibiSettings:
    actions: bool = True    # stage direction shown by the avatar and in the chat before an answer
    phrases: bool = True    # the avatar greets with a phrase from the library
    ambient: bool = False   # occasional unprompted phrases while idle
    generate: bool = True   # ask the AI for a new action when all are used
    persona: bool = False   # use the JUUNIBI character profile in the assistant's prompt


def validate_settings(raw: Any) -> JuunibiSettings:
    raw = raw if isinstance(raw, dict) else {}
    d = JuunibiSettings()

    def flag(key: str) -> bool:
        v = raw.get(key)
        return v if isinstance(v, bool) else getattr(d, key)

    return JuunibiSettings(**{k: flag(k) for k in ("actions", "phrases", "ambient", "generate", "persona")})


# ---------- text similarity (same method as the reference selector) ----------
def normalized(text: str) -> str:
    return re.sub(r"[^а-яёa-z0-9]+", " ", str(text).lower()).strip()


def shingles(text: str) -> set[str]:
    words = normalized(text).split()
    return {" ".join(words[i : i + 3]) for i in range(max(0, len(words) - 2))}


def similarity(a: str, b: str) -> float:
    x, y = shingles(a), shingles(b)
    common = len(x & y)
    return common / max(1, len(x) + len(y) - common)


class Library:
    """Read-only content pack; `available` is False when the files are missing or malformed."""

    def __init__(self, directory: Path) -> None:
        self.directory = directory
        self.actions: list[dict[str, Any]] = []
        self.phrases: list[dict[str, Any]] = []
        self.character: dict[str, Any] = {}
        self.error = ""
        self._load()

    def _read(self, name: str) -> Any:
        return json.loads((self.directory / name).read_text(encoding="utf-8"))

    def _load(self) -> None:
        try:
            actions = self._read(ACTIONS_FILE)["actions"]
            phrases = self._read(PHRASES_FILE)["phrases"]
            self.character = self._read(CHARACTER_FILE)
        except (OSError, ValueError, KeyError, TypeError) as exc:
            self.error = f"Материалы JUUNIBI не найдены или повреждены ({type(exc).__name__})."
            return
        good = lambda x: isinstance(x, dict) and isinstance(x.get("id"), str) and isinstance(x.get("text"), str) and isinstance(x.get("category"), str)
        self.actions = [x for x in actions if good(x)]
        self.phrases = [x for x in phrases if good(x)]
        for items in (self.actions, self.phrases):
            if len({x["id"] for x in items}) != len(items):
                self.error = "В материалах JUUNIBI повторяются идентификаторы."
                self.actions, self.phrases = [], []
                return

    @property
    def available(self) -> bool:
        return bool(self.actions) and bool(self.phrases)

    def persona(self) -> dict[str, Any]:
        """Condensed profile for the system prompt (the full file is ~10 KB)."""
        c = self.character
        if not c:
            return {}
        pers, beh = c.get("personality", {}), c.get("behavior", {})
        return {
            "name": c.get("identity", {}).get("name", "JUUNIBI"),
            "identity": c.get("identity", {}),
            "character": pers.get("core_description", ""),
            "traits": [f"{t.get('name')}: {t.get('description')}" for t in pers.get("traits", []) if isinstance(t, dict)],
            "contrasts": pers.get("contrasts", []),
            "speaking_style": beh.get("speaking_style", {}),
            "principles": beh.get("principles", []),
            "contexts": beh.get("contexts", {}),
            "initiative": beh.get("initiative", {}),
            "examples": [e.get("text") for e in c.get("dialogue_examples", [])[:4] if isinstance(e, dict)],
            "motto": c.get("motto", ""),
        }


class Engine:
    def __init__(self, db: Database, library: Library) -> None:
        self.db, self.library = db, library
        self._gen_lock = threading.Lock()
        self.last_error = ""
        self._rng = random.Random()

    # ---------- actions ----------
    def all_actions(self) -> list[dict[str, Any]]:
        return [*self.library.actions, *self.db.juunibi_generated()]

    def categories(self) -> list[str]:
        return sorted({x["category"] for x in self.all_actions()})

    def validate(self, text: Any) -> str:
        """Return '' when the text is acceptable, otherwise the reason."""
        if not isinstance(text, str):
            return "нет текста"
        s = text.strip()
        if len(s) < MIN_LEN or len(s) > MAX_LEN:
            return f"длина {len(s)} знаков вне диапазона {MIN_LEN}–{MAX_LEN}"
        if re.search(r"juunibi|джууниби|«|»|\bговорит\b", s, re.I):
            return "содержит имя персонажа, кавычки или прямую речь"
        n = normalized(s)
        for a in self.all_actions():
            if n == normalized(a["text"]) or similarity(s, a["text"]) > SIMILARITY_LIMIT:
                return "слишком похоже на существующее действие"
        return ""

    def _pick_unused(self, category: str | None) -> dict[str, Any] | None:
        for _ in range(8):  # another request may claim the same item between the read and the claim
            used = self.db.juunibi_used_ids("action")
            pool = [a for a in self.all_actions() if a["id"] not in used]
            if category:
                pool = [a for a in pool if a["category"] == category]
            if not pool:
                return None
            last = self.db.juunibi_recent("action", 1)
            last_cat = next((a["category"] for a in self.all_actions() if last and a["id"] == last[0]), None)
            varied = [a for a in pool if a["category"] != last_cat] or pool  # avoid two moods in a row when possible
            choice = self._rng.choice(varied)
            if self.db.juunibi_mark("action", choice["id"], choice["category"]):
                return choice
        return None

    def next_action(self, settings: ai.AISettings, api_key: str, category: str | None = None, allow_generate: bool = True, context: str = "") -> dict[str, Any]:
        if not self.library.available:
            raise JuunibiError(self.library.error or "Материалы JUUNIBI не найдены.")
        if category and category not in self.categories():
            category = None
        picked = self._pick_unused(category) or (self._pick_unused(None) if category else None)
        if picked:
            return picked
        if not allow_generate:
            raise JuunibiError("Все действия использованы, а автогенерация выключена. Повтор не выполняется.")
        created = self.generate_action(settings, api_key, category, context)
        self.db.juunibi_mark("action", created["id"], created["category"])
        return created

    def generate_action(self, settings: ai.AISettings, api_key: str, category: str | None = None, context: str = "") -> dict[str, Any]:
        """Ask the provider for ONE new action; validated and saved (unused), or JuunibiError."""
        if settings.provider == "none" or not api_key:
            self.last_error = "Все действия использованы, а ИИ не подключён: новые создать нельзя. Повтор не выполняется."
            raise JuunibiError(self.last_error)
        with self._gen_lock:
            reason = ""
            for attempt in range(MAX_ATTEMPTS):
                try:
                    raw = ai.complete(self._gen_settings(settings), api_key, self._gen_system(), [{"role": "user", "content": self._gen_request(category, context, reason)}])
                except ai.AIError as exc:
                    self.last_error = f"Не удалось создать новое действие: {exc}. Повтор не выполняется."
                    raise JuunibiError(self.last_error) from None
                proposal = self._parse(raw, category)
                reason = self.validate(proposal["text"])
                if not reason:
                    item = {"id": f"JUA-GEN-{uuid.uuid4().hex[:12]}", **proposal, "tags": ["generated"]}
                    self.db.juunibi_add_generated(item)
                    self.last_error = ""
                    return item
            self.last_error = f"Не удалось получить подходящее новое действие за {MAX_ATTEMPTS} попыток ({reason}). Повтор не выполняется."
            raise JuunibiError(self.last_error)

    @staticmethod
    def _gen_settings(settings: ai.AISettings) -> ai.AISettings:
        # Short, creative, cheap: the fast model regardless of the chat model.
        return replace(settings, model=ai.DEFAULT_MODELS["cloudru"], max_tokens=400, temperature=0.95)

    @staticmethod
    def _gen_system() -> str:
        return "Ты пишешь сценические ремарки для персонажа-лисицы. Отвечай только JSON без пояснений."

    def _gen_request(self, category: str | None, context: str, rejected: str) -> str:
        cats = self.categories()
        pool = [a for a in self.all_actions() if not category or a["category"] == category]
        examples = self._rng.sample(pool, min(6, len(pool)))
        recent = [a["text"] for a in self.db.juunibi_generated()][-4:]
        lines = [GENERATION_TASK, f"Категории: {', '.join(cats)}."]
        if category:
            lines.append(f"Нужная категория: {category}.")
        if context:
            lines.append(f"Контекст: {context[:200]}")
        lines.append("Примеры стиля (не копируй):\n" + "\n".join(f"- {a['text']}" for a in [*examples, *({'text': t} for t in recent)]))
        if rejected:
            lines.append(f"Предыдущая попытка отклонена: {rejected}. Придумай другое.")
        return "\n\n".join(lines)

    def _parse(self, raw: str, category: str | None) -> dict[str, Any]:
        text = raw.strip()
        data: dict[str, Any] = {}
        m = re.search(r"\{.*\}", text, re.S)
        if m:
            try:
                parsed = json.loads(m.group(0))
                data = parsed if isinstance(parsed, dict) else {}
            except ValueError:
                data = {}
        body = data.get("text") if isinstance(data.get("text"), str) else re.sub(r"^```\w*|```$", "", text).strip()
        body = body.strip()
        if body and not body.startswith("*"):
            body = "*" + body.strip("* ") + "*"
        cats = self.categories()
        cat = data.get("category") if data.get("category") in cats else (category if category in cats else "тайна")
        emotion = data.get("emotion") if isinstance(data.get("emotion"), str) and 0 < len(data["emotion"]) <= 40 else cat
        dur = data.get("duration_seconds")
        dur = float(dur) if isinstance(dur, (int, float)) and not isinstance(dur, bool) else 4.5
        return {"text": body, "category": cat, "emotion": emotion, "duration_seconds": round(min(max(dur, 3.0), 7.0), 1)}

    # ---------- phrases (shuffle bag per category + global recent history) ----------
    def next_phrase(self, category: str | None = None) -> dict[str, Any]:
        if not self.library.available:
            raise JuunibiError(self.library.error or "Материалы JUUNIBI не найдены.")
        cats = sorted({p["category"] for p in self.library.phrases})
        if category == "auto":
            h = datetime.now().hour
            category = self._rng.choice(["приветствие", "утро" if 5 <= h < 12 else "вечер" if (h >= 18 or h < 4) else "приветствие"])
        elif category == "ambient":
            category = self._rng.choice([c for c in AMBIENT_CATEGORIES if c in cats] or cats)
        elif category not in cats:
            category = self._rng.choice(cats)
        for _ in range(8):
            used = self.db.juunibi_used_ids("phrase")
            pool = [p for p in self.library.phrases if p["category"] == category and p["id"] not in used]
            if not pool:  # bag exhausted: refill this category (fallback from the dataset's policy)
                self.db.juunibi_clear_category("phrase", category)
                recent = set(self.db.juunibi_recent("phrase", PHRASE_RECENT))
                pool = [p for p in self.library.phrases if p["category"] == category and p["id"] not in recent] or [p for p in self.library.phrases if p["category"] == category]
            else:
                recent = set(self.db.juunibi_recent("phrase", PHRASE_RECENT))
                pool = [p for p in pool if p["id"] not in recent] or pool
            choice = self._rng.choice(pool)
            if self.db.juunibi_mark("phrase", choice["id"], category):
                return choice
        raise JuunibiError("Не удалось выбрать реплику, попробуйте ещё раз.")

    # ---------- stats / reset ----------
    def stats(self) -> dict[str, Any]:
        actions = self.all_actions()
        used = self.db.juunibi_used_ids("action")
        return {
            "available": self.library.available, "error": self.library.error, "last_error": self.last_error,
            "actions_total": len(actions), "actions_used": len([a for a in actions if a["id"] in used]),
            "actions_unused": len([a for a in actions if a["id"] not in used]), "generated": len(self.db.juunibi_generated()),
            "phrases_total": len(self.library.phrases), "phrase_categories": len({p["category"] for p in self.library.phrases}),
            "categories": self.categories(),
        }

    def reset(self, scope: str) -> int:
        n = 0
        if scope in ("actions", "all"):
            n += self.db.juunibi_reset("action")
        if scope in ("phrases", "all"):
            n += self.db.juunibi_reset("phrase")
        return n
