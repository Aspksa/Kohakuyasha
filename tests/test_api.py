import logging
from pathlib import Path

from fastapi.testclient import TestClient

from core.api import create_app
from core.config import ConfigStore, Paths
from core.database import Database
from core.events import EventHub
from core.runtime import RuntimeState


def make_client(tmp_path: Path):
    web = tmp_path / "web"
    static = web / "static"
    static.mkdir(parents=True)
    (web / "index.html").write_text("<html>Kohakuyasha</html>", encoding="utf-8")
    (static / "app.css").write_text("", encoding="utf-8")
    paths = Paths(tmp_path)
    cfg = ConfigStore(paths)
    db = Database(paths.database)
    db.initialize()
    logger = logging.getLogger(f"test-{tmp_path.name}")
    events = EventHub(db, logger)
    runtime = RuntimeState(paths, "0.1.0", port=8710, status="Наблюдает")
    app = create_app(paths=paths, config=cfg, db=db, events=events, runtime=runtime)
    return TestClient(app), db


def test_status_and_events(tmp_path: Path):
    client, db = make_client(tmp_path)
    db.add_event("hello", event_type="test")
    status = client.get("/api/status")
    assert status.status_code == 200
    assert status.json()["runtime"]["version"] == "0.1.0"
    events = client.get("/api/events?limit=10")
    assert events.status_code == 200
    assert events.json()["events"][-1]["message"] == "hello"


def test_mutation_requires_local_header(tmp_path: Path):
    client, _ = make_client(tmp_path)
    denied = client.post("/api/tests/run?mode=quick")
    assert denied.status_code == 403
