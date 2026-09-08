"""👁️ Vision engine: провайдеры, fusion кадров, бюджеты и fail-safe решения."""
from __future__ import annotations

import base64
import binascii
import hashlib
import json
import logging
import threading
import time
from abc import ABC, abstractmethod
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass
from string import Template
from typing import Any

import httpx

from octopus_browser.config import AppConfig

log = logging.getLogger("octopus.vision")
ACTIONS = {"goto", "click", "fill", "scroll", "wait", "new_tab", "close_tab", "done"}
VISION_MODES = {"describe", "decide", "ground"}
MIME_TYPES = {"image/png", "image/jpeg", "image/webp"}
DOM_BUDGET_CHARS = 4000
A11Y_BUDGET_CHARS = 4000
CACHE_MAX_ENTRIES = 128
STUB_MESSAGE = "Vision API не настроена — анализатор в режиме заглушки"


class VisionProviderError(RuntimeError):
    """Провайдер недоступен или вернул некорректный ответ."""


class VisionBudgetExceeded(RuntimeError):
    """Исчерпан почасовой бюджет vision-вызовов."""


@dataclass
class VisionDecision:
    action: str
    target: str = ""
    text: str = ""
    reason: str = ""
    confidence: float = 0.0


@dataclass
class VisionResult:
    provider: str
    model: str
    text: str
    latency_ms: float = 0.0


@dataclass
class VisionGrounding:
    x: float = 0.0
    y: float = 0.0
    selector: str = ""
    confidence: float = 0.0


@dataclass
class VisionFrame:
    """Кадр для fusion: скриншот + DOM + accessibility tree."""

    image_b64: str
    mime_type: str = "image/png"
    dom: str = ""
    a11y: str = ""

    def image_bytes(self) -> bytes:
        try:
            return base64.b64decode(self.image_b64.encode("ascii"), validate=True)
        except (ValueError, binascii.Error, UnicodeEncodeError) as exc:
            raise ValueError("image_b64 должен быть корректным base64") from exc

    def cache_key(self, prompt: str) -> str:
        digest = hashlib.sha256()
        digest.update(self.mime_type.encode("utf-8"))
        digest.update(b"\x00")
        digest.update(prompt.encode("utf-8"))
        digest.update(b"\x00")
        digest.update(self.image_b64.encode("utf-8"))
        return digest.hexdigest()


PROMPTS: dict[str, tuple[str, Template]] = {
    "describe": ("v1", Template("Опиши содержимое скриншота кратко и структурированно.$context")),
    "decide": (
        "v1",
        Template(
            "Цель: $goal\nКраткое описание кадра: $description\nИстория: $history\n"
            "Выбери одно действие из: goto, click, fill, scroll, wait, new_tab, close_tab, done. "
            'Верни ТОЛЬКО JSON: {"action":"...","target":"...","text":"...","reason":"...","confidence":0.0}'
        ),
    ),
    "ground": (
        "v1",
        Template(
            "Найди элемент: $target.\nКонтекст: $context\n"
            'Верни ТОЛЬКО JSON: {"x":0.0,"y":0.0,"selector":"...","confidence":0.0} (x/y — относительные координаты 0..1)'
        ),
    ),
}


def render_prompt(name: str, **kwargs: str) -> tuple[str, str]:
    try:
        version, template = PROMPTS[name]
    except KeyError as exc:
        raise ValueError(f"Неизвестный vision-промпт '{name}'") from exc
    return version, template.safe_substitute(kwargs)


def compose_context(frame: VisionFrame) -> str:
    parts = []
    if frame.dom.strip():
        parts.append("DOM (усечён):\n" + frame.dom.strip()[:DOM_BUDGET_CHARS])
    if frame.a11y.strip():
        parts.append("Accessibility tree (усечено):\n" + frame.a11y.strip()[:A11Y_BUDGET_CHARS])
    return ("\n\n" + "\n\n".join(parts)) if parts else ""


class VisionProvider(ABC):
    """Абстракция vision-бэкенда (без локальных моделей — см. DECISIONS.md #7)."""

    name: str = "base"

    @abstractmethod
    def complete(self, image: bytes, mime_type: str, prompt: str) -> VisionResult:
        """Один vision-вызов; ошибки — VisionProviderError."""


