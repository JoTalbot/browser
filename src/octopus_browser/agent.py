"""🤖 OctopusAgent: ИИ-агент, управляющий браузером «как человек».

Цикл: скриншот → vision → решение (действие) → исполнение → повтор.
Скорость/задержки — HumanPacer; лимиты — max_steps (безопасность).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import List, Optional

from octopus_browser.config import AppConfig
from octopus_browser.core.launcher import BrowserController
from octopus_browser.vision import VisionEngine

log = logging.getLogger("octopus.agent")


@dataclass
class AgentRun:
    """Результат/состояние выполнения задачи."""

    task: str
    steps: int = 0
    status: str = "idle"  # idle | running | done | error
    log: List[str] = field(default_factory=list)
    final_url: str = ""


class OctopusAgent:
    """Оркестратор браузера с vision-управлением."""

    def __init__(self, config: AppConfig, controller: BrowserController,
                 vision: Optional[VisionEngine] = None) -> None:
        self.config = config
        self.controller = controller
        self.vision = vision or VisionEngine(config)

    def run(self, task: str, max_steps: Optional[int] = None) -> AgentRun:
        """🚀 Выполнить задачу (синхронно, для тестов/CLI)."""
        run = AgentRun(task=task, status="running")
        limit = max_steps or self.config.max_steps
        history: List[str] = []
        try:
            self.controller.start()
            run.log.append("Браузер запущен")
            for step in range(limit):
                screenshot = self.controller.screenshot()
                decision = self.vision.decide(screenshot, task, history)
                run.log.append(f"шаг {step + 1}: {decision.action} {decision.target} "
                               f"({decision.reason})")
                self._execute(decision.action, decision.target, decision.text)
                history.append(f"{decision.action} {decision.target}")
                if decision.action == "done":
                    run.status = "done"
                    break
                run.steps = step + 1
            else:
                run.status = "done"
                run.log.append(f"Достигнут лимит шагов ({limit})")
            run.final_url = self.controller.url()
        except Exception as exc:  # noqa: BLE001
            run.status = "error"
            run.log.append(f"ошибка: {exc}")
            log.exception("Agent run failed")
        finally:
            self.controller.stop()
        return run

    # ---- защищённое исполнение ------------------------------------------
    def _execute(self, action: str, target: str = "", text: str = "") -> None:
        """Исполнить действие из whitelist (безопасность)."""
        if action == "goto":
            if not target.startswith(("http://", "https://")):
                raise ValueError("goto: только http/https URL")
            self.controller.goto(target)
        elif action == "click":
            self.controller.click(target)
        elif action == "fill":
            self.controller.fill(target, text)
        elif action == "scroll":
            self.controller.scroll(400)
        elif action == "new_tab":
            self.controller.new_tab()
        elif action == "close_tab":
            self.controller.close_tab()
        elif action == "wait":
            self.controller.wait(1.0)
        elif action == "done":
            return
        else:
            raise ValueError(f"Неизвестное действие: {action}")
