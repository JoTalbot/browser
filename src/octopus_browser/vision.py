"""👁️ Vision-движок: «зрение» браузера + планирование действий.

Агент смотрит на скриншот, описывает его (или получает описание от LLM),
выбирает следующее действие и возвращает его исполнителю.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any, Callable, Optional

from octopus_browser.config import AppConfig

log = logging.getLogger("octopus.vision")

ACTIONS = {"goto", "click", "fill", "scroll", "wait", "new_tab", "close_tab", "done"}


@dataclass
class VisionDecision:
    """Решение агента после анализа кадра."""

    action: str
    target: str = ""
    text: str = ""
    reason: str = ""


class VisionEngine:
    """Обёртка над vision-LLM (OpenAI-совместимый эндпоинт) с fallback."""

    def __init__(self, config: AppConfig, describe_fn: Optional[Callable[[str], str]] = None):
        self.config = config
        self._describe_fn = describe_fn

    def describe(self, image_b64: str) -> str:
        """Описание кадра: через LLM или локальный хук."""
        if self._describe_fn is not None:
            return self._describe_fn(image_b64)
        if not self.config.vision_api_url or not self.config.vision_api_key:
            return "Vision API не настроена — анализатор в режиме заглушки"
        return self._call_llm("Опиши содержимое скриншота кратко и структурированно.", image_b64)

    def decide(self, image_b64: str, goal: str, history: list[str]) -> VisionDecision:
        """Принять решение: следующее действие для достижения цели."""
        description = self.describe(image_b64)
        if not self.config.vision_api_url or not self.config.vision_api_key:
            return VisionDecision(action="wait", reason=description)

        plan = self._call_llm(
            prompt=(
                f"Цель: {goal}\nКраткое описание кадра: {description}\n"
                f"История: {history[-3:]}\n"
                "Выбери одно действие из: goto, click, fill, scroll, wait, new_tab, "
                "close_tab, done. Верни ТОЛЬКО JSON: "
                '{"action":"...","target":"...","text":"...","reason":"..."}'
            ),
            image=image_b64,
        )
        try:
            raw = json.loads(plan)
            action = raw.get("action", "wait")
            if action not in ACTIONS:
                action = "wait"
            return VisionDecision(
                action=action,
                target=str(raw.get("target", "")),
                text=str(raw.get("text", "")),
                reason=str(raw.get("reason", "")),
            )
        except (ValueError, TypeError, json.JSONDecodeError):
            return VisionDecision(action="wait", reason="Не удалось распарсить план")

    def _call_llm(self, prompt: str, image: Optional[str] = None) -> str:
        """Вызов OpenAI-совместимого vision API (chat/completions)."""
        import httpx  # noqa: PLC0415

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
        resp = httpx.post(
            f"{self.config.vision_api_url.rstrip('/')}/chat/completions",
            headers=headers,
            json=payload,
            timeout=60,
        )
        resp.raise_for_status()
        data = resp.json()
        content = data["choices"][0]["message"]["content"]
        if not isinstance(content, str):
            raise ValueError("Vision API вернула неподдерживаемый формат content")
        return content
