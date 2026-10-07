import json
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


def connect_ai(client, **extra):
    """Select Cloud.ru and store a dummy key so the assistant is 'connected'."""
    client.put("/api/settings/ai", headers=ACTION, json={"provider": "cloudru", **extra})
    assert client.put("/api/ai/key", headers=ACTION, json={"key": "sk-test-12345678"}).status_code == 200


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
    assert d["avatar"]["shape"] == "soft" and d["ai"]["provider"] == "cloudru" and d["ai"]["has_key"] is False
    r = client.put("/api/settings/avatar", headers=ACTION, json={"shape": "circle", "size": 120, "crop": "full"})
    assert r.json()["shape"] == "circle"
    assert client.get("/api/settings").json()["avatar"]["size"] == 120
    r = client.put("/api/settings/ai", headers=ACTION, json={"provider": "cloudru", "model": "m", "api_key": "leak-me-12345"})
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
    connect_ai(client)
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
    connect_ai(client)
    monkeypatch.setattr("core.ai._http_post_json", lambda u, h, b: {"choices": [{"message": {"content": "да"}}]})
    assert client.post("/api/ai/test", headers=ACTION).json() == {"ok": True, "detail": "да"}
    client.post("/api/chat", headers=ACTION, json={"text": "hi"})
    assert client.delete("/api/chat", headers=ACTION).json()["removed"] == 2
    assert client.delete("/api/chat").status_code == 403


def png_data(size=(300, 500)):
    import base64, io
    from PIL import Image
    out = io.BytesIO()
    Image.new("RGB", size, (180, 60, 90)).save(out, "PNG")
    return "data:image/png;base64," + base64.b64encode(out.getvalue()).decode()


def test_face_upload_edit_activate_delete(tmp_path: Path):
    client, db, _ = make_client(tmp_path)
    establish_session(client)
    r = client.post("/api/avatar/faces", headers=ACTION, json={"name": "Тест", "data": png_data()})
    assert r.status_code == 200
    fid = r.json()["id"]
    faces = r.json()["settings"]["faces"]
    assert [f["id"] for f in faces] == ["default", fid] and faces[1]["url"].startswith("/media/face-")
    assert client.get(faces[1]["url"]).status_code == 200 and client.get(faces[1]["full"]).status_code == 200
    r = client.put(f"/api/avatar/faces/{fid}", headers=ACTION, json={"zoom": 2, "x": 0.5, "y": -0.5})
    new_url = [f for f in r.json()["faces"] if f["id"] == fid][0]["url"]
    assert new_url != faces[1]["url"] and client.get(new_url).status_code == 200
    assert client.get(faces[1]["url"]).status_code == 404  # old render removed
    client.put("/api/settings/avatar", headers=ACTION, json={"active_face": fid, "shape": "rounded"})
    assert client.get("/api/settings").json()["avatar"]["active_face"] == fid
    r = client.delete(f"/api/avatar/faces/{fid}", headers=ACTION)
    assert r.status_code == 200 and [f["id"] for f in r.json()["faces"]] == ["default"]
    assert r.json()["avatar"]["active_face"] == "default"
    assert client.get(new_url).status_code == 404


def test_upload_validation_and_media_path_safety(tmp_path: Path):
    client, _, _ = make_client(tmp_path)
    establish_session(client)
    assert client.post("/api/avatar/faces", headers=ACTION, json={"data": "aGVsbG8="}).status_code == 400
    assert client.post("/api/avatar/faces", headers=ACTION, json={}).status_code == 400
    assert client.put("/api/avatar/faces/default", headers=ACTION, json={}).status_code == 400
    assert client.delete("/api/avatar/faces/zzzzzzzz", headers=ACTION).status_code == 404
    assert client.get("/media/..%2Fsecrets.json").status_code in (404, 422)
    assert client.get("/media/secrets.json").status_code == 404
    assert client.post("/api/avatar/faces", json={"data": png_data()}).status_code == 403
    big = client.post("/api/avatar/faces", headers={**ACTION, "Content-Length": "99999999"}, content=b"{}")
    assert big.status_code == 413


