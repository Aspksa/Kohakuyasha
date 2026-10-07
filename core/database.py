from __future__ import annotations

import json
import re
import shutil
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 5


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

    @contextmanager
    def session(self):
        conn = self.connect()
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    @staticmethod
    def _check_file(path: Path) -> tuple[bool, str]:
        if not path.exists() or path.stat().st_size == 0:
            return True, "empty"
        conn = None
        try:
            conn = sqlite3.connect(path, timeout=5)
            value = conn.execute("PRAGMA quick_check").fetchone()[0]
            return value == "ok", str(value)
        except sqlite3.DatabaseError as exc:
            return False, str(exc)
        finally:
            if conn is not None:
                conn.close()

    def _existing_schema_version(self) -> int:
        if not self.path.exists() or self.path.stat().st_size == 0:
            return 0
        conn = None
        try:
            conn = sqlite3.connect(self.path)
            table = conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='meta'").fetchone()
            if not table:
                return 0
            row = conn.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()
            return int(row[0]) if row else 0
        except (sqlite3.DatabaseError, ValueError):
            return 0
        finally:
            if conn is not None:
                conn.close()

    def _apply_schema(self) -> None:
        with self.session() as conn:
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
                CREATE TABLE IF NOT EXISTS chat_messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at TEXT NOT NULL,
                    role TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
                    content TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS notifications (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    title TEXT NOT NULL,
                    body TEXT NOT NULL DEFAULT '',
                    actions_json TEXT NOT NULL DEFAULT '[]',
                    dedupe_key TEXT UNIQUE,
                    status TEXT NOT NULL DEFAULT 'new' CHECK (status IN ('new', 'seen', 'done'))
                );
                CREATE TABLE IF NOT EXISTS dialogs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT NOT NULL,
                    source TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    message_count INTEGER NOT NULL DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS memory_items (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    dialog_id INTEGER REFERENCES dialogs(id) ON DELETE CASCADE,
                    role TEXT NOT NULL CHECK (role IN ('user', 'assistant', 'note')),
                    content TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_memory_dialog ON memory_items(dialog_id);
                CREATE TABLE IF NOT EXISTS facts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    text TEXT NOT NULL,
                    category TEXT NOT NULL DEFAULT 'other',
                    importance INTEGER NOT NULL DEFAULT 3,
                    pinned INTEGER NOT NULL DEFAULT 0,
                    source TEXT NOT NULL DEFAULT 'auto',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    last_used_at TEXT,
                    use_count INTEGER NOT NULL DEFAULT 0
                );
                CREATE INDEX IF NOT EXISTS idx_facts_importance ON facts(importance DESC, updated_at DESC);
                CREATE INDEX IF NOT EXISTS idx_events_created_at ON events(created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_events_type ON events(event_type);
                CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);
                """
            )
            try:  # FTS5 is optional: search falls back to LIKE when the SQLite build lacks it
                conn.executescript(
                    """
                    CREATE VIRTUAL TABLE IF NOT EXISTS memory_fts USING fts5(
                        content, content='memory_items', content_rowid='id', tokenize='unicode61 remove_diacritics 2');
                    CREATE TRIGGER IF NOT EXISTS memory_ai AFTER INSERT ON memory_items BEGIN
                        INSERT INTO memory_fts(rowid, content) VALUES (new.id, new.content);
                    END;
                    CREATE TRIGGER IF NOT EXISTS memory_ad AFTER DELETE ON memory_items BEGIN
                        INSERT INTO memory_fts(memory_fts, rowid, content) VALUES ('delete', old.id, old.content);
                    END;
                    """
                )
            except sqlite3.OperationalError:
                pass
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
        with self._lock, self.session() as conn:
            cur = conn.execute(
                "INSERT INTO events(created_at, level, source, event_type, message, payload_json) VALUES (?, ?, ?, ?, ?, ?)",
                (created_at, level, source, event_type, message, payload_json),
            )
            return int(cur.lastrowid)

    def recent_events(self, limit: int = 100) -> list[dict[str, Any]]:
        limit = max(1, min(int(limit), 1000))
        with self._lock, self.session() as conn:
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

    def add_chat_message(self, role: str, content: str) -> dict[str, Any]:
        created_at = datetime.now(timezone.utc).isoformat()
        with self._lock, self.session() as conn:
            cur = conn.execute(
                "INSERT INTO chat_messages(created_at, role, content) VALUES (?, ?, ?)",
                (created_at, role, content),
            )
            return {"id": int(cur.lastrowid), "created_at": created_at, "role": role, "content": content}

    def recent_chat(self, limit: int = 100) -> list[dict[str, Any]]:
        limit = max(1, min(int(limit), 500))
        with self._lock, self.session() as conn:
            rows = conn.execute(
                "SELECT id, created_at, role, content FROM chat_messages ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(row) for row in reversed(rows)]

    def chat_count(self) -> int:
        with self._lock, self.session() as conn:
            return int(conn.execute("SELECT COUNT(*) FROM chat_messages").fetchone()[0])

    def clear_chat(self) -> int:
        with self._lock, self.session() as conn:
            return int(conn.execute("DELETE FROM chat_messages").rowcount)

    def get_setting(self, key: str, default: Any = None) -> Any:
        with self._lock, self.session() as conn:
            row = conn.execute("SELECT value_json FROM app_settings WHERE key = ?", (key,)).fetchone()
        if not row:
            return default
        try:
            return json.loads(row["value_json"])
        except json.JSONDecodeError:
            return default

    def set_setting(self, key: str, value: Any) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with self._lock, self.session() as conn:
            conn.execute(
                "INSERT INTO app_settings(key, value_json, updated_at) VALUES (?, ?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json, updated_at=excluded.updated_at",
                (key, json.dumps(value, ensure_ascii=False), now),
            )

    # ---------- memory (imported dialogs, notes, learned chat) ----------
    def add_dialog(self, title: str, source: str, messages: list[dict[str, str]]) -> int:
        now = datetime.now(timezone.utc).isoformat()
        with self._lock, self.session() as conn:
            cur = conn.execute(
                "INSERT INTO dialogs(title, source, created_at, message_count) VALUES (?, ?, ?, ?)",
                (title[:120], source, now, len(messages)),
            )
            dialog_id = int(cur.lastrowid)
            conn.executemany(
                "INSERT INTO memory_items(dialog_id, role, content, created_at) VALUES (?, ?, ?, ?)",
                [(dialog_id, m["role"], m["content"], now) for m in messages],
            )
            return dialog_id

    def add_learned(self, role: str, content: str) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with self._lock, self.session() as conn:
            conn.execute(
                "INSERT INTO memory_items(dialog_id, role, content, created_at) VALUES (NULL, ?, ?, ?)",
                (role, content, now),
            )

    def list_dialogs(self) -> list[dict[str, Any]]:
        with self._lock, self.session() as conn:
            rows = conn.execute(
                "SELECT id, title, source, created_at, message_count FROM dialogs ORDER BY id DESC LIMIT 500"
            ).fetchall()
        return [dict(r) for r in rows]

    def delete_dialog(self, dialog_id: int) -> bool:
        with self._lock, self.session() as conn:
            conn.execute("DELETE FROM memory_items WHERE dialog_id = ?", (dialog_id,))
            return conn.execute("DELETE FROM dialogs WHERE id = ?", (dialog_id,)).rowcount > 0

    def clear_learned(self) -> int:
        with self._lock, self.session() as conn:
            return int(conn.execute("DELETE FROM memory_items WHERE dialog_id IS NULL").rowcount)

    def memory_stats(self) -> dict[str, int]:
        with self._lock, self.session() as conn:
            dialogs = conn.execute("SELECT COUNT(*) FROM dialogs").fetchone()[0]
            imported = conn.execute("SELECT COUNT(*) FROM memory_items WHERE dialog_id IS NOT NULL").fetchone()[0]
            learned = conn.execute("SELECT COUNT(*) FROM memory_items WHERE dialog_id IS NULL").fetchone()[0]
        return {"dialogs": int(dialogs), "imported": int(imported), "learned": int(learned)}

    @staticmethod
    def _query_tokens(text: str) -> list[str]:
        words = {w for w in re.findall(r"\w+", text.lower()) if len(w) >= 3}
        return sorted(words, key=len, reverse=True)[:8]

    def search_memory(self, query: str, limit: int = 6, skip_recent_learned: int = 40) -> list[dict[str, Any]]:
        tokens = self._query_tokens(query)
        if not tokens:
            return []
        limit = max(1, min(int(limit), 20))
        recent_cut = "(SELECT COALESCE(MAX(id), 0) FROM memory_items) - ?"
        with self._lock, self.session() as conn:
            fts = conn.execute("SELECT 1 FROM sqlite_master WHERE name = 'memory_fts'").fetchone()
            rows: list[Any] = []
            if fts:
                # Crude Russian stemming: drop the last two letters of long words and match by prefix.
                match = " OR ".join(f'"{t[:max(3, len(t) - 2)]}"*' if len(t) >= 5 else f'"{t}"' for t in tokens)
                try:
                    rows = conn.execute(
                        "SELECT m.role, m.content, d.title FROM memory_fts f JOIN memory_items m ON m.id = f.rowid "
                        "LEFT JOIN dialogs d ON d.id = m.dialog_id WHERE memory_fts MATCH ? "
                        f"AND NOT (m.dialog_id IS NULL AND m.id > {recent_cut}) ORDER BY rank LIMIT ?",
                        (match, skip_recent_learned, limit),
                    ).fetchall()
                except sqlite3.OperationalError:
                    rows = []
            else:
                like = " OR ".join("m.content LIKE ?" for _ in tokens)
                rows = conn.execute(
                    "SELECT m.role, m.content, d.title FROM memory_items m LEFT JOIN dialogs d ON d.id = m.dialog_id "
                    f"WHERE ({like}) AND NOT (m.dialog_id IS NULL AND m.id > {recent_cut}) ORDER BY m.id DESC LIMIT ?",
                    ([f"%{t}%" for t in tokens] + [skip_recent_learned, limit]),
                ).fetchall()
        return [{"role": r["role"], "content": r["content"], "title": r["title"] or "чат"} for r in rows]

    # ---------- facts (long-term knowledge about the user) ----------
    FACT_CATEGORIES = ("personal", "preference", "relation", "project", "schedule", "other")

    def add_fact(self, text: str, category: str = "other", importance: int = 3, source: str = "auto", pinned: bool = False) -> int:
        now = datetime.now(timezone.utc).isoformat()
        category = category if category in self.FACT_CATEGORIES else "other"
        with self._lock, self.session() as conn:
            cur = conn.execute(
                "INSERT INTO facts(text, category, importance, pinned, source, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (text[:300], category, max(1, min(5, int(importance))), 1 if pinned else 0, source, now, now),
            )
            return int(cur.lastrowid)

    def list_facts(self, limit: int = 500) -> list[dict[str, Any]]:
        with self._lock, self.session() as conn:
            rows = conn.execute(
                "SELECT id, text, category, importance, pinned, source, created_at, updated_at, last_used_at, use_count "
                "FROM facts ORDER BY pinned DESC, importance DESC, updated_at DESC LIMIT ?",
                (max(1, min(int(limit), 1000)),),
            ).fetchall()
        return [{**dict(r), "pinned": bool(r["pinned"])} for r in rows]

    def update_fact(self, fact_id: int, **changes: Any) -> bool:
        columns, values = [], []
        if isinstance(changes.get("text"), str) and changes["text"].strip():
            columns.append("text = ?"); values.append(changes["text"].strip()[:300])
        if changes.get("category") in self.FACT_CATEGORIES:
            columns.append("category = ?"); values.append(changes["category"])
        if isinstance(changes.get("importance"), int) and not isinstance(changes["importance"], bool):
            columns.append("importance = ?"); values.append(max(1, min(5, changes["importance"])))
        if isinstance(changes.get("pinned"), bool):
            columns.append("pinned = ?"); values.append(1 if changes["pinned"] else 0)
        if not columns:
            return False
        columns.append("updated_at = ?"); values.append(datetime.now(timezone.utc).isoformat())
        with self._lock, self.session() as conn:
            return conn.execute(f"UPDATE facts SET {', '.join(columns)} WHERE id = ?", (*values, fact_id)).rowcount > 0

    def delete_fact(self, fact_id: int) -> bool:
        with self._lock, self.session() as conn:
            return conn.execute("DELETE FROM facts WHERE id = ?", (fact_id,)).rowcount > 0

    def clear_facts(self, source: str | None = "auto") -> int:
        with self._lock, self.session() as conn:
            if source is None:
                return int(conn.execute("DELETE FROM facts").rowcount)
            return int(conn.execute("DELETE FROM facts WHERE source = ? AND pinned = 0", (source,)).rowcount)

    def touch_facts(self, ids: list[int]) -> None:
        if not ids:
            return
        now = datetime.now(timezone.utc).isoformat()
        with self._lock, self.session() as conn:
            conn.executemany("UPDATE facts SET last_used_at = ?, use_count = use_count + 1 WHERE id = ?", [(now, i) for i in ids])

    def fact_count(self) -> int:
        with self._lock, self.session() as conn:
            return int(conn.execute("SELECT COUNT(*) FROM facts").fetchone()[0])

    def trim_facts(self, keep: int = 500) -> None:
        """Drop the least valuable unpinned facts beyond the cap."""
        with self._lock, self.session() as conn:
            conn.execute(
                "DELETE FROM facts WHERE pinned = 0 AND id NOT IN ("
                "SELECT id FROM facts ORDER BY pinned DESC, importance DESC, updated_at DESC LIMIT ?)",
                (keep,),
            )

    # ---------- notifications (shown on the avatar and as cards in the chat) ----------
    def add_notification(self, kind: str, title: str, body: str = "", actions: list[dict[str, Any]] | None = None, dedupe_key: str | None = None) -> dict[str, Any] | None:
        """Returns the new notification, or None when one with the same dedupe_key already exists (even a dismissed one)."""
        now = datetime.now(timezone.utc).isoformat()
        with self._lock, self.session() as conn:
            if dedupe_key and conn.execute("SELECT 1 FROM notifications WHERE dedupe_key = ?", (dedupe_key,)).fetchone():
                return None
            cur = conn.execute(
                "INSERT INTO notifications(created_at, kind, title, body, actions_json, dedupe_key) VALUES(?, ?, ?, ?, ?, ?)",
                (now, kind, title[:200], body[:2000], json.dumps(actions or [], ensure_ascii=False), dedupe_key),
            )
            conn.execute("DELETE FROM notifications WHERE id NOT IN (SELECT id FROM notifications ORDER BY id DESC LIMIT 100)")
            nid = int(cur.lastrowid)
        return self.get_notification(nid)

    @staticmethod
    def _notification_row(row: sqlite3.Row) -> dict[str, Any]:
        item = dict(row)
        try:
            item["actions"] = json.loads(item.pop("actions_json") or "[]")
        except ValueError:
            item["actions"] = []
        return item

    def get_notification(self, nid: int) -> dict[str, Any] | None:
        with self._lock, self.session() as conn:
            row = conn.execute("SELECT id, created_at, kind, title, body, actions_json, status FROM notifications WHERE id = ?", (int(nid),)).fetchone()
        return self._notification_row(row) if row else None

    def list_notifications(self, limit: int = 50) -> list[dict[str, Any]]:
        """Active (not dismissed) notifications, oldest first."""
        with self._lock, self.session() as conn:
            rows = conn.execute(
                "SELECT id, created_at, kind, title, body, actions_json, status FROM notifications WHERE status != 'done' ORDER BY id DESC LIMIT ?",
                (max(1, min(int(limit), 100)),),
            ).fetchall()
        return [self._notification_row(r) for r in reversed(rows)]

    def unread_notifications(self) -> list[dict[str, Any]]:
        with self._lock, self.session() as conn:
            rows = conn.execute("SELECT id, created_at, kind, title, body, actions_json, status FROM notifications WHERE status = 'new' ORDER BY id").fetchall()
        return [self._notification_row(r) for r in rows]

    def mark_notifications_seen(self) -> int:
        with self._lock, self.session() as conn:
            return int(conn.execute("UPDATE notifications SET status = 'seen' WHERE status = 'new'").rowcount)

    def resolve_notification(self, nid: int) -> bool:
        with self._lock, self.session() as conn:
            return conn.execute("UPDATE notifications SET status = 'done' WHERE id = ?", (int(nid),)).rowcount > 0

    def resolve_notifications_by_prefix(self, prefix: str) -> int:
        with self._lock, self.session() as conn:
            return int(conn.execute("UPDATE notifications SET status = 'done' WHERE dedupe_key LIKE ? AND status != 'done'", (prefix + "%",)).rowcount)

    def chat_after(self, after_id: int, limit: int = 200) -> list[dict[str, Any]]:
        with self._lock, self.session() as conn:
            rows = conn.execute(
                "SELECT id, created_at, role, content FROM chat_messages WHERE id > ? ORDER BY id ASC LIMIT ?",
                (int(after_id), max(1, min(int(limit), 1000))),
            ).fetchall()
        return [dict(r) for r in rows]

    def integrity_check(self) -> tuple[bool, str]:
        with self._lock, self.session() as conn:
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
        with self._lock, self.session() as conn:
            conn.execute(
                "DELETE FROM events WHERE id NOT IN (SELECT id FROM events ORDER BY id DESC LIMIT ?)",
                (keep,),
            )
