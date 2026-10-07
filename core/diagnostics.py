from __future__ import annotations

import os
import socket
import sys
import tempfile
import time
import urllib.request
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Callable

from .database import Database


@dataclass(slots=True)
class CheckResult:
    name: str
    ok: bool
    duration_ms: int
    detail: str

    def as_dict(self) -> dict:
        return asdict(self)


class Diagnostics:
    def __init__(self, root: Path, db: Database, host: str, port: int) -> None:
        self.root = root
        self.db = db
        self.host = host
        self.port = port

    def _run(self, name: str, fn: Callable[[], str]) -> CheckResult:
        start = time.perf_counter()
        try:
            detail = fn()
            ok = True
        except Exception as exc:
            detail = str(exc)
            ok = False
        ms = max(0, round((time.perf_counter() - start) * 1000))
        return CheckResult(name=name, ok=ok, duration_ms=ms, detail=detail)

    def run(self, mode: str = "quick") -> dict:
        checks = [
            self._run("Ядро", lambda: "Модули ядра загружены"),
            self._run("Python", self._python),
            self._run("SQLite", self._sqlite),
            self._run("Целостность БД", self._integrity),
            self._run("Файловая система", self._filesystem),
            self._run("Локальный порт", self._local_port),
        ]
        if mode == "full":
            checks.extend(
                [
                    self._run("Интернет", self._internet),
                    self._run("Свободное место", self._disk),
                ]
            )
        passed = sum(1 for check in checks if check.ok)
        return {
            "mode": mode,
            "passed": passed,
            "total": len(checks),
            "ok": passed == len(checks),
            "checks": [check.as_dict() for check in checks],
        }

    def _python(self) -> str:
        if sys.version_info < (3, 11):
            raise RuntimeError(f"Требуется Python 3.11+, сейчас {sys.version.split()[0]}")
        return f"Python {sys.version.split()[0]}"

    def _sqlite(self) -> str:
        self.db.initialize()
        return "SQLite доступна"

    def _integrity(self) -> str:
        ok, detail = self.db.integrity_check()
        if not ok:
            raise RuntimeError(detail)
        return "integrity_check = ok"

    def _filesystem(self) -> str:
        data = self.root / "data"
        data.mkdir(parents=True, exist_ok=True)
        fd, name = tempfile.mkstemp(prefix="kohakuyasha-", dir=data)
        os.close(fd)
        Path(name).unlink(missing_ok=True)
        return "Запись разрешена"

    def _local_port(self) -> str:
        with socket.create_connection((self.host, self.port), timeout=2):
            return f"{self.host}:{self.port} отвечает"

    def _internet(self) -> str:
        req = urllib.request.Request("https://www.python.org/", headers={"User-Agent": "Kohakuyasha/0.1"})
        with urllib.request.urlopen(req, timeout=4) as response:
            if response.status >= 400:
                raise RuntimeError(f"HTTP {response.status}")
            response.read(1)
        return "python.org доступен"

    def _disk(self) -> str:
        import shutil
        usage = shutil.disk_usage(self.root)
        free_gb = usage.free / (1024 ** 3)
        if free_gb < 0.5:
            raise RuntimeError(f"Мало места: {free_gb:.2f} ГБ")
        return f"Свободно {free_gb:.1f} ГБ"
