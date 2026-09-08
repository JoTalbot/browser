"""🔗 AIOS integration: durable event feed, optional webhook push, bridge probing."""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

log = logging.getLogger("octopus.aios")

EVENT_VERSION = 1


class AIOSError(RuntimeError):
    """AIOS bridge/webhook недоступен или вернул некорректный ответ."""


@dataclass
class AIOSEvent:
    type: str
    job_id: str = ""
    correlation_id: str = ""
    data: dict[str, Any] = field(default_factory=dict)
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    ts: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict[str, Any]:
        return {
            "v": EVENT_VERSION,
            "id": self.id,
            "ts": self.ts,
            "type": self.type,
            "job_id": self.job_id,
            "correlation_id": self.correlation_id,
            "data": self.data,
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> AIOSEvent:
        return cls(
            type=str(raw.get("type", "")),
            job_id=str(raw.get("job_id", "")),
            correlation_id=str(raw.get("correlation_id", "")),
            data=dict(raw.get("data") or {}),
            id=str(raw.get("id", "")),
            ts=str(raw.get("ts", "")),
        )


class EventLog:
    """Durable JSONL event feed with cursor reads."""

    def __init__(self, path: Path, max_lines: int = 5000) -> None:
        self.path = path
        self.max_lines = max(100, max_lines)
        self._lock = threading.RLock()

    def append(self, event: AIOSEvent) -> None:
        line = json.dumps(event.to_dict(), ensure_ascii=False, default=str)
        with self._lock:
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                with open(self.path, "a", encoding="utf-8") as handle:
                    handle.write(line + "\n")
                self._prune_locked()
            except OSError as exc:
                log.warning("aios event log write failed: %s", exc)

    def read(self, since: str | None = None, limit: int = 100) -> tuple[list[dict[str, Any]], str | None]:
        limit = min(max(1, limit), 500)
        with self._lock:
            try:
                lines = self.path.read_text(encoding="utf-8").splitlines()
            except FileNotFoundError:
                return [], None
            except OSError as exc:
                log.warning("aios event log read failed: %s", exc)
                return [], None
        events = []
        for line in lines:
            try:
                raw = json.loads(line)
            except ValueError:
                continue
            if isinstance(raw, dict) and raw.get("id"):
                events.append(raw)
        start = 0
        if since:
            for index, item in enumerate(events):
                if item.get("id") == since:
                    start = index + 1
                    break
        window = events[start : start + limit]
        last_id = window[-1]["id"] if window else since
        return window, last_id

    def count(self) -> int:
        with self._lock:
            try:
                return sum(1 for _ in self.path.read_text(encoding="utf-8").splitlines())
            except OSError:
                return 0

    def _prune_locked(self) -> None:
        try:
            lines = self.path.read_text(encoding="utf-8").splitlines()
        except OSError:
            return
        if len(lines) > self.max_lines + 500:
            try:
                self.path.write_text("\n".join(lines[-self.max_lines :]) + "\n", encoding="utf-8")
            except OSError as exc:
                log.warning("aios event log prune failed: %s", exc)


class EventDispatcher:
    """Публикация событий: всегда в durable-лог + опциональный push в webhook с ретраями."""

    def __init__(
        self,
        event_log: EventLog,
        webhook_url: str = "",
        webhook_secret: str = "",
        pending_path: Path | None = None,
        transport: httpx.BaseTransport | None = None,
        timeout: float = 5.0,
        max_pending: int = 1000,
    ) -> None:
        self.event_log = event_log
        self.webhook_url = webhook_url.strip()
        self.webhook_secret = webhook_secret
        self.pending_path = pending_path
        self.transport = transport
        self.timeout = timeout
        self.max_pending = max(1, max_pending)
        self._lock = threading.RLock()
        self._pending: list[dict[str, Any]] = []
        self._unsigned_warned = False
        self.dropped_push_total = 0
        self._load_pending()

    def publish(self, event: AIOSEvent) -> bool:
        self.event_log.append(event)
        if not self.webhook_url:
            return True
        self.flush(limit=20)
        if self._push(event.to_dict()):
            return True
        with self._lock:
            self._pending.append(event.to_dict())
            while len(self._pending) > self.max_pending:
                self._pending.pop(0)
                self.dropped_push_total += 1
            self._save_pending_locked()
        return False

    def flush(self, limit: int = 50) -> dict[str, int]:
        if not self.webhook_url:
            return {"flushed": 0, "still_pending": self.pending_count()}
        flushed = 0
        with self._lock:
            while self._pending and flushed < max(1, limit):
                if not self._push(self._pending[0]):
                    break
                self._pending.pop(0)
                flushed += 1
            if flushed:
                self._save_pending_locked()
            still_pending = len(self._pending)
        return {"flushed": flushed, "still_pending": still_pending}

    def pending_count(self) -> int:
        with self._lock:
            return len(self._pending)

    def _push(self, payload: dict[str, Any]) -> bool:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            "X-Event-Id": str(payload.get("id", "")),
            "X-Event-Type": str(payload.get("type", "")),
        }
        if self.webhook_secret:
            digest = hmac.new(self.webhook_secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
            headers["X-Signature"] = f"sha256={digest}"
        elif not self._unsigned_warned:
            self._unsigned_warned = True
            log.warning("aios webhook без секрета — события уходят неподписанными")
        try:
            with httpx.Client(timeout=self.timeout, transport=self.transport) as client:
                response = client.post(self.webhook_url, content=body, headers=headers)
        except httpx.HTTPError as exc:
            log.warning("aios webhook push failed: %s", type(exc).__name__)
            return False
        if response.status_code >= 400:
            log.warning("aios webhook push HTTP %s", response.status_code)
            return False
        return True

    def _load_pending(self) -> None:
        if self.pending_path is None:
            return
        try:
            raw = json.loads(self.pending_path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return
        except (OSError, ValueError) as exc:
            log.warning("aios pending load failed: %s", exc)
            return
        if isinstance(raw, list):
            self._pending = [item for item in raw if isinstance(item, dict) and item.get("id")][: self.max_pending]

    def _save_pending_locked(self) -> None:
        if self.pending_path is None:
            return
        try:
            self.pending_path.parent.mkdir(parents=True, exist_ok=True)
            self.pending_path.write_text(json.dumps(self._pending, ensure_ascii=False), encoding="utf-8")
        except OSError as exc:
            log.warning("aios pending save failed: %s", exc)


class AIOSBridge:
    """Минимальный клиент опроса состояния AIOS bridge."""

    def __init__(self, base_url: str, timeout: float = 5.0, transport: httpx.BaseTransport | None = None) -> None:
        if not base_url:
            raise ValueError("AIOS_BRIDGE_URL не настроен")
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.transport = transport

    def status(self) -> dict[str, Any]:
        started = time.monotonic()
        try:
            with httpx.Client(timeout=self.timeout, transport=self.transport) as client:
                response = client.get(f"{self.base_url}/api/v1/aios/status")
                response.raise_for_status()
                data = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise AIOSError(f"bridge status: {type(exc).__name__}") from exc
        if not isinstance(data, dict):
            raise AIOSError("bridge status должен быть JSON-объектом")
        data["latency_ms"] = round((time.monotonic() - started) * 1000.0, 1)
        return data
