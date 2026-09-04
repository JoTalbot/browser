"""Bounded in-process job queue for browser/agent work."""
from __future__ import annotations

import threading
import uuid
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass
class Job:
    id: str
    status: str = "queued"
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    result: Any = None
    error: str | None = None


class JobManager:
    def __init__(self, workers: int = 2, max_queued: int = 100) -> None:
        if workers < 1 or max_queued < 1:
            raise ValueError("workers and max_queued must be >= 1")
        self._executor = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="octopus-job")
        self._max_queued = max_queued
        self._jobs: dict[str, Job] = {}
        self._futures: dict[str, Future] = {}
        self._lock = threading.RLock()

    def submit(self, fn: Callable[[], Any]) -> Job:
        with self._lock:
            active = sum(job.status in {"queued", "running"} for job in self._jobs.values())
            if active >= self._max_queued:
                raise RuntimeError("Очередь задач переполнена")
            job = Job(id=uuid.uuid4().hex)
            self._jobs[job.id] = job
            future = self._executor.submit(self._run, job.id, fn)
            self._futures[job.id] = future
            return job

    def _run(self, job_id: str, fn: Callable[[], Any]) -> None:
        with self._lock:
            self._jobs[job_id].status = "running"
        try:
            result = fn()
        except Exception as exc:  # noqa: BLE001 - job boundary must capture task failures
            with self._lock:
                self._jobs[job_id].status = "error"
                self._jobs[job_id].error = str(exc)
        else:
            with self._lock:
                self._jobs[job_id].status = "done"
                self._jobs[job_id].result = result

    def get(self, job_id: str) -> Job | None:
        with self._lock:
            return self._jobs.get(job_id)

    def cancel(self, job_id: str) -> bool:
        with self._lock:
            future = self._futures.get(job_id)
            job = self._jobs.get(job_id)
            if not future or not job:
                return False
            if future.cancel():
                job.status = "cancelled"
                return True
            return False

    def shutdown(self) -> None:
        self._executor.shutdown(wait=True, cancel_futures=True)
