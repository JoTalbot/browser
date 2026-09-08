"""🤖 Typed, bounded agent orchestration with retries, recovery and verification."""
from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import ClassVar, Protocol

from octopus_browser.config import AppConfig
from octopus_browser.core.launcher import BrowserController
from octopus_browser.vision import VisionDecision, VisionEngine

log = logging.getLogger("octopus.agent")

STALE_MARKERS = ("stale", "detached", "timeout", "Timeout", "waiting for", "not found", "Target closed", "has been closed")


class AgentState(str, Enum):
    OBSERVE = "observe"
    PLAN = "plan"
    VALIDATE = "validate"
    ACT = "act"
    VERIFY = "verify"
    DONE = "done"
    LIMIT = "limit"
    ERROR = "error"
    CANCELLED = "cancelled"
    TIMEOUT = "timeout"


@dataclass
class ActionIssue:
    field: str
    message: str


class ActionValidationError(ValueError):
    """Структурированная ошибка валидации действия (подкласс ValueError)."""

    def __init__(self, issues: list[ActionIssue]) -> None:
        self.issues = list(issues)
        super().__init__("; ".join(f"{issue.field}: {issue.message}" for issue in self.issues))


@dataclass
class AgentAction:
    action: str
    target: str = ""
    text: str = ""
    reason: str = ""
    confidence: float = 0.0

    @classmethod
    def from_decision(cls, decision: VisionDecision) -> AgentAction:
        return cls(decision.action, decision.target, decision.text, decision.reason, decision.confidence)


@dataclass
class AgentRun:
    task: str
    steps: int = 0
    status: str = "idle"
    state: AgentState = AgentState.OBSERVE
    log: list[str] = field(default_factory=list)
    final_url: str = ""
    retries: int = 0
    recoveries: int = 0
    verified: bool = False
    error: str = ""


class AgentPlanner(Protocol):
    """Абстракция планировщика (провайдер решений для агента)."""

    def decide(self, image_b64: str, task: str, history: list[str]) -> VisionDecision:
        """Спланировать следующее действие по скриншоту."""
        ...


VerifyFn = Callable[[str, str, list[str]], bool]


class _CancelRequested(Exception):
    """Внутренний сигнал кооперативной отмены."""


