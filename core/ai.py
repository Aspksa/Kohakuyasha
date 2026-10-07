from __future__ import annotations

import json
import os
import threading
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from .prefs import _bool, _choice, _int

PROVIDERS = ("none", "cloudru")
# Cloud.ru Evolution Foundation Models: OpenAI-compatible chat completions. Model ids follow the catalog naming (vendor/Model).
DEFAULT_MODELS = {"cloudru": "deepseek-ai/DeepSeek-V4-Flash"}
DEFAULT_BASE_URLS = {"cloudru": "https://foundation-models.api.cloud.ru/v1"}
MODEL_SUGGESTIONS = {
    "cloudru": [
        {"id": "deepseek-ai/DeepSeek-V4-Flash", "name": "DeepSeek V4 Flash", "hint": "быстрая и дешёвая"},
        {"id": "deepseek-ai/DeepSeek-V4-Pro", "name": "DeepSeek V4 Pro", "hint": "максимальное качество"},
    ]
}
TIMEOUT_SECONDS = 60
MAX_PROMPT_CHARS = 8000


class AIError(Exception):
    """Human-readable (Russian) provider failure that is safe to show in the UI."""


@dataclass(slots=True)
class AISettings:
    provider: str = "cloudru"
    model: str = ""
    base_url: str = ""
    temperature: float | None = None
    max_tokens: int = 1024
    system_prompt: str = ""
    use_character: bool = True


def _text(value: Any, default: str, limit: int) -> str:
    return value.strip()[:limit] if isinstance(value, str) else default


def validate_base_url(value: Any) -> str:
    text = _text(value, "", 300).rstrip("/")
    if not text:
        return ""
    parts = urlsplit(text)
    if parts.scheme not in {"http", "https"} or not parts.hostname:
        return ""
    return text


def validate_ai(raw: dict[str, Any] | None) -> AISettings:
    raw = raw if isinstance(raw, dict) else {}
    d = AISettings()
    temperature = raw.get("temperature")
    if isinstance(temperature, bool) or not isinstance(temperature, (int, float)):
        temperature = None
    else:
        temperature = round(min(max(float(temperature), 0.0), 1.0), 2)
    return AISettings(
        provider=_choice(raw.get("provider"), PROVIDERS, d.provider),
        model=_text(raw.get("model"), d.model, 120),
        base_url=validate_base_url(raw.get("base_url")),
        temperature=temperature,
        max_tokens=_int(raw.get("max_tokens"), d.max_tokens, 64, 8192),
        system_prompt=_text(raw.get("system_prompt"), d.system_prompt, MAX_PROMPT_CHARS),
        use_character=_bool(raw.get("use_character"), d.use_character),
    )


def public_ai(settings: AISettings, secrets: "SecretStore") -> dict[str, Any]:
    data = asdict(settings)
    data["has_key"] = secrets.has_key()
    data["key_hint"] = secrets.hint()
    data["defaults"] = {"model": DEFAULT_MODELS["cloudru"], "base_url": DEFAULT_BASE_URLS["cloudru"], "suggestions": MODEL_SUGGESTIONS["cloudru"]}
    return data


