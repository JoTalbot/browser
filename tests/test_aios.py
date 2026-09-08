"""🧪 Тесты AIOS-интеграции: события, webhook-push, лизы, durable-очередь."""
from __future__ import annotations

import hashlib
import hmac
import json
import threading
import time

import httpx
import pytest
from fastapi.testclient import TestClient

from octopus_browser import api as api_module
from octopus_browser.agent import AgentRun, AgentState
from octopus_browser.aios import (
    AIOSBridge,
    AIOSError,
    AIOSEvent,
    EventDispatcher,
    EventLog,
)
from octopus_browser.jobs import JobManager
from octopus_browser.leases import LeaseConflict, ProfileLeaseManager
from octopus_browser.profiles import ProfileManager


def test_event_log_cursor_and_limit(tmp_path) -> None:
    log = EventLog(tmp_path / "ev.jsonl")
    ids = []
    for i in range(5):
        event = AIOSEvent(type="t", data={"i": i})
        log.append(event)
        ids.append(event.id)
    events, last_id = log.read(limit=2)
    assert [e["data"]["i"] for e in events] == [0, 1] and last_id == ids[1]
    events, last_id = log.read(since=ids[1], limit=10)
    assert [e["data"]["i"] for e in events] == [2, 3, 4] and last_id == ids[4]
    assert log.read(since="unknown", limit=10)[0][0]["data"]["i"] == 0
    assert log.count() == 5


def test_event_log_skips_corrupt_lines(tmp_path) -> None:
    path = tmp_path / "ev.jsonl"
    path.write_text("not-json\n" + json.dumps(AIOSEvent(type="ok").to_dict()) + "\n", encoding="utf-8")
    events, _ = EventLog(path).read()
    assert len(events) == 1 and events[0]["type"] == "ok"


def test_event_log_prunes_oldest(tmp_path) -> None:
    log = EventLog(tmp_path / "ev.jsonl", max_lines=100)
    for i in range(601):
        log.append(AIOSEvent(type="t", data={"i": i}))
    events, _ = log.read(limit=500)
    assert len(events) == 100 and events[0]["data"]["i"] == 501 and events[-1]["data"]["i"] == 600


def test_dispatcher_no_webhook_ok(tmp_path) -> None:
    dispatcher = EventDispatcher(EventLog(tmp_path / "ev.jsonl"))
    assert dispatcher.publish(AIOSEvent(type="t")) is True
    assert dispatcher.flush() == {"flushed": 0, "still_pending": 0}


def test_dispatcher_push_headers_and_signature(tmp_path) -> None:
    seen: list[httpx.Request] = []

    def ok(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"ok": True})

    dispatcher = EventDispatcher(EventLog(tmp_path / "ev.jsonl"), webhook_url="http://hook/ev",
                                 webhook_secret="s3cr3t", transport=httpx.MockTransport(ok))
    assert dispatcher.publish(AIOSEvent(type="agent.job.started")) is True
    assert len(seen) == 1
    body = seen[0].content
    assert seen[0].headers["X-Event-Type"] == "agent.job.started"
    assert seen[0].headers["X-Event-Id"] == json.loads(body)["id"]
    expected = hmac.new(b"s3cr3t", body, hashlib.sha256).hexdigest()
    assert seen[0].headers["X-Signature"] == f"sha256={expected}"


def test_dispatcher_pending_and_flush(tmp_path) -> None:
    calls = {"fail": True}

    def flaky(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={}) if calls["fail"] else httpx.Response(200, json={})

    dispatcher = EventDispatcher(EventLog(tmp_path / "ev.jsonl"), webhook_url="http://hook/ev",
                                 pending_path=tmp_path / "pending.json",
                                 transport=httpx.MockTransport(flaky), max_pending=3)
    assert dispatcher.publish(AIOSEvent(type="a")) is False
    assert dispatcher.publish(AIOSEvent(type="b")) is False
    assert dispatcher.pending_count() == 2
    assert dispatcher.flush() == {"flushed": 0, "still_pending": 2}
    calls["fail"] = False
    assert dispatcher.flush() == {"flushed": 2, "still_pending": 0}
    assert EventDispatcher(EventLog(tmp_path / "ev.jsonl"), webhook_url="http://hook/ev",
                           pending_path=tmp_path / "pending.json").pending_count() == 0


def test_bridge_status_paths() -> None:
    def ok(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"ok": True, "service": "b"})

    status = AIOSBridge("http://b:9600", transport=httpx.MockTransport(ok)).status()
    assert status["ok"] is True and status["latency_ms"] >= 0

    def down(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={})

    with pytest.raises(AIOSError, match="bridge status"):
        AIOSBridge("http://b", transport=httpx.MockTransport(down)).status()
    with pytest.raises(ValueError, match="AIOS_BRIDGE_URL"):
        AIOSBridge("")


