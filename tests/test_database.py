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
