from __future__ import annotations

from pathlib import Path

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
    config = ConfigStore(paths)
    settings = config.load()
    db = Database(paths.database)
    db.initialize()
    logger = setup_logging(paths.logs, settings.log_max_bytes, settings.log_backups)
    events = EventHub(db, logger, settings.event_limit)
    port = find_free_port(settings.host, settings.port)
    runtime = RuntimeState(paths, VERSION, port=port, status="Наблюдает", current_action="Ручной запуск")
    app = create_app(paths=paths, config=config, db=db, events=events, runtime=runtime)
    events.emit("Kohakuyasha запущена в консольном режиме", event_type="startup")
    uvicorn.run(app, host=settings.host, port=port, log_level="info")


if __name__ == "__main__":
    main()
