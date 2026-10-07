import logging
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from core.api import create_app
from core.config import ConfigStore, Paths
from core.database import Database
from core.events import EventHub
from core.runtime import RuntimeState

ORIGIN = "http://127.0.0.1:8710"
ACTION = {"Origin": ORIGIN, "X-Kohakuyasha-Request": "1"}


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
    events = EventHub(db, logging.getLogger(f"test-{tmp_path.name}"))
    runtime = RuntimeState(paths, "0.1.1", port=8710, status="Наблюдает")
    app = create_app(paths=paths, config=cfg, db=db, events=events, runtime=runtime)
    return TestClient(app, base_url=ORIGIN), db, runtime


def establish_session(client: TestClient):
    r = client.get("/")
    assert r.status_code == 200
    assert "kohakuyasha_session" in client.cookies


def test_host_and_origin_are_rejected(tmp_path: Path):
    client, _, _ = make_client(tmp_path)
    assert client.get("/", headers={"Host": "evil.example"}).status_code == 400
    assert client.get("/", headers={"Origin": "https://evil.example"}).status_code == 403


def test_api_get_requires_local_session(tmp_path: Path):
    client, _, _ = make_client(tmp_path)
    assert client.get("/api/status").status_code == 401
    establish_session(client)
    assert client.get("/api/status").status_code == 200
    assert client.get("/api/events").status_code == 200


def test_cross_origin_mutation_is_rejected_even_with_marker(tmp_path: Path):
    client, _, _ = make_client(tmp_path)
    establish_session(client)
    headers = {"Origin": "https://evil.example", "X-Kohakuyasha-Request": "1"}
    assert client.post("/api/tests/run", headers=headers).status_code == 403


def test_shutdown_requires_same_origin_and_calls_callback(tmp_path: Path):
    client, _, runtime = make_client(tmp_path)
    establish_session(client)
    called = []
    runtime.on_shutdown = lambda: called.append(True)
    r = client.post("/api/system/shutdown", headers=ACTION)
    assert r.status_code == 200
    import time; time.sleep(0.25)
    assert called


def test_autostart_endpoint_can_be_exercised_without_windows(monkeypatch, tmp_path: Path):
    client, _, _ = make_client(tmp_path)
    establish_session(client)
    monkeypatch.setattr("core.api.autostart.disable", lambda: None)
    monkeypatch.setattr("core.api.autostart.is_enabled", lambda: False)
    r = client.post("/api/autostart", headers=ACTION, json={"enabled": False})
    assert r.status_code == 200
    assert r.json() == {"enabled": False}


def test_websocket_requires_same_origin(tmp_path: Path):
    client, _, _ = make_client(tmp_path)
    establish_session(client)
    cookie = client.cookies.get("kohakuyasha_session")
    base_headers = {"Host": "127.0.0.1:8710", "Cookie": f"kohakuyasha_session={cookie}"}
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/ws/events", headers={**base_headers, "Origin": "https://evil.example"}):
            pass
    with client.websocket_connect("/ws/events", headers={**base_headers, "Origin": ORIGIN}) as ws:
        assert ws is not None


def test_failed_diagnostics_restores_status_and_reports_error(monkeypatch, tmp_path: Path):
    client, _, runtime = make_client(tmp_path)
    establish_session(client)

    def boom(self, mode):
        raise RuntimeError("boom")

    monkeypatch.setattr("core.api.Diagnostics.run", boom)
    r = client.post("/api/tests/run?mode=quick", headers=ACTION)
    assert r.status_code == 500
    assert runtime.status == "Наблюдает"


def test_websocket_without_origin_is_rejected(tmp_path: Path):
    client, _, _ = make_client(tmp_path)
    establish_session(client)
    cookie = client.cookies.get("kohakuyasha_session")
    headers = {"Host": "127.0.0.1:8710", "Cookie": f"kohakuyasha_session={cookie}"}
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/ws/events", headers=headers):
            pass


def test_websocket_without_session_is_rejected(tmp_path: Path):
    client, _, _ = make_client(tmp_path)
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/ws/events", headers={"Host": "127.0.0.1:8710", "Origin": ORIGIN}):
            pass


def test_chat_roundtrip_and_validation(tmp_path: Path):
    client, db, _ = make_client(tmp_path)
    establish_session(client)
    assert client.get("/api/chat").json() == {"messages": []}
    r = client.post("/api/chat", headers=ACTION, json={"text": "  привет  "})
    assert r.status_code == 200
    user, answer = r.json()["messages"]
    assert user["role"] == "user" and user["content"] == "привет"
    assert answer["role"] == "assistant" and answer["content"]
    assert [m["role"] for m in client.get("/api/chat").json()["messages"]] == ["user", "assistant"]
    assert client.post("/api/chat", headers=ACTION, json={"text": "   "}).status_code == 400
    assert client.post("/api/chat", headers=ACTION, json={"text": 5}).status_code == 400
    assert client.post("/api/chat", headers=ACTION, json={"text": "x" * 4001}).status_code == 413
    assert db.chat_count() == 2


