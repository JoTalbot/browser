"""🔌 HTTP API (FastAPI) для ИИ-агентов и внутренних систем."""
from __future__ import annotations
from typing import Any, List, Optional
from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel, Field, field_validator
from octopus_browser.config import AppConfig
from octopus_browser.profiles import ProfileManager
from octopus_browser.sessions import SessionManager
from octopus_browser.security import require_api_key, validate_external_url

app = FastAPI(title="🐙 Octopus Browser API", version="0.2.0")
config = AppConfig(); config.ensure_dirs()
profiles = ProfileManager(config); sessions = SessionManager(config)

class ProfileIn(BaseModel): name: Optional[str] = Field(default=None, max_length=64)
class CreateProfileOut(BaseModel): name: str; dir: str
class SessionIn(BaseModel): profile: str = "main"; label: str = ""; storage_state: dict[str, Any] = Field(default_factory=dict)
class SessionOut(BaseModel): id: str
class NavigateIn(BaseModel):
    url: str; profile: str = "main"
    @field_validator("url")
    @classmethod
    def validate_url(cls, value: str) -> str: return value
    @field_validator("profile")
    @classmethod
    def validate_profile(cls, value: str) -> str: return ProfileManager.validate_name(value)
class AgentTaskIn(BaseModel):
    task: str = Field(min_length=1, max_length=4000); profile: str = "main"; max_steps: Optional[int] = Field(default=None, ge=1, le=100)
    @field_validator("profile")
    @classmethod
    def validate_profile(cls, value: str) -> str: return ProfileManager.validate_name(value)

def protected() -> None: require_api_key()

def _url(value: str) -> str:
    try: return validate_external_url(value, config.allowed_hosts)
    except ValueError as exc: raise HTTPException(422, str(exc)) from exc

@app.get("/health")
def health() -> dict: return {"status":"ok","service":"octopus-browser","version":app.version}

@app.get("/octopus/info")
def octopus_info(_: None = Depends(protected)) -> dict:
    return {"adapter":"octopus-browser","version":app.version,"capabilities":["profiles","sessions","navigation","vision","agent"],"octopus":{"runtime":"AIOS","module":"browser-adapter"}}

@app.get("/profiles")
def list_profiles(_: None = Depends(protected)) -> List[dict]: return profiles.list()

@app.post("/profiles", response_model=CreateProfileOut, status_code=201)
def create_profile(data: ProfileIn, _: None = Depends(protected)) -> dict:
    try: meta = profiles.create(data.name)
    except ValueError as exc: raise HTTPException(400, str(exc)) from exc
    except FileExistsError as exc: raise HTTPException(409, str(exc)) from exc
    return {"name":meta["name"],"dir":meta["dir"]}

@app.delete("/profiles/{name}")
def delete_profile(name: str, _: None = Depends(protected)) -> dict:
    try: deleted = profiles.delete(name)
    except ValueError as exc: raise HTTPException(400, str(exc)) from exc
    if not deleted: raise HTTPException(404, f"Профиль '{name}' не найден")
    return {"deleted":name}

@app.get("/sessions")
def list_sessions(_: None = Depends(protected)) -> List[dict]: return sessions.list()

@app.post("/sessions", response_model=SessionOut, status_code=201)
def save_session(data: SessionIn, _: None = Depends(protected)) -> dict:
    try:
        ProfileManager.validate_name(data.profile); sid = sessions.save(data.storage_state, data.profile, data.label)
    except ValueError as exc: raise HTTPException(400, str(exc)) from exc
    return {"id":sid}

@app.post("/cookies/import")
def import_cookies(payload: dict[str, Any], _: None = Depends(protected)) -> dict:
    raw = payload.get("data") or payload.get("cookies")
    if not raw: raise HTTPException(400,"Ожидаются 'data' или 'cookies'")
    import json
    try: json.loads(raw if isinstance(raw,str) else json.dumps(raw))
    except (TypeError,ValueError) as exc: raise HTTPException(400,"Некорректный JSON") from exc
    return {"ok":True,"note":"Импорт применяется при старте профиля"}

@app.post("/navigate")
def navigate(data: NavigateIn, _: None = Depends(protected)) -> dict:
    from octopus_browser.core.launcher import BrowserController
    controller = BrowserController(config, profile_dir=profiles.get(data.profile))
    try:
        controller.start(); controller.goto(_url(data.url)); return {"url":controller.url(),"title":controller.title()}
    finally: controller.stop()

@app.post("/screenshot")
def screenshot(data: NavigateIn, _: None = Depends(protected)) -> dict:
    from octopus_browser.core.launcher import BrowserController
    controller = BrowserController(config, profile_dir=profiles.get(data.profile))
    try:
        controller.start(); controller.goto(_url(data.url)); return {"image_base64":controller.screenshot()}
    finally: controller.stop()

@app.post("/agent/run")
def agent_run(data: AgentTaskIn, _: None = Depends(protected)) -> dict:
    from octopus_browser.agent import OctopusAgent
    from octopus_browser.core.launcher import BrowserController
    controller = BrowserController(config, profile_dir=profiles.get(data.profile))
    agent = OctopusAgent(config, controller); run = agent.run(data.task, max_steps=data.max_steps)
    return {"status":run.status,"steps":run.steps,"final_url":run.final_url,"log":run.log}

@app.get("/")
def root() -> dict: return {"service":"octopus-browser","docs":"/docs","health":"/health"}
