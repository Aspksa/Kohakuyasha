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


def test_database_backup(tmp_path: Path):
    db = Database(tmp_path / "test.db")
    db.initialize()
    target = db.backup(tmp_path / "backups")
    assert target.exists()
