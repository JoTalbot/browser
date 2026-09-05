"""🔌 HTTP API (FastAPI) для ИИ-агентов и внутренних систем."""
from __future__ import annotations

import json
import threading
from typing import Any
from urllib.parse import urlparse

from fastapi import Depends, FastAPI, Header, HTTPException, Request, Response
from pydantic import BaseModel, Field, field_validator

from octopus_browser.config import AppConfig
from octopus_browser.observability import AuditSink, correlation_id, request_context
from octopus_browser.profiles import ProfileManager
from octopus_browser.rate_limit import RateLimiter
from octopus_browser.security import require_api_key, validate_external_url
from octopus_browser.sessions import SessionManager

app = FastAPI(title="🐙 Octopus Browser API", version="0.3.0")
config = AppConfig()
config.ensure_dirs()
profiles = ProfileManager(config)
sessions = SessionManager(config)
_audit = AuditSink(config.logs_dir / "audit.jsonl")
_browser_slots = threading.BoundedSemaphore(max(1, config.max_concurrency))
_rate_limiter = RateLimiter(config.rate_limit_per_minute)
_request_count = 0
_request_lock = threading.Lock()


class ProfileIn(BaseModel):
    name: str | None = Field(default=None, max_length=64)


class CreateProfileOut(BaseModel):
    name: str
    dir: str


class SessionIn(BaseModel):
    profile: str = "main"
    label: str = ""
    storage_state: dict[str, Any] = Field(default_factory=dict)


class SessionOut(BaseModel):
    id: str


class NavigateIn(BaseModel):
    url: str
    profile: str = "main"

    @field_validator("url")
    @classmethod
    def validate_url(cls, value: str) -> str:
        parsed = urlparse(value)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("url должен быть абсолютным http/https URL")
        return value

    @field_validator("profile")
    @classmethod
    def validate_profile(cls, value: str) -> str:
        return ProfileManager.validate_name(value)


class AgentTaskIn(BaseModel):
    task: str = Field(min_length=1, max_length=4000)
    profile: str = "main"
    max_steps: int | None = Field(default=None, ge=1, le=100)

    @field_validator("profile")
    @classmethod
    def validate_profile(cls, value: str) -> str:
        return ProfileManager.validate_name(value)


def protected(x_api_key: str | None = Header(default=None)) -> None:
    require_api_key(x_api_key=x_api_key, expected_key=config.api_key)


def _url(value: str) -> str:
    try:
        return validate_external_url(value, config.allowed_hosts)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


def _acquire_browser_slot() -> None:
    if not _browser_slots.acquire(blocking=False):
        raise HTTPException(429, "Достигнут лимит одновременно работающих браузеров")


@app.middleware("http")
async def admission_control(request: Request, call_next):
    global _request_count
    with request_context(request.headers.get("x-request-id")) as request_id:
        key = request.headers.get("x-api-key") or (request.client.host if request.client else "unknown")
        if not _rate_limiter.allow(key):
            retry_after = max(1, int(_rate_limiter.retry_after(key) + 0.999))
            return Response(
                content=json.dumps({"detail": "Слишком много запросов", "request_id": request_id}),
                status_code=429,
                media_type="application/json",
                headers={"Retry-After": str(retry_after), "X-Request-ID": request_id},
            )
        content_length = request.headers.get("content-length")
        if content_length is not None:
            try:
                body_size = int(content_length)
            except ValueError:
                return Response(
                    content=json.dumps({"detail": "Некорректный Content-Length", "request_id": request_id}),
                    status_code=400,
                    media_type="application/json",
                    headers={"X-Request-ID": request_id},
                )
            if body_size < 0 or body_size > config.request_body_max_bytes:
                return Response(
                    content=json.dumps({"detail": "Размер тела запроса превышает допустимый лимит", "request_id": request_id}),
                    status_code=413,
                    media_type="application/json",
                    headers={
                        "X-Request-ID": request_id,
                        "Content-Length-Limit": str(config.request_body_max_bytes),
                    },
                )
        with _request_lock:
            _request_count += 1
        response = await call_next(request)
        response.headers["X-Request-ID"] = correlation_id.get()
        if config.audit_log_enabled:
            _audit.write({"event": "http_request", "method": request.method, "path": request.url.path, "status": response.status_code})
        return response


@app.get("/health")
def health() -> dict:
    return {
        "status": "ok",
        "service": "octopus-browser",
        "version": app.version,
        "browser_concurrency": config.max_concurrency,
        "request_body_max_bytes": config.request_body_max_bytes,
    }


@app.get("/ready")
def readiness() -> dict:
    return {"status": "ready", "service": "octopus-browser", "profiles": len(profiles.list())}


