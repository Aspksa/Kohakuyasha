from __future__ import annotations

import json
import os
import socket
import sys
import threading
import time
import webbrowser
from pathlib import Path

# Embedded Python (._pth) runs isolated and does not put the script directory on sys.path.
sys.path.insert(0, str(Path(__file__).resolve().parent))

import psutil
import uvicorn

from core.api import create_app
from core.autostart import ensure_instance_marker
from core.config import ConfigStore, Paths
from core.database import Database
from core.diagnostics import Diagnostics
from core.events import EventHub
from core.instance import InstanceLock, acquire_or_wait
from core.logging_setup import setup_logging
from core.runtime import RuntimeState, find_free_port, port_is_open
from core.tray import TrayController

ROOT = Path(__file__).resolve().parent
VERSION = (ROOT / "VERSION").read_text(encoding="utf-8").strip()


class Supervisor:
    def __init__(self, safe_mode: bool = False) -> None:
        self.safe_mode = safe_mode
        self.paths = Paths(ROOT)
        self.paths.ensure()
        try:
            ensure_instance_marker(ROOT)
        except OSError:
            pass  # read-only media: only autostart needs the marker, and it reports its own error
        self.config_store = ConfigStore(self.paths)
        self.settings = self.config_store.load()
        self.logger = setup_logging(self.paths.logs, self.settings.log_max_bytes, self.settings.log_backups)
        self.db = Database(self.paths.database, max_backups=self.settings.database_backups)
        self.db.initialize()
        self.runtime = RuntimeState(
            self.paths,
            VERSION,
            status="Безопасный режим" if safe_mode else "Запуск",
            current_action="Минимальная конфигурация" if safe_mode else "Инициализация",
            safe_mode=safe_mode,
        )
        self.events = EventHub(self.db, self.logger, self.settings.event_limit)
        for warning in self.config_store.warnings:
            self.events.emit(warning, level="WARNING", event_type="config")
        self.port = find_free_port(self.settings.host, self.settings.port)
        self.runtime.port = self.port
        self.server: uvicorn.Server | None = None
        self.server_thread: threading.Thread | None = None
        self.tray: TrayController | None = None
        self._stopping = threading.Event()
        self._restart_lock = threading.Lock()
        self._watchdog_failures = 0
        self._watchdog_retry_at = 0.0

    @property
    def url(self) -> str:
        return f"http://{self.settings.host}:{self.port}"

    def _build_server(self) -> uvicorn.Server:
        app = create_app(paths=self.paths, config=self.config_store, db=self.db, events=self.events, runtime=self.runtime)
        cfg = uvicorn.Config(
            app,
            host=self.settings.host,
            port=self.port,
            log_config=None,
            access_log=False,
            timeout_graceful_shutdown=2,  # do not wait for idle browser connections: a relaunch must not hang
        )
        return uvicorn.Server(cfg)

    def start_server(self, attempts: int = 3) -> None:
        for attempt in range(attempts):
            self.server = self._build_server()
            self.server_thread = threading.Thread(target=self.server.run, name="kohakuyasha-web", daemon=True)
            self.server_thread.start()
            deadline = time.time() + 15
            while time.time() < deadline:
                if self.server.started:
                    self.runtime.port = self.port
                    self.runtime.set_status("Наблюдает", "Готова к работе")
                    if self.tray:
                        self.tray.set_url(self.url)
                    self.events.emit("Ядро и веб-интерфейс запущены", event_type="startup", payload={"url": self.url, "version": VERSION})
                    self._watchdog_failures = 0
                    return
                if not self.server_thread.is_alive():
                    break
                time.sleep(0.1)
            # The port can be taken between the free-port probe and the bind: pick another and retry.
            if self.server_thread.is_alive():
                self.server.should_exit = True
                self.server_thread.join(timeout=5)
            if attempt + 1 < attempts:
                self.port = find_free_port(self.settings.host, self.port + 1)
                self.runtime.port = self.port
        raise RuntimeError("Веб-сервер не запустился.")

    def restart(self) -> bool:
        if self._stopping.is_set() or not self._restart_lock.acquire(blocking=False):
            return False
        try:
            self.runtime.set_status("Перезапуск", "Остановка веб-ядра")
            if self.server:
                self.server.should_exit = True
            if self.server_thread:
                self.server_thread.join(timeout=8)
                if self.server_thread.is_alive():
                    raise RuntimeError("Старый веб-сервер не завершился за 8 секунд.")
            # Keep the same port when possible so open browser tabs stay valid.
            try:
                self.port = find_free_port(self.settings.host, self.port, span=1)
            except RuntimeError:
                self.port = find_free_port(self.settings.host, self.settings.port)
            self.runtime.port = self.port
            self.start_server()
            return True
        except Exception as exc:
            self._watchdog_failures += 1
            delay = min(60, 2 ** min(self._watchdog_failures, 6))
            self._watchdog_retry_at = time.monotonic() + delay
            self.events.emit(f"Ошибка перезапуска: {exc}. Следующая попытка не раньше чем через {delay} с.", level="ERROR", event_type="watchdog")
            self.runtime.set_status("Ошибка", str(exc))
            return False
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
        self.runtime.clear_persisted()
        hard_exit = threading.Timer(15, lambda: os._exit(0))  # last resort so the lock is always released
        hard_exit.daemon = True
        hard_exit.start()

    def quick_test(self) -> None:
        try:
            result = Diagnostics(ROOT, self.db, self.settings.host, self.port).run("quick")
            self.runtime.last_test_summary = result
            self.events.emit(f"Быстрый тест: {result['passed']}/{result['total']}", level="INFO" if result["ok"] else "WARNING", event_type="diagnostics", payload=result)
        except Exception as exc:
            self.events.emit(str(exc), level="ERROR", event_type="diagnostics")

    def watchdog(self) -> None:
        self.runtime.watchdog_active = True
        while not self._stopping.wait(2):
            if self.server_thread and not self.server_thread.is_alive() and time.monotonic() >= self._watchdog_retry_at:
                self.events.emit("Watchdog обнаружил остановку веб-ядра. Выполняется восстановление.", level="WARNING", event_type="watchdog")
                self.restart()
        self.runtime.watchdog_active = False

    def run(self) -> None:
        self.runtime.on_restart = lambda: threading.Thread(target=self.restart, daemon=True).start()
        self.runtime.on_shutdown = lambda: threading.Thread(target=self.shutdown, daemon=True).start()
        self.start_server()

        if not self.safe_mode:
            threading.Thread(target=self.watchdog, name="kohakuyasha-watchdog", daemon=True).start()
            threading.Thread(target=self.quick_test, name="kohakuyasha-startup-diagnostics", daemon=True).start()
        else:
            self.events.emit("Запущен безопасный режим", level="WARNING", event_type="safe_mode")

        if self.settings.open_browser:
            threading.Timer(0.6, lambda: webbrowser.open(self.url)).start()

        self.tray = TrayController(url=self.url, on_restart=self.restart, on_shutdown=self.shutdown, on_quick_test=self.quick_test, project_root=ROOT)
        try:
            self.tray.run()
        finally:
            self.shutdown()
            if self.server_thread:
                self.server_thread.join(timeout=5)
            self.runtime.clear_persisted()


