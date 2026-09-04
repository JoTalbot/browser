"""Minimal structured observability primitives with secret-safe fields."""
from __future__ import annotations

import json
import logging
import time
import uuid
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Iterator

correlation_id: ContextVar[str] = ContextVar("correlation_id", default="")


class JsonFormatter(logging.Formatter):
    """Emit one JSON object per log event and never log API keys."""

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
        return json.dumps(payload, ensure_ascii=False)


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