def test_background_upload_and_app_settings(tmp_path: Path):
    client, _, _ = make_client(tmp_path)
    establish_session(client)
    r = client.put("/api/settings/app", headers=ACTION, json={"theme": "light", "accent": "rose", "ui_zoom": 500, "background": "image", "bg_image": "evil.jpg"})
    app = r.json()["app"]
    assert (app["theme"], app["accent"], app["ui_zoom"], app["background"], app["bg_image"]) == ("light", "rose", 130, "glow", "")
    r = client.post("/api/background", headers=ACTION, json={"data": png_data((800, 400))})
    app = r.json()["app"]
    assert app["background"] == "image" and client.get("/media/" + app["bg_image"]).status_code == 200
    r = client.put("/api/settings/app", headers=ACTION, json={"theme": "black", "bg_image": "hacked.png"})
    assert r.json()["app"]["bg_image"] == app["bg_image"]  # file name cannot be set directly
    r = client.delete("/api/background", headers=ACTION)
    assert r.json()["app"]["background"] == "glow" and client.get("/media/" + app["bg_image"]).status_code == 404


def test_memory_endpoints_and_chat_uses_memory(monkeypatch, tmp_path: Path):
    client, db, _ = make_client(tmp_path)
    establish_session(client)
    r = client.post("/api/memory/import", headers=ACTION, json={"filename": "cats.txt", "text": "Пользователь: мою кошку зовут Мурка\nАссистент: запомнила"})
    assert r.json() == {"dialogs": 1, "messages": 2}
    assert client.post("/api/memory/import", headers=ACTION, json={"text": "  "}).status_code == 400
    assert client.get("/api/memory/search?q=кошку").json()["results"]
    info = client.get("/api/memory").json()
    assert info["stats"]["dialogs"] == 1 and info["dialogs"][0]["title"] == "cats"
    sent = {}

    def fake(u, h, b):
        sent["system"] = b["messages"][0]["content"]
        return {"choices": [{"message": {"content": "Мурка"}}]}

    monkeypatch.setattr("core.ai._http_post_json", fake)
    connect_ai(client, use_character=False)
    client.post("/api/chat", headers=ACTION, json={"text": "Как зовут мою кошку?"})
    assert "Мурка" in sent["system"]
    assert client.get("/api/memory").json()["stats"]["learned"] == 2  # chat turn was learned
    client.put("/api/settings/memory", headers=ACTION, json={"enabled": False, "learn_chat": False})
    sent.clear()
    client.post("/api/chat", headers=ACTION, json={"text": "Как зовут мою кошку?"})
    assert "Мурка" not in sent.get("system", "")
    assert client.delete("/api/memory/learned", headers=ACTION).json()["removed"] == 2
    did = info["dialogs"][0]["id"]
    assert client.delete(f"/api/memory/dialogs/{did}", headers=ACTION).status_code == 200
    assert client.delete(f"/api/memory/dialogs/{did}", headers=ACTION).status_code == 404


def test_chat_export_and_calendar_is_gone(tmp_path: Path):
    client, _, _ = make_client(tmp_path)
    establish_session(client)
    assert client.get("/api/calendar?start=2026-10-01&end=2026-10-31").status_code == 404  # the calendar feature was removed
    client.post("/api/chat", headers=ACTION, json={"text": "привет"})
    exp = client.get("/api/chat/export")
    assert exp.status_code == 200 and "attachment" in exp.headers["content-disposition"] and len(exp.json()["messages"]) == 2



