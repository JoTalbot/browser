"""🧪 Нагрузочный сценарий агента: 100 задач со смешанными исходами (без браузера)."""
from __future__ import annotations

import threading
import time

from helpers_agent import FakeController, ScriptedPlanner

from octopus_browser.agent import AgentState, OctopusAgent
from octopus_browser.config import AppConfig
from octopus_browser.vision import VisionDecision


class CancellingPlanner(ScriptedPlanner):
    def __init__(self, decisions: list[VisionDecision], event, at: int = 2) -> None:
        super().__init__(decisions)
        self.event = event
        self.at = at
        self.n = 0

    def decide(self, image_b64: str, task: str, history: list[str]) -> VisionDecision:
        decision = super().decide(image_b64, task, history)
        self.n += 1
        if self.n >= self.at:
            self.event.set()
        return decision


def test_agent_load_100_tasks() -> None:
    config = AppConfig()
    outcomes: dict[str, int] = {}
    total_steps = 0
    total_retries = 0
    total_recoveries = 0
    planner_calls = 0
    started = time.monotonic()
    for i in range(100):
        controller = FakeController()
        kind = i % 20
        if kind < 17:
            planner = ScriptedPlanner([VisionDecision("goto", target=f"https://t{i}.test", confidence=0.9),
                                       VisionDecision("done", confidence=0.9)])
            agent = OctopusAgent(config, controller, planner=planner, sleep=lambda s: None)
            run = agent.run(f"task-{i}", max_steps=5)
        elif kind == 17:
            planner = ScriptedPlanner([VisionDecision("click", target="#ok"), VisionDecision("done")])
            controller.failures["click"] = 1
            agent = OctopusAgent(config, controller, planner=planner, sleep=lambda s: None)
            run = agent.run(f"task-{i}", max_steps=5)
        elif kind == 18:
            cancel = threading.Event()
            agent = OctopusAgent(config, controller, planner=CancellingPlanner([VisionDecision("wait")], cancel),
                                 sleep=lambda s: None)
            run = agent.run(f"task-{i}", max_steps=10, cancel=cancel)
        else:
            ticks = iter([0.0, 1000.0])
            agent = OctopusAgent(config, controller, planner=ScriptedPlanner([VisionDecision("wait")]),
                                 sleep=lambda s: None, clock=lambda ticks=ticks: next(ticks, 1000.0))
            run = agent.run(f"task-{i}", max_steps=10, deadline_seconds=5)
        outcomes[run.status] = outcomes.get(run.status, 0) + 1
        total_steps += run.steps
        total_retries += run.retries
        total_recoveries += run.recoveries
        planner_calls += planner.calls
        assert run.state in {AgentState.DONE, AgentState.CANCELLED, AgentState.TIMEOUT}
    elapsed = time.monotonic() - started
    print(f"\nload: {outcomes} steps={total_steps} retries={total_retries} "
          f"recoveries={total_recoveries} planner_calls={planner_calls} elapsed={elapsed:.2f}s")
    assert outcomes == {"done": 90, "cancelled": 5, "timeout": 5}
    assert total_retries == 5 and total_recoveries == 0
    assert elapsed < 60.0
