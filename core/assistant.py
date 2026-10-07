from __future__ import annotations

from typing import Any

from . import ai

NOT_CONNECTED = (
    "Я слышу вас, господин. Мой разум ещё не подключён к ИИ-провайдеру: "
    "откройте личный кабинет (правый клик по аватару) → «ИИ», чтобы выбрать провайдера и указать ключ."
)


def reply(settings: ai.AISettings, api_key: str, character: dict[str, Any], history: list[dict[str, Any]]) -> str:
    """Answer the latest user message. Without a provider it reports honestly how to connect one."""
    if settings.provider == "none":
        return NOT_CONNECTED
    messages = ai.normalize_history([m for m in history if m.get("content") != NOT_CONNECTED])
    return ai.complete(settings, api_key, ai.build_system_prompt(settings, character), messages)
