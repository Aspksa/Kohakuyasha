from __future__ import annotations

import json
import shutil
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1


class Database:
    def __init__(self, path: Path, max_backups: int = 10) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.max_backups = max(1, int(max_backups))
        self._lock = threading.RLock()

    @property
    def backup_dir(self) -> Path:
        return self.path.parent / "backups"

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=10, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=5000")
        return conn

    @staticmethod
    def _check_file(path: Path) -> tuple[bool, str]:
        if not path.exists() or path.stat().st_size == 0:
            return True, "empty"
        try:
            with sqlite3.connect(path, timeout=5) as conn:
                value = conn.execute("PRAGMA quick_check").fetchone()[0]
            return value == "ok", str(value)
        except sqlite3.DatabaseError as exc:
            return False, str(exc)

    def _existing_schema_version(self) -> int:
        if not self.path.exists() or self.path.stat().st_size == 0:
            return 0
        try:
            with sqlite3.connect(self.path) as conn:
                table = conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='meta'").fetchone()
                if not table:
                    return 0
                row = conn.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()
                return int(row[0]) if row else 0
        except (sqlite3.DatabaseError, ValueError):
            return 0

    def _apply_schema(self) -> None:
        with self.connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at TEXT NOT NULL,
                    level TEXT NOT NULL,
                    source TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    message TEXT NOT NULL,
                    payload_json TEXT
                );
                CREATE TABLE IF NOT EXISTS tasks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'queued',
                    priority INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    payload_json TEXT
                );
                CREATE TABLE IF NOT EXISTS app_settings (
                    key TEXT PRIMARY KEY,
                    value_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_events_created_at ON events(created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_events_type ON events(event_type);
                CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);
                """
            )
            conn.execute(
                "INSERT INTO meta(key, value) VALUES('schema_version', ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (str(SCHEMA_VERSION),),
            )

    def initialize(self) -> None:
        with self._lock:
            existed = self.path.exists() and self.path.stat().st_size > 0
            if existed:
                healthy, detail = self._check_file(self.path)
                if not healthy:
                    self._quarantine_and_restore(detail)
                    existed = self.path.exists() and self.path.stat().st_size > 0
            old_version = self._existing_schema_version() if existed else 0
            if existed and old_version < SCHEMA_VERSION:
                self.backup()
            self._apply_schema()
            ok, detail = self.integrity_check()
            if not ok:
                self._quarantine_and_restore(detail)
                self._apply_schema()

    def _quarantine_and_restore(self, reason: str) -> None:
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        if self.path.exists():
            corrupt = self.path.with_name(f"{self.path.stem}.corrupt-{stamp}{self.path.suffix}")
            self.path.replace(corrupt)
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        for candidate in sorted(self.backup_dir.glob("kohakuyasha-*.db"), reverse=True):
            healthy, _ = self._check_file(candidate)
            if healthy:
                shutil.copy2(candidate, self.path)
                return
        # No trusted backup: leave no DB so schema creation starts clean.
        self.path.unlink(missing_ok=True)

    def add_event(
        self,
        message: str,
        *,
        level: str = "INFO",
        source: str = "core",
        event_type: str = "event",
        payload: dict[str, Any] | None = None,
        created_at: str | None = None,
    ) -> int:
        created_at = created_at or datetime.now(timezone.utc).isoformat()
        payload_json = json.dumps(payload, ensure_ascii=False) if payload is not None else None
        with self._lock, self.connect() as conn:
            cur = conn.execute(
                "INSERT INTO events(created_at, level, source, event_type, message, payload_json) VALUES (?, ?, ?, ?, ?, ?)",
                (created_at, level, source, event_type, message, payload_json),
            )
            return int(cur.lastrowid)

    def recent_events(self, limit: int = 100) -> list[dict[str, Any]]:
        limit = max(1, min(int(limit), 1000))
        with self._lock, self.connect() as conn:
            rows = conn.execute(
                "SELECT id, created_at, level, source, event_type, message, payload_json FROM events ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        result: list[dict[str, Any]] = []
        for row in reversed(rows):
            item = dict(row)
            raw_payload = item.pop("payload_json", None)
            if raw_payload:
                try:
                    item["payload"] = json.loads(raw_payload)
                except json.JSONDecodeError:
                    item["payload"] = None
            else:
                item["payload"] = None
            result.append(item)
        return result

    def integrity_check(self) -> tuple[bool, str]:
        with self._lock, self.connect() as conn:
            value = conn.execute("PRAGMA integrity_check").fetchone()[0]
        return value == "ok", str(value)

    def backup(self, backup_dir: Path | None = None) -> Path:
        backup_dir = backup_dir or self.backup_dir
        backup_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        target = backup_dir / f"kohakuyasha-{stamp}.db"
        with self._lock:
            source = self.connect()
            dest = sqlite3.connect(target)
            try:
                source.backup(dest)
            finally:
                dest.close()
                source.close()
        healthy, detail = self._check_file(target)
        if not healthy:
            target.unlink(missing_ok=True)
            raise sqlite3.DatabaseError(f"Невалидный backup: {detail}")
        self._rotate_backups(backup_dir)
        return target

    def _rotate_backups(self, backup_dir: Path) -> None:
        backups = sorted(backup_dir.glob("kohakuyasha-*.db"), reverse=True)
        for old in backups[self.max_backups:]:
            old.unlink(missing_ok=True)

    def trim_events(self, keep: int) -> None:
        keep = max(100, int(keep))
        with self._lock, self.connect() as conn:
            conn.execute(
                "DELETE FROM events WHERE id NOT IN (SELECT id FROM events ORDER BY id DESC LIMIT ?)",
                (keep,),
            )
