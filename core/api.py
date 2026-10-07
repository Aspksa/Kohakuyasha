from __future__ import annotations

import asyncio
import json
import re
import secrets as pysecrets
import threading
import time
from dataclasses import asdict
from typing import Any

from fastapi import Body, FastAPI, Header, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from . import ai, assistant, autostart, media, memory, prefs
from .config import ConfigStore, Paths
from .database import Database
from .diagnostics import Diagnostics
from .events import EventHub
from .runtime import RuntimeState
from .security import ACTION_HEADER, SESSION_COOKIE, is_allowed_host_header, is_allowed_origin, session_matches


def create_app(*, paths: Paths, config: ConfigStore, db: Database, events: EventHub, runtime: RuntimeState) -> FastAPI:
    app = FastAPI(title="Kohakuyasha", docs_url=None, redoc_url=None, openapi_url=None)
    app.mount("/static", StaticFiles(directory=paths.static), name="static")
    diagnostics_lock = asyncio.Lock()
    cancelled_requests: dict[str, float] = {}
    secrets = ai.SecretStore(paths.secrets)

    def load_character() -> dict:
        try:
            data = json.loads(paths.character.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    def ai_settings() -> ai.AISettings:
        return ai.validate_ai(db.get_setting("ai"))

    def avatar_settings() -> prefs.AvatarSettings:
        return prefs.validate_avatar(db.get_setting("avatar"))

    def app_settings() -> prefs.AppSettings:
        return prefs.validate_app(db.get_setting("app"))

    def memory_settings() -> prefs.MemorySettings:
        return prefs.validate_memory(db.get_setting("memory"))

    store = media.MediaStore(paths.media)
    MAX_FACES = 12
    MAX_BODY = 9_000_000

    def faces_list() -> list[dict]:
        raw = db.get_setting("faces", [])
        return [f for f in raw if isinstance(f, dict) and prefs.FACE_ID_RE.match(str(f.get("id", "")))] if isinstance(raw, list) else []

    def face_public(f: dict) -> dict:
        return {
            "id": f["id"], "name": f.get("name", "Лицо"), "builtin": False,
            "url": f"/media/{f['file']}", "small": f"/media/{f['file']}", "full": f"/media/{f['orig']}",
            "zoom": f.get("zoom", 1.0), "x": f.get("x", 0.0), "y": f.get("y", 0.0), "w": f.get("w", 1), "h": f.get("h", 1),
        }

    def all_faces() -> list[dict]:
        default = {
            "id": "default", "name": "Kohakuyasha", "builtin": True, "url": "/static/avatar.png",
            "small": "/static/avatar-small.png", "full": "/static/avatar-full.png", "zoom": 1.0, "x": 0.0, "y": 0.0, "w": 1, "h": 1,
        }
        return [default] + [face_public(f) for f in faces_list()]

    def all_settings() -> dict:
        avatar = avatar_settings()
        if avatar.active_face != "default" and not any(f["id"] == avatar.active_face for f in faces_list()):
            avatar.active_face = "default"
        app_cfg = asdict(app_settings())
        app_cfg["open_browser"] = config.load().open_browser
        return {
            "avatar": asdict(avatar), "faces": all_faces(), "ai": ai.public_ai(ai_settings(), secrets),
            "app": app_cfg, "memory": asdict(memory_settings()),
        }

    def security_headers(response: Response) -> Response:
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Cache-Control"] = "no-store"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; img-src 'self'; style-src 'self'; script-src 'self'; "
            "connect-src 'self' ws://127.0.0.1:* ws://localhost:*; "
            "frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
        )
        return response

    @app.middleware("http")
    async def security_guard(request: Request, call_next):
        if not is_allowed_host_header(request.headers.get("host"), runtime.port):
            return security_headers(JSONResponse({"detail": "Недопустимый Host."}, status_code=400))

        origin = request.headers.get("origin")
        if origin and not is_allowed_origin(origin, runtime.port):
            return security_headers(JSONResponse({"detail": "Недопустимый Origin."}, status_code=403))

        if request.url.path.startswith("/api/"):
            try:
                too_big = int(request.headers.get("content-length") or 0) > MAX_BODY
            except ValueError:
                too_big = True
            if too_big:
                return security_headers(JSONResponse({"detail": "Запрос слишком большой."}, status_code=413))
            token = request.cookies.get(SESSION_COOKIE)
            if not session_matches(token, runtime.session_token):
                return security_headers(JSONResponse({"detail": "Требуется локальная сессия."}, status_code=401))
            if request.method not in {"GET", "HEAD", "OPTIONS"}:
                if not origin or not is_allowed_origin(origin, runtime.port):
                    return security_headers(JSONResponse({"detail": "Для изменения требуется same-origin запрос."}, status_code=403))
                if request.headers.get(ACTION_HEADER) != "1":
                    return security_headers(JSONResponse({"detail": "Маркер локального действия отсутствует."}, status_code=403))

        response = await call_next(request)
        return security_headers(response)

    @app.get("/")
    async def index():
        response = FileResponse(paths.web / "index.html")
        response.set_cookie(
            SESSION_COOKIE,
            runtime.session_token,
            httponly=True,
            secure=False,
            samesite="strict",
            path="/",
        )
        return response

    @app.get("/api/status")
    async def status():
        settings, snap, autostart_enabled = await asyncio.gather(
            asyncio.to_thread(config.load),
            asyncio.to_thread(runtime.snapshot),
            asyncio.to_thread(autostart.is_enabled),
        )
        return {
            "runtime": snap,
            "settings": {
                "language": settings.language,
                "open_browser": settings.open_browser,
                "minimize_to_tray": settings.minimize_to_tray,
                "autostart": autostart_enabled,
            },
            "services": {
                "core": "ONLINE",
                "database": "READY" if paths.database.exists() else "INIT",
                "web": "LOCAL",
                "watchdog": "ACTIVE" if snap["watchdog_active"] else "OFF",
            },
        }

    @app.get("/api/character")
    async def character():
        profile, messages = await asyncio.gather(asyncio.to_thread(load_character), asyncio.to_thread(db.chat_count))
        return {"character": profile, "stats": {"messages": messages}}

    @app.get("/api/settings")
    async def get_settings():
        return await asyncio.to_thread(all_settings)

    @app.put("/api/settings/avatar")
    async def put_avatar(payload: dict[str, Any] = Body(...)):
        settings = prefs.validate_avatar(payload)
        if settings.active_face != "default" and not any(f["id"] == settings.active_face for f in faces_list()):
            settings.active_face = "default"
        await asyncio.to_thread(db.set_setting, "avatar", asdict(settings))
        return asdict(settings)

    @app.put("/api/settings/app")
    async def put_app(payload: dict[str, Any] = Body(...)):
        current = app_settings()
        merged = {**asdict(current), **{k: v for k, v in payload.items() if k in asdict(current)}}
        merged["bg_image"] = current.bg_image  # the file is managed only via /api/background
        settings = prefs.validate_app(merged)
        if settings.background == "image" and not store.path(settings.bg_image):
            settings.background = "glow"
        await asyncio.to_thread(db.set_setting, "app", asdict(settings))
        if isinstance(payload.get("open_browser"), bool):
            await asyncio.to_thread(config.update, open_browser=payload["open_browser"])
        return await asyncio.to_thread(all_settings)

    @app.put("/api/settings/memory")
    async def put_memory(payload: dict[str, Any] = Body(...)):
        settings = prefs.validate_memory(payload)
        await asyncio.to_thread(db.set_setting, "memory", asdict(settings))
        return asdict(settings)

    # ---------- media: faces and background ----------
    @app.get("/media/{name}")
    async def serve_media(name: str):
        path = store.path(name)
        if not path:
            return JSONResponse({"detail": "Не найдено."}, status_code=404)
        return FileResponse(path)

    def rev_of(zoom: float, x: float, y: float) -> str:
        return media.short_hash(f"{zoom:.3f}|{x:.3f}|{y:.3f}".encode(), 6)

    def clamp_params(payload: dict) -> tuple[float, float, float]:
        def num(key: str, default: float, lo: float, hi: float) -> float:
            v = payload.get(key, default)
            return min(max(float(v), lo), hi) if isinstance(v, (int, float)) and not isinstance(v, bool) else default
        return num("zoom", 1.0, 1.0, 4.0), num("x", 0.0, -1.0, 1.0), num("y", 0.0, -1.0, 1.0)

    def create_face(payload: dict) -> dict:
        faces = faces_list()
        if len(faces) >= MAX_FACES:
            raise media.MediaError(f"Можно хранить не больше {MAX_FACES} лиц.")
        raw = media.decode_upload(payload.get("data"))
        img = media.open_image(raw)
        orig_bytes, ext = media.encode(img, 1280, quality=92)
        fid = pysecrets.token_hex(4)
        orig = store.save(f"face-{fid}-orig-{media.short_hash(orig_bytes, 8)}.{ext}", orig_bytes)
        loaded = media.open_image(orig_bytes)
        w, h = loaded.size
        y0 = -0.35 if h > w else 0.0
        file = f"face-{fid}-{rev_of(1.0, 0.0, y0)}.png"
        store.save(file, media.render_face(loaded, 1.0, 0.0, y0))
        name = str(payload.get("name") or "Моё лицо").strip()[:60] or "Моё лицо"
        face = {"id": fid, "name": name, "orig": orig, "file": file, "zoom": 1.0, "x": 0.0, "y": y0, "w": w, "h": h}
        db.set_setting("faces", faces + [face])
        return face

    def update_face(fid: str, payload: dict) -> dict | None:
        faces = faces_list()
        face = next((f for f in faces if f["id"] == fid), None)
        if not face:
            return None
        zoom, x, y = clamp_params(payload)
        loaded = media.open_image(store.read(face["orig"]) or b"")
        old = face["file"]
        face.update(zoom=zoom, x=x, y=y, file=f"face-{fid}-{rev_of(zoom, x, y)}.png")
        store.save(face["file"], media.render_face(loaded, zoom, x, y))
        if old != face["file"]:
            store.delete(old)
        if isinstance(payload.get("name"), str) and payload["name"].strip():
            face["name"] = payload["name"].strip()[:60]
        db.set_setting("faces", faces)
        return face

    def remove_face(fid: str) -> bool:
        faces = faces_list()
        face = next((f for f in faces if f["id"] == fid), None)
        if not face:
            return False
        store.delete(face["file"])
        store.delete(face["orig"])
        db.set_setting("faces", [f for f in faces if f["id"] != fid])
        avatar = avatar_settings()
        if avatar.active_face == fid:
            avatar.active_face = "default"
            db.set_setting("avatar", asdict(avatar))
        return True

    @app.post("/api/avatar/faces")
    async def add_face(payload: dict[str, Any] = Body(...)):
        try:
            face = await asyncio.to_thread(create_face, payload)
        except media.MediaError as exc:
            return JSONResponse({"detail": str(exc)}, status_code=400)
        events.emit("Добавлено новое лицо аватара", event_type="settings")
        return {"id": face["id"], "settings": await asyncio.to_thread(all_settings)}

    @app.put("/api/avatar/faces/{fid}")
    async def edit_face(fid: str, payload: dict[str, Any] = Body(...)):
        if not prefs.FACE_ID_RE.match(fid) or fid == "default":
            return JSONResponse({"detail": "Это лицо нельзя изменить."}, status_code=400)
        try:
            face = await asyncio.to_thread(update_face, fid, payload)
        except media.MediaError as exc:
            return JSONResponse({"detail": str(exc)}, status_code=400)
        if face is None:
            return JSONResponse({"detail": "Лицо не найдено."}, status_code=404)
        return await asyncio.to_thread(all_settings)

    @app.delete("/api/avatar/faces/{fid}")
    async def delete_face(fid: str):
        if not prefs.FACE_ID_RE.match(fid) or fid == "default" or not await asyncio.to_thread(remove_face, fid):
            return JSONResponse({"detail": "Лицо не найдено."}, status_code=404)
        return await asyncio.to_thread(all_settings)

    def set_background(payload: dict) -> None:
        raw = media.decode_upload(payload.get("data"))
        img = media.open_image(raw)
        data, _ = media.encode(img, 1920, force_jpeg=True, quality=85)
        name = store.save(f"bg-{media.short_hash(data)}.jpg", data)
        current = app_settings()
        if current.bg_image and current.bg_image != name:
            store.delete(current.bg_image)
        current.bg_image, current.background = name, "image"
        db.set_setting("app", asdict(current))

    @app.post("/api/background")
    async def upload_background(payload: dict[str, Any] = Body(...)):
        try:
            await asyncio.to_thread(set_background, payload)
        except media.MediaError as exc:
            return JSONResponse({"detail": str(exc)}, status_code=400)
        return await asyncio.to_thread(all_settings)

    @app.delete("/api/background")
    async def delete_background():
        def run() -> None:
            current = app_settings()
            store.delete(current.bg_image)
            current.bg_image, current.background = "", "glow"
            db.set_setting("app", asdict(current))
        await asyncio.to_thread(run)
        return await asyncio.to_thread(all_settings)

    @app.put("/api/settings/ai")
    async def put_ai(payload: dict[str, Any] = Body(...)):
        settings = ai.validate_ai(payload)
        await asyncio.to_thread(db.set_setting, "ai", asdict(settings))
        events.emit("Настройки ИИ обновлены", event_type="settings", payload={"provider": settings.provider})
        return await asyncio.to_thread(ai.public_ai, settings, secrets)

    @app.put("/api/ai/key")
    async def put_key(payload: dict[str, Any] = Body(...)):
        key = payload.get("key")
        try:
            if not isinstance(key, str):
                raise ValueError
            await asyncio.to_thread(secrets.set_key, key)
        except ValueError:
            return JSONResponse({"detail": "Некорректный ключ."}, status_code=400)
        events.emit("API-ключ ИИ сохранён", event_type="settings")
        return {"has_key": True, "key_hint": secrets.hint()}

    @app.delete("/api/ai/key")
    async def delete_key():
        await asyncio.to_thread(secrets.delete_key)
        events.emit("API-ключ ИИ удалён", event_type="settings")
        return {"has_key": False, "key_hint": ""}

    @app.post("/api/ai/test")
    async def test_ai():
        settings = await asyncio.to_thread(ai_settings)
        if settings.provider == "none":
            return {"ok": False, "detail": "ИИ отключён в настройках."}
        try:
            text = await asyncio.to_thread(
                ai.complete, settings, secrets.get_key(), "", [{"role": "user", "content": "Ответь одним словом: готова?"}]
            )
        except ai.AIError as exc:
            return {"ok": False, "detail": str(exc)}
        return {"ok": True, "detail": text[:200]}

    @app.get("/api/chat")
    async def chat_history(limit: int = 100):
        return {"messages": await asyncio.to_thread(db.recent_chat, limit)}

    @app.delete("/api/chat")
    async def chat_clear():
        removed = await asyncio.to_thread(db.clear_chat)
        events.emit("История чата очищена", event_type="chat", payload={"removed": removed})
        return {"removed": removed}

    @app.post("/api/chat")
    async def chat_send(payload: dict[str, Any] = Body(...)):
        text = payload.get("text")
        if not isinstance(text, str) or not text.strip():
            return JSONResponse({"detail": "Пустое сообщение."}, status_code=400)
        text = text.strip()
        if len(text) > 4000:
            return JSONResponse({"detail": "Сообщение длиннее 4000 символов."}, status_code=413)
        user_message = await asyncio.to_thread(db.add_chat_message, "user", text)
        settings = await asyncio.to_thread(ai_settings)
        mem = await asyncio.to_thread(memory_settings)
        history = await asyncio.to_thread(db.recent_chat, 60)
        ready = settings.provider != "none" and secrets.has_key()
        snippets = await asyncio.to_thread(db.search_memory, text, mem.max_snippets) if mem.enabled and ready else []
        character_data = await asyncio.to_thread(load_character)
        rid = payload.get("request_id") if isinstance(payload.get("request_id"), str) else ""
        try:
            answer = await asyncio.to_thread(assistant.reply, settings, secrets.get_key(), character_data, history, snippets)
        except ai.AIError as exc:
            cancelled_requests.pop(rid, None)
            return {"messages": [user_message], "error": str(exc)}
        if rid and cancelled_requests.pop(rid, None) is not None:
            # The user pressed "Stop" while the provider was working: the call cannot be aborted mid-flight, so its answer is discarded.
            return {"messages": [user_message], "cancelled": True}
        assistant_message = await asyncio.to_thread(db.add_chat_message, "assistant", answer)
        if mem.learn_chat and ready:
            await asyncio.to_thread(db.add_learned, "user", text)
            await asyncio.to_thread(db.add_learned, "assistant", answer)
        return {"messages": [user_message, assistant_message]}

    @app.post("/api/chat/cancel")
    async def chat_cancel(payload: dict[str, Any] = Body(...)):
        rid = payload.get("request_id")
        if not isinstance(rid, str) or not 0 < len(rid) <= 64:
            return JSONResponse({"detail": "Нужен request_id."}, status_code=400)
        now = time.monotonic()
        for key in [k for k, t in cancelled_requests.items() if now - t > 600]:
            cancelled_requests.pop(key, None)
        cancelled_requests[rid] = now
        return {"cancelled": rid}

    @app.get("/api/chat/export")
    async def chat_export():
        messages = await asyncio.to_thread(db.recent_chat, 500)
        return Response(
            content=json.dumps({"project": "Kohakuyasha", "messages": messages}, ensure_ascii=False, indent=2),
            media_type="application/json",
            headers={"Content-Disposition": "attachment; filename=kohakuyasha-chat.json"},
        )

    # ---------- memory ----------
    @app.get("/api/memory")
    async def get_memory():
        def build() -> dict:
            return {"settings": asdict(memory_settings()), "stats": db.memory_stats(), "dialogs": db.list_dialogs()}
        return await asyncio.to_thread(build)

    @app.post("/api/memory/import")
    async def import_memory(payload: dict[str, Any] = Body(...)):
        text, filename = payload.get("text"), str(payload.get("filename") or "")[:200]
        title = str(payload.get("title") or "").strip()[:120]
        if isinstance(text, str) and len(text) > 5_000_000:
            return JSONResponse({"detail": "Текст длиннее 5 МБ."}, status_code=413)
        try:
            convs = await asyncio.to_thread(memory.parse_import, title or filename, text)
        except memory.ImportError_ as exc:
            return JSONResponse({"detail": str(exc)}, status_code=400)
        source = "text" if any(m["role"] == "note" for c in convs for m in c["messages"]) else "dialog"

        def store_all() -> int:
            total = 0
            for conv in convs:
                db.add_dialog(conv["title"], source, conv["messages"])
                total += len(conv["messages"])
            return total

        total = await asyncio.to_thread(store_all)
        events.emit("Импортирована память", event_type="memory", payload={"dialogs": len(convs), "messages": total})
        return {"dialogs": len(convs), "messages": total}

    @app.delete("/api/memory/dialogs/{dialog_id}")
    async def delete_dialog(dialog_id: int):
        if not await asyncio.to_thread(db.delete_dialog, dialog_id):
            return JSONResponse({"detail": "Диалог не найден."}, status_code=404)
        return {"deleted": dialog_id}

    @app.delete("/api/memory/learned")
    async def clear_learned():
        return {"removed": await asyncio.to_thread(db.clear_learned)}

    @app.get("/api/memory/search")
    async def search_memory(q: str = "", limit: int = 6):
        return {"results": await asyncio.to_thread(db.search_memory, q[:500], limit, 0)}

    # ---------- calendar notes ----------
    DAY_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

    @app.get("/api/calendar")
    async def calendar_range(start: str = "", end: str = ""):
        if not (DAY_RE.match(start) and DAY_RE.match(end)):
            return JSONResponse({"detail": "Нужны даты start и end в формате ГГГГ-ММ-ДД."}, status_code=400)
        return {"notes": await asyncio.to_thread(db.list_event_notes, start, end)}

    @app.post("/api/calendar")
    async def calendar_add(payload: dict[str, Any] = Body(...)):
        day, text = payload.get("day"), payload.get("text")
        if not (isinstance(day, str) and DAY_RE.match(day)) or not isinstance(text, str) or not text.strip():
            return JSONResponse({"detail": "Нужны дата и текст заметки."}, status_code=400)
        if await asyncio.to_thread(db.day_note_count, day) >= 50:
            return JSONResponse({"detail": "На один день можно добавить не больше 50 заметок."}, status_code=400)
        return await asyncio.to_thread(db.add_event_note, day, text.strip()[:300])

    @app.delete("/api/calendar/{note_id}")
    async def calendar_delete(note_id: int):
        if not await asyncio.to_thread(db.delete_event_note, note_id):
            return JSONResponse({"detail": "Заметка не найдена."}, status_code=404)
        return {"deleted": note_id}

    @app.get("/api/events")
    async def recent_events(limit: int = 80):
        return {"events": await asyncio.to_thread(db.recent_events, limit)}

    @app.post("/api/tests/run")
    async def run_tests(mode: str = "quick", x_kohakuyasha_request: str | None = Header(default=None)):
        mode = "full" if mode == "full" else "quick"
        if diagnostics_lock.locked():
            return JSONResponse({"detail": "Диагностика уже выполняется."}, status_code=409)
        async with diagnostics_lock:
            runtime.set_status("Тестирование", f"{'Полная' if mode == 'full' else 'Быстрая'} диагностика")
            events.emit("Запущена диагностика", event_type="diagnostics", payload={"mode": mode})
            try:
                result = await asyncio.to_thread(Diagnostics(paths.root, db, config.load().host, runtime.port).run, mode)
            except Exception as exc:
                events.emit(f"Диагностика прервана: {exc}", level="ERROR", event_type="diagnostics")
                return JSONResponse({"detail": "Диагностика завершилась ошибкой."}, status_code=500)
            finally:
                runtime.set_status("Наблюдает", "Готова к работе")
            runtime.last_test_summary = result
            events.emit(
                f"Диагностика завершена: {result['passed']}/{result['total']}",
                level="INFO" if result["ok"] else "WARNING",
                event_type="diagnostics",
                payload=result,
            )
            return result

    @app.post("/api/autostart")
    async def set_autostart(payload: dict[str, Any], x_kohakuyasha_request: str | None = Header(default=None)):
        enabled = bool(payload.get("enabled"))
        if enabled:
            await asyncio.to_thread(autostart.enable, paths.root)
        else:
            await asyncio.to_thread(autostart.disable)
        settings = await asyncio.to_thread(config.load)
        settings.autostart = enabled
        await asyncio.to_thread(config.save, settings)
        actual = await asyncio.to_thread(autostart.is_enabled)
        events.emit("Автозапуск включён" if actual else "Автозапуск отключён", event_type="settings")
        return {"enabled": actual}

    @app.get("/api/diagnostics/export")
    async def export_diagnostics():
        settings, snap, integrity, recent = await asyncio.gather(
            asyncio.to_thread(config.load),
            asyncio.to_thread(runtime.snapshot),
            asyncio.to_thread(db.integrity_check),
            asyncio.to_thread(db.recent_events, 250),
        )
        report = {
            "project": "Kohakuyasha",
            "runtime": snap,
            "database_integrity": integrity,
            "settings": {
                "language": settings.language,
                "host": settings.host,
                "port": settings.port,
                "open_browser": settings.open_browser,
                "minimize_to_tray": settings.minimize_to_tray,
                "autostart": await asyncio.to_thread(autostart.is_enabled),
            },
            "events": recent,
        }
        return Response(
            content=json.dumps(report, ensure_ascii=False, indent=2),
            media_type="application/json",
            headers={"Content-Disposition": "attachment; filename=kohakuyasha-diagnostics.json"},
        )

    @app.post("/api/system/restart")
    async def restart(x_kohakuyasha_request: str | None = Header(default=None)):
        events.emit("Запрошен перезапуск ядра", event_type="system")
        if runtime.on_restart:
            threading.Timer(0.2, runtime.on_restart).start()
        return {"accepted": bool(runtime.on_restart)}

    @app.post("/api/system/shutdown")
    async def shutdown(x_kohakuyasha_request: str | None = Header(default=None)):
        events.emit("Запрошено завершение Kohakuyasha", event_type="system")
        if runtime.on_shutdown:
            threading.Timer(0.2, runtime.on_shutdown).start()
        return {"accepted": bool(runtime.on_shutdown)}

    @app.websocket("/ws/events")
    async def websocket_events(websocket: WebSocket):
        if not is_allowed_host_header(websocket.headers.get("host"), runtime.port):
            await websocket.close(code=1008)
            return
        if not is_allowed_origin(websocket.headers.get("origin"), runtime.port):
            await websocket.close(code=1008)
            return
        if not session_matches(websocket.cookies.get(SESSION_COOKIE), runtime.session_token):
            await websocket.close(code=1008)
            return
        await websocket.accept()
        subscription = events.subscribe()
        queue = subscription[1]
        try:
            while True:
                event = await queue.get()
                await websocket.send_text(json.dumps(event, ensure_ascii=False))
        except WebSocketDisconnect:
            pass
        finally:
            events.unsubscribe(subscription)

    return app
