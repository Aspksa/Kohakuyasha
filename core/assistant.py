from __future__ import annotations

NOT_CONNECTED = (
    "Я слышу вас, господин. Мой разум ещё не подключён к ИИ-провайдеру: "
    "сообщение сохранено и будет доступно мне, когда подключение появится."
)


def reply(text: str) -> str:
    """Extension point: replace with a real AI provider call. Currently reports honestly that none is connected."""
    return NOT_CONNECTED
