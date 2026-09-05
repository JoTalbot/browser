"""🤖 Typed, bounded agent orchestration primitives."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import ClassVar

from octopus_browser.config import AppConfig
from octopus_browser.core.launcher import BrowserController
from octopus_browser.vision import VisionDecision, VisionEngine

log = logging.getLogger("octopus.agent")


class AgentState(str, Enum):
    OBSERVE = "observe"
    PLAN = "plan"
    VALIDATE = "validate"
    ACT = "act"
    VERIFY = "verify"
    DONE = "done"
    LIMIT = "limit"
    ERROR = "error"


@dataclass
class AgentAction:
    action: str
    target: str = ""
    text: str = ""
    reason: str = ""

    @classmethod
    def from_decision(cls, decision: VisionDecision) -> AgentAction:
        return cls(decision.action, decision.target, decision.text, decision.reason)


@dataclass
class AgentRun:
    task: str
    steps: int = 0
    status: str = "idle"
    state: AgentState = AgentState.OBSERVE
    log: list[str] = field(default_factory=list)
    final_url: str = ""


class OctopusAgent:
    """Bounded observe/plan/validate/act/verify loop."""

    ALLOWED_ACTIONS: ClassVar[set[str]] = {"goto", "click", "fill", "scroll", "wait", "new_tab", "close_tab", "done"}

    def __init__(self, config: AppConfig, controller: BrowserController, vision: VisionEngine | None = None) -> None:
        self.config = config
        self.controller = controller
        self.vision = vision or VisionEngine(config)

    def run(self, task: str, max_steps: int | None = None) -> AgentRun:
        if not task or not task.strip():
            raise ValueError("Задача агента не может быть пустой")
        run = AgentRun(task=task, status="running")
        limit = max_steps if max_steps is not None else self.config.max_steps
        if limit < 1:
            raise ValueError("max_steps должен быть >= 1")
        history: list[str] = []
        try:
            self.controller.start()
            run.log.append("Браузер запущен")
            for step in range(limit):
                run.state = AgentState.OBSERVE
                screenshot = self.controller.screenshot()
                run.state = AgentState.PLAN
                action = AgentAction.from_decision(self.vision.decide(screenshot, task, history))
                run.state = AgentState.VALIDATE
                self._validate(action)
                run.state = AgentState.ACT
                self._execute(action)
                history.append(f"{action.action} {action.target}")
                run.steps = step + 1
                run.log.append(f"шаг {run.steps}: {action.action} {action.target} ({action.reason})")
                run.state = AgentState.VERIFY
                if action.action == "done":
                    run.state = AgentState.DONE
                    run.status = "done"
                    break
            else:
                run.state = AgentState.LIMIT
                run.status = "limit"
                run.log.append(f"Достигнут лимит шагов ({limit}) без подтверждения done")
            run.final_url = self.controller.url()
        except Exception as exc:
            run.state = AgentState.ERROR
            run.status = "error"
            run.log.append(f"ошибка: {exc}")
            log.exception("Agent run failed")
        finally:
            self.controller.stop()
        return run

    def _validate(self, action: AgentAction) -> None:
        if action.action not in self.ALLOWED_ACTIONS:
            raise ValueError(f"Неизвестное действие: {action.action}")
        if action.action == "goto" and not action.target.startswith(("http://", "https://")):
            raise ValueError("goto: только http/https URL")
        if action.action in {"click", "fill"} and not action.target.strip():
            raise ValueError(f"{action.action}: target обязателен")
        if action.action == "fill" and not action.text:
            raise ValueError("fill: text обязателен")

    def _execute(self, action: AgentAction) -> None:
        if action.action == "goto":
            self.controller.goto(action.target)
        elif action.action == "click":
            self.controller.click(action.target)
        elif action.action == "fill":
            self.controller.fill(action.target, action.text)
        elif action.action == "scroll":
            self.controller.scroll(400)
        elif action.action == "new_tab":
            self.controller.new_tab()
        elif action.action == "close_tab":
            self.controller.close_tab()
        elif action.action == "wait":
            self.controller.wait(1.0)
        elif action.action == "done":
            return