def test_leases_lifecycle_and_expiry(tmp_path) -> None:
    now = {"t": 1000.0}
    manager = ProfileLeaseManager(tmp_path / "leases.json", clock=lambda: now["t"])
    lease = manager.acquire("main", "worker-1", 60)
    assert lease["profile"] == "main" and lease["holder"] == "worker-1"
    with pytest.raises(LeaseConflict) as exc_info:
        manager.acquire("main", "worker-2", 60)
    assert exc_info.value.current["holder"] == "worker-1"
    assert manager.status("main")["lease_id"] == lease["lease_id"]
    assert manager.status("other") is None
    refreshed = manager.refresh(lease["lease_id"], 120)
    assert refreshed is not None and refreshed["ttl_seconds"] == 120
    now["t"] += 121
    assert manager.status("main") is None
    lease2 = manager.acquire("main", "worker-2", 60)
    assert manager.release(lease2["lease_id"]) is not None
    assert manager.release("nope") is None and manager.held_count() == 0


def test_leases_persist_and_prune_expired(tmp_path) -> None:
    path = tmp_path / "leases.json"
    manager = ProfileLeaseManager(path, clock=lambda: 1000.0)
    lease = manager.acquire("main", "w", 60)
    same = ProfileLeaseManager(path, clock=lambda: 1010.0)
    assert same.status("main")["lease_id"] == lease["lease_id"]
    expired = ProfileLeaseManager(path, clock=lambda: 2000.0)
    assert expired.status("main") is None and expired.held_count() == 0


def test_jobs_durable_roundtrip_and_interrupt(tmp_path) -> None:
    path = tmp_path / "jobs.json"
    manager = JobManager(workers=1, persist_path=path)
    job = manager.submit(lambda: {"n": 1})
    deadline = time.monotonic() + 5
    while manager.get(job.id).status not in {"done", "error"} and time.monotonic() < deadline:
        time.sleep(0.02)
    assert manager.get(job.id).status == "done"
    assert path.exists()
    manager.shutdown()
    revived = JobManager(workers=1, persist_path=path)
    assert revived.get(job.id).status == "done" and revived.get(job.id).result == {"n": 1}
    revived.shutdown()
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw["jobs"].append({"id": "stuck", "status": "running", "created_at": "t", "started_at": "t",
                        "finished_at": None, "result": None, "error": None})
    path.write_text(json.dumps(raw), encoding="utf-8")
    restarted = JobManager(workers=1, persist_path=path)
    stuck = restarted.get("stuck")
    assert stuck.status == "error" and stuck.error == "interrupted by restart"
    restarted.shutdown()


def test_jobs_backpressure() -> None:
    gate = threading.Event()
    manager = JobManager(workers=1, max_queued=1)
    try:
        manager.submit(lambda: gate.wait(timeout=10))
        with pytest.raises(RuntimeError, match="переполнена"):
            manager.submit(lambda: 1)
    finally:
        gate.set()
        manager.shutdown()


def test_jobs_submit_explicit_id_and_duplicate() -> None:
    manager = JobManager(workers=1)
    try:
        job = manager.submit(lambda: 1, job_id="fixed-id")
        assert job.id == "fixed-id" and manager.get("fixed-id") is job
        with pytest.raises(RuntimeError, match="уже существует"):
            manager.submit(lambda: 2, job_id="fixed-id")
    finally:
        manager.shutdown()


@pytest.fixture()
def aios_client(tmp_path, monkeypatch):
    monkeypatch.setattr(api_module, "event_log", EventLog(tmp_path / "ev.jsonl"))
    monkeypatch.setattr(api_module, "event_dispatcher", EventDispatcher(api_module.event_log))
    monkeypatch.setattr(api_module, "leases", ProfileLeaseManager(tmp_path / "leases.json"))
    monkeypatch.setattr(api_module.profiles, "exists", lambda name: (ProfileManager.validate_name(name), True)[1])
    monkeypatch.setattr(api_module.profiles, "get", lambda name: tmp_path)
    api_module.app.dependency_overrides[api_module.protected] = lambda: None
    yield TestClient(api_module.app)
    api_module.app.dependency_overrides.clear()


def _wait_until(fn, timeout: float = 10.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if fn():
            return True
        time.sleep(0.02)
    return False


def test_api_lease_crud_and_conflict(aios_client) -> None:
    first = aios_client.post("/profiles/main/lease", json={"holder": "w1", "ttl_seconds": 60})
    assert first.status_code == 201
    lease_id = first.json()["lease_id"]
    busy = aios_client.post("/profiles/main/lease", json={"holder": "w2"})
    assert busy.status_code == 409 and busy.json()["detail"]["lease"]["holder"] == "w1"
    assert aios_client.get("/profiles/main/lease").json()["lease_id"] == lease_id
    assert aios_client.get("/profiles/other/lease").status_code == 404
    wrong = aios_client.delete("/profiles/main/lease", params={"lease_id": "nope"})
    assert wrong.status_code == 409
    released = aios_client.delete("/profiles/main/lease", params={"lease_id": lease_id})
    assert released.status_code == 200 and released.json() == {"released": lease_id}
    assert aios_client.get("/profiles/main/lease").status_code == 404
    assert aios_client.post("/profiles/bad name!/lease", json={"holder": "w"}).status_code == 400


def test_api_events_feed_and_flush(aios_client, monkeypatch) -> None:
    api_module.event_dispatcher.publish(AIOSEvent(type="agent.job.started", job_id="j1"))
    api_module.event_dispatcher.publish(AIOSEvent(type="agent.job.finished", job_id="j1"))
    feed = aios_client.get("/aios/events", params={"limit": 1}).json()
    assert len(feed["events"]) == 1 and feed["pending_push"] == 0
    rest = aios_client.get("/aios/events", params={"since": feed["last_id"]}).json()
    assert [e["type"] for e in rest["events"]] == ["agent.job.finished"]
    assert aios_client.post("/aios/events/flush").json() == {"flushed": 0, "still_pending": 0}

    def ok(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"ok": True})

    monkeypatch.setattr(api_module, "aios_bridge", AIOSBridge("http://b", transport=httpx.MockTransport(ok)))
    status = aios_client.get("/aios/status").json()
    assert status["reachable"] is True and status["events_total"] == 2

    def down(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={})

    monkeypatch.setattr(api_module, "aios_bridge", AIOSBridge("http://b", transport=httpx.MockTransport(down)))
    assert aios_client.get("/aios/status").json()["reachable"] is False


