"""🔌 HTTP API (FastAPI) для ИИ-агентов и внутренних систем."""
from __future__ import annotations

import json
import threading
from typing import Any
from urllib.parse import urlparse

from fastapi import Depends, FastAPI, Header, HTTPException, Request, Response
from pydantic import BaseModel, Field, field_validator

from octopus_browser.aios import (
    AIOSBridge,
    AIOSError,
    AIOSEvent,
    EventDispatcher,
    EventLog,
)
from octopus_browser.config import AppConfig
from octopus_browser.jobs import Job, JobManager
from octopus_browser.leases import LeaseConflict, ProfileLeaseManager
from octopus_browser.network import ProxyManager
from octopus_browser.observability import AuditSink, correlation_id, request_context
from octopus_browser.profiles import ProfileManager
from octopus_browser.rate_limit import RateLimiter
from octopus_browser.security import require_api_key, validate_external_url
from octopus_browser.sessions import SessionManager
from octopus_browser.vision import (
    MIME_TYPES,
    VISION_MODES,
    VisionBudgetExceeded,
    VisionEngine,
    VisionFrame,
    VisionProviderError,
    compose_context,
    render_prompt,
)

app = FastAPI(title="🐙 Octopus Browser API", version="0.3.2")
config = AppConfig()
config.ensure_dirs()
profiles = ProfileManager(config)
sessions = SessionManager(config)
proxies = ProxyManager(config)
vision_engine = VisionEngine(config)
_audit = AuditSink(config.logs_dir / "audit.jsonl")
_browser_slots = threading.BoundedSemaphore(max(1, config.max_concurrency))
_rate_limiter = RateLimiter(config.rate_limit_per_minute)
_jobs = JobManager(workers=max(1, config.max_concurrency), max_queued=max(1, config.max_concurrency * 8), persist_path=config.data_dir / "agent_jobs.json")
event_log = EventLog(config.data_dir / "aios_events.jsonl", config.aios_events_max_lines)
event_dispatcher = EventDispatcher(event_log, config.aios_events_webhook_url, config.aios_events_webhook_secret, config.data_dir / "aios_push_pending.json")
leases = ProfileLeaseManager(config.data_dir / "profile_leases.json")
aios_bridge = AIOSBridge(config.aios_bridge_url)
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


class ProxyIn(BaseModel):
    server: str = Field(min_length=1, max_length=512)
    label: str = Field(default="", max_length=128)
    secret_ref: str = Field(default="", max_length=64)


class ProxyCredentialsIn(BaseModel):
    ref: str = Field(min_length=1, max_length=64)
    username: str = Field(min_length=1, max_length=256)
    password: str = Field(min_length=1, max_length=512)


class VisionAnalyzeIn(BaseModel):
    image_b64: str = Field(min_length=1, max_length=12_000_000)
    mime_type: str = "image/png"
    prompt: str = Field(default="", max_length=4000)
    goal: str = Field(default="", max_length=2000)
    mode: str = "describe"
    target: str = Field(default="", max_length=500)
    dom: str = Field(default="", max_length=20000)
    a11y: str = Field(default="", max_length=20000)


class LeaseIn(BaseModel):
    holder: str = Field(min_length=1, max_length=128)
    ttl_seconds: int = Field(default=300, ge=1, le=86400)


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
    deadline_seconds: float | None = Field(default=None, ge=0, le=86400)
    require_lease: bool = False
    lease_ttl_seconds: int | None = Field(default=None, ge=1, le=86400)

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


def _job_view(job: Job) -> dict[str, Any]:
    return {
        "id": job.id,
        "status": job.status,
        "created_at": job.created_at,
        "started_at": job.started_at,
        "finished_at": job.finished_at,
        "result": job.result,
        "error": job.error,
    }


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
                    headers={"X-Request-ID": request_id, "Content-Length-Limit": str(config.request_body_max_bytes)},
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
    return {"status": "ok", "service": "octopus-browser", "version": app.version, "browser_concurrency": config.max_concurrency, "request_body_max_bytes": config.request_body_max_bytes}


@app.get("/ready")
def readiness() -> dict:
    return {"status": "ready", "service": "octopus-browser", "profiles": len(profiles.list())}


