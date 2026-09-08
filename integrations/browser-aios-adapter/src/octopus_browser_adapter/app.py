"""Локальный HTTP слой адаптера для подключения из AIOS."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from .adapter import AIOSBrowserAdapter
from .browser import BrowserAdapterError


class ObserveRequest(BaseModel):
    profile: str = "secondary"
    prompt: str = Field(default="Опиши интерфейс кратко.", max_length=2000)


class ActionRequest(BaseModel):
    profile: str = "secondary"
    action: str
    approved: bool = False
    url: str | None = None
    selector: str | None = None
    text: str | None = None


def create_app(adapter: AIOSBrowserAdapter | None = None) -> FastAPI:
    runtime = adapter or AIOSBrowserAdapter()
    app = FastAPI(title="Octopus Browser AIOS Adapter", version="0.1.0")

    @app.get("/health")
    def health() -> dict[str, Any]:
        return {"status": "ok", **runtime.capabilities()}

    @app.get("/status")
    def status() -> dict[str, Any]:
        try:
            return runtime.status()
        except BrowserAdapterError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    @app.get("/aios/status")
    def aios_status() -> dict[str, Any]:
        try:
            return runtime.aios_status()
        except BrowserAdapterError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=503, detail=type(exc).__name__) from exc

    @app.post("/observe")
    def observe(request: ObserveRequest) -> dict[str, Any]:
        try:
            return runtime.observe(request.profile, request.prompt)
        except BrowserAdapterError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post("/action")
    def action(request: ActionRequest) -> dict[str, Any]:
        try:
            return runtime.action(
                request.profile,
                request.action,
                approved=request.approved,
                url=request.url,
                selector=request.selector,
                text=request.text,
            )
        except (BrowserAdapterError, KeyError, ValueError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    return app


app = create_app()