@app.get("/metrics")
def metrics(_: None = Depends(protected)) -> dict:
    return {
        "requests_total": _request_count,
        "browser_concurrency_limit": config.max_concurrency,
        "rate_limit_per_minute": config.rate_limit_per_minute,
        "request_body_max_bytes": config.request_body_max_bytes,
    }


@app.get("/octopus/info")
def octopus_info(_: None = Depends(protected)) -> dict:
    return {
        "adapter": "octopus-browser",
        "version": app.version,
        "capabilities": ["profiles", "sessions", "navigation", "vision", "agent", "readiness", "metrics"],
        "octopus": {"runtime": "AIOS", "module": "browser-adapter"},
    }


@app.get("/profiles")
def list_profiles(_: None = Depends(protected)) -> list[dict]:
    return profiles.list()


@app.post("/profiles", response_model=CreateProfileOut, status_code=201)
def create_profile(data: ProfileIn, _: None = Depends(protected)) -> dict:
    try:
        meta = profiles.create(data.name)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except FileExistsError as exc:
        raise HTTPException(409, str(exc)) from exc
    return {"name": meta["name"], "dir": meta["dir"]}


@app.delete("/profiles/{name}")
def delete_profile(name: str, _: None = Depends(protected)) -> dict:
    try:
        deleted = profiles.delete(name)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    if not deleted:
        raise HTTPException(404, f"Профиль '{name}' не найден")
    return {"deleted": name}


@app.get("/sessions")
def list_sessions(_: None = Depends(protected)) -> list[dict]:
    return sessions.list()


@app.post("/sessions", response_model=SessionOut, status_code=201)
def save_session(data: SessionIn, _: None = Depends(protected)) -> dict:
    try:
        ProfileManager.validate_name(data.profile)
        sid = sessions.save(data.storage_state, data.profile, data.label)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(503, str(exc)) from exc
    return {"id": sid}


@app.post("/sessions/{session_id}/revoke")
def revoke_session(session_id: str, _: None = Depends(protected)) -> dict:
    try:
        revoked = sessions.revoke(session_id)
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(400, str(exc)) from exc
    if not revoked:
        raise HTTPException(404, f"Сессия '{session_id}' не найдена")
    return {"revoked": session_id}


@app.post("/cookies/import")
def import_cookies(payload: dict[str, Any], _: None = Depends(protected)) -> dict:
    raw = payload.get("data") or payload.get("cookies")
    if not raw:
        raise HTTPException(400, "Ожидаются 'data' или 'cookies'")
    try:
        json.loads(raw if isinstance(raw, str) else json.dumps(raw))
    except (TypeError, ValueError) as exc:
        raise HTTPException(400, "Некорректный JSON") from exc
    return {"ok": True, "note": "Импорт применяется при старте профиля"}


def _with_browser_slot(callback):
    _acquire_browser_slot()
    try:
        return callback()
    finally:
        _browser_slots.release()


@app.post("/navigate")
def navigate(data: NavigateIn, _: None = Depends(protected)) -> dict:
    from octopus_browser.core.launcher import BrowserController

    url = _url(data.url)

    def run() -> dict:
        controller = BrowserController(config, profile_dir=profiles.get(data.profile))
        try:
            controller.start()
            controller.goto(url)
            return {"url": controller.url(), "title": controller.title()}
        finally:
            controller.stop()

    return _with_browser_slot(run)


@app.post("/screenshot")
def screenshot(data: NavigateIn, _: None = Depends(protected)) -> dict:
    from octopus_browser.core.launcher import BrowserController

    url = _url(data.url)

    def run() -> dict:
        controller = BrowserController(config, profile_dir=profiles.get(data.profile))
        try:
            controller.start()
            controller.goto(url)
            return {"image_base64": controller.screenshot()}
        finally:
            controller.stop()

    return _with_browser_slot(run)


@app.post("/agent/run")
def agent_run(data: AgentTaskIn, _: None = Depends(protected)) -> dict:
    from octopus_browser.agent import OctopusAgent
    from octopus_browser.core.launcher import BrowserController

    def run() -> dict:
        controller = BrowserController(config, profile_dir=profiles.get(data.profile))
        agent = OctopusAgent(config, controller)
        result = agent.run(data.task, max_steps=data.max_steps)
        return {
            "status": result.status,
            "steps": result.steps,
            "final_url": result.final_url,
            "log": result.log,
            "state": result.state.value,
            "request_id": correlation_id.get(),
        }

    return _with_browser_slot(run)


@app.get("/")
def root() -> dict:
    return {"service": "octopus-browser", "docs": "/docs", "health": "/health", "ready": "/ready"}
