"""Vision router для анализа скриншотов без вывода API-ключей в логи."""

from __future__ import annotations

import asyncio
import base64
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any

import httpx

from .config import AdapterSettings


class VisionError(RuntimeError):
    """Ошибка vision-провайдера или privacy/consent gate."""


@dataclass(frozen=True)
class VisionResult:
    provider: str
    model: str
    text: str
    latency_ms: float
    image_bytes: int

    def as_dict(self) -> dict[str, object]:
        return {
            "provider": self.provider,
            "model": self.model,
            "text": self.text,
            "latency_ms": self.latency_ms,
            "image_bytes": self.image_bytes,
        }


class VisionRouter:
    """Выбирает vision-провайдера с bounded fallback.

    Приоритет по умолчанию основан на безопасном синтетическом benchmark на сервере:
    Gemini 2.5 Flash показал рабочий путь для base64-кадров. Groq Qwen 3.8
    остаётся fallback и также поддерживается для valid PNG/JPEG кадров.

    `balancer` — опциональный OpenAI-compatible LLM gateway (например,
    self-hosted Arena Gateway). Он не включается автоматически и всё равно
    защищён общим consent gate внешнего vision.
    """

    def __init__(
        self,
        settings: AdapterSettings,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.settings = settings
        self.transport = transport

    def _providers(self) -> list[tuple[str, str, str]]:
        configured = {
            "gemini": (self.settings.gemini_api_key, self.settings.gemini_model),
            "groq": (self.settings.groq_api_key, self.settings.groq_model),
            "balancer": (
                self.settings.llm_balancer_url,
                self.settings.llm_balancer_model,
            ),
        }
        order = (
            ["balancer", "gemini", "groq"]
            if self.settings.vision_provider == "auto"
            else [self.settings.vision_provider]
        )
        if self.settings.vision_provider != "auto":
            fallback = {
                "gemini": "groq",
                "groq": "gemini",
                "balancer": "gemini",
            }[self.settings.vision_provider]
            order.append(fallback)
        providers = []
        for name in order:
            endpoint, model = configured[name]
            if endpoint and (name, model) not in {
                (item[0], item[1]) for item in providers
            }:
                providers.append((name, model, endpoint))
        return providers

    async def analyze(
        self,
        image: bytes,
        mime_type: str = "image/png",
        prompt: str = "Опиши интерфейс кратко.",
    ) -> VisionResult:
        if not self.settings.allow_external_vision:
            raise VisionError(
                "Внешний vision отключён: установите OCTOPUS_BROWSER_ALLOW_EXTERNAL_VISION=1 после проверки политики данных"
            )
        if not image or len(image) > self.settings.max_image_bytes:
            raise VisionError("размер изображения не соответствует лимиту")
        if mime_type not in {"image/png", "image/jpeg", "image/webp"}:
            raise VisionError("поддерживаются только PNG, JPEG и WEBP")
        providers = self._providers()
        if not providers:
            raise VisionError("не настроен ни один vision API key")
        errors: list[str] = []
        for provider, model, key in providers:
            started = time.perf_counter()
            try:
                text = await self._call(provider, model, key, image, mime_type, prompt)
                return VisionResult(
                    provider,
                    model,
                    text,
                    round((time.perf_counter() - started) * 1000, 1),
                    len(image),
                )
            except (
                httpx.HTTPError,
                KeyError,
                TypeError,
                ValueError,
                VisionError,
            ) as exc:
                errors.append(f"{provider}:{type(exc).__name__}")
        raise VisionError(
            "все vision-провайдеры завершились ошибкой: " + ", ".join(errors)
        )

    def analyze_sync(
        self,
        image: bytes,
        mime_type: str = "image/png",
        prompt: str = "Опиши интерфейс кратко.",
    ) -> VisionResult:
        """Run async vision from both sync code and an active event-loop thread."""
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(self.analyze(image, mime_type, prompt))

        # FastAPI/AnyIO or a sync Playwright integration may already own the
        # current thread's event loop. Run the bounded HTTP call in a helper
        # thread instead of nesting asyncio.run() into that loop.
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(
                asyncio.run, self.analyze(image, mime_type, prompt)
            )
            return future.result()

    async def _call(
        self,
        provider: str,
        model: str,
        key: str,
        image: bytes,
        mime_type: str,
        prompt: str,
    ) -> str:
        encoded = base64.b64encode(image).decode("ascii")
        if provider == "gemini":
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
            payload: dict[str, Any] = {
                "contents": [
                    {
                        "parts": [
                            {"text": prompt},
                            {"inline_data": {"mime_type": mime_type, "data": encoded}},
                        ]
                    }
                ],
                "generationConfig": {"maxOutputTokens": 128},
            }
            headers = {"x-goog-api-key": key, "Content-Type": "application/json"}
            path = url
        elif provider in {"groq", "balancer"}:
            if provider == "groq":
                path = "https://api.groq.com/openai/v1/chat/completions"
                headers = {
                    "Authorization": f"Bearer {key}",
                    "Content-Type": "application/json",
                }
                max_tokens_key = "max_completion_tokens"
            else:
                path = f"{key.rstrip('/')}/chat/completions"
                headers = {"Content-Type": "application/json"}
                if self.settings.llm_balancer_api_key:
                    headers["Authorization"] = (
                        f"Bearer {self.settings.llm_balancer_api_key}"
                    )
                max_tokens_key = "max_tokens"
            payload = {
                "model": model,
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": prompt},
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:{mime_type};base64,{encoded}"
                                },
                            },
                        ],
                    }
                ],
                max_tokens_key: 128,
                "temperature": 0,
            }
        else:
            raise VisionError(f"неподдерживаемый provider: {provider}")
        async with httpx.AsyncClient(
            timeout=self.settings.request_timeout_seconds, transport=self.transport
        ) as client:
            response = await client.post(path, headers=headers, json=payload)
        if response.status_code >= 400:
            raise VisionError(f"{provider}: HTTP {response.status_code}")
        data = response.json()
        if provider == "gemini":
            text = data["candidates"][0]["content"]["parts"][0]["text"]
        else:
            text = data["choices"][0]["message"]["content"]
        if not isinstance(text, str) or not text.strip():
            raise VisionError(f"{provider}: пустой ответ")
        return text.strip()
