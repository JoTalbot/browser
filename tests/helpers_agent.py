"""🧪 Общие фейки для тестов агента (контроллер + планировщик, без браузера)."""
from __future__ import annotations

from octopus_browser.vision import VisionDecision


class FakeController:
    def __init__(self) -> None:
        self.started = False
        self.current_url = "https://start.test"
        self.actions: list[tuple] = []
        self.failures: dict[str, int] = {}
        self.fail_msg: dict[str, str] = {}
        self.reloads = 0

    def _maybe_fail(self, name: str) -> None:
        remaining = self.failures.get(name, 0)
        if remaining > 0:
            self.failures[name] = remaining - 1
            raise RuntimeError(self.fail_msg.get(name, f"{name} boom"))

    def start(self) -> None:
        self.started = True

    def stop(self) -> None:
        self.started = False

    def screenshot(self) -> str:
        self._maybe_fail("screenshot")
        return "aGk="

    def url(self) -> str:
        return self.current_url

    def goto(self, url: str) -> None:
        self._maybe_fail("goto")
        self.actions.append(("goto", url))
        self.current_url = url

    def click(self, selector: str) -> None:
        self._maybe_fail("click")
        self.actions.append(("click", selector))

    def fill(self, selector: str, text: str) -> None:
        self._maybe_fail("fill")
        self.actions.append(("fill", selector, text))

    def scroll(self, amount: int = 400) -> None:
        self.actions.append(("scroll", amount))

    def wait(self, seconds: float = 1.0) -> None:
        self.actions.append(("wait", seconds))

    def new_tab(self) -> None:
        self.actions.append(("new_tab",))

    def close_tab(self) -> None:
        self.actions.append(("close_tab",))

    def reload(self) -> None:
        self.reloads += 1
        self.actions.append(("reload",))


class ScriptedPlanner:
    def __init__(self, decisions: list[VisionDecision]) -> None:
        assert decisions
        self.decisions = list(decisions)
        self.calls = 0

    def decide(self, image_b64: str, task: str, history: list[str]) -> VisionDecision:
        self.calls += 1
        if len(self.decisions) > 1:
            return self.decisions.pop(0)
        return self.decisions[0]


