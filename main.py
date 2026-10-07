from __future__ import annotations

import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import uvicorn

from core.api import create_app
from core.config import ConfigStore, Paths
from core.database import Database
from core.events import EventHub
from core.logging_setup import setup_logging
from core.runtime import RuntimeState, find_free_port

ROOT = Path(__file__).resolve().parent
VERSION = (ROOT / "VERSION").read_text(encoding="utf-8").strip()


def main() -> None:
    paths = Paths(ROOT)
    paths.ensure()
    config = ConfigStore(paths)
    settings = config.load()
    db = Database(paths.database, max_backups=settings.database_backups)
    db.initialize()
    logger = setup_logging(paths.logs, settings.log_max_bytes, settings.log_backups)
    events = EventHub(db, logger, settings.event_limit)
    restart_requested = threading.Event()
    shutdown_requested = threading.Event()

    while not shutdown_requested.is_set():
        port = find_free_port(settings.host, settings.port)
        runtime = RuntimeState(paths, VERSION, port=port, status="Наблюдает", current_action="Консольный режим", watchdog_active=False)
        app = create_app(paths=paths, config=config, db=db, events=events, runtime=runtime)
        server = uvicorn.Server(uvicorn.Config(app, host=settings.host, port=port, log_config=None, access_log=False, timeout_graceful_shutdown=2))

        def restart() -> None:
            restart_requested.set()
            server.should_exit = True

        def shutdown() -> None:
            shutdown_requested.set()
            server.should_exit = True

        runtime.on_restart = restart
        runtime.on_shutdown = shutdown
        events.emit("Kohakuyasha запущена в консольном режиме", event_type="startup", payload={"port": port})
        server.run()
        runtime.clear_persisted()
        if restart_requested.is_set() and not shutdown_requested.is_set():
            restart_requested.clear()
            continue
        break


if __name__ == "__main__":
    main()
