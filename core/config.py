from __future__ import annotations

import json
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class Settings:
    language: str = "ru"
    host: str = "127.0.0.1"
    port: int = 8710
    open_browser: bool = True
    minimize_to_tray: bool = True
    autostart: bool = False
    event_limit: int = 5000
    log_max_bytes: int = 2_000_000
    log_backups: int = 5


class Paths:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.data = self.root / "data"
        self.logs = self.root / "logs"
        self.web = self.root / "web"
        self.static = self.web / "static"
        self.settings = self.data / "settings.json"
        self.database = self.data / "kohakuyasha.db"
        self.runtime_state = self.data / "runtime.json"
        self.lock = self.data / "kohakuyasha.lock"
        self.marker = self.root / ".kohakuyasha-id"

    def ensure(self) -> None:
        self.data.mkdir(parents=True, exist_ok=True)
        self.logs.mkdir(parents=True, exist_ok=True)


class ConfigStore:
    def __init__(self, paths: Paths) -> None:
        self.paths = paths
        self.paths.ensure()

    def load(self) -> Settings:
        if not self.paths.settings.exists():
            settings = Settings()
            self.save(settings)
            return settings
        try:
            raw = json.loads(self.paths.settings.read_text(encoding="utf-8"))
            allowed = Settings.__dataclass_fields__.keys()
            return Settings(**{k: v for k, v in raw.items() if k in allowed})
        except (OSError, ValueError, TypeError):
            return Settings()

    def save(self, settings: Settings) -> None:
        tmp = self.paths.settings.with_suffix(".tmp")
        tmp.write_text(json.dumps(asdict(settings), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        tmp.replace(self.paths.settings)

    def update(self, **changes: Any) -> Settings:
        settings = self.load()
        for key, value in changes.items():
            if hasattr(settings, key):
                setattr(settings, key, value)
        self.save(settings)
        return settings
