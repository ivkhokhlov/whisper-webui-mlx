from __future__ import annotations

import logging
import os
from collections.abc import Mapping
from datetime import datetime, timezone
from pathlib import Path
import threading

from mlx_ui.db import claim_next_job, update_job_status
from mlx_ui.engine_registry import create_transcriber
from mlx_ui.settings import (
    ResolvedTranscriberSettings,
    resolve_job_transcriber_spec_with_settings,
)
from mlx_ui.telegram import maybe_send_telegram
from mlx_ui.transcriber import Transcriber
from mlx_ui.uploads import cleanup_upload_path

logger = logging.getLogger(__name__)

_worker_lock = threading.Lock()
_worker_instance: Worker | None = None


class Worker:
    def __init__(
        self,
        db_path: Path,
        uploads_dir: Path,
        results_dir: Path,
        poll_interval: float = 0.5,
        transcriber: Transcriber | None = None,
        effective_engine: str | None = None,
        base_dir: Path | None = None,
        env: Mapping[str, str] | None = None,
    ) -> None:
        self.db_path = Path(db_path)
        self.uploads_dir = Path(uploads_dir)
        self.results_dir = Path(results_dir)
        self.poll_interval = poll_interval
        self.base_dir = Path(base_dir) if base_dir is not None else _default_base_dir(
            self.db_path
        )
        self.env = env if env is not None else os.environ
        self.transcriber = transcriber
        self.effective_engine = _normalize_engine_id(
            effective_engine
        ) or _transcriber_engine_id(transcriber)
        self._transcriber_cache: dict[tuple[object, ...], Transcriber] = {}
        self._stop_event = threading.Event()
        self._paused_event = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self.is_running():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run_loop,
            name="mlx-ui-worker",
            daemon=True,
        )
        self._thread.start()

    def stop(self, timeout: float | None = None) -> None:
        self._stop_event.set()
        thread = self._thread
        if thread is not None:
            thread.join(timeout=timeout)

    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def pause(self) -> None:
        self._paused_event.set()

    def resume(self) -> None:
        self._paused_event.clear()

    def is_paused(self) -> bool:
        return self._paused_event.is_set()

    def _resolve_transcriber_for_job(
        self,
        job,
    ) -> tuple[Transcriber, str | None]:
        if self.transcriber is not None:
            return self.transcriber, self.effective_engine
        resolved = resolve_job_transcriber_spec_with_settings(
            job.requested_engine,
            base_dir=self.base_dir,
            env=self.env,
        )
        transcriber = _cached_transcriber(self._transcriber_cache, resolved)
        return transcriber, resolved.engine_id

    def _run_loop(self) -> None:
        while not self._stop_event.is_set():
            processed = self.run_once()
            if not processed:
                self._stop_event.wait(self.poll_interval)

    def run_once(self) -> bool:
        if self._paused_event.is_set():
            return False
        job = claim_next_job(self.db_path)
        if job is None:
            return False
        try:
            transcriber, effective_engine = self._resolve_transcriber_for_job(job)
        except Exception as exc:
            _log_transcriber_resolution_error(job.id, exc)
            update_job_status(
                self.db_path,
                job.id,
                "failed",
                completed_at=_now_utc(),
                error_message=_truncate_error(str(exc) or exc.__class__.__name__),
            )
            cleanup_upload_path(job.upload_path, self.uploads_dir, job.id)
            return True
        job.effective_engine = effective_engine
        update_job_status(
            self.db_path,
            job.id,
            "running",
            effective_engine=effective_engine,
        )
        try:
            result_path = transcriber.transcribe(job, self.results_dir)
        except Exception as exc:
            logger.exception("Worker failed to transcribe job %s", job.id)
            update_job_status(
                self.db_path,
                job.id,
                "failed",
                completed_at=_now_utc(),
                error_message=_truncate_error(str(exc) or exc.__class__.__name__),
                effective_engine=effective_engine,
            )
            cleanup_upload_path(job.upload_path, self.uploads_dir, job.id)
            return True
        try:
            maybe_send_telegram(job, result_path)
        except Exception:
            logger.exception(
                "Worker failed to deliver Telegram message for job %s", job.id
            )
        update_job_status(
            self.db_path,
            job.id,
            "done",
            completed_at=_now_utc(),
            effective_engine=effective_engine,
        )
        cleanup_upload_path(job.upload_path, self.uploads_dir, job.id)
        return True


def start_worker(
    db_path: Path,
    uploads_dir: Path,
    results_dir: Path,
    poll_interval: float = 0.5,
    transcriber: Transcriber | None = None,
    effective_engine: str | None = None,
    base_dir: Path | None = None,
    env: Mapping[str, str] | None = None,
) -> Worker:
    global _worker_instance
    with _worker_lock:
        if _worker_instance and _worker_instance.is_running():
            return _worker_instance
        _worker_instance = Worker(
            db_path=db_path,
            uploads_dir=uploads_dir,
            results_dir=results_dir,
            poll_interval=poll_interval,
            transcriber=transcriber,
            effective_engine=effective_engine,
            base_dir=base_dir,
            env=env,
        )
        _worker_instance.start()
        return _worker_instance


def stop_worker(timeout: float | None = None) -> None:
    global _worker_instance
    with _worker_lock:
        if not _worker_instance:
            return
        _worker_instance.stop(timeout=timeout)
        _worker_instance = None


def _now_utc() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _truncate_error(message: str, limit: int = 4000) -> str:
    if len(message) <= limit:
        return message
    return message[: limit - 1] + "…"


def _transcriber_engine_id(transcriber: Transcriber) -> str | None:
    return _normalize_engine_id(getattr(transcriber, "engine_id", None))


def _normalize_engine_id(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None


def _default_base_dir(db_path: Path) -> Path:
    if db_path.parent.name == "data":
        return db_path.parent.parent
    return db_path.parent


def _log_transcriber_resolution_error(job_id: str, error: Exception) -> None:
    if isinstance(error, ValueError):
        logger.warning("Worker failed to resolve engine for job %s: %s", job_id, error)
        return
    logger.exception("Worker failed to resolve engine for job %s", job_id)


def _cached_transcriber(
    cache: dict[tuple[object, ...], Transcriber],
    resolved: ResolvedTranscriberSettings,
) -> Transcriber:
    transcriber = cache.get(resolved.cache_key)
    if transcriber is None:
        transcriber = create_transcriber(
            resolved.engine_id,
            options=resolved.options,
        )
        cache[resolved.cache_key] = transcriber
    return transcriber
