"""Structured observability primitives with a secret-safe audit sink."""
from __future__ import annotations

import json
import logging
import os
import re
import time
import uuid
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from pathlib import Path
from threading import Lock
from typing import Any

correlation_id: ContextVar[str] = ContextVar("correlation_id", default="")
_SECRET_KEYS = re.compile(r"(?:api[_-]?key|authorization|cookie|password|secret|token|session[_-]?encryption)", re.IGNORECASE)


def _redact(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(k): "[REDACTED]" if _SECRET_KEYS.search(str(k)) else _redact(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_redact(v) for v in value]
    if isinstance(value, tuple):
        return [_redact(v) for v in value]
    if isinstance(value, str) and len(value) > 256:
        return value[:256] + "…"
    return value


class JsonFormatter(logging.Formatter):
    """Emit one JSON object per log event and never log known secret fields."""

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": time.time(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        cid = correlation_id.get()
        if cid:
            payload["correlation_id"] = cid
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(_redact(payload), ensure_ascii=False)


class AuditSink:
    """Append-only JSONL audit sink with restrictive file permissions and redaction."""

    def __init__(self, path: Path) -> None:
        self.path = path.resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = Lock()
        if self.path.exists():
            self.path.chmod(0o600)

    def write(self, event: Mapping[str, Any]) -> None:
        payload = dict(_redact(event))
        payload.setdefault("ts", time.time())
        cid = correlation_id.get()
        if cid:
            payload.setdefault("correlation_id", cid)
        line = json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n"
        with self._lock, self.path.open("a", encoding="utf-8") as handle:
            if os.name != "nt":
                os.chmod(self.path, 0o600)
            handle.write(line)
            handle.flush()
            if os.name != "nt":
                os.fsync(handle.fileno())


@dataclass
class Counter:
    value: int = 0

    def inc(self, amount: int = 1) -> int:
        self.value += amount
        return self.value


@contextmanager
def request_context(request_id: str | None = None) -> Iterator[str]:
    token = correlation_id.set(request_id or uuid.uuid4().hex)
    try:
        yield correlation_id.get()
    finally:
        correlation_id.reset(token)
