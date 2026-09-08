"""Тонкий клиент к существующему локальному AIOS bridge."""

from __future__ import annotations

from typing import Any

import httpx


class AIOSBridgeError(RuntimeError):
    """AIOS bridge недоступен или вернул некорректный ответ."""


class AIOSBridgeClient:
    """Делегирует планирование/статус локальному AIOS, не передавая ему секреты профиля."""

    def __init__(
        self, base_url: str, transport: httpx.BaseTransport | None = None
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.transport = transport

    def status(self) -> dict[str, Any]:
        try:
            with httpx.Client(timeout=5.0, transport=self.transport) as client:
                response = client.get(f"{self.base_url}/api/v1/aios/status")
                response.raise_for_status()
                data = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise AIOSBridgeError(
                f"AIOS bridge status error: {type(exc).__name__}"
            ) from exc
        if not isinstance(data, dict):
            raise AIOSBridgeError("AIOS bridge status должен быть JSON-объектом")
        return data

    def ask(self, goal: str, system_prompt: str | None = None) -> dict[str, Any]:
        if not goal or len(goal) > 20_000:
            raise ValueError("goal должен быть непустым и не длиннее 20000 символов")
        payload: dict[str, str] = {"goal": goal}
        if system_prompt:
            payload["system_prompt"] = system_prompt
        try:
            with httpx.Client(timeout=30.0, transport=self.transport) as client:
                response = client.post(f"{self.base_url}/api/v1/aios/ask", json=payload)
                response.raise_for_status()
                data = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise AIOSBridgeError(
                f"AIOS bridge ask error: {type(exc).__name__}"
            ) from exc
        if not isinstance(data, dict):
            raise AIOSBridgeError("AIOS bridge ask должен вернуть JSON-объект")
        return data