def test_stop_discards_the_answer_and_validates_request_id(monkeypatch, tmp_path: Path):
    client, db, _ = make_client(tmp_path)
    establish_session(client)
    connect_ai(client)
    monkeypatch.setattr("core.ai._http_post_json", lambda u, h, b: {"choices": [{"message": {"content": "поздно"}}]})
    assert client.post("/api/chat/cancel", headers=ACTION, json={"request_id": ""}).status_code == 400
    assert client.post("/api/chat/cancel", json={"request_id": "r1"}).status_code == 403
    assert client.post("/api/chat/cancel", headers=ACTION, json={"request_id": "r1"}).json() == {"cancelled": "r1"}
    r = client.post("/api/chat", headers=ACTION, json={"text": "привет", "request_id": "r1"}).json()
    assert r["cancelled"] is True and [m["role"] for m in r["messages"]] == ["user"]
    assert db.chat_count() == 1 and db.memory_stats()["learned"] == 0
    r = client.post("/api/chat", headers=ACTION, json={"text": "ещё раз", "request_id": "r1"}).json()  # the id was consumed
    assert [m["role"] for m in r["messages"]] == ["user", "assistant"]


def test_facts_api_and_extract_requires_connection(tmp_path: Path):
    client, db, _ = make_client(tmp_path)
    establish_session(client)
    assert client.get("/api/memory/facts").json()["facts"] == []
    assert client.post("/api/memory/facts", headers=ACTION, json={"text": "ab"}).status_code == 400
    fid = client.post("/api/memory/facts", headers=ACTION, json={"text": "Любит чай с лимоном", "category": "preference", "importance": 4, "pinned": True}).json()["id"]
    f = client.get("/api/memory/facts").json()["facts"][0]
    assert f["text"] == "Любит чай с лимоном" and f["pinned"] is True and f["source"] == "manual"
    assert client.put(f"/api/memory/facts/{fid}", headers=ACTION, json={"text": "Любит зелёный чай", "importance": 2, "pinned": False}).status_code == 200
    assert client.put("/api/memory/facts/999", headers=ACTION, json={"text": "x y z"}).status_code == 404
    assert client.get("/api/memory").json()["stats"]["facts"] == 1
    assert client.post("/api/memory/extract", headers=ACTION).status_code == 400  # no key yet
    assert client.post("/api/memory/facts", json={"text": "без маркера"}).status_code == 403
    assert client.delete(f"/api/memory/facts/{fid}", headers=ACTION).status_code == 200
    assert client.delete(f"/api/memory/facts/{fid}", headers=ACTION).status_code == 404


def test_chat_remember_command_and_context_injection(monkeypatch, tmp_path: Path):
    from core import brain
    client, db, _ = make_client(tmp_path)
    client.app.state.run_background = lambda fn: fn()  # run background memory work inline so the test is deterministic
    establish_session(client)
    connect_ai(client, use_character=False)
    seen = {"systems": []}

    def fake(u, h, b):
        system = b["messages"][0]["content"] if b["messages"][0]["role"] == "system" else ""
        if system == brain.EXTRACT_SYSTEM:
            return {"choices": [{"message": {"content": json.dumps({"facts": [{"text": "Живёт в Казани", "category": "personal", "importance": 5}]})}}]}
        seen["systems"].append(system)
        return {"choices": [{"message": {"content": "Хорошо, господин."}}]}

    monkeypatch.setattr("core.ai._http_post_json", fake)
    r = client.post("/api/chat", headers=ACTION, json={"text": "Запомни: я живу в Казани"}).json()
    assert r["remembered"] == ["Живёт в Казани"] and [m["role"] for m in r["messages"]] == ["user", "assistant"]
    assert [f["text"] for f in db.list_facts()] == ["Живёт в Казани"]
    client.post("/api/chat", headers=ACTION, json={"text": "Где я живу?"})
    assert "Живёт в Казани" in seen["systems"][-1] and "Сейчас:" in seen["systems"][-1]
    assert db.list_facts()[0]["use_count"] == 1  # the fact was used and counted
    client.put("/api/settings/memory", headers=ACTION, json={"use_facts": False})
    client.post("/api/chat", headers=ACTION, json={"text": "А теперь?"})
    assert "Живёт в Казани" not in seen["systems"][-1]


