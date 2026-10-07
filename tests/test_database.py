from pathlib import Path

from core.database import Database


def test_database_initialization_and_events(tmp_path: Path):
    db = Database(tmp_path / "test.db")
    db.initialize()
    event_id = db.add_event("Тест", event_type="test", payload={"ok": True})
    assert event_id >= 1
    events = db.recent_events(10)
    assert events[-1]["message"] == "Тест"
    assert events[-1]["payload"]["ok"] is True
    ok, detail = db.integrity_check()
    assert ok, detail


def test_corrupt_database_restores_only_valid_backup(tmp_path: Path):
    path = tmp_path / "data" / "test.db"
    db = Database(path, max_backups=3)
    db.initialize()
    db.add_event("Сохранённое событие")
    backup = db.backup()
    assert backup.exists()
    for sidecar in (path.with_name(path.name + "-wal"), path.with_name(path.name + "-shm")):
        sidecar.unlink(missing_ok=True)
    path.write_bytes(b"not sqlite")
    recovered = Database(path, max_backups=3)
    recovered.initialize()
    assert recovered.recent_events(10)[-1]["message"] == "Сохранённое событие"
    assert list(path.parent.glob("test.corrupt-*.db"))


def test_backup_rotation(tmp_path: Path):
    db = Database(tmp_path / "test.db", max_backups=2)
    db.initialize()
    for _ in range(4):
        db.backup()
    assert len(list(db.backup_dir.glob("kohakuyasha-*.db"))) == 2


def test_chat_messages_and_migration_from_v1(tmp_path):
    import sqlite3
    path = tmp_path / "old.db"
    conn = sqlite3.connect(path)
    conn.executescript("CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT NOT NULL); INSERT INTO meta VALUES('schema_version','1');")
    conn.commit(); conn.close()
    db = Database(path)
    db.initialize()
    assert list((tmp_path / "backups").glob("kohakuyasha-*.db"))  # backup before migration
    db.add_chat_message("user", "a")
    db.add_chat_message("assistant", "b")
    assert [m["content"] for m in db.recent_chat(10)] == ["a", "b"]
    assert db.chat_count() == 2


def test_notifications_dedupe_resolve_and_cap(tmp_path):
    db = Database(tmp_path / "k.db"); db.initialize()
    first = db.add_notification("update", "Обновление", "тело", [{"id": "dismiss", "label": "Позже"}], dedupe_key="update:1.0.0")
    assert first and first["status"] == "new" and first["actions"][0]["id"] == "dismiss"
    assert db.add_notification("update", "Обновление", dedupe_key="update:1.0.0") is None
    assert len(db.unread_notifications()) == 1 and db.mark_notifications_seen() == 1 and db.unread_notifications() == []
    assert db.resolve_notification(first["id"]) and db.list_notifications() == []
    assert db.add_notification("update", "ещё", dedupe_key="update:1.0.0") is None  # a dismissed card is not re-created
    for i in range(120):
        db.add_notification("info", f"n{i}")
    assert len(db.list_notifications(100)) == 100
