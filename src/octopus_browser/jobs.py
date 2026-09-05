"""Bounded in-process job queue for browser/agent work."""
from __future__ import annotations

import threading
import uuid
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


TERMINAL_STATES = {"done", "error", "cancelled", "timeout"}


@dataclass
class Job:
    id: str
    status: str = "queued"
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    started_at: str | None = None
    finished_at: str | None = None
    result: Any = None
    error: str | None = None


class JobManager:
    """Thread-backed bounded queue with observable lifecycle and cancellation."""

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
            self._futures[job.id] = self._executor.submit(self._run, job.id, fn)
            return job

    def _run(self, job_id: str, fn: Callable[[], Any]) -> None:
        with self._lock:
            job = self._jobs[job_id]
            if job.status == "cancelled":
                return
            job.status = "running"
            job.started_at = datetime.now(timezone.utc).isoformat()
        try:
            result = fn()
        except Exception as exc:  # noqa: BLE001 - job boundary must capture task failures
            with self._lock:
                job = self._jobs[job_id]
                if job.status != "cancelled":
                    job.status = "error"
                    job.error = str(exc)
                    job.finished_at = datetime.now(timezone.utc).isoformat()
        else:
            with self._lock:
                job = self._jobs[job_id]
                if job.status != "cancelled":
                    job.status = "done"
                    job.result = result
                    job.finished_at = datetime.now(timezone.utc).isoformat()

    def get(self, job_id: str) -> Job | None:
        with self._lock:
            return self._jobs.get(job_id)

    def list(self) -> list[Job]:
        with self._lock:
            return list(self._jobs.values())

    def cancel(self, job_id: str) -> bool:
        with self._lock:
            future = self._futures.get(job_id)
            job = self._jobs.get(job_id)
            if not future or not job or job.status in TERMINAL_STATES:
                return False
            if future.cancel():
                job.status = "cancelled"
                job.finished_at = datetime.now(timezone.utc).isoformat()
                return True
            return False

    def shutdown(self, wait: bool = True) -> None:
        self._executor.shutdown(wait=wait, cancel_futures=True)