def test_extract_endpoint_summary_and_clear(monkeypatch, tmp_path: Path):
    from core import brain
    client, db, _ = make_client(tmp_path)
    establish_session(client)
    connect_ai(client)
    for t in ("мою собаку зовут Рекс", "ей три года"):
        db.add_chat_message("user", t); db.add_chat_message("assistant", "ок")
    monkeypatch.setattr("core.ai._http_post_json", lambda u, h, b: {"choices": [{"message": {"content": json.dumps({"facts": [{"text": "Собаку зовут Рекс", "category": "relation", "importance": 4}]})}}]})
    r = client.post("/api/memory/extract", headers=ACTION).json()
    assert r["added"] == 1 and r["texts"] == ["Собаку зовут Рекс"]
    db.set_setting("memory_state", {"summary": "Обсуждали собаку."})
    assert client.get("/api/memory").json()["summary"] == "Обсуждали собаку."
    assert client.delete("/api/memory/summary", headers=ACTION).json() == {"cleared": True}
    assert client.get("/api/memory").json()["summary"] == ""
    assert client.delete("/api/memory/facts", headers=ACTION).json()["removed"] == 1
    monkeypatch.setattr("core.ai._http_post_json", lambda u, h, b: (_ for _ in ()).throw(OSError("down")))
    db.add_chat_message("user", "ещё сообщение")
    assert client.post("/api/memory/extract", headers=ACTION).status_code == 502


def update_zip(version="9.9.9"):
    import io, zipfile
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, content in {"VERSION": version + "\n", "main.py": "print(1)\n", "launcher.pyw": "#\n", "core/__init__.py": "", "core/new.py": "x=1\n", "data/steal.db": "x"}.items():
            z.writestr(f"Aspksa-Kohakuyasha-abc/{name}", content)
    return buf.getvalue()


def test_update_flow_check_install_rollback(monkeypatch, tmp_path: Path):
    from core import updater
    client, db, runtime = make_client(tmp_path)
    establish_session(client)
    state = client.get("/api/update").json()
    assert state["settings"]["repo"] == "Aspksa/Kohakuyasha" and state["info"] is None and state["installed"] == "0.1.1" and "data/" in state["protected"]
    assert client.put("/api/update/settings", json={"repo": "x/y"}).status_code == 403  # needs the same-origin marker
    r = client.put("/api/update/settings", headers=ACTION, json={"repo": "me/proj", "branch": "dev", "auto_check": False}).json()
    assert r["settings"] == {"repo": "me/proj", "branch": "dev", "auto_check": False}

    seen = {}

    def fake_text(repo, branch, path, token, limit=0):
        seen["token"] = token
        return "9.9.9\n" if path == "VERSION" else json.dumps({"version": "9.9.9", "summary": "Большое обновление"}) + "\n"

    monkeypatch.setattr(updater, "fetch_text", fake_text)
    monkeypatch.setattr(updater, "fetch_commit", lambda *a: {"sha": "abc1234", "date": ""})
    monkeypatch.setattr(updater, "fetch_zip", lambda *a: update_zip())
    assert client.put("/api/update/token", headers=ACTION, json={"token": "bad token"}).status_code == 400
    st = client.put("/api/update/token", headers=ACTION, json={"token": "ghp_secret1234567"}).json()
    assert st["has_token"] is True and "secret" not in json.dumps(st)
    info = client.post("/api/update/check", headers=ACTION).json()["info"]
    assert info["newer"] is True and info["remote"] == "9.9.9" and info["notes"][0]["summary"] == "Большое обновление" and seen["token"] == "ghp_secret1234567"
    assert client.get("/api/update").json()["info"]["remote"] == "9.9.9"  # cached

    res = client.post("/api/update/install", headers=ACTION).json()
    assert res["result"]["version"] == "9.9.9" and res["state"]["restart_needed"] is True and [b["to"] for b in res["state"]["backups"]] == ["9.9.9"]
    assert (tmp_path / "VERSION").read_text().strip() == "9.9.9" and not (tmp_path / "data" / "steal.db").exists()
    monkeypatch.setattr(updater, "fetch_zip", lambda *a: update_zip("0.0.1"))
    assert client.post("/api/update/install", headers=ACTION).status_code == 409  # not newer than the running version

    monkeypatch.setattr(updater, "fetch_zip", lambda *a: (_ for _ in ()).throw(updater.UpdateError("Нет связи с GitHub: x")))
    r = client.post("/api/update/install", headers=ACTION)
    assert r.status_code == 502 and "Нет связи" in r.json()["detail"]
    rb = client.post("/api/update/rollback", headers=ACTION).json()
    assert rb["result"]["version"] == "0.1.1" and not (tmp_path / "VERSION").exists() and rb["state"]["backups"] == []  # files the update added are removed again
    assert client.delete("/api/update/token", headers=ACTION).json()["has_token"] is False
    assert client.post("/api/update/restart", headers=ACTION).json() == {"relaunched": False}  # Linux: manual restart


