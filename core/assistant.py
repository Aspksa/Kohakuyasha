from __future__ import annotations

from typing import Any

from . import ai, brain

NOT_CONNECTED = (
    "Я слышу вас, господин. Мой разум ещё не подключён к ИИ-провайдеру: "
    "откройте личный кабинет (правый клик по аватару) → «ИИ» и вставьте API-ключ Cloud.ru."
)


def reply(
    settings: ai.AISettings,
    api_key: str,
    character: dict[str, Any],
    history: list[dict[str, Any]],
    memory: list[dict[str, Any]] | None = None,
    blocks: list[str] | None = None,
) -> str:
    """Answer one turn; complex requests get a guarded second-pass review."""
    if settings.provider == "none" or not api_key:
        return NOT_CONNECTED
    messages = ai.normalize_history([m for m in history if m.get("content") != NOT_CONNECTED])
    system = ai.build_system_prompt(settings, character, memory, blocks)
    draft = ai.complete(settings, api_key, system, messages)
    latest = messages[-1]["content"] if messages and messages[-1]["role"] == "user" else ""
    if brain.reasoning_mode(latest) != "deep":
        return draft

    review_prompt = (
        "Запрос пользователя:\n" + latest[:4000] + "\n\n"
        "Черновик ответа:\n" + draft[:12000]
    )
    review_system = system + "\n\n" + brain.REVIEW_SYSTEM
    try:
        return ai.complete(settings, api_key, review_system, [{"role": "user", "content": review_prompt}])
    except ai.AIError:
        return draft
