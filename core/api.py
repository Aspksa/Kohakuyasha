from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Header, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles

from . import autostart
from .config import ConfigStore, Paths
from .database import Database
from .diagnostics import Diagnostics
from .events import EventHub
from .runtime import RuntimeState


def create_app(
    *,
    paths: Paths,
    config: ConfigStore,
    db: Database,
    events: EventHub,
    runtime: RuntimeState,
) -> FastAPI:
    app = FastAPI(title="Kohakuyasha", docs_url=None, redoc_url=None)
    app.mount("/static", StaticFiles(directory=paths.static), name="static")

    def require_local_action(marker: str | None) -> None:
        if marker != "1":
            raise HTTPException(status_code=403, detail="Локальное действие отклонено.")

    @app.middleware("http")
    async def local_only(request: Request, call_next):
        host = (request.client.host if request.client else "")
        if host not in {"127.0.0.1", "::1", "localhost", "testclient"}:
            raise HTTPException(status_code=403, detail="Kohakuyasha доступна только локально.")
        return await call_next(request)

    @app.get("/")
    async def index():
        return FileResponse(paths.web / "index.html")

    @app.get("/api/status")
    async def status():
        settings = config.load()
        return {
            "runtime": runtime.snapshot(),
            "settings": {
                "language": settings.language,
                "open_browser": settings.open_browser,
                "minimize_to_tray": settings.minimize_to_tray,
                "autostart": autostart.is_enabled(),
            },
            "database": {"path": str(paths.database), "exists": paths.database.exists()},
        }

    @app.get("/api/events")
    async def recent_events(limit: int = 100):
        return {"events": db.recent_events(limit)}

    @app.post("/api/tests/run")
    async def run_tests(
        mode: str = "quick",
        x_kohakuyasha_request: str | None = Header(default=None),
    ):
        require_local_action(x_kohakuyasha_request)
        mode = "full" if mode == "full" else "quick"
        runtime.set_status("Тестирование", f"{'Полная' if mode == 'full' else 'Быстрая'} диагностика")
        events.emit("Запущена диагностика", event_type="diagnostics", payload={"mode": mode})
        result = await asyncio.to_thread(Diagnostics(paths.root, db, config.load().host, runtime.port).run, mode)
        runtime.last_test_summary = result
        runtime.set_status("Наблюдает", "Готова к работе")
        events.emit(
            f"Диагностика завершена: {result['passed']}/{result['total']}",
            level="INFO" if result["ok"] else "WARNING",
            event_type="diagnostics",
            payload=result,
        )
        return result

    @app.post("/api/autostart")
    async def set_autostart(
        payload: dict[str, Any],
        x_kohakuyasha_request: str | None = Header(default=None),
    ):
        require_local_action(x_kohakuyasha_request)
        enabled = bool(payload.get("enabled"))
        if enabled:
            autostart.enable(paths.root)
        else:
            autostart.disable()
        settings = config.load()
        settings.autostart = enabled
        config.save(settings)
        events.emit(
            "Автозапуск включён" if enabled else "Автозапуск отключён",
            event_type="settings",
        )
        return {"enabled": autostart.is_enabled()}

    @app.get("/api/diagnostics/export")
    async def export_diagnostics():
        settings = config.load()
        report = {
            "project": "Kohakuyasha",
            "runtime": runtime.snapshot(),
            "database_integrity": db.integrity_check(),
            "settings": {
                "language": settings.language,
                "host": settings.host,
                "port": settings.port,
                "open_browser": settings.open_browser,
                "minimize_to_tray": settings.minimize_to_tray,
                "autostart": autostart.is_enabled(),
            },
            "events": db.recent_events(250),
        }
        payload = json.dumps(report, ensure_ascii=False, indent=2)
        return Response(
            content=payload,
            media_type="application/json",
            headers={"Content-Disposition": "attachment; filename=kohakuyasha-diagnostics.json"},
        )

    @app.post("/api/system/restart")
    async def restart(x_kohakuyasha_request: str | None = Header(default=None)):
        require_local_action(x_kohakuyasha_request)
        events.emit("Запрошен перезапуск ядра", event_type="system")
        if runtime.on_restart:
            asyncio.get_running_loop().call_later(0.2, runtime.on_restart)
        return {"accepted": True}

    @app.post("/api/system/shutdown")
    async def shutdown(x_kohakuyasha_request: str | None = Header(default=None)):
        require_local_action(x_kohakuyasha_request)
        events.emit("Запрошено завершение Kohakuyasha", event_type="system")
        if runtime.on_shutdown:
            asyncio.get_running_loop().call_later(0.2, runtime.on_shutdown)
        return {"accepted": True}

    @app.websocket("/ws/events")
    async def websocket_events(websocket: WebSocket):
        client = websocket.client.host if websocket.client else ""
        if client not in {"127.0.0.1", "::1", "localhost", "testclient"}:
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