class SecretStore:
    """API key lives only in data/secrets.json (git-ignored). It is never returned by the API or logged."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self._lock = threading.Lock()

    def _read(self) -> dict[str, str]:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    def get_key(self) -> str:
        value = self._read().get("api_key")
        return value if isinstance(value, str) else ""

    def has_key(self) -> bool:
        return bool(self.get_key())

    def hint(self) -> str:
        key = self.get_key()
        return f"…{key[-4:]}" if len(key) >= 8 else ("…" if key else "")

    def set_key(self, key: str) -> None:
        key = key.strip()
        if not key or len(key) > 500 or any(ch.isspace() for ch in key):
            raise ValueError("Некорректный ключ.")
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps({"api_key": key}), encoding="utf-8")
            try:
                os.chmod(tmp, 0o600)
            except OSError:
                pass
            tmp.replace(self.path)

    def delete_key(self) -> None:
        with self._lock:
            self.path.unlink(missing_ok=True)


def format_memory(snippets: list[dict[str, Any]], limit_chars: int = 3000) -> str:
    names = {"user": "пользователь", "assistant": "ассистент", "note": "заметка"}
    lines, used = [], 0
    for item in snippets:
        line = f"- [{item.get('title', 'чат')} · {names.get(item.get('role'), 'запись')}] {str(item.get('content', ''))[:500]}"
        if used + len(line) > limit_chars:
            break
        lines.append(line)
        used += len(line)
    if not lines:
        return ""
    return (
        "Релевантные фрагменты из памяти (прошлые диалоги и заметки пользователя). Используй их как контекст, "
        "если они уместны, и не выдумывай того, чего в них нет:\n" + "\n".join(lines)
    )


def build_system_prompt(settings: AISettings, character: dict[str, Any], memory: list[dict[str, Any]] | None = None) -> str:
    parts: list[str] = []
    if settings.use_character and character:
        parts.append(
            "Ты — персонаж личного помощника. Строго соблюдай этот образ и отвечай по-русски, "
            "если пользователь не просит иначе. Профиль персонажа (JSON): "
            + json.dumps(character, ensure_ascii=False)
        )
    if settings.system_prompt:
        parts.append(settings.system_prompt)
    mem = format_memory(memory or [])
    if mem:
        parts.append(mem)
    return "\n\n".join(parts)


def normalize_history(history: list[dict[str, Any]], limit: int = 30) -> list[dict[str, str]]:
    """Providers require alternating roles starting with 'user': merge repeats, drop leading assistant turns."""
    merged: list[dict[str, str]] = []
    for item in history[-limit:]:
        role, text = item.get("role"), item.get("content")
        if role not in ("user", "assistant") or not isinstance(text, str) or not text:
            continue
        if merged and merged[-1]["role"] == role:
            merged[-1]["content"] += "\n\n" + text
        else:
            merged.append({"role": role, "content": text})
    while merged and merged[0]["role"] != "user":
        merged.pop(0)
    return merged


def _http_post_json(url: str, headers: dict[str, str], body: dict[str, Any]) -> dict[str, Any]:
    req = urllib.request.Request(
        url, data=json.dumps(body).encode("utf-8"), headers={"Content-Type": "application/json", **headers}, method="POST"
    )
    with urllib.request.urlopen(req, timeout=TIMEOUT_SECONDS) as response:
        return json.loads(response.read().decode("utf-8"))


def complete(settings: AISettings, api_key: str, system: str, messages: list[dict[str, str]]) -> str:
    if settings.provider != "cloudru":
        raise AIError("ИИ отключён в настройках.")
    if not messages:
        raise AIError("Нет сообщений для отправки.")
    if not api_key:
        raise AIError("API-ключ не задан.")
    model = settings.model or DEFAULT_MODELS["cloudru"]
    base = settings.base_url or DEFAULT_BASE_URLS["cloudru"]
    msgs = ([{"role": "system", "content": system}] if system else []) + messages
    body: dict[str, Any] = {"model": model, "max_tokens": settings.max_tokens, "messages": msgs}
    if settings.temperature is not None:
        body["temperature"] = settings.temperature
    try:
        data = _http_post_json(f"{base}/chat/completions", {"Authorization": f"Bearer {api_key}"}, body)
        text = data["choices"][0]["message"]["content"] or ""
    except urllib.error.HTTPError as exc:
        try:
            detail = exc.read().decode("utf-8", "replace")[:300]
        except Exception:
            detail = ""
        detail = detail.replace(api_key, "***")
        raise AIError(f"Cloud.ru вернул ошибку {exc.code}. {detail}".strip()) from None
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise AIError(f"Нет связи с Cloud.ru: {getattr(exc, 'reason', exc)}") from None
    except (ValueError, KeyError, IndexError, TypeError):
        raise AIError("Cloud.ru вернул неожиданный ответ.") from None
    text = text.strip()
    if not text:
        raise AIError("Cloud.ru вернул пустой ответ.")
    return text
