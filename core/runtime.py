from __future__ import annotations

import json
import os
import secrets
import socket
import sys
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

import psutil

from .config import Paths


@dataclass
class RuntimeState:
    paths: Paths
    version: str
    port: int = 0
    status: str = "Запуск"
    current_action: str = "Инициализация"
    safe_mode: bool = False
    watchdog_active: bool = False
    started_at: float = field(default_factory=time.time)
    last_test_summary: dict | None = None
    on_restart: Callable[[], None] | None = None
    on_shutdown: Callable[[], None] | None = None
    toast: Callable[[str, str], None] | None = None  # (title, message): Windows tray notification, set by the launcher
    session_token: str = field(default_factory=lambda: secrets.token_urlsafe(32), repr=False)

    def __post_init__(self) -> None:
        self._lock = threading.RLock()
        psutil.cpu_percent(interval=None)

    def set_status(self, status: str, action: str | None = None) -> None:
        with self._lock:
            self.status = status
            if action is not None:
                self.current_action = action
            self.persist()

    def persist(self) -> None:
        payload = {
            "pid": os.getpid(),
            "port": self.port,
            "status": self.status,
            "current_action": self.current_action,
            "started_at": datetime.fromtimestamp(self.started_at, timezone.utc).isoformat(),
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "version": self.version,
        }
        tmp = self.paths.runtime_state.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self.paths.runtime_state)

    def clear_persisted(self) -> None:
        self.paths.runtime_state.unlink(missing_ok=True)

    def snapshot(self) -> dict:
        with self._lock:
            process = psutil.Process(os.getpid())
            return {
                "version": self.version,
                "status": self.status,
                "current_action": self.current_action,
                "port": self.port,
                "uptime_seconds": max(0, int(time.time() - self.started_at)),
                "cpu_percent": psutil.cpu_percent(interval=None),
                "memory_mb": round(process.memory_info().rss / (1024 * 1024), 1),
                "system_memory_percent": psutil.virtual_memory().percent,
                "python": sys.version.split()[0],
                "pid": os.getpid(),
                "safe_mode": self.safe_mode,
                "watchdog_active": self.watchdog_active,
                "last_test_summary": self.last_test_summary,
            }


def find_free_port(host: str, preferred: int, span: int = 50) -> int:
    for port in range(preferred, preferred + span):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            try:
                sock.bind((host, port))
            except OSError:
                continue
            return port
    raise RuntimeError("Не найден свободный локальный порт.")


def port_is_open(host: str, port: int, timeout: float = 0.25) -> bool:
    try:
        with socket.create_connection((host, int(port)), timeout=timeout):
            return True
    except OSError:
        return False
