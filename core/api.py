from __future__ import annotations

import asyncio
import json
import os
import re
import secrets as pysecrets
import threading
import time
from dataclasses import asdict
from typing import Any

from fastapi import Body, FastAPI, Header, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from . import ai, assistant, autostart, brain, disk as disk_mod, media, memory, notifier as notifier_mod, prefs, updater
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
    app.state.run_background = lambda fn: threading.Thread(target=fn, daemon=True, name="kohakuyasha-memory").start()
    secrets = ai.SecretStore(paths.secrets)
    notifier = notifier_mod.Notifier(db, runtime, events)

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
    disk_store = disk_mod.DiskStore(paths.disk)

    def disk_settings() -> dict[str, int]:
        return disk_mod.validate_settings(db.get_setting("disk"))

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

    def security_headers(response: Response, path: str = "") -> Response:
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        if path.startswith("/media/"):
            response.headers["Cache-Control"] = "public, max-age=31536000, immutable"  # content-addressed names never change
        elif path.startswith("/static/"):
            response.headers["Cache-Control"] = "no-cache"  # revalidate by ETag: cheap 304s, instant updates after an upgrade
        else:
            response.headers["Cache-Control"] = "no-store"
        if "content-security-policy" not in response.headers:
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
            is_upload = request.url.path == "/api/disk/upload"
            try:
                length = int(request.headers.get("content-length") or 0)
                too_big = length > (disk_settings()["max_file_mb"] * 1024 * 1024 if is_upload else MAX_BODY)
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
        return security_headers(response, request.url.path)

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
        settings, snap, autostart_enabled, unread = await asyncio.gather(
            asyncio.to_thread(config.load),
            asyncio.to_thread(runtime.snapshot),
            asyncio.to_thread(autostart.is_enabled),
            asyncio.to_thread(db.unread_notifications),
        )
        latest = unread[-1] if unread else None
        return {
            "notifications": {"unread": len(unread), "latest": {"id": latest["id"], "kind": latest["kind"], "title": latest["title"]} if latest else None},
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
        return {"has_key": True, "key_hint": secrets.hint("api_key")}

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
        ready = settings.provider != "none" and secrets.has_key()
        history = await asyncio.to_thread(brain.history_window, db, mem)
        memory_query = brain.contextual_query(text, history)
        if mem.enabled and ready:
            semantic_query = brain.semantic_expand_query(memory_query)
            candidate_limit = min(20, max(mem.max_snippets * 3, mem.max_snippets))
            candidates = await asyncio.to_thread(db.search_memory, semantic_query, candidate_limit)
            snippets = brain.rank_memory_snippets(candidates, memory_query, mem.max_snippets)
        else:
            snippets = []
        blocks, used_facts = (await asyncio.to_thread(brain.build_context, db, mem, text, None, history)) if ready else ([], [])
        character_data = await asyncio.to_thread(load_character)
        rid = payload.get("request_id") if isinstance(payload.get("request_id"), str) else ""
        try:
            answer = await asyncio.to_thread(assistant.reply, settings, secrets.get_key(), character_data, history, snippets, blocks)
        except ai.AIError as exc:
            cancelled_requests.pop(rid, None)
            return {"messages": [user_message], "error": str(exc)}
        if rid and cancelled_requests.pop(rid, None) is not None:
            # The user pressed "Stop" while the provider was working: the call cannot be aborted mid-flight, so its answer is discarded.
            return {"messages": [user_message], "cancelled": True}
        assistant_message = await asyncio.to_thread(db.add_chat_message, "assistant", answer)
        out: dict[str, Any] = {"messages": [user_message, assistant_message]}
        if not ready or answer == assistant.NOT_CONNECTED:
            return out
        if used_facts:
            await asyncio.to_thread(db.touch_facts, used_facts)
        if mem.learn_chat:
            await asyncio.to_thread(db.add_learned, "user", text)
            await asyncio.to_thread(db.add_learned, "assistant", answer)

        def notify(level: str, message: str) -> None:
            events.emit(message, level=level, event_type="memory")

        key = secrets.get_key()
        explicit = brain.explicit_remember(text)
        if explicit:
            # "Запомни ..." is answered with confirmation of what was stored, so extract right away.
            result = await asyncio.to_thread(brain.run_maintenance, db, settings, key, mem, force=True, explicit=explicit, notify=notify)
            if result["texts"]:
                out["remembered"] = result["texts"]
        elif mem.auto_facts or mem.use_summary:
            app.state.run_background(lambda: brain.run_maintenance(db, settings, key, mem, notify=notify))
        return out

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
            state = db.get_setting("memory_state", {}) or {}
            stats = {**db.memory_stats(), "facts": db.fact_count()}
            return {"settings": asdict(memory_settings()), "stats": stats, "dialogs": db.list_dialogs(), "summary": state.get("summary", "")}
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

    # ---------- facts (what the assistant knows about the user) ----------
    @app.get("/api/memory/facts")
    async def get_facts():
        return {"facts": await asyncio.to_thread(db.list_facts, 500), "categories": list(db.FACT_CATEGORIES)}

    @app.post("/api/memory/facts")
    async def add_fact(payload: dict[str, Any] = Body(...)):
        text = payload.get("text")
        if not isinstance(text, str) or not 3 <= len(text.strip()) <= 300:
            return JSONResponse({"detail": "Факт должен быть от 3 до 300 символов."}, status_code=400)
        importance = payload.get("importance")
        fid = await asyncio.to_thread(
            db.add_fact, text.strip(), str(payload.get("category") or "other"),
            importance if isinstance(importance, int) and not isinstance(importance, bool) else 3, "manual", bool(payload.get("pinned")),
        )
        return {"id": fid}

    @app.put("/api/memory/facts/{fact_id}")
    async def edit_fact(fact_id: int, payload: dict[str, Any] = Body(...)):
        if not await asyncio.to_thread(lambda: db.update_fact(fact_id, **{k: payload.get(k) for k in ("text", "category", "importance", "pinned") if k in payload})):
            return JSONResponse({"detail": "Факт не найден или нечего менять."}, status_code=404)
        return {"updated": fact_id}

    @app.delete("/api/memory/facts/{fact_id}")
    async def remove_fact(fact_id: int):
        if not await asyncio.to_thread(db.delete_fact, fact_id):
            return JSONResponse({"detail": "Факт не найден."}, status_code=404)
        return {"deleted": fact_id}

    @app.delete("/api/memory/facts")
    async def clear_facts(scope: str = "auto"):
        return {"removed": await asyncio.to_thread(db.clear_facts, None if scope == "all" else "auto")}

    @app.post("/api/memory/extract")
    async def extract_now():
        settings, mem = await asyncio.to_thread(ai_settings), await asyncio.to_thread(memory_settings)
        if settings.provider == "none" or not secrets.has_key():
            return JSONResponse({"detail": "Сначала подключите ИИ: нужен API-ключ Cloud.ru."}, status_code=400)
        result = await asyncio.to_thread(brain.run_maintenance, db, settings, secrets.get_key(), mem, force=True)
        if result["busy"]:
            return JSONResponse({"detail": "Память уже обрабатывается, попробуйте через минуту."}, status_code=409)
        if result["error"]:
            return JSONResponse({"detail": result["error"]}, status_code=502)
        return {"added": result["added"], "updated": result["updated"], "texts": result["texts"]}

    @app.delete("/api/memory/summary")
    async def clear_summary():
        def run() -> None:
            state = dict(db.get_setting("memory_state", {}) or {})
            state.pop("summary", None)
            db.set_setting("memory_state", state)
        await asyncio.to_thread(run)
        return {"cleared": True}

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

    # ---------- project update from GitHub ----------
    def update_settings() -> updater.UpdateSettings:
        return updater.validate_settings(db.get_setting("update"))

    def update_state() -> dict:
        try:
            disk_version = (paths.root / "VERSION").read_text(encoding="utf-8").strip()
        except OSError:
            disk_version = runtime.version
        info = db.get_setting("update_info")
        if isinstance(info, dict) and info.get("remote"):  # the cached check may predate an upgrade or rollback
            info = {**info, "local": runtime.version, "newer": updater.is_newer(str(info["remote"]), runtime.version)}
        return {
            "settings": asdict(update_settings()), "has_token": secrets.get("github_token") != "", "token_hint": secrets.hint("github_token"),
            "installed": runtime.version, "restart_needed": disk_version != runtime.version, "disk_version": disk_version,
            "info": info if isinstance(info, dict) else None, "backups": updater.list_backups(paths.root),
            "can_relaunch": os.name == "nt", "protected": list(updater.PROTECTED),
        }

    @app.get("/api/update")
    async def get_update():
        return await asyncio.to_thread(update_state)

    @app.put("/api/update/settings")
    async def put_update_settings(payload: dict[str, Any] = Body(...)):
        await asyncio.to_thread(db.set_setting, "update", asdict(updater.validate_settings(payload)))
        return await asyncio.to_thread(update_state)

    @app.put("/api/update/token")
    async def put_update_token(payload: dict[str, Any] = Body(...)):
        token = payload.get("token")
        try:
            if not isinstance(token, str):
                raise ValueError
            await asyncio.to_thread(secrets.set, "github_token", token)
        except ValueError:
            return JSONResponse({"detail": "Некорректный токен."}, status_code=400)
        events.emit("Токен GitHub сохранён", event_type="settings")
        return await asyncio.to_thread(update_state)

    @app.delete("/api/update/token")
    async def delete_update_token():
        await asyncio.to_thread(secrets.delete, "github_token")
        return await asyncio.to_thread(update_state)

    def do_update_check() -> dict:
        cfg = update_settings()
        info = updater.check(cfg.repo, cfg.branch, secrets.get("github_token"), runtime.version)
        db.set_setting("update_info", info)
        notifier.update_available(info, runtime.version)
        return info

    def background_update_check() -> None:
        if update_settings().auto_check:
            do_update_check()

    @app.post("/api/update/check")
    async def update_check():
        try:
            await asyncio.to_thread(do_update_check)
        except updater.UpdateError as exc:
            return JSONResponse({"detail": str(exc)}, status_code=502)
        return await asyncio.to_thread(update_state)

    @app.post("/api/update/install")
    async def update_install():
        cfg = await asyncio.to_thread(update_settings)

        def run() -> dict:
            token = secrets.get("github_token")
            files = updater.read_zip(updater.fetch_zip(cfg.repo, cfg.branch, token))
            new_version = files["VERSION"].decode("utf-8", "replace").strip()
            if not updater.is_newer(new_version, runtime.version):
                raise updater.UpdateError(f"Установлена актуальная версия (v{runtime.version}), загруженная — v{new_version}.")
            return updater.apply(paths.root, files, runtime.version)

        try:
            result = await asyncio.to_thread(run)
        except updater.UpdateError as exc:
            return JSONResponse({"detail": str(exc)}, status_code=409 if "актуальная" in str(exc) else 502)
        events.emit(f"Проект обновлён до v{result['version']}", event_type="update", payload=result)
        await asyncio.to_thread(notifier.update_installed, str(result["version"]), os.name == "nt")
        return {"result": result, "state": await asyncio.to_thread(update_state)}

    @app.post("/api/update/rollback")
    async def update_rollback():
        try:
            result = await asyncio.to_thread(updater.rollback, paths.root)
        except updater.UpdateError as exc:
            return JSONResponse({"detail": str(exc)}, status_code=409)
        events.emit(f"Откат проекта к v{result['version']}", event_type="update", level="WARNING", payload=result)
        return {"result": result, "state": await asyncio.to_thread(update_state)}

    @app.post("/api/update/restart")
    async def update_restart():
        started = await asyncio.to_thread(updater.relaunch, paths.root)
        if started and runtime.on_shutdown:
            threading.Timer(0.6, runtime.on_shutdown).start()
        return {"relaunched": started}

    # ---------- notifications ----------
    @app.get("/api/notifications")
    async def get_notifications():
        return {"notifications": await asyncio.to_thread(db.list_notifications)}

    @app.post("/api/notifications/seen")
    async def notifications_seen():
        return {"seen": await asyncio.to_thread(db.mark_notifications_seen)}

    @app.post("/api/notifications/{nid}/resolve")
    async def notification_resolve(nid: int):
        if not await asyncio.to_thread(db.resolve_notification, nid):
            return JSONResponse({"detail": "Уведомление не найдено."}, status_code=404)
        return {"resolved": nid}

    watcher = notifier_mod.UpdateWatcher(background_update_check)
    app.router.on_startup.append(watcher.start)
    app.router.on_shutdown.append(watcher.stop)

    # ---------- Диск Kohakuyasha ----------
    async def disk_call(fn, *args):
        try:
            return await asyncio.to_thread(fn, *args)
        except disk_mod.DiskError as exc:
            return JSONResponse({"detail": str(exc)}, status_code=exc.status)
        except OSError as exc:
            return JSONResponse({"detail": f"Ошибка диска: {exc.strerror or exc}"}, status_code=500)

    @app.get("/api/disk")
    async def disk_info():
        def run() -> dict:
            disk_store.ensure()
            return {"settings": disk_settings(), "usage": disk_store.usage(), "root": str(disk_store.files)}
        return await disk_call(run)

    @app.put("/api/disk/settings")
    async def disk_put_settings(payload: dict[str, Any] = Body(...)):
        await asyncio.to_thread(db.set_setting, "disk", disk_mod.validate_settings(payload))
        return {"settings": disk_settings()}

    @app.get("/api/disk/list")
    async def disk_list(path: str = ""):
        return await disk_call(disk_store.list, path)

    @app.get("/api/disk/search")
    async def disk_search(q: str = ""):
        result = await disk_call(disk_store.search, q)
        return result if isinstance(result, JSONResponse) else {"items": result}

    @app.post("/api/disk/folder")
    async def disk_folder(payload: dict[str, Any] = Body(...)):
        return await disk_call(disk_store.mkdir, payload.get("path"))

    @app.post("/api/disk/move")
    async def disk_move(payload: dict[str, Any] = Body(...)):
        return await disk_call(disk_store.move, payload.get("from"), payload.get("to"))

    @app.post("/api/disk/delete")
    async def disk_delete(payload: dict[str, Any] = Body(...)):
        result = await disk_call(disk_store.delete, payload.get("path"))
        if not isinstance(result, JSONResponse):
            events.emit(f"Диск: в корзину «{result['name']}»", event_type="disk")
        return result

    @app.get("/api/disk/trash")
    async def disk_trash():
        result = await disk_call(lambda: disk_store.trash_list(disk_settings()["trash_days"]))
        return result if isinstance(result, JSONResponse) else {"items": result, "days": disk_settings()["trash_days"]}

    @app.post("/api/disk/restore")
    async def disk_restore(payload: dict[str, Any] = Body(...)):
        return await disk_call(disk_store.restore, payload.get("id"))

    @app.delete("/api/disk/trash/{tid}")
    async def disk_purge(tid: str):
        result = await disk_call(disk_store.purge, tid)
        return result if isinstance(result, JSONResponse) else {"purged": tid}

    @app.delete("/api/disk/trash")
    async def disk_empty_trash():
        result = await disk_call(disk_store.empty_trash)
        return result if isinstance(result, JSONResponse) else {"purged": result}

    @app.put("/api/disk/upload")
    async def disk_upload(request: Request, path: str = "", name: str = ""):
        limit = disk_settings()["max_file_mb"] * 1024 * 1024
        if not request.headers.get("content-length"):
            return JSONResponse({"detail": "Нужен Content-Length."}, status_code=411)
        try:
            upload = await asyncio.to_thread(disk_store.begin_upload, path, name, limit)
        except disk_mod.DiskError as exc:
            return JSONResponse({"detail": str(exc)}, status_code=exc.status)
        try:
            async for chunk in request.stream():
                await asyncio.to_thread(upload.write, chunk)
            entry = await asyncio.to_thread(upload.commit)
        except disk_mod.DiskError as exc:
            await asyncio.to_thread(upload.abort)
            return JSONResponse({"detail": str(exc)}, status_code=exc.status)
        except BaseException:
            await asyncio.to_thread(upload.abort)
            raise
        events.emit(f"Диск: загружен «{entry['name']}»", event_type="disk")
        return entry

    @app.get("/api/disk/file")
    async def disk_file(path: str, download: int = 0):
        try:
            file = await asyncio.to_thread(disk_store.file_for_read, path)
        except disk_mod.DiskError as exc:
            return JSONResponse({"detail": str(exc)}, status_code=exc.status)
        inline_type = disk_mod.INLINE_TYPES.get(file.suffix.lower())
        if download or not inline_type:
            response = FileResponse(file, filename=file.name, media_type="application/octet-stream", content_disposition_type="attachment")
        else:
            response = FileResponse(file, filename=file.name, media_type=inline_type, content_disposition_type="inline")
        if not (inline_type or "").startswith("application/pdf"):  # the PDF viewer does not work under a sandbox CSP
            response.headers["Content-Security-Policy"] = "sandbox; default-src 'none'; img-src 'self'; media-src 'self'; style-src 'unsafe-inline'"
        return response

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
