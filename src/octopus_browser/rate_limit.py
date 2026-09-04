"""Request admission controls for the single-process API runtime."""
from __future__ import annotations

import threading
import time
from collections import defaultdict, deque


class RateLimiter:
    """Small fixed-window limiter keyed by caller identity.

    This is intentionally process-local. Distributed deployments should put a
    shared limiter at the gateway instead of pretending an in-memory counter
    is magically consistent across replicas.
    """

    def __init__(self, limit: int, window_seconds: float = 60.0) -> None:
        if limit < 1:
            raise ValueError("limit must be >= 1")
        if window_seconds <= 0:
            raise ValueError("window_seconds must be > 0")
        self.limit = limit
        self.window_seconds = window_seconds
        self._events: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def allow(self, key: str) -> bool:
        now = time.monotonic()
        with self._lock:
            events = self._events[key]
            cutoff = now - self.window_seconds
            while events and events[0] <= cutoff:
                events.popleft()
            if len(events) >= self.limit:
                return False
            events.append(now)
            return True

    def retry_after(self, key: str) -> float:
        now = time.monotonic()
        with self._lock:
            events = self._events.get(key)
            if not events or len(events) < self.limit:
                return 0.0
            return max(0.0, events[0] + self.window_seconds - now)