def test_api_submit_429_retry_after(aios_client, monkeypatch) -> None:
    gate = threading.Event()
    small = JobManager(workers=1, max_queued=1)
    monkeypatch.setattr(api_module, "_jobs", small)
    try:
        small.submit(lambda: gate.wait(timeout=10))
        resp = aios_client.post("/agent/jobs", json={"task": "t"})
        assert resp.status_code == 429 and resp.headers.get("Retry-After") == "5"
    finally:
        gate.set()
        small.shutdown()


class DoneAgent:
    def __init__(self, config, controller) -> None:
        pass

    def run(self, task, max_steps=None, cancel=None, deadline_seconds=None):
        return AgentRun(task=task, steps=2, status="done", state=AgentState.DONE,
                        log=["ok"], final_url="https://done.test", verified=True)


class DummyController:
    def __init__(self, config, profile_dir=None) -> None:
        pass

    def stop(self) -> None:
        pass


def test_api_require_lease_busy_and_free(aios_client, monkeypatch) -> None:
    monkeypatch.setattr("octopus_browser.agent.OctopusAgent", DoneAgent)
    monkeypatch.setattr("octopus_browser.core.launcher.BrowserController", DummyController)
    hold = aios_client.post("/profiles/main/lease", json={"holder": "other"}).json()["lease_id"]
    busy = aios_client.post("/agent/jobs", json={"task": "t", "require_lease": True})
    assert busy.status_code == 202
    busy_id = busy.json()["id"]
    assert _wait_until(lambda: api_module._jobs.get(busy_id).status == "error")
    assert "Профиль занят" in (api_module._jobs.get(busy_id).error or "")
    aios_client.delete("/profiles/main/lease", params={"lease_id": hold})
    free = aios_client.post("/agent/jobs", json={"task": "t", "require_lease": True, "lease_ttl_seconds": 60})
    free_id = free.json()["id"]
    assert _wait_until(lambda: api_module._jobs.get(free_id).status == "done")
    result = api_module._jobs.get(free_id).result
    assert result["status"] == "done" and result["lease"]
    assert aios_client.get("/profiles/main/lease").status_code == 404
    types = [e["type"] for e in aios_client.get("/aios/events", params={"limit": 200}).json()["events"]]
    assert "agent.job.started" in types and "agent.job.finished" in types
    assert "profile.leased" in types and "profile.released" in types


def test_api_webhook_e2e_push(aios_client, monkeypatch) -> None:
    monkeypatch.setattr("octopus_browser.agent.OctopusAgent", DoneAgent)
    monkeypatch.setattr("octopus_browser.core.launcher.BrowserController", DummyController)
    seen: list[httpx.Request] = []

    def hook(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"ok": True})

    hooked = EventDispatcher(api_module.event_log, webhook_url="http://hook/ev", webhook_secret="s3cr3t",
                             transport=httpx.MockTransport(hook))
    monkeypatch.setattr(api_module, "event_dispatcher", hooked)
    submit = aios_client.post("/agent/jobs", json={"task": "webhook-demo"})
    job_id = submit.json()["id"]
    assert _wait_until(lambda: api_module._jobs.get(job_id).status == "done")
    assert _wait_until(lambda: len(seen) >= 2), f"webhook got {len(seen)} events"
    # Порядок started/finished не гарантирован: быстрая задача финиширует раньше,
    # чем endpoint успевает запушить started. Потребители упорядочивают по ts.
    kinds = sorted(r.headers["X-Event-Type"] for r in seen)
    assert kinds == ["agent.job.finished", "agent.job.started"]
    for request in seen:
        expected = hmac.new(b"s3cr3t", request.content, hashlib.sha256).hexdigest()
        assert request.headers["X-Signature"] == f"sha256={expected}"
    bodies = [json.loads(r.content) for r in seen]
    finished = next(b for b in bodies if b["type"] == "agent.job.finished")
    started = next(b for b in bodies if b["type"] == "agent.job.started")
    assert finished["data"]["status"] == "done" and finished["data"]["final_url"] == "https://done.test"
    assert started["ts"] <= finished["ts"]