@app.get("/metrics")
def metrics(_: None = Depends(protected)) -> dict:
    jobs = _jobs.list()
    proxy_stats = proxies.stats()
    return {
        "requests_total": _request_count,
        "browser_concurrency_limit": config.max_concurrency,
        "rate_limit_per_minute": config.rate_limit_per_minute,
        "request_body_max_bytes": config.request_body_max_bytes,
        "jobs_total": len(jobs),
        "jobs_active": sum(j.status in {"queued", "running"} for j in jobs),
        "jobs_failed": sum(j.status == "error" for j in jobs),
        "proxies_total": proxy_stats["total"],
        "proxies_enabled": proxy_stats["enabled"],
        "proxies_cooldown": proxy_stats["in_cooldown"],
        "proxy_rotations_total": proxy_stats["rotations_total"],
        "vision_calls_total": vision_engine.stats()["calls_total"],
        "vision_blocked_budget": vision_engine.stats()["blocked_budget"],
        "agent_runs_total": _agent_stats["runs_total"],
        "agent_steps_total": _agent_stats["steps_total"],
        "agent_runs_done": _agent_stats["runs_done"],
        "agent_runs_verified": _agent_stats["runs_verified"],
        "jobs_queued": sum(j.status == "queued" for j in jobs),
        "profile_leases_held": leases.held_count(),
        "aios_events_pending_push": event_dispatcher.pending_count(),
    }


@app.get("/octopus/info")
def octopus_info(_: None = Depends(protected)) -> dict:
    return {"adapter": "octopus-browser", "version": app.version, "capabilities": ["profiles", "sessions", "navigation", "vision", "agent", "agent-jobs", "readiness", "metrics", "session-revocation", "audit", "proxies", "vision-analyze", "aios-events", "profile-leases", "durable-jobs"], "octopus": {"runtime": "AIOS", "module": "browser-adapter"}}


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


@app.get("/proxies")
def list_proxies(_: None = Depends(protected)) -> list[dict]:
    return proxies.list()


@app.post("/proxies", status_code=201)
def add_proxy(data: ProxyIn, response: Response, _: None = Depends(protected)) -> dict:
    try:
        created = proxies.add(data.server, data.label or None, data.secret_ref or None)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    response.status_code = 201 if created else 200
    stored = next((item for item in proxies.list() if item["server"] == data.server), {})
    return {
        "server": ProxyManager.redact_server(data.server),
        "label": stored.get("label", ""),
        "secret_ref": stored.get("secret_ref", ""),
        "created": created,
    }


@app.delete("/proxies")
def delete_proxy(server: str, _: None = Depends(protected)) -> dict:
    if not proxies.remove(server):
        raise HTTPException(404, "Прокси не найден")
    return {"deleted": ProxyManager.redact_server(server)}


@app.get("/proxies/health")
def proxies_health(_: None = Depends(protected)) -> dict:
    return proxies.refresh_health()


@app.post("/proxies/rotate")
def rotate_proxy(_: None = Depends(protected)) -> dict:
    server = proxies.rotate()
    return {"server": ProxyManager.redact_server(server) if server else None}


@app.post("/proxies/credentials", status_code=201)
def store_proxy_credentials(data: ProxyCredentialsIn, _: None = Depends(protected)) -> dict:
    try:
        proxies.credentials.set(data.ref, data.username, data.password)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(503, str(exc)) from exc
    return {"stored": data.ref}


@app.post("/vision/analyze")
def vision_analyze(data: VisionAnalyzeIn, _: None = Depends(protected)) -> dict:
    if data.mode not in VISION_MODES:
        raise HTTPException(422, f"mode должен быть одним из: {sorted(VISION_MODES)}")
    if data.mime_type not in MIME_TYPES:
        raise HTTPException(422, "mime_type: только image/png, image/jpeg, image/webp")
    frame = VisionFrame(image_b64=data.image_b64, mime_type=data.mime_type, dom=data.dom, a11y=data.a11y)
    try:
        frame.image_bytes()
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    try:
        if data.mode == "describe":
            if data.prompt:
                result = vision_engine.ask(frame, data.prompt)
                return {"mode": "describe", "text": result.text, "provider": result.provider,
                        "model": result.model, "latency_ms": result.latency_ms, "degraded": False}
            version, prompt = render_prompt("describe", context=compose_context(frame))
            result = vision_engine.ask(frame, prompt)
            return {"mode": "describe", "text": result.text, "provider": result.provider,
                    "model": result.model, "prompt_version": version,
                    "latency_ms": result.latency_ms, "degraded": False}
        if data.mode == "ground":
            if not data.target:
                raise HTTPException(422, "Для mode=ground нужен target")
            grounding, degraded = vision_engine.ground(frame, data.target)
            return {"mode": "ground", "x": grounding.x, "y": grounding.y, "selector": grounding.selector,
                    "confidence": grounding.confidence, "degraded": degraded}
        decision, degraded = vision_engine.decide_frame(frame, data.goal or "?", [])
        return {"mode": "decide", "action": decision.action, "target": decision.target, "text": decision.text,
                "reason": decision.reason, "confidence": decision.confidence, "degraded": degraded}
    except VisionBudgetExceeded as exc:
        raise HTTPException(429, str(exc)) from exc
    except VisionProviderError as exc:
        raise HTTPException(503, str(exc)) from exc


