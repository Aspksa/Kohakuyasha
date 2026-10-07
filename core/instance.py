"""Single-instance lock and the waiting logic used when Kohakuyasha is relaunched (for example after an update)."""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Callable

import psutil

from .config import Paths
from .runtime import port_is_open

STOPPING = "Остановка"


class InstanceLock:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.handle = None

    def acquire(self) -> bool:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        handle = open(self.path, "a+b")
        try:
            if self.path.stat().st_size == 0:
                handle.write(b"0")
                handle.flush()
            if os.name == "nt":
                import msvcrt
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except (OSError, IOError):
            handle.close()  # do not leak a handle for every failed attempt
            return False
        self.handle = handle
        return True

    def release(self) -> None:
        if not self.handle:
            return
        try:
            if os.name == "nt":
                import msvcrt
                self.handle.seek(0)
                msvcrt.locking(self.handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.handle.fileno(), fcntl.LOCK_UN)
        except Exception:
            pass
        self.handle.close()
        self.handle = None


def read_runtime(paths: Paths) -> dict[str, Any] | None:
    try:
        data = json.loads(paths.runtime_state.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except (OSError, ValueError):
        return None


def holder_is_healthy(paths: Paths) -> bool:
    """True when another instance is up and serving (and not in the middle of shutting down)."""
    data = read_runtime(paths)
    if not data or data.get("status") == STOPPING:
        return False
    try:
        return psutil.pid_exists(int(data["pid"])) and port_is_open("127.0.0.1", int(data["port"]))
    except (KeyError, TypeError, ValueError):
        return False


def acquire_or_wait(
    lock: InstanceLock | Any,
    paths: Paths,
    *,
    timeout: float = 30.0,
    interval: float = 0.5,
    healthy: Callable[[Paths], bool] = holder_is_healthy,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> str:
    """'acquired' | 'running' (a healthy instance owns the lock) | 'timeout'.

    A previous instance that is still shutting down (after Restart or an update) holds the lock for a few seconds;
    waiting for it is what makes a relaunch reliable instead of exiting as "already running".
    """
    deadline = clock() + timeout
    while True:
        if lock.acquire():
            return "acquired"
        if healthy(paths):
            return "running"
        if clock() >= deadline:
            return "timeout"
        sleep(interval)
