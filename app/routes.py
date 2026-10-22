"""HTTP routes and FastAPI application factory."""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.requests import Request

from app.sockets import register_websocket

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def create_app(room_name: str = "LAN Chat Room") -> FastAPI:
    app = FastAPI(title="Local Chat App", docs_url=None, redoc_url=None)
    app.state.room_name = room_name
    app.mount("/static", StaticFiles(directory=str(PROJECT_ROOT / "static")), name="static")
    templates = Jinja2Templates(directory=str(PROJECT_ROOT / "templates"))

    @app.get("/", response_class=HTMLResponse)
    async def index(request: Request) -> HTMLResponse:
        return templates.TemplateResponse(
            request=request, name="index.html", context={"room_name": room_name}
        )

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "app": "local-chat-app"}

    register_websocket(app)
    return app
