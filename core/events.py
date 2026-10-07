from __future__ import annotations

import asyncio
import logging
import threading
from datetime import datetime, timezone
from typing import Any

from .database import Database


class EventHub:
    def __init__(self, db: Database, logger: logging.Logger, limit: int = 5000) -> None:
        self.db = db
        self.logger = logger
        self.limit = limit
        self._subscribers: set[tuple[asyncio.AbstractEventLoop, asyncio.Queue]] = set()
        self._lock = threading.RLock()
        self._since_trim: int | None = None

    @staticmethod
    def _offer(queue: asyncio.Queue, event: dict[str, Any]) -> None:
        try:
            queue.put_nowait(event)
        except asyncio.QueueFull:
            try:
                queue.get_nowait()
                queue.put_nowait(event)
            except Exception:
                pass

    def emit(
        self,
        message: str,
        *,
        level: str = "INFO",
        source: str = "core",
        event_type: str = "event",
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        created_at = datetime.now(timezone.utc).isoformat()
        event_id = self.db.add_event(
            message,
            level=level,
            source=source,
            event_type=event_type,
            payload=payload,
            created_at=created_at,
        )
        getattr(self.logger, level.lower(), self.logger.info)("%s | %s | %s", source, event_type, message)
        event = {
            "id": event_id,
            "created_at": created_at,
            "level": level,
            "source": source,
            "event_type": event_type,
            "message": message,
            "payload": payload,
        }
        with self._lock:
            subscribers = list(self._subscribers)
        for loop, queue in subscribers:
            if not loop.is_closed():
                try:
                    loop.call_soon_threadsafe(self._offer, queue, event)
                except RuntimeError:
                    pass
        self._maybe_trim()
        return event

    TRIM_EVERY = 50

    def _maybe_trim(self) -> None:
        with self._lock:
            if self._since_trim is None or self._since_trim >= self.TRIM_EVERY:
                self._since_trim = 0
                due = True
            else:
                self._since_trim += 1
                due = False
        if due:
            self.db.trim_events(self.limit)

    def subscribe(self) -> tuple[asyncio.AbstractEventLoop, asyncio.Queue]:
        subscription = (asyncio.get_running_loop(), asyncio.Queue(maxsize=500))
        with self._lock:
            self._subscribers.add(subscription)
        return subscription

    def unsubscribe(self, subscription: tuple[asyncio.AbstractEventLoop, asyncio.Queue]) -> None:
        with self._lock:
            self._subscribers.discard(subscription)
