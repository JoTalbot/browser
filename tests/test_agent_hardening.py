"""🧪 Тесты hardening агента: ретраи, восстановление, отмена, дедлайны, верификация."""
from __future__ import annotations

import threading
import time

import pytest
from fastapi.testclient import TestClient
from helpers_agent import FakeController, ScriptedPlanner

from octopus_browser import api as api_module
from octopus_browser.agent import (
    ActionIssue,
    ActionValidationError,
    AgentAction,
    AgentRun,
    AgentState,
    OctopusAgent,
)
from octopus_browser.config import AppConfig
from octopus_browser.vision import VisionDecision


def make_agent(config_overrides=None, planner=None, **kwargs) -> OctopusAgent:
    config = AppConfig()
    for key, value in (config_overrides or {}).items():
        setattr(config, key, value)
    controller = FakeController()
    agent = OctopusAgent(config, controller, planner=planner or ScriptedPlanner([VisionDecision("done")]),
                         sleep=lambda s: None, **kwargs)
    return agent


def test_done_happy_path_verified() -> None:
    planner = ScriptedPlanner([VisionDecision("goto", target="https://ok.test", confidence=0.9),
                               VisionDecision("done", confidence=0.9)])
    agent = make_agent(planner=planner)
    run = agent.run("open page", max_steps=5)
    assert run.status == "done" and run.state == AgentState.DONE
    assert run.verified is True and run.steps == 2
    assert run.final_url == "https://ok.test" and run.retries == 0 and run.recoveries == 0


def test_structured_validation_error() -> None:
    agent = make_agent()
    with pytest.raises(ActionValidationError) as exc_info:
        agent._validate(AgentAction("click", target=""))
    assert isinstance(exc_info.value, ValueError)
    assert exc_info.value.issues == [ActionIssue("target", "click: target обязателен")]
    with pytest.raises(ActionValidationError) as exc_info:
        agent._validate(AgentAction("hack"))
    assert exc_info.value.issues[0].field == "action"


def test_bad_plan_recovers_and_replans() -> None:
    planner = ScriptedPlanner([VisionDecision("click", target=""), VisionDecision("done")])
    agent = make_agent(planner=planner)
    run = agent.run("t", max_steps=5)
    assert run.status == "done" and run.recoveries == 1
    assert any("validate:" in line for line in run.log)


def test_retries_then_success() -> None:
    planner = ScriptedPlanner([VisionDecision("click", target="#ok"), VisionDecision("done")])
    agent = make_agent(planner=planner)
    agent.controller.failures["click"] = 2
    run = agent.run("t", max_steps=5)
    assert run.status == "done" and run.retries == 2 and run.recoveries == 0
    assert sum(1 for line in run.log if line.startswith("retry")) == 2


def test_retries_exhausted_triggers_reload_and_abort() -> None:
    planner = ScriptedPlanner([VisionDecision("click", target="#x")])
    agent = make_agent(planner=planner, config_overrides={"agent_max_recoveries": 1, "agent_max_retries": 1})
    agent.controller.failures["click"] = 100
    run = agent.run("t", max_steps=10)
    assert run.status == "error" and run.state == AgentState.ERROR
    assert run.recoveries == 2 and agent.controller.reloads == 1
    assert run.error.startswith("act:") and any("ошибка:" in line for line in run.log)


def test_stale_like_failures_are_marked() -> None:
    planner = ScriptedPlanner([VisionDecision("click", target="#s")])
    agent = make_agent(planner=planner, config_overrides={"agent_max_recoveries": 0, "agent_max_retries": 0})
    agent.controller.failures["click"] = 1
    agent.controller.fail_msg["click"] = "stale element reference: detached"
    run = agent.run("t", max_steps=3)
    assert run.status == "error" and any("stale-like" in line for line in run.log)


def test_cancel_event_stops_run() -> None:
    cancel = threading.Event()

    class CancellingPlanner(ScriptedPlanner):
        def decide(self, image_b64: str, task: str, history: list[str]) -> VisionDecision:
            decision = super().decide(image_b64, task, history)
            if self.calls >= 2:
                cancel.set()
            return decision

    agent = make_agent(planner=CancellingPlanner([VisionDecision("wait")]))
    run = agent.run("t", max_steps=10, cancel=cancel)
    assert run.status == "cancelled" and run.state == AgentState.CANCELLED
    assert run.steps == 1 and any("Отменено" in line for line in run.log)  # отмена видна уже на act шага 2


def test_deadline_stops_run() -> None:
    ticks = iter([0.0, 1000.0])
    agent = make_agent(planner=ScriptedPlanner([VisionDecision("wait")]), clock=lambda: next(ticks, 1000.0))
    run = agent.run("t", max_steps=10, deadline_seconds=5)
    assert run.status == "timeout" and run.state == AgentState.TIMEOUT
    assert run.steps == 0 and any("дедлайн" in line for line in run.log)


def test_deadline_zero_disables() -> None:
    agent = make_agent(planner=ScriptedPlanner([VisionDecision("done")]))
    run = agent.run("t", max_steps=2, deadline_seconds=0)
    assert run.status == "done"