class AdapterVisionProvider(VisionProvider):
    """Клиент к VisionRouter адаптера (ключи и failover — на стороне адаптера)."""

    name = "adapter"

    def __init__(self, base_url: str, timeout: float = 30.0, transport: httpx.BaseTransport | None = None) -> None:
        if not base_url:
            raise ValueError("VISION_ADAPTER_URL не настроен")
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.transport = transport

    def complete(self, image: bytes, mime_type: str, prompt: str) -> VisionResult:
        payload = {
            "image_b64": base64.b64encode(image).decode("ascii"),
            "mime_type": mime_type,
            "prompt": prompt,
        }
        try:
            with httpx.Client(timeout=self.timeout, transport=self.transport) as client:
                response = client.post(f"{self.base_url}/vision/analyze", json=payload)
        except httpx.HTTPError as exc:
            raise VisionProviderError(f"adapter: {type(exc).__name__}") from exc
        if response.status_code >= 400:
            raise VisionProviderError(f"adapter: HTTP {response.status_code}")
        try:
            data = response.json()
            text = str(data["text"])
            if not text.strip():
                raise VisionProviderError("adapter: пустой ответ")
            return VisionResult(
                provider=str(data.get("provider", "adapter")),
                model=str(data.get("model", "")),
                text=text.strip(),
                latency_ms=float(data.get("latency_ms", 0.0) or 0.0),
            )
        except (ValueError, KeyError, TypeError) as exc:
            raise VisionProviderError(f"adapter: некорректный ответ ({type(exc).__name__})") from exc


class OpenAICompatVisionProvider(VisionProvider):
    """Прямой OpenAI-compatible endpoint (VISION_API_URL/VISION_API_KEY/VISION_MODEL)."""

    name = "openai"

    def __init__(
        self,
        api_url: str,
        api_key: str,
        model: str,
        timeout: float = 30.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        if not api_url or not api_key:
            raise ValueError("VISION_API_URL/VISION_API_KEY не настроены")
        self.api_url = api_url.rstrip("/")
        self.api_key = api_key
        self.model = model or "gpt-4o"
        self.timeout = timeout
        self.transport = transport

    def complete(self, image: bytes, mime_type: str, prompt: str) -> VisionResult:
        encoded = base64.b64encode(image).decode("ascii")
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": f"data:{mime_type};base64,{encoded}"}},
                    ],
                }
            ],
        }
        started = time.monotonic()
        try:
            with httpx.Client(timeout=self.timeout, transport=self.transport) as client:
                response = client.post(
                    f"{self.api_url}/chat/completions",
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    json=payload,
                )
            response.raise_for_status()
            data = response.json()
            content = data["choices"][0]["message"]["content"]
            if not isinstance(content, str) or not content.strip():
                raise VisionProviderError("openai: пустой ответ")
            return VisionResult(
                provider="openai",
                model=self.model,
                text=content.strip(),
                latency_ms=round((time.monotonic() - started) * 1000.0, 1),
            )
        except httpx.HTTPError as exc:
            raise VisionProviderError(f"openai: {type(exc).__name__}") from exc
        except (ValueError, KeyError, TypeError) as exc:
            raise VisionProviderError(f"openai: некорректный ответ ({type(exc).__name__})") from exc


class MockVisionProvider(VisionProvider):
    """Скриптованный провайдер без сети — тесты и dev."""

    name = "mock"

    def __init__(self, script: dict[str, str] | None = None, default: str = "mock-описание кадра") -> None:
        self.script = dict(script or {})
        self.default = default
        self.calls: list[str] = []

    def complete(self, image: bytes, mime_type: str, prompt: str) -> VisionResult:
        self.calls.append(prompt)
        for key, text in self.script.items():
            if key in prompt:
                return VisionResult(provider="mock", model="mock", text=text)
        return VisionResult(provider="mock", model="mock", text=self.default)


class VisionBudget:
    """Почасовой бюджет вызовов (0 — без лимита)."""

    def __init__(self, max_calls_per_hour: int = 0, clock: Callable[[], float] | None = None) -> None:
        self.max_calls = max(0, max_calls_per_hour)
        self._clock = clock or time.monotonic
        self._lock = threading.Lock()
        self._window_start = self._clock()
        self._used = 0

    def check(self) -> None:
        if self.max_calls <= 0:
            return
        with self._lock:
            now = self._clock()
            if now - self._window_start >= 3600.0:
                self._window_start = now
                self._used = 0
            if self._used >= self.max_calls:
                raise VisionBudgetExceeded("Исчерпан почасовой бюджет vision-вызовов")
            self._used += 1

    def usage(self) -> dict:
        with self._lock:
            return {"max_calls_per_hour": self.max_calls, "used_in_window": self._used}