def open_existing(paths: Paths) -> bool:
    for _ in range(10):
        try:
            data = json.loads(paths.runtime_state.read_text(encoding="utf-8"))
            pid = int(data["pid"])
            port = int(data["port"])
            if psutil.pid_exists(pid) and port_is_open("127.0.0.1", port):
                webbrowser.open(f"http://127.0.0.1:{port}")
                return True
        except Exception:
            pass
        time.sleep(0.2)
    return False


def main() -> int:
    paths = Paths(ROOT)
    paths.ensure()
    lock = InstanceLock(paths.lock)
    state = acquire_or_wait(lock, paths)
    if state != "acquired":
        if state == "running":
            open_existing(paths)  # a healthy instance is already serving: just show it
        return 0
    try:
        Supervisor(safe_mode="--safe" in sys.argv).run()
        return 0
    finally:
        paths.runtime_state.unlink(missing_ok=True)
        lock.release()


def run() -> int:
    """pythonw has no console, so write any startup crash to logs/launcher-crash.log."""
    try:
        return main()
    except SystemExit:
        raise
    except BaseException:
        import traceback
        try:
            log = ROOT / "logs" / "launcher-crash.log"
            log.parent.mkdir(parents=True, exist_ok=True)
            with open(log, "a", encoding="utf-8") as f:
                f.write(f"--- {time.strftime('%Y-%m-%d %H:%M:%S')} v{VERSION}\n{traceback.format_exc()}\n")
        except OSError:
            pass
        return 1


if __name__ == "__main__":
    raise SystemExit(run())
