"""Notifications: stored in SQLite, shown as a badge/bubble on the avatar and as cards in the chat.

A notification is data only: its actions are ids that the chat UI maps to existing, authenticated API calls
(e.g. "install" -> /api/update/install). Nothing is installed or executed because a notification arrived.
"""
from __future__ import annotations

import threading
from typing import Any, Callable

from . import prefs, updater
from .database import Database

UPDATE_ACTIONS = [
    {"id": "update_install", "label": "Установить", "primary": True},
    {"id": "update_details", "label": "Подробнее"},
    {"id": "dismiss", "label": "Позже"},
]


class Notifier:
    def __init__(self, db: Database, runtime: Any, events: Any) -> None:
        self.db, self.runtime, self.events = db, runtime, events

    def settings(self) -> prefs.AppSettings:
        return prefs.validate_app(self.db.get_setting("app"))

    def push(self, kind: str, title: str, body: str = "", actions: list[dict[str, Any]] | None = None, dedupe_key: str | None = None) -> dict[str, Any] | None:
        item = self.db.add_notification(kind, title, body, actions, dedupe_key)
        if item is None:
            return None
        self.events.emit(title, event_type="notification", payload={"id": item["id"], "kind": kind})
        toast = getattr(self.runtime, "toast", None)
        if toast and self.settings().toast:
            try:
                toast(title, body or title)
            except Exception:
                pass
        return item

    def update_available(self, info: dict[str, Any] | None, installed: str) -> dict[str, Any] | None:
        """One card per remote version; a newer version replaces the card about an older one."""
        if not isinstance(info, dict) or not info.get("remote") or not updater.is_newer(str(info["remote"]), installed):
            return None
        remote = str(info["remote"])
        notes = info.get("notes") if isinstance(info.get("notes"), list) else []
        summary = str(notes[0].get("summary", "")) if notes and isinstance(notes[0], dict) else ""
        body = f"Установлена v{installed}. " + (summary[:300] if summary else "Данные, настройки и ключи сохранятся, перед заменой создаётся резервная копия.")
        item = self.push("update", f"Доступно обновление v{remote}", body, UPDATE_ACTIONS, dedupe_key=f"update:{remote}")
        if item:  # an older card about this same topic is obsolete
            for old in self.db.list_notifications():
                if old["kind"] == "update" and old["id"] != item["id"]:
                    self.db.resolve_notification(old["id"])
        return item

    def update_installed(self, version: str, can_relaunch: bool) -> dict[str, Any] | None:
        self.db.resolve_notifications_by_prefix("update:")
        actions = [{"id": "restart", "label": "Перезапустить сейчас", "primary": True}, {"id": "dismiss", "label": "Позже"}] if can_relaunch else [{"id": "dismiss", "label": "Понятно"}]
        body = "Перезапустите Kohakuyasha, чтобы начать использовать новую версию." if can_relaunch else "Закройте Kohakuyasha (Настройки → Выход) и запустите Kohakuyasha.bat снова."
        return self.push("restart", f"Обновление v{version} установлено", body, actions, dedupe_key=f"restart:{version}")


class UpdateWatcher:
    """Checks GitHub in the background (only when auto-check is on) so the avatar can announce a release."""

    def __init__(self, check: Callable[[], None], interval: float = 6 * 3600, first_delay: float = 20) -> None:
        self.check, self.interval, self.first_delay = check, interval, first_delay
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="kohakuyasha-update-watch", daemon=True)

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _run(self) -> None:
        if self._stop.wait(self.first_delay):
            return
        while not self._stop.is_set():
            try:
                self.check()
            except Exception:
                pass
            if self._stop.wait(self.interval):
                return