class VisionCache:
    """TTL-кэш ответов (ключ — sha256 кадра + промпта)."""

    def __init__(self, ttl_seconds: float = 300.0, max_entries: int = CACHE_MAX_ENTRIES, clock: Callable[[], float] | None = None) -> None:
        self.ttl = max(0.0, ttl_seconds)
        self.max_entries = max(1, max_entries)
        self._clock = clock or time.monotonic
        self._lock = threading.Lock()
        self._items: OrderedDict[str, tuple[float, str]] = OrderedDict()

    def get(self, key: str) -> str | None:
        if self.ttl <= 0:
            return None
        with self._lock:
            found = self._items.get(key)
            if found is None:
                return None
            expires, text = found
            if self._clock() >= expires:
                del self._items[key]
                return None
            self._items.move_to_end(key)
            return text

    def put(self, key: str, text: str) -> None:
        if self.ttl <= 0:
            return
        with self._lock:
            while len(self._items) >= self.max_entries:
                self._items.popitem(last=False)
            self._items[key] = (self._clock() + self.ttl, text)


class VisionEngine:
    """Движок зрения: цепочка провайдеров, fusion кадров, бюджеты, fail-safe."""

    def __init__(
        self,
        config: AppConfig,
        describe_fn: Callable[[str], str] | None = None,
        provider: VisionProvider | list[VisionProvider] | None = None,
    ) -> None:
        self.config = config
        self._describe_fn = describe_fn
        self._providers = self._resolve_chain(provider)
        self.budget = VisionBudget(config.vision_max_calls_per_hour)
        self.cache = VisionCache(config.vision_cache_ttl_seconds)
        self._lock = threading.Lock()
        self._calls_total = 0
        self._calls_by_provider: dict[str, int] = {}
        self._blocked_budget = 0
        self._cache_hits = 0
        self._latency_ms_total = 0.0

    def _timeout(self) -> float:
        return min(60.0, self.config.request_timeout_seconds)

    def _resolve_chain(self, provider: VisionProvider | list[VisionProvider] | None) -> list[VisionProvider]:
        if provider is not None:
            return [provider] if isinstance(provider, VisionProvider) else list(provider)
        mode = (self.config.vision_provider or "auto").strip().lower()
        if mode not in {"auto", "adapter", "openai", "mock"}:
            log.warning("vision: неизвестный VISION_PROVIDER '%s', использую auto", mode)
            mode = "auto"
        chain: list[VisionProvider] = []
        if mode in {"auto", "adapter"} and self.config.adapter_url:
            chain.append(AdapterVisionProvider(self.config.adapter_url, timeout=self._timeout()))
        if mode in {"auto", "openai"} and self.config.vision_api_url and self.config.vision_api_key:
            chain.append(
                OpenAICompatVisionProvider(
                    self.config.vision_api_url,
                    self.config.vision_api_key,
                    self.config.vision_model,
                    timeout=self._timeout(),
                )
            )
        if mode == "mock":
            chain.append(MockVisionProvider())
        return chain

    @property
    def chain(self) -> list[str]:
        return [provider.name for provider in self._providers]

    def _complete(self, frame: VisionFrame, prompt: str) -> VisionResult:
        image = frame.image_bytes()
        if frame.mime_type not in MIME_TYPES:
            raise ValueError("mime_type: только image/png, image/jpeg, image/webp")
        if len(image) > self.config.vision_max_image_bytes:
            raise ValueError("Изображение превышает лимит vision_max_image_bytes")
        key = frame.cache_key(prompt)
        cached = self.cache.get(key)
        if cached is not None:
            with self._lock:
                self._cache_hits += 1
            return VisionResult(provider="cache", model="", text=cached)
        self.budget.check()
        if not self._providers:
            raise VisionProviderError("нет настроенных vision-провайдеров")
        errors = []
        for provider in self._providers:
            started = time.monotonic()
            try:
                result = provider.complete(image, frame.mime_type, prompt)
            except VisionProviderError as exc:
                errors.append(f"{provider.name}: {exc}")
                continue
            latency_ms = (time.monotonic() - started) * 1000.0
            with self._lock:
                self._calls_total += 1
                self._calls_by_provider[provider.name] = self._calls_by_provider.get(provider.name, 0) + 1
                self._latency_ms_total += latency_ms
            self.cache.put(key, result.text)
            return result
        raise VisionProviderError("; ".join(errors) if errors else "все провайдеры недоступны")

    def ask(self, frame: VisionFrame, prompt: str) -> VisionResult:
        """Прямой vision-вызов (ошибки провайдера/бюджета — наружу, для API)."""
        if not prompt or len(prompt) > 4000:
            raise ValueError("prompt должен быть непустым и короче 4000 символов")
        return self._complete(frame, prompt)

    def describe(self, image_b64: str) -> str:
        if self._describe_fn is not None:
            return self._describe_fn(image_b64)
        return self.describe_frame(VisionFrame(image_b64=image_b64))

    def describe_frame(self, frame: VisionFrame) -> str:
        _, prompt = render_prompt("describe", context=compose_context(frame))
        try:
            return self._complete(frame, prompt).text
        except VisionBudgetExceeded:
            with self._lock:
                self._blocked_budget += 1
            return STUB_MESSAGE
        except (VisionProviderError, ValueError) as exc:
            log.debug("vision describe degraded: %s", exc)
            return STUB_MESSAGE

    def decide(self, image_b64: str, goal: str, history: list[str]) -> VisionDecision:
        decision, _ = self.decide_frame(VisionFrame(image_b64=image_b64), goal, history)
        return decision

    def decide_frame(self, frame: VisionFrame, goal: str, history: list[str]) -> tuple[VisionDecision, bool]:
        """Возвращает (решение, degraded)."""
        try:
            _, desc_prompt = render_prompt("describe", context=compose_context(frame))
            description = self._complete(frame, desc_prompt).text
            _, prompt = render_prompt("decide", goal=goal, description=description, history=str(history[-3:]))
            plan = self._complete(frame, prompt).text
        except (VisionProviderError, VisionBudgetExceeded, ValueError) as exc:
            log.debug("vision decide degraded: %s", exc)
            return VisionDecision(action="wait", reason="Vision недоступен — ожидание"), True
        return self._parse_decision(plan), False

    def _parse_decision(self, plan: str) -> VisionDecision:
        try:
            raw = json.loads(plan)
            if not isinstance(raw, dict):
                raise TypeError("decision должен быть JSON-объектом")
            action = str(raw.get("action", "wait"))
            if action not in ACTIONS:
                action = "wait"
            confidence = min(1.0, max(0.0, float(raw.get("confidence", 0.0))))
            return VisionDecision(
                action=action,
                target=str(raw.get("target", "")),
                text=str(raw.get("text", "")),
                reason=str(raw.get("reason", "")),
                confidence=confidence,
            )
        except (ValueError, TypeError, json.JSONDecodeError, KeyError):
            return VisionDecision(action="wait", reason="Не удалось распарсить план")

    def ground(self, frame: VisionFrame, target: str) -> tuple[VisionGrounding, bool]:
        """Возвращает (координаты, degraded)."""
        if not target or len(target) > 500:
            raise ValueError("target должен быть непустым и короче 500 символов")
        _, prompt = render_prompt("ground", target=target, context=compose_context(frame) or "без контекста")
        try:
            raw_text = self._complete(frame, prompt).text
            raw = json.loads(raw_text)
            if not isinstance(raw, dict):
                raise ValueError("grounding должен быть JSON-объектом")  # noqa: TRY004 — fail-safe семантика: некорректный ответ модели это ошибка данных
            return (
                VisionGrounding(
                    x=min(1.0, max(0.0, float(raw.get("x", 0.0)))),
                    y=min(1.0, max(0.0, float(raw.get("y", 0.0)))),
                    selector=str(raw.get("selector", ""))[:256],
                    confidence=min(1.0, max(0.0, float(raw.get("confidence", 0.0)))),
                ),
                False,
            )
        except (VisionProviderError, VisionBudgetExceeded, ValueError, TypeError, KeyError) as exc:
            log.debug("vision ground degraded: %s", exc)
            return VisionGrounding(), True

    def stats(self) -> dict:
        with self._lock:
            avg = self._latency_ms_total / self._calls_total if self._calls_total else 0.0
            return {
                "chain": self.chain,
                "prompts": {name: version for name, (version, _) in PROMPTS.items()},
                "calls_total": self._calls_total,
                "calls_by_provider": dict(self._calls_by_provider),
                "blocked_budget": self._blocked_budget,
                "cache_hits": self._cache_hits,
                "avg_latency_ms": round(avg, 2),
                "budget": self.budget.usage(),
            }