def test_update_errors_are_reported(monkeypatch, tmp_path: Path):
    from core import updater
    client, _, _ = make_client(tmp_path)
    establish_session(client)
    monkeypatch.setattr(updater, "fetch_text", lambda *a, **k: (_ for _ in ()).throw(updater.UpdateError("Репозиторий или ветка не найдены.")))
    r = client.post("/api/update/check", headers=ACTION)
    assert r.status_code == 502 and "не найдены" in r.json()["detail"]
    assert client.post("/api/update/rollback", headers=ACTION).status_code == 409


def test_static_files_use_revalidation_and_media_is_immutable(tmp_path: Path):
    client, _, _ = make_client(tmp_path)
    assert client.get("/static/app.css").headers["cache-control"] == "no-cache"
    assert client.get("/").headers["cache-control"] == "no-store"
    establish_session(client)
    assert client.get("/api/settings").headers["cache-control"] == "no-store"


def test_notifications_update_card_toast_and_actions(monkeypatch, tmp_path: Path):
    from core import updater
    client, db, runtime = make_client(tmp_path)
    toasts = []
    runtime.toast = lambda title, message: toasts.append((title, message))
    establish_session(client)
    assert client.get("/api/status").json()["notifications"] == {"unread": 0, "latest": None}

    monkeypatch.setattr(updater, "fetch_text", lambda repo, branch, path, token, limit=0: "9.9.9\n" if path == "VERSION" else json.dumps({"version": "9.9.9", "summary": "Новое"}) + "\n")
    monkeypatch.setattr(updater, "fetch_commit", lambda *a: {"sha": "abc1234", "date": ""})
    monkeypatch.setattr(updater, "fetch_zip", lambda *a: update_zip())
    client.post("/api/update/check", headers=ACTION)
    client.post("/api/update/check", headers=ACTION)  # the same release is announced only once
    st = client.get("/api/status").json()["notifications"]
    assert st["unread"] == 1 and st["latest"]["kind"] == "update" and "9.9.9" in st["latest"]["title"]
    assert len(toasts) == 1 and "9.9.9" in toasts[0][0]
    cards = client.get("/api/notifications").json()["notifications"]
    assert [a["id"] for a in cards[0]["actions"]] == ["update_install", "update_details", "dismiss"]

    assert client.post("/api/notifications/seen").status_code == 403  # needs the same-origin marker
    assert client.post("/api/notifications/seen", headers=ACTION).json()["seen"] == 1
    assert client.get("/api/status").json()["notifications"]["unread"] == 0 and len(client.get("/api/notifications").json()["notifications"]) == 1

    client.post("/api/update/install", headers=ACTION)  # installing replaces the card with a "restart" card
    cards = client.get("/api/notifications").json()["notifications"]
    assert [c["kind"] for c in cards] == ["restart"] and "9.9.9" in cards[0]["title"]
    assert client.post(f"/api/notifications/{cards[0]['id']}/resolve", headers=ACTION).status_code == 200
    assert client.get("/api/notifications").json()["notifications"] == []
    assert client.post("/api/notifications/999/resolve", headers=ACTION).status_code == 404