def test_verify_fn_false_then_true() -> None:
    answers = iter([False, True])
    agent = make_agent(planner=ScriptedPlanner([VisionDecision("done")]), verify_fn=lambda t, u, h: next(answers))
    run = agent.run("t", max_steps=5)
    assert run.status == "done" and run.verified is True and run.steps == 2
    assert any("отклонён" in line for line in run.log)


def test_verify_fn_crash_rejects() -> None:
    def bad(task: str, url: str, history: list[str]) -> bool:
        raise RuntimeError("verifier down")

    agent = make_agent(planner=ScriptedPlanner([VisionDecision("done")]), verify_fn=bad)
    run = agent.run("t", max_steps=2)
    assert run.status == "limit" and run.verified is False
    assert any("verify_fn упал" in line for line in run.log)


def test_confidence_gate() -> None:
    agent = make_agent(planner=ScriptedPlanner([VisionDecision("done", confidence=0.3)]),
                       config_overrides={"agent_min_done_confidence": 0.8})
    run = agent.run("t", max_steps=2)
    assert run.status == "limit" and any("confidence 0.30 < 0.80" in line for line in run.log)
    agent = make_agent(planner=ScriptedPlanner([VisionDecision("done", confidence=0.9)]),
                       config_overrides={"agent_min_done_confidence": 0.8})
    assert agent.run("t", max_steps=2).status == "done"


def test_goto_postcondition() -> None:
    agent = make_agent()
    assert agent._check_postconditions(AgentAction("goto", target="https://a.test/x"), "https://a.test/x") is None
    assert agent._check_postconditions(AgentAction("goto", target="https://b.test"), "https://a.test") is None
    agent.controller.current_url = "https://a.test"
    issue = agent._check_postconditions(AgentAction("goto", target="https://b.test"), "https://a.test")
    assert issue is not None and "не сменил страницу" in issue


def test_custom_precondition_hook() -> None:
    def no_scroll(action: AgentAction) -> ActionIssue | None:
        if action.action == "scroll":
            return ActionIssue("action", "scroll запрещён политикой")
        return None

    planner = ScriptedPlanner([VisionDecision("scroll"), VisionDecision("done")])
    agent = make_agent(planner=planner, preconditions=[no_scroll])
    run = agent.run("t", max_steps=5)
    assert run.status == "done" and run.recoveries == 1
    assert any("scroll запрещён" in line for line in run.log)


def test_planner_abstraction_duck_typed() -> None:
    class MinimalPlanner:
        def __init__(self) -> None:
            self.seen: list[str] = []

        def decide(self, image_b64: str, task: str, history: list[str]) -> VisionDecision:
            self.seen.append(task)
            return VisionDecision("done", reason="custom")

    planner = MinimalPlanner()
    agent = make_agent(planner=planner)
    run = agent.run("hello", max_steps=2)
    assert run.status == "done" and planner.seen == ["hello"]


@pytest.fixture()
def agent_client(tmp_path, monkeypatch):
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


def test_api_agent_submit_cancel_cooperative(agent_client, monkeypatch) -> None:
    started = threading.Event()

    class BlockingAgent:
        def __init__(self, config, controller) -> None:
            pass

        def run(self, task, max_steps=None, cancel=None, deadline_seconds=None):
            started.set()
            ok = cancel.wait(timeout=10) if cancel is not None else True
            state = AgentState.CANCELLED if ok else AgentState.DONE
            return AgentRun(task=task, steps=1, status=state.value, state=state, log=["t"], final_url="u")

    class DummyController:
        def __init__(self, config, profile_dir=None) -> None:
            pass

        def stop(self) -> None:
            pass

    monkeypatch.setattr("octopus_browser.agent.OctopusAgent", BlockingAgent)
    monkeypatch.setattr("octopus_browser.core.launcher.BrowserController", DummyController)
    before = agent_client.get("/metrics").json()["agent_runs_total"]
    submit = agent_client.post("/agent/jobs", json={"task": "long", "profile": "main", "deadline_seconds": 60})
    assert submit.status_code == 202
    job_id = submit.json()["id"]
    assert _wait_until(started.is_set), "job did not start"
    cancel = agent_client.post(f"/agent/jobs/{job_id}/cancel")
    assert cancel.status_code == 200 and cancel.json()["mode"] == "cooperative"
    assert _wait_until(lambda: api_module._jobs.get(job_id).status == "done")
    assert api_module._jobs.get(job_id).result["status"] == "cancelled"
    after = agent_client.get("/metrics").json()
    assert after["agent_runs_total"] == before + 1
    assert agent_client.post("/agent/jobs/does-not-exist/cancel").status_code == 404
    assert agent_client.post(f"/agent/jobs/{job_id}/cancel").status_code == 409


def test_api_agent_task_deadline_validation(agent_client) -> None:
    bad = agent_client.post("/agent/jobs", json={"task": "t", "deadline_seconds": -1})
    assert bad.status_code == 422