@app.get("/vision/status")
def vision_status(_: None = Depends(protected)) -> dict:
    stats = vision_engine.stats()
    return {"adapter_url": config.adapter_url, "vision_provider": config.vision_provider,
            "max_image_bytes": config.vision_max_image_bytes, **stats}


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


_agent_stats_lock = threading.Lock()
_agent_stats = {"runs_total": 0, "steps_total": 0, "runs_done": 0, "runs_verified": 0}
_job_cancel_lock = threading.Lock()
_job_cancel: dict[str, threading.Event] = {}


def _agent_job(data: AgentTaskIn, cancel: threading.Event, correlation: str = "") -> dict:
    from octopus_browser.agent import OctopusAgent
    from octopus_browser.core.launcher import BrowserController

    controller = BrowserController(config, profile_dir=profiles.get(data.profile))
    lease_id: str | None = None
    try:
        if data.require_lease:
            ttl = data.lease_ttl_seconds or config.agent_lease_ttl_seconds
            try:
                lease = leases.acquire(data.profile, holder="agent-job", ttl_seconds=ttl)
            except LeaseConflict as exc:
                busy = f"Профиль занят: {exc.current.get('holder')}"
                event_dispatcher.publish(AIOSEvent(type="agent.job.failed", correlation_id=correlation,
                                                   data={"profile": data.profile, "task": data.task[:200],
                                                         "error": busy, "lease_id": ""}))
                raise RuntimeError(busy) from exc
            lease_id = lease["lease_id"]
            event_dispatcher.publish(AIOSEvent(type="profile.leased", correlation_id=correlation,
                                               data={"profile": data.profile, "lease_id": lease_id, "holder": "agent-job"}))
        agent = OctopusAgent(config, controller)
        try:
            result = agent.run(data.task, max_steps=data.max_steps, cancel=cancel, deadline_seconds=data.deadline_seconds)
        except Exception as exc:
            event_dispatcher.publish(AIOSEvent(type="agent.job.failed", correlation_id=correlation,
                                               data={"profile": data.profile, "task": data.task[:200],
                                                     "error": str(exc)[:300], "lease_id": lease_id or ""}))
            raise
        event_dispatcher.publish(AIOSEvent(type="agent.job.finished", correlation_id=correlation,
                                           data={"profile": data.profile, "task": data.task[:200], "status": result.status,
                                                 "steps": result.steps, "retries": result.retries,
                                                 "recoveries": result.recoveries, "verified": result.verified,
                                                 "final_url": result.final_url, "lease_id": lease_id or ""}))
        with _agent_stats_lock:
            _agent_stats["runs_total"] += 1
            _agent_stats["steps_total"] += result.steps
            _agent_stats["runs_done"] += 1 if result.status == "done" else 0
            _agent_stats["runs_verified"] += 1 if result.verified else 0
        return {"status": result.status, "steps": result.steps, "retries": result.retries, "recoveries": result.recoveries, "verified": result.verified, "lease": lease_id, "final_url": result.final_url, "log": result.log, "state": result.state.value, "request_id": correlation_id.get()}
    finally:
        if lease_id is not None:
            leases.release(lease_id)
            event_dispatcher.publish(AIOSEvent(type="profile.released", correlation_id=correlation,
                                               data={"profile": data.profile, "lease_id": lease_id}))
        controller.stop()


@app.post("/agent/jobs", status_code=202)
def submit_agent_job(data: AgentTaskIn, _: None = Depends(protected)) -> dict:
    try:
        cancel = threading.Event()
        cid = correlation_id.get()
        job = _jobs.submit(lambda: _with_browser_slot(lambda: _agent_job(data, cancel, cid)))
    except RuntimeError as exc:
        raise HTTPException(429, str(exc), headers={"Retry-After": "5"}) from exc
    with _job_cancel_lock:
        _job_cancel[job.id] = cancel
    event_dispatcher.publish(AIOSEvent(type="agent.job.started", job_id=job.id, correlation_id=correlation_id.get(),
                                       data={"profile": data.profile, "task": data.task[:200],
                                             "require_lease": data.require_lease}))
    return _job_view(job)