def test_toast_can_be_disabled_and_dismissed_release_is_not_repeated(monkeypatch, tmp_path: Path):
    from core import updater
    client, db, runtime = make_client(tmp_path)
    toasts = []
    runtime.toast = lambda title, message: toasts.append(title)
    establish_session(client)
    client.put("/api/settings/app", headers=ACTION, json={"toast": False})
    monkeypatch.setattr(updater, "fetch_text", lambda repo, branch, path, token, limit=0: "9.9.9\n" if path == "VERSION" else "")
    monkeypatch.setattr(updater, "fetch_commit", lambda *a: {"sha": "", "date": ""})
    client.post("/api/update/check", headers=ACTION)
    assert toasts == [] and client.get("/api/status").json()["notifications"]["unread"] == 1
    nid = client.get("/api/notifications").json()["notifications"][0]["id"]
    client.post(f"/api/notifications/{nid}/resolve", headers=ACTION)
    client.post("/api/update/check", headers=ACTION)
    assert client.get("/api/notifications").json()["notifications"] == []  # "later" means: do not nag about the same version


def test_disk_api_end_to_end(tmp_path: Path):
    client, db, runtime = make_client(tmp_path)
    establish_session(client)
    assert client.get("/api/disk/list").status_code == 200
    assert client.post("/api/disk/folder", json={"path": "x"}).status_code == 403  # needs the same-origin marker
    assert client.post("/api/disk/folder", headers=ACTION, json={"path": "Папка"}).status_code == 200
    assert client.post("/api/disk/folder", headers=ACTION, json={"path": "../evil"}).status_code == 400
    body = b"hello " * 400_000  # 2.4 MB, streamed
    up = client.put("/api/disk/upload?path=Папка&name=hello.txt", headers=ACTION, content=body)
    assert up.status_code == 200 and up.json()["size"] == len(body)
    assert client.put("/api/disk/upload?path=Папка&name=..%2Fx.txt", headers=ACTION, content=b"x").status_code == 400
    assert client.put("/api/disk/upload?path=Нет&name=a.txt", headers=ACTION, content=b"x").status_code == 404
    assert [i["name"] for i in client.get("/api/disk/list", params={"path": "Папка"}).json()["items"]] == ["hello.txt"]
    r = client.get("/api/disk/file", params={"path": "Папка/hello.txt"})
    assert r.status_code == 200 and r.content == body and r.headers["content-type"].startswith("text/plain") and "sandbox" in r.headers["content-security-policy"]
    dl = client.get("/api/disk/file", params={"path": "Папка/hello.txt", "download": 1})
    assert dl.headers["content-disposition"].startswith("attachment") and dl.headers["content-type"] == "application/octet-stream"
    client.put("/api/disk/upload?path=&name=page.html", headers=ACTION, content=b"<script>alert(1)</script>")
    h = client.get("/api/disk/file", params={"path": "page.html"})
    assert h.headers["content-disposition"].startswith("attachment") and h.headers["x-content-type-options"] == "nosniff"  # HTML is never rendered inline
    assert client.get("/api/disk/file", params={"path": "../data/kohakuyasha.db"}).status_code == 400
    assert client.get("/api/disk/search", params={"q": "hel"}).json()["items"][0]["path"] == "Папка/hello.txt"
    assert client.post("/api/disk/move", headers=ACTION, json={"from": "Папка/hello.txt", "to": "Папка/hi.txt"}).json()["name"] == "hi.txt"
    d = client.post("/api/disk/delete", headers=ACTION, json={"path": "Папка/hi.txt"}).json()
    trash = client.get("/api/disk/trash").json()
    assert trash["items"][0]["id"] == d["id"]
    assert client.post("/api/disk/restore", headers=ACTION, json={"id": d["id"]}).json()["name"] == "hi.txt"
    assert client.put("/api/disk/settings", headers=ACTION, json={"max_file_mb": 1}).json()["settings"]["max_file_mb"] == 1
    big = client.put("/api/disk/upload?path=&name=big.bin", headers=ACTION, content=b"x" * (2 * 1024 * 1024))
    assert big.status_code == 413
    assert not [p for p in (tmp_path / "data" / "disk" / "files").rglob("*.part")]
    assert client.get("/api/disk").json()["usage"]["files"] >= 2
