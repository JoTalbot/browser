"""Bounded in-process job queue for browser/agent work (optionally durable)."""
from __future__ import annotations

import json
import logging
import threading
import uuid
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

log = logging.getLogger("octopus.jobs")

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

    def __init__(self, workers: int = 2, max_queued: int = 100, persist_path: Path | None = None, persist_limit: int = 500) -> None:
        if workers < 1 or max_queued < 1:
            raise ValueError("workers and max_queued must be >= 1")
        self._executor = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="octopus-job")
        self._max_queued = max_queued
        self._jobs: dict[str, Job] = {}
        self._futures: dict[str, Future] = {}
        self._lock = threading.RLock()
        self._persist_path = persist_path
        self._persist_limit = max(10, persist_limit)
        if self._persist_path is not None:
            try:
                self._persist_path.parent.mkdir(parents=True, exist_ok=True)
            except OSError as exc:
                log.warning("jobs persist disabled: %s", exc)
                self._persist_path = None
        self._restore()

    def submit(self, fn: Callable[[], Any]) -> Job:
        with self._lock:
            active = sum(job.status in {"queued", "running"} for job in self._jobs.values())
            if active >= self._max_queued:
                raise RuntimeError("Очередь задач переполнена")
            job = Job(id=uuid.uuid4().hex)
            self._jobs[job.id] = job
            self._futures[job.id] = self._executor.submit(self._run, job.id, fn)
            self._save_locked()
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
                self._save_locked()
        else:
            with self._lock:
                job = self._jobs[job_id]
                if job.status != "cancelled":
                    job.status = "done"
                    job.result = result
                    job.finished_at = datetime.now(timezone.utc).isoformat()
                self._save_locked()

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
                self._save_locked()
                return True
            return False

    def _snapshot_locked(self) -> list[dict]:
        return [
            {
                "id": job.id,
                "status": job.status,
                "created_at": job.created_at,
                "started_at": job.started_at,
                "finished_at": job.finished_at,
                "result": job.result,
                "error": job.error,
            }
            for job in self._jobs.values()
        ]

    def _save_locked(self) -> None:
        if self._persist_path is None:
            return
        snapshot = self._snapshot_locked()
        active = [item for item in snapshot if item["status"] not in TERMINAL_STATES]
        terminal = sorted(
            (item for item in snapshot if item["status"] in TERMINAL_STATES),
            key=lambda item: item.get("finished_at") or item.get("created_at") or "",
        )
        trimmed = active + terminal[-self._persist_limit :]
        try:
            self._persist_path.write_text(json.dumps({"jobs": trimmed}, ensure_ascii=False, default=str), encoding="utf-8")
        except OSError as exc:
            log.warning("jobs persist save failed: %s", exc)

    def _restore(self) -> None:
        if self._persist_path is None:
            return
        try:
            raw = json.loads(self._persist_path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return
        except (OSError, ValueError) as exc:
            log.warning("jobs persist load failed: %s", exc)
            return
        items = raw.get("jobs", []) if isinstance(raw, dict) else []
        now = datetime.now(timezone.utc).isoformat()
        with self._lock:
            for item in items:
                if not isinstance(item, dict) or not item.get("id"):
                    continue
                status = item.get("status", "error")
                error = item.get("error")
                finished_at = item.get("finished_at")
                if status not in TERMINAL_STATES:
                    status = "error"
                    error = "interrupted by restart"
                    finished_at = now
                self._jobs[str(item["id"])] = Job(
                    id=str(item["id"]),
                    status=status,
                    created_at=str(item.get("created_at", now)),
                    started_at=item.get("started_at"),
                    finished_at=finished_at,
                    result=item.get("result"),
                    error=error,
                )

    def shutdown(self, wait: bool = True) -> None:
        self._executor.shutdown(wait=wait, cancel_futures=True)