def test_chat_post_requires_same_origin_marker(tmp_path: Path):
    client, db, _ = make_client(tmp_path)
    establish_session(client)
    assert client.post("/api/chat", json={"text": "hi"}).status_code == 403
    assert client.post("/api/chat", headers={"Origin": "https://evil.example", "X-Kohakuyasha-Request": "1"}, json={"text": "hi"}).status_code == 403
    assert db.chat_count() == 0


def test_character_endpoint(tmp_path: Path):
    client, _, _ = make_client(tmp_path)
    establish_session(client)
    assert client.get("/api/character").json()["character"] == {}
    (tmp_path / "CHARACTER.json").write_text('{"name": "Kohakuyasha", "traits": ["calm"]}', encoding="utf-8")
    data = client.get("/api/character").json()
    assert data["character"]["name"] == "Kohakuyasha"
    assert data["stats"] == {"messages": 0}
    (tmp_path / "CHARACTER.json").write_text("not json", encoding="utf-8")
    assert client.get("/api/character").json()["character"] == {}


def test_settings_roundtrip_and_key_is_never_returned(tmp_path: Path):
    client, db, _ = make_client(tmp_path)
    establish_session(client)
    d = client.get("/api/settings").json()
    assert d["avatar"]["shape"] == "soft" and d["ai"]["provider"] == "none" and d["ai"]["has_key"] is False
    r = client.put("/api/settings/avatar", headers=ACTION, json={"shape": "circle", "size": 120, "crop": "full"})
    assert r.json()["shape"] == "circle"
    assert client.get("/api/settings").json()["avatar"]["size"] == 120
    r = client.put("/api/settings/ai", headers=ACTION, json={"provider": "anthropic", "model": "m", "api_key": "leak-me-12345"})
    assert r.status_code == 200 and "leak-me" not in r.text
    assert client.put("/api/ai/key", headers=ACTION, json={"key": "sk-abcdef123456"}).json()["has_key"] is True
    text = client.get("/api/settings").text
    assert "sk-abcdef" not in text and '"has_key":true' in text.replace(" ", "")
    assert client.put("/api/ai/key", headers=ACTION, json={"key": "bad key"}).status_code == 400
    assert client.delete("/api/ai/key", headers=ACTION).json()["has_key"] is False
    assert client.put("/api/settings/avatar", json={"shape": "circle"}).status_code == 403  # needs same-origin marker


def test_chat_uses_provider_and_reports_errors(monkeypatch, tmp_path: Path):
    client, db, _ = make_client(tmp_path)
    establish_session(client)
    client.put("/api/settings/ai", headers=ACTION, json={"provider": "openai", "base_url": "http://127.0.0.1:1/v1"})
    monkeypatch.setattr("core.ai._http_post_json", lambda u, h, b: {"choices": [{"message": {"content": "**Да**, господин"}}]})
    r = client.post("/api/chat", headers=ACTION, json={"text": "ты здесь?"}).json()
    assert [m["role"] for m in r["messages"]] == ["user", "assistant"] and "Да" in r["messages"][1]["content"]

    def boom(u, h, b):
        raise OSError("down")

    monkeypatch.setattr("core.ai._http_post_json", boom)
    r = client.post("/api/chat", headers=ACTION, json={"text": "ещё"}).json()
    assert [m["role"] for m in r["messages"]] == ["user"] and "Нет связи" in r["error"]
    assert db.chat_count() == 3


def test_ai_test_endpoint_and_chat_clear(monkeypatch, tmp_path: Path):
    client, db, _ = make_client(tmp_path)
    establish_session(client)
    assert client.post("/api/ai/test", headers=ACTION).json()["ok"] is False
    client.put("/api/settings/ai", headers=ACTION, json={"provider": "openai", "base_url": "http://127.0.0.1:1/v1"})
    monkeypatch.setattr("core.ai._http_post_json", lambda u, h, b: {"choices": [{"message": {"content": "да"}}]})
    assert client.post("/api/ai/test", headers=ACTION).json() == {"ok": True, "detail": "да"}
    client.post("/api/chat", headers=ACTION, json={"text": "hi"})
    assert client.delete("/api/chat", headers=ACTION).json()["removed"] == 2
    assert client.delete("/api/chat").status_code == 403
