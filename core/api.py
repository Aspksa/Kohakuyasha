from __future__ import annotations

import asyncio
import json
import threading
from typing import Any

from fastapi import FastAPI, Header, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from . import autostart
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

    def security_headers(response: Response) -> Response:
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Cache-Control"] = "no-store"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; img-src 'self'; style-src 'self'; script-src 'self'; "
            "connect-src 'self' ws://127.0.0.1:* ws://localhost:* ws://[::1]:*; "
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
