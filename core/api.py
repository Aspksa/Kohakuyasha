from __future__ import annotations

import asyncio
import json
import threading
from dataclasses import asdict
from typing import Any

from fastapi import Body, FastAPI, Header, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from . import ai, assistant, autostart
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
    secrets = ai.SecretStore(paths.secrets)

    def load_character() -> dict:
        try:
            data = json.loads(paths.character.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    def ai_settings() -> ai.AISettings:
        return ai.validate_ai(db.get_setting("ai"))

    def avatar_settings() -> ai.AvatarSettings:
        return ai.validate_avatar(db.get_setting("avatar"))

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
        def build() -> dict:
            return {"avatar": asdict(avatar_settings()), "ai": ai.public_ai(ai_settings(), secrets)}

        return await asyncio.to_thread(build)

    @app.put("/api/settings/avatar")
    async def put_avatar(payload: dict[str, Any] = Body(...)):
        settings = ai.validate_avatar(payload)
        await asyncio.to_thread(db.set_setting, "avatar", asdict(settings))
        return asdict(settings)

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
            return JSONResponse({"ok": False, "detail": "ИИ-провайдер не выбран."}, status_code=200)
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
        history = await asyncio.to_thread(db.recent_chat, 60)
        try:
            answer = await asyncio.to_thread(
                assistant.reply, settings, secrets.get_key(), await asyncio.to_thread(load_character), history
            )
        except ai.AIError as exc:
            return {"messages": [user_message], "error": str(exc)}
        assistant_message = await asyncio.to_thread(db.add_chat_message, "assistant", answer)
        return {"messages": [user_message, assistant_message]}

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