@app.get("/agent/jobs")
def list_agent_jobs(_: None = Depends(protected)) -> list[dict]:
    return [_job_view(job) for job in _jobs.list()]


@app.get("/agent/jobs/{job_id}")
def get_agent_job(job_id: str, _: None = Depends(protected)) -> dict:
    job = _jobs.get(job_id)
    if not job:
        raise HTTPException(404, "Задача не найдена")
    return _job_view(job)


@app.post("/agent/jobs/{job_id}/cancel")
def cancel_agent_job(job_id: str, _: None = Depends(protected)) -> dict:
    job = _jobs.get(job_id)
    if not job:
        raise HTTPException(404, "Задача не найдена")
    if _jobs.cancel(job_id):
        with _job_cancel_lock:
            _job_cancel.pop(job_id, None)
        return {"cancelled": job_id}
    with _job_cancel_lock:
        event = _job_cancel.get(job_id)
    if job.status == "running" and event is not None:
        event.set()
        return {"cancelled": job_id, "mode": "cooperative"}
    with _job_cancel_lock:
        _job_cancel.pop(job_id, None)
    raise HTTPException(409, "Задача уже выполняется или завершена; принудительное убийство процесса не выполняется")


@app.post("/profiles/{name}/lease", status_code=201)
def acquire_profile_lease(name: str, data: LeaseIn, _: None = Depends(protected)) -> dict:
    try:
        if not profiles.exists(name):
            raise HTTPException(404, f"Профиль '{name}' не найден")
        lease = leases.acquire(name, data.holder, data.ttl_seconds)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except LeaseConflict as exc:
        raise HTTPException(409, {"message": f"Профиль '{name}' занят", "lease": exc.current}) from exc
    event_dispatcher.publish(AIOSEvent(type="profile.leased", correlation_id=correlation_id.get(), data=dict(lease)))
    return lease


@app.get("/profiles/{name}/lease")
def get_profile_lease(name: str, _: None = Depends(protected)) -> dict:
    try:
        if not profiles.exists(name):
            raise HTTPException(404, f"Профиль '{name}' не найден")
        lease = leases.status(name)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    if lease is None:
        raise HTTPException(404, f"У профиля '{name}' нет активной аренды")
    return lease


@app.delete("/profiles/{name}/lease")
def release_profile_lease(name: str, lease_id: str, _: None = Depends(protected)) -> dict:
    try:
        if not profiles.exists(name):
            raise HTTPException(404, f"Профиль '{name}' не найден")
        current = leases.status(name)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    if current is None:
        raise HTTPException(404, f"У профиля '{name}' нет активной аренды")
    if current["lease_id"] != lease_id:
        raise HTTPException(409, "lease_id не совпадает с активной арендой")
    leases.release(lease_id)
    event_dispatcher.publish(AIOSEvent(type="profile.released", correlation_id=correlation_id.get(),
                                       data={"profile": name, "lease_id": lease_id}))
    return {"released": lease_id}


@app.get("/aios/events")
def list_aios_events(since: str | None = None, limit: int = 100, _: None = Depends(protected)) -> dict:
    events, last_id = event_log.read(since=since, limit=limit)
    return {"events": events, "last_id": last_id, "pending_push": event_dispatcher.pending_count()}


@app.post("/aios/events/flush")
def flush_aios_events(_: None = Depends(protected)) -> dict:
    return event_dispatcher.flush()


@app.get("/aios/status")
def aios_status(_: None = Depends(protected)) -> dict:
    try:
        bridge = aios_bridge.status()
        reachable = True
    except AIOSError as exc:
        bridge = {"error": str(exc)}
        reachable = False
    return {
        "bridge_url": config.aios_bridge_url,
        "reachable": reachable,
        "bridge": bridge,
        "webhook_configured": bool(config.aios_events_webhook_url),
        "pending_push": event_dispatcher.pending_count(),
        "events_total": event_log.count(),
    }


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
    return _with_browser_slot(lambda: _agent_job(data))


@app.get("/")
def root() -> dict:
    return {"service": "octopus-browser", "docs": "/docs", "health": "/health", "ready": "/ready"}
