from __future__ import annotations

import json
import shutil
from dataclasses import asdict, dataclass
from datetime import datetime
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
    database_backups: int = 10


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
        self.character = self.root / "CHARACTER.json"
        self.secrets = self.data / "secrets.json"
        self.media = self.data / "media"
        self.disk = self.data / "disk"

    def ensure(self) -> None:
        self.data.mkdir(parents=True, exist_ok=True)
        self.logs.mkdir(parents=True, exist_ok=True)


class ConfigStore:
    def __init__(self, paths: Paths) -> None:
        self.paths = paths
        self.paths.ensure()
        self.warnings: list[str] = []

    @staticmethod
    def _bool(value: Any, default: bool) -> bool:
        return value if isinstance(value, bool) else default

    @staticmethod
    def _int(value: Any, default: int, low: int, high: int) -> int:
        if isinstance(value, bool):
            return default
        try:
            number = int(value)
        except (TypeError, ValueError):
            return default
        return number if low <= number <= high else default

    def _validate(self, raw: dict[str, Any]) -> Settings:
        defaults = Settings()
        language = raw.get("language") if isinstance(raw.get("language"), str) else defaults.language
        if language not in {"ru"}:
            language = defaults.language
        host = raw.get("host") if isinstance(raw.get("host"), str) else defaults.host
        if host != "127.0.0.1":
            self.warnings.append("Небезопасное значение host заменено на 127.0.0.1.")
            host = defaults.host
        return Settings(
            language=language,
            host=host,
            port=self._int(raw.get("port"), defaults.port, 1024, 65535),
            open_browser=self._bool(raw.get("open_browser"), defaults.open_browser),
            minimize_to_tray=self._bool(raw.get("minimize_to_tray"), defaults.minimize_to_tray),
            autostart=self._bool(raw.get("autostart"), defaults.autostart),
            event_limit=self._int(raw.get("event_limit"), defaults.event_limit, 100, 100_000),
            log_max_bytes=self._int(raw.get("log_max_bytes"), defaults.log_max_bytes, 100_000, 100_000_000),
            log_backups=self._int(raw.get("log_backups"), defaults.log_backups, 1, 50),
            database_backups=self._int(raw.get("database_backups"), defaults.database_backups, 1, 100),
        )

    def _backup_corrupt(self) -> Path | None:
        if not self.paths.settings.exists():
            return None
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        target = self.paths.settings.with_name(f"settings.corrupt-{stamp}.json")
        shutil.copy2(self.paths.settings, target)
        return target

    def load(self) -> Settings:
        if not self.paths.settings.exists():
            settings = Settings()
            self.save(settings)
            return settings
        try:
            raw = json.loads(self.paths.settings.read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                raise ValueError("settings.json должен содержать JSON-объект")
        except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
            backup = self._backup_corrupt()
            self.warnings.append(
                f"Повреждён settings.json; сохранена копия {backup.name if backup else 'недоступна'}: {exc}"
            )
            settings = Settings()
            self.save(settings)
            return settings
        settings = self._validate(raw)
        normalized = asdict(settings)
        if raw != normalized:
            self.save(settings)
        return settings

    def save(self, settings: Settings) -> None:
        validated = self._validate(asdict(settings))
        tmp = self.paths.settings.with_suffix(".tmp")
        tmp.write_text(json.dumps(asdict(validated), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        tmp.replace(self.paths.settings)

    def update(self, **changes: Any) -> Settings:
        settings = self.load()
        for key, value in changes.items():
            if hasattr(settings, key):
                setattr(settings, key, value)
        self.save(settings)
        return self.load()
