from __future__ import annotations

import json
import os
import socket
import sys
import threading
import time
import webbrowser
from pathlib import Path

import uvicorn

from core.api import create_app
from core.config import ConfigStore, Paths
from core.database import Database
from core.diagnostics import Diagnostics
from core.events import EventHub
from core.logging_setup import setup_logging
from core.runtime import RuntimeState, find_free_port
from core.tray import TrayController


ROOT = Path(__file__).resolve().parent
VERSION = (ROOT / "VERSION").read_text(encoding="utf-8").strip()


class InstanceLock:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.handle = None

    def acquire(self) -> bool:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.handle = open(self.path, "a+b")
        if self.path.stat().st_size == 0:
            self.handle.write(b"0")
            self.handle.flush()
        try:
            if os.name == "nt":
                import msvcrt
                self.handle.seek(0)
                msvcrt.locking(self.handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            return True
        except (OSError, IOError):
            return False

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


class Supervisor:
    def __init__(self, safe_mode: bool = False) -> None:
        self.safe_mode = safe_mode
        self.paths = Paths(ROOT)
        self.paths.ensure()
        self.config_store = ConfigStore(self.paths)
        self.settings = self.config_store.load()
        self.logger = setup_logging(self.paths.logs, self.settings.log_max_bytes, self.settings.log_backups)
        self.db = Database(self.paths.database)
        self.db.initialize()
        self.runtime = RuntimeState(
            self.paths,
            VERSION,
            status="Безопасный режим" if safe_mode else "Запуск",
            current_action="Минимальная конфигурация" if safe_mode else "Инициализация",
        )
        self.events = EventHub(self.db, self.logger, self.settings.event_limit)
        self.port = find_free_port(self.settings.host, self.settings.port)
        self.runtime.port = self.port
        self.server: uvicorn.Server | None = None
        self.server_thread: threading.Thread | None = None
        self.tray: TrayController | None = None
        self._stopping = threading.Event()
        self._restart_lock = threading.Lock()

    @property
    def url(self) -> str:
        return f"http://{self.settings.host}:{self.port}"

    def _build_server(self) -> uvicorn.Server:
        app = create_app(
            paths=self.paths,
            config=self.config_store,
            db=self.db,
            events=self.events,
            runtime=self.runtime,
        )
        cfg = uvicorn.Config(
            app,
            host=self.settings.host,
            port=self.port,
            log_level="warning",
            access_log=False,
        )
        return uvicorn.Server(cfg)

    def start_server(self) -> None:
        self.server = self._build_server()
        self.server_thread = threading.Thread(target=self.server.run, name="kohakuyasha-web", daemon=True)
        self.server_thread.start()
        deadline = time.time() + 15
        while time.time() < deadline:
            if self.server.started:
                self.runtime.set_status("Наблюдает", "Готова к работе")
                self.events.emit(
                    "Ядро и веб-интерфейс запущены",
                    event_type="startup",
                    payload={"url": self.url, "version": VERSION},
                )
                return
            if not self.server_thread.is_alive():
                break
            time.sleep(0.1)
        raise RuntimeError("Веб-сервер не запустился.")

    def restart(self) -> None:
        if self._stopping.is_set() or not self._restart_lock.acquire(blocking=False):
            return
        try:
            self.runtime.set_status("Перезапуск", "Перезапуск веб-ядра")
            if self.server:
                self.server.should_exit = True
            if self.server_thread:
                self.server_thread.join(timeout=8)
            self.start_server()
        except Exception as exc:
            self.events.emit(
                f"Ошибка перезапуска: {exc}",
                level="ERROR",
                event_type="watchdog",
            )
            self.runtime.set_status("Ошибка", str(exc))
        finally:
            self._restart_lock.release()

    def shutdown(self) -> None:
        if self._stopping.is_set():
            return
        self._stopping.set()
        self.runtime.set_status("Остановка", "Завершение работы")
        self.events.emit("Kohakuyasha завершает работу", event_type="shutdown")
        if self.server:
            self.server.should_exit = True
        if self.tray:
            self.tray.stop()

    def quick_test(self) -> None:
        try:
            result = Diagnostics(ROOT, self.db, self.settings.host, self.port).run("quick")
            self.runtime.last_test_summary = result
            self.events.emit(
                f"Быстрый тест: {result['passed']}/{result['total']}",
                level="INFO" if result["ok"] else "WARNING",
                event_type="diagnostics",
                payload=result,
            )
        except Exception as exc:
            self.events.emit(str(exc), level="ERROR", event_type="diagnostics")

    def watchdog(self) -> None:
        while not self._stopping.wait(2):
            if self.server_thread and not self.server_thread.is_alive():
                self.events.emit(
                    "Watchdog обнаружил остановку веб-ядра. Выполняется восстановление.",
                    level="WARNING",
                    event_type="watchdog",
                )
                self.restart()

    def run(self) -> None:
        self.runtime.on_restart = lambda: threading.Thread(target=self.restart, daemon=True).start()
        self.runtime.on_shutdown = self.shutdown
        self.start_server()

        if not self.safe_mode:
            threading.Thread(target=self.watchdog, name="kohakuyasha-watchdog", daemon=True).start()
            threading.Thread(target=self.quick_test, name="kohakuyasha-startup-test", daemon=True).start()
        else:
            self.events.emit("Запущен безопасный режим", level="WARNING", event_type="safe_mode")

        if self.settings.open_browser:
            threading.Timer(0.6, lambda: webbrowser.open(self.url)).start()

        self.tray = TrayController(
            url=self.url,
            on_restart=self.runtime.on_restart,
            on_shutdown=self.shutdown,
            on_quick_test=self.quick_test,
            project_root=ROOT,
        )
        try:
            self.tray.run()
        finally:
            self.shutdown()
            if self.server_thread:
                self.server_thread.join(timeout=5)


def open_existing(paths: Paths) -> None:
    try:
        data = json.loads(paths.runtime_state.read_text(encoding="utf-8"))
        port = int(data.get("port", 8710))
    except Exception:
        port = 8710
    webbrowser.open(f"http://127.0.0.1:{port}")


def main() -> int:
    paths = Paths(ROOT)
    lock = InstanceLock(paths.lock)
    if not lock.acquire():
        open_existing(paths)
        return 0
    try:
        Supervisor(safe_mode="--safe" in sys.argv).run()
        return 0
    finally:
        lock.release()


if __name__ == "__main__":
    raise SystemExit(main())