class OctopusAgent:
    """Bounded observe/plan/validate/act/verify loop with retries, recovery, deadlines."""

    ALLOWED_ACTIONS: ClassVar[set[str]] = {"goto", "click", "fill", "scroll", "wait", "new_tab", "close_tab", "done"}

    def __init__(
        self,
        config: AppConfig,
        controller: BrowserController,
        vision: VisionEngine | None = None,
        planner: AgentPlanner | None = None,
        verify_fn: VerifyFn | None = None,
        preconditions: list[Callable[[AgentAction], ActionIssue | None]] | None = None,
        clock: Callable[[], float] | None = None,
        sleep: Callable[[float], None] | None = None,
    ) -> None:
        self.config = config
        self.controller = controller
        self.vision = vision or VisionEngine(config)
        self.planner = planner if planner is not None else self.vision
        self.verify_fn = verify_fn
        self.preconditions = list(preconditions or [])
        self._clock = clock or time.monotonic
        self._sleep = sleep or time.sleep

    def run(
        self,
        task: str,
        max_steps: int | None = None,
        cancel: threading.Event | None = None,
        deadline_seconds: float | None = None,
    ) -> AgentRun:
        if not task or not task.strip():
            raise ValueError("Задача агента не может быть пустой")
        run = AgentRun(task=task, status="running")
        limit = max_steps if max_steps is not None else self.config.max_steps
        if limit < 1:
            raise ValueError("max_steps должен быть >= 1")
        deadline = self.config.agent_deadline_seconds if deadline_seconds is None else deadline_seconds
        if deadline is not None and deadline < 0:
            raise ValueError("deadline_seconds должен быть >= 0")
        started = self._clock()
        history: list[str] = []
        try:
            self.controller.start()
            run.log.append("Браузер запущен")
            for step in range(limit):
                if cancel is not None and cancel.is_set():
                    run.state = AgentState.CANCELLED
                    run.status = "cancelled"
                    run.log.append("Отменено по запросу")
                    break
                if deadline and self._clock() - started >= deadline:
                    run.state = AgentState.TIMEOUT
                    run.status = "timeout"
                    run.log.append(f"Превышен дедлайн ({deadline:g} c)")
                    break
                outcome = self._step(task, history, run, step, cancel)
                if outcome != "next":
                    if outcome == "done":
                        run.state = AgentState.DONE
                        run.status = "done"
                    break
            else:
                run.state = AgentState.LIMIT
                run.status = "limit"
                run.log.append(f"Достигнут лимит шагов ({limit}) без подтверждения done")
            try:
                run.final_url = self.controller.url()
            except Exception as exc:
                if run.status != "error":
                    raise
                run.log.append(f"final_url недоступен: {exc}")
        except Exception as exc:
            run.state = AgentState.ERROR
            run.status = "error"
            run.error = str(exc)
            run.log.append(f"ошибка: {exc}")
            log.exception("Agent run failed")
        finally:
            self.controller.stop()
        return run

    def _step(self, task: str, history: list[str], run: AgentRun, step: int, cancel: threading.Event | None) -> str:
        run.state = AgentState.OBSERVE
        try:
            screenshot = self.controller.screenshot()
        except Exception as exc:  # noqa: BLE001 - observe failures go to recovery
            return self._fail_or_recover(run, f"observe: {exc}", refresh=True)
        run.state = AgentState.PLAN
        try:
            action = AgentAction.from_decision(self.planner.decide(screenshot, task, history))
        except Exception as exc:  # noqa: BLE001 - planner failures go to recovery
            return self._fail_or_recover(run, f"plan: {exc}", refresh=False)
        run.state = AgentState.VALIDATE
        try:
            self._validate(action)
        except ActionValidationError as exc:
            return self._fail_or_recover(run, f"validate: {exc}", refresh=False)
        run.state = AgentState.ACT
        before_url = self._safe_url()
        try:
            self._execute_with_retries(action, run, cancel)
        except _CancelRequested:
            run.state = AgentState.CANCELLED
            run.status = "cancelled"
            run.log.append("Отменено по запросу")
            return "cancelled"
        except Exception as exc:  # noqa: BLE001 - act failures go to recovery
            stale = " (stale-like)" if self._looks_stale(exc) else ""
            return self._fail_or_recover(run, f"act: {exc}{stale}", refresh=True)
        history.append(f"{action.action} {action.target}")
        run.steps = step + 1
        run.log.append(f"шаг {run.steps}: {action.action} {action.target} ({action.reason})")
        run.state = AgentState.VERIFY
        post_issue = self._check_postconditions(action, before_url)
        if post_issue is not None:
            return self._fail_or_recover(run, f"postcondition: {post_issue}", refresh=True)
        if action.action == "done":
            if self._verify_goal(task, action, history, run):
                run.verified = True
                return "done"
            run.log.append("done отклонён верификацией цели — продолжаю")
        return "next"

    def _validate(self, action: AgentAction) -> None:
        issues: list[ActionIssue] = []
        if action.action not in self.ALLOWED_ACTIONS:
            issues.append(ActionIssue("action", f"Неизвестное действие: {action.action}"))
        elif action.action == "goto" and not action.target.startswith(("http://", "https://")):
            issues.append(ActionIssue("target", "goto: только http/https URL"))
        elif action.action in {"click", "fill"} and not action.target.strip():
            issues.append(ActionIssue("target", f"{action.action}: target обязателен"))
        elif action.action == "fill" and not action.text:
            issues.append(ActionIssue("text", "fill: text обязателен"))
        for precondition in self.preconditions:
            try:
                issue = precondition(action)
            except Exception as exc:  # noqa: BLE001 - broken precondition becomes an issue, not a crash
                name = getattr(precondition, "__name__", "custom")
                issues.append(ActionIssue("precondition", f"{name}: {exc}"))
            else:
                if issue is not None:
                    issues.append(issue)
        if issues:
            raise ActionValidationError(issues)

    def _execute_with_retries(self, action: AgentAction, run: AgentRun, cancel: threading.Event | None) -> None:
        for attempt in range(self.config.agent_max_retries + 1):
            if cancel is not None and cancel.is_set():
                raise _CancelRequested
            try:
                self._execute(action)
                return
            except Exception as exc:
                if attempt >= self.config.agent_max_retries:
                    raise
                run.retries += 1
                run.log.append(f"retry {attempt + 1}/{self.config.agent_max_retries}: {action.action} ({exc})")
                self._sleep(min(2.0, 0.2 * (2**attempt)))

    def _fail_or_recover(self, run: AgentRun, reason: str, refresh: bool) -> str:
        run.recoveries += 1
        run.log.append(f"сбой: {reason} (восстановление {run.recoveries}/{self.config.agent_max_recoveries})")
        log.warning("agent recovery: %s", reason)
        if run.recoveries > self.config.agent_max_recoveries:
            run.state = AgentState.ERROR
            run.status = "error"
            run.error = reason
            run.log.append(f"ошибка: {reason}")
            return "abort"
        if refresh:
            reload = getattr(self.controller, "reload", None)
            if callable(reload):
                try:
                    reload()
                    run.log.append("страница обновлена (reload)")
                except Exception as exc:  # noqa: BLE001 - failed reload is logged, loop continues
                    run.log.append(f"reload не удался: {exc}")
        return "next"

    def _check_postconditions(self, action: AgentAction, before_url: str) -> str | None:
        after_url = self._safe_url()
        if after_url == "" and before_url != "":
            return "контроллер перестал отвечать (пустой url после действия)"
        if action.action == "goto" and after_url and before_url and after_url == before_url:
            host = action.target.split("://", 1)[1].split("/", 1)[0] if "://" in action.target else ""
            if host and host not in after_url:
                return f"goto не сменил страницу (url без изменений: {before_url})"
        return None

    def _verify_goal(self, task: str, action: AgentAction, history: list[str], run: AgentRun) -> bool:
        if self.verify_fn is not None:
            try:
                return bool(self.verify_fn(task, self._safe_url(), list(history)))
            except Exception as exc:  # noqa: BLE001 - broken verifier rejects the goal, loudly
                run.log.append(f"verify_fn упал: {exc} — считаю непройденной")
                return False
        threshold = self.config.agent_min_done_confidence
        if threshold > 0 and action.confidence < threshold:
            run.log.append(f"done confidence {action.confidence:.2f} < {threshold:.2f}")
            return False
        return True

    def _safe_url(self) -> str:
        try:
            url = self.controller.url()
        except Exception:  # noqa: BLE001 - url probe must never fail
            return ""
        return url if isinstance(url, str) else ""

    @staticmethod
    def _looks_stale(exc: Exception) -> bool:
        return any(marker in str(exc) for marker in STALE_MARKERS)

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
