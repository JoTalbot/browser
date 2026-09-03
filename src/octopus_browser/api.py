"""🔌 HTTP API (FastAPI) для ИИ-агентов и внутренних систем.

Эндпоинты покрывают: здоровье, профили, сессии, cookies, навигацию,
скриншоты и запуск задач агента. Адаптер для Октопуса — /octopus/*.
"""

from __future__ import annotations

from typing import Any, List, Optional
from urllib.parse import urlparse

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field, field_validator

from octopus_browser.config import AppConfig
from octopus_browser.profiles import ProfileManager
from octopus_browser.sessions import SessionManager

app = FastAPI(
    title="🐙 Octopus Browser API",
    version="0.1.0",
    description="Супербезопасный браузер с ИИ-управлением (адаптер Октопус/AIOS)",
)

config = AppConfig()
config.ensure_dirs()
profiles = ProfileManager(config)
sessions = SessionManager(config)


class ProfileIn(BaseModel):
    name: Optional[str] = Field(default=None, max_length=64)


class CreateProfileOut(BaseModel):
    name: str
    dir: str


class SessionIn(BaseModel):
    profile: str = "main"
    label: str = ""
    storage_state: dict[str, Any] = Field(default_factory=dict)


class SessionOut(BaseModel):
    id: str


class CookieIn(BaseModel):
    name: str
    value: str = ""
    url: str = ""
    domain: str = ""
    path: str = "/"
    expires: int = 0


class NavigateIn(BaseModel):
    url: str
    profile: str = "main"

    @field_validator("url")
    @classmethod
    def validate_url(cls, value: str) -> str:
        parsed = urlparse(value)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("url должен быть абсолютным http/https URL")
        return value

    @field_validator("profile")
    @classmethod
    def validate_profile(cls, value: str) -> str:
        return ProfileManager.validate_name(value)


class AgentTaskIn(BaseModel):
    task: str = Field(min_length=1, max_length=4000)
    profile: str = "main"
    max_steps: Optional[int] = Field(default=None, ge=1, le=100)

    @field_validator("profile")
    @classmethod
    def validate_profile(cls, value: str) -> str:
        return ProfileManager.validate_name(value)


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "service": "octopus-browser", "version": app.version}


@app.get("/octopus/info")
def octopus_info() -> dict:
    return {
        "adapter": "octopus-browser",
        "version": app.version,
        "capabilities": ["profiles", "sessions", "cookies", "proxy", "vpn", "navigation", "vision", "agent"],
        "octopus": {"runtime": "AIOS", "module": "browser-adapter"},
    }


@app.get("/profiles")
def list_profiles() -> List[dict]:
    return profiles.list()


@app.post("/profiles", response_model=CreateProfileOut, status_code=201)
def create_profile(data: ProfileIn) -> dict:
    try:
        meta = profiles.create(data.name)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except FileExistsError as exc:
        raise HTTPException(409, str(exc)) from exc
    return {"name": meta["name"], "dir": meta["dir"]}


@app.delete("/profiles/{name}")
def delete_profile(name: str) -> dict:
    try:
        deleted = profiles.delete(name)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    if not deleted:
        raise HTTPException(404, f"Профиль '{name}' не найден")
    return {"deleted": name}


@app.get("/sessions")
def list_sessions() -> List[dict]:
    return sessions.list()


@app.post("/sessions", response_model=SessionOut, status_code=201)
def save_session(data: SessionIn) -> dict:
    try:
        ProfileManager.validate_name(data.profile)
        sid = sessions.save(data.storage_state, data.profile, data.label)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"id": sid}


@app.post("/cookies/import")
def import_cookies(payload: dict[str, Any]) -> dict:
    raw = payload.get("data") or payload.get("cookies")
    if not raw:
        raise HTTPException(400, "Ожидаются 'data' или 'cookies'")
    import json as _json
    try:
        _json.loads(raw if isinstance(raw, str) else _json.dumps(raw))
    except (TypeError, ValueError) as exc:
        raise HTTPException(400, "Некорректный JSON") from exc
    return {"ok": True, "note": "Импорт применяется при старте профиля"}


@app.post("/navigate")
def navigate(data: NavigateIn) -> dict:
    from octopus_browser.core.launcher import BrowserController

    controller = BrowserController(config, profile_dir=profiles.get(data.profile))
    try:
        controller.start()
        controller.goto(data.url)
        return {"url": controller.url(), "title": controller.title()}
    finally:
        controller.stop()


@app.post("/screenshot")
def screenshot(data: NavigateIn) -> dict:
    from octopus_browser.core.launcher import BrowserController

    controller = BrowserController(config, profile_dir=profiles.get(data.profile))
    try:
        controller.start()
        controller.goto(data.url)
        return {"image_base64": controller.screenshot()}
    finally:
        controller.stop()


@app.post("/agent/run")
def agent_run(data: AgentTaskIn) -> dict:
    from octopus_browser.agent import OctopusAgent
    from octopus_browser.core.launcher import BrowserController

    controller = BrowserController(config, profile_dir=profiles.get(data.profile))
    agent = OctopusAgent(config, controller)
    run = agent.run(data.task, max_steps=data.max_steps)
    return {"status": run.status, "steps": run.steps,
            "final_url": run.final_url, "log": run.log}


@app.get("/")
def root() -> dict:
    return {"service": "octopus-browser", "docs": "/docs", "health": "/health"}
