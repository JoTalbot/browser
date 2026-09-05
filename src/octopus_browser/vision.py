"""👁️ Vision engine with bounded, typed decisions and provider budgets."""
from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from octopus_browser.config import AppConfig

log = logging.getLogger("octopus.vision")
ACTIONS = {"goto", "click", "fill", "scroll", "wait", "new_tab", "close_tab", "done"}


@dataclass
class VisionDecision:
    action: str
    target: str = ""
    text: str = ""
    reason: str = ""
    confidence: float = 0.0


class VisionEngine:
    """Обёртка над OpenAI-compatible vision API с fail-safe parsing."""

    def __init__(self, config: AppConfig, describe_fn: Callable[[str], str] | None = None) -> None:
        self.config = config
        self._describe_fn = describe_fn

    def describe(self, image_b64: str) -> str:
        if self._describe_fn is not None:
            return self._describe_fn(image_b64)
        if not self.config.vision_api_url or not self.config.vision_api_key:
            return "Vision API не настроена — анализатор в режиме заглушки"
        return self._call_llm("Опиши содержимое скриншота кратко и структурированно.", image_b64)

    def decide(self, image_b64: str, goal: str, history: list[str]) -> VisionDecision:
        description = self.describe(image_b64)
        if not self.config.vision_api_url or not self.config.vision_api_key:
            return VisionDecision(action="wait", reason=description)
        plan = self._call_llm(
            prompt=(
                f"Цель: {goal}\nКраткое описание кадра: {description}\n"
                f"История: {history[-3:]}\n"
                "Выбери одно действие из: goto, click, fill, scroll, wait, new_tab, "
                "close_tab, done. Верни ТОЛЬКО JSON: "
                '{"action":"...","target":"...","text":"...",'
                '"reason":"...","confidence":0.0}'
            ),
            image=image_b64,
        )
        try:
            raw = json.loads(plan)
            if not isinstance(raw, dict):
                raise TypeError("decision должен быть JSON-объектом")
            action = str(raw.get("action", "wait"))
            if action not in ACTIONS:
                action = "wait"
            confidence = float(raw.get("confidence", 0.0))
            confidence = min(1.0, max(0.0, confidence))
            return VisionDecision(
                action=action,
                target=str(raw.get("target", "")),
                text=str(raw.get("text", "")),
                reason=str(raw.get("reason", "")),
                confidence=confidence,
            )
        except (ValueError, TypeError, json.JSONDecodeError, KeyError):
            return VisionDecision(action="wait", reason="Не удалось распарсить план")

    def _call_llm(self, prompt: str, image: str | None = None) -> str:
        import httpx

        headers = {"Authorization": f"Bearer {self.config.vision_api_key}"}
        payload: dict[str, Any] = {
            "model": self.config.vision_model or "gpt-4o",
            "messages": [{"role": "user", "content": prompt}],
        }
        if image:
            payload["messages"][0]["content"] = [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{image}"}},
            ]
        started = time.monotonic()
        try:
            response = httpx.post(
                f"{self.config.vision_api_url.rstrip('/')}/chat/completions",
                headers=headers,
                json=payload,
                timeout=min(60.0, self.config.request_timeout_seconds),
            )
            response.raise_for_status()
            data = response.json()
            content = data["choices"][0]["message"]["content"]
            if not isinstance(content, str):
                raise TypeError("Vision API вернула неподдерживаемый формат content")
            return content
        finally:
            log.debug("vision provider latency_ms=%.1f", (time.monotonic() - started) * 1000)
