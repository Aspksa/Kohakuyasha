from __future__ import annotations

import asyncio
import logging
import threading
from typing import Any

from .database import Database


class EventHub:
    def __init__(self, db: Database, logger: logging.Logger, limit: int = 5000) -> None:
        self.db = db
        self.logger = logger
        self.limit = limit
        self._subscribers: set[tuple[asyncio.AbstractEventLoop, asyncio.Queue]] = set()
        self._lock = threading.RLock()

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
        event_id = self.db.add_event(
            message,
            level=level,
            source=source,
            event_type=event_type,
            payload=payload,
        )
        getattr(self.logger, level.lower(), self.logger.info)("%s | %s | %s", source, event_type, message)
        event = {
            "id": event_id,
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
        if event_id % 100 == 0:
            self.db.trim_events(self.limit)
        return event

    def subscribe(self) -> tuple[asyncio.AbstractEventLoop, asyncio.Queue]:
        subscription = (asyncio.get_running_loop(), asyncio.Queue(maxsize=500))
        with self._lock:
            self._subscribers.add(subscription)
        return subscription

    def unsubscribe(self, subscription: tuple[asyncio.AbstractEventLoop, asyncio.Queue]) -> None:
        with self._lock:
            self._subscribers.discard(subscription)
