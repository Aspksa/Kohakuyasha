import logging
from pathlib import Path

from core.database import Database
from core.events import EventHub


def test_live_event_has_database_timestamp(tmp_path: Path):
    db = Database(tmp_path / "events.db")
    db.initialize()
    hub = EventHub(db, logging.getLogger("events-test"), limit=100)
    event = hub.emit("live")
    stored = db.recent_events(1)[0]
    assert event["created_at"] == stored["created_at"]


def test_event_limit_is_enforced_after_emit(tmp_path: Path):
    db = Database(tmp_path / "events.db")
    db.initialize()
    for i in range(140):
        db.add_event(f"manual-{i}")
    hub = EventHub(db, logging.getLogger("events-limit-test"), limit=100)
    hub.emit("trigger-trim")
    assert len(db.recent_events(1000)) == 100


def test_trim_runs_periodically_not_on_every_emit(tmp_path: Path):
    db = Database(tmp_path / "events.db")
    db.initialize()
    calls = []
    original = db.trim_events
    db.trim_events = lambda keep: (calls.append(keep), original(keep))[1]
    hub = EventHub(db, logging.getLogger("events-cadence"), limit=100)
    for _ in range(hub.TRIM_EVERY + 2):
        hub.emit("x")
    assert len(calls) == 2
