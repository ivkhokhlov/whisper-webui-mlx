from __future__ import annotations

import logging
import os
from collections.abc import Mapping
from datetime import datetime, timezone
from pathlib import Path
import threading

from mlx_ui.db import (
    claim_next_job,
    mark_job_done,
    mark_job_failed,
    mark_job_running,
    update_job_status,
)
from mlx_ui.engine_registry import create_transcriber
from mlx_ui.hot_folder import (
    export_hot_folder_transcript,
    resolve_hot_folder_output_dir,
    restore_failed_hot_folder_upload,
)
from mlx_ui.settings import (
    ResolvedTranscriberSettings,
    resolve_job_transcriber_spec_with_settings,
)
from mlx_ui.telegram import maybe_send_telegram
from mlx_ui.storage import remove_results_dir
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
        effective_implementation_id: str | None = None,
        base_dir: Path | None = None,
        env: Mapping[str, str] | None = None,
    ) -> None:
        self.db_path = Path(db_path)
        self.uploads_dir = Path(uploads_dir)
        self.results_dir = Path(results_dir)
        self.poll_interval = poll_interval
        self.base_dir = (
            Path(base_dir) if base_dir is not None else _default_base_dir(self.db_path)
        )
        self.env = env if env is not None else os.environ
        self.transcriber = transcriber
        self.effective_engine = _normalize_engine_id(
            effective_engine
        ) or _transcriber_engine_id(transcriber)
        self.effective_implementation_id = _normalize_engine_id(
            effective_implementation_id
        )
        self._transcriber_cache: dict[tuple[object, ...], Transcriber] = {}
        self._stop_event = threading.Event()
        self._paused_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._state_lock = threading.Lock()
        self._current_job_id: str | None = None
        self._current_job_filename: str | None = None
        self._current_job_started_at: str | None = None
        self._current_transcriber: Transcriber | None = None
        self._cancel_requested = False

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

    def snapshot(self) -> dict[str, object] | None:
        with self._state_lock:
            if not self._current_job_id:
                return None
            return {
                "job_id": self._current_job_id,
                "filename": self._current_job_filename,
                "started_at": self._current_job_started_at,
                "cancel_requested": self._cancel_requested,
            }

    def request_cancel(self, job_id: str) -> dict[str, object] | None:
        with self._state_lock:
            if self._current_job_id != job_id:
                return None
            transcriber = self._current_transcriber
            already_requested = self._cancel_requested
            self._cancel_requested = True
        interrupted = False
        if not already_requested:
            interrupted = _request_transcriber_cancel(transcriber, job_id)
        snapshot = self.snapshot()
        if snapshot is None:
            return None
        snapshot["interrupted"] = interrupted
        snapshot["already_requested"] = already_requested
        return snapshot

    def _resolve_transcriber_for_job(
        self,
        job,
    ) -> tuple[Transcriber, str | None, str | None]:
        if self.transcriber is not None:
            return (
                self.transcriber,
                self.effective_engine,
                self.effective_implementation_id,
            )
        resolved = resolve_job_transcriber_spec_with_settings(
            job.requested_engine,
            base_dir=self.base_dir,
            env=self.env,
        )
        transcriber = _cached_transcriber(self._transcriber_cache, resolved)
        return transcriber, resolved.engine_id, resolved.implementation_id

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
            (
                transcriber,
                effective_engine,
                effective_implementation_id,
            ) = self._resolve_transcriber_for_job(job)
        except Exception as exc:
            _log_transcriber_resolution_error(job.id, exc)
            mark_job_failed(
                self.db_path,
                job.id,
                completed_at=_now_utc(),
                error_message=_truncate_error(str(exc) or exc.__class__.__name__),
            )
            restore_failed_hot_folder_upload(job)
            cleanup_upload_path(job.upload_path, self.uploads_dir, job.id)
            return True
        started_at = _now_utc()
        job.started_at = started_at
        job.effective_engine = effective_engine
        job.effective_implementation_id = effective_implementation_id
        self._set_current_job(job, transcriber)
        if not mark_job_running(
            self.db_path,
            job.id,
            started_at=started_at,
            effective_engine=effective_engine,
            effective_implementation_id=effective_implementation_id,
        ):
            logger.warning(
                "Worker lost reservation for job %s before starting transcription",
                job.id,
            )
            self._clear_current_job(job.id)
            restore_failed_hot_folder_upload(job)
            cleanup_upload_path(job.upload_path, self.uploads_dir, job.id)
            return True
        try:
            try:
                result_path = transcriber.transcribe(job, self.results_dir)
            except Exception as exc:
                if self._is_cancel_requested(job.id):
                    logger.info("Worker cancelled job %s during transcription", job.id)
                    self._mark_job_cancelled(job.id)
                    cleanup_cancelled_job_artifacts(
                        job,
                        uploads_dir=self.uploads_dir,
                        results_dir=self.results_dir,
                    )
                    return True
                logger.exception("Worker failed to transcribe job %s", job.id)
                mark_job_failed(
                    self.db_path,
                    job.id,
                    completed_at=_now_utc(),
                    error_message=_truncate_error(str(exc) or exc.__class__.__name__),
                )
                restore_failed_hot_folder_upload(job)
                cleanup_upload_path(job.upload_path, self.uploads_dir, job.id)
                return True
            if self._is_cancel_requested(job.id):
                logger.info("Worker cancelled job %s after transcription", job.id)
                self._mark_job_cancelled(job.id)
                cleanup_cancelled_job_artifacts(
                    job,
                    uploads_dir=self.uploads_dir,
                    results_dir=self.results_dir,
                )
                return True
            try:
                maybe_send_telegram(job, result_path)
            except Exception:
                logger.exception(
                    "Worker failed to deliver Telegram message for job %s", job.id
                )
            if self._is_cancel_requested(job.id):
                logger.info("Worker cancelled job %s before export", job.id)
                self._mark_job_cancelled(job.id)
                cleanup_cancelled_job_artifacts(
                    job,
                    uploads_dir=self.uploads_dir,
                    results_dir=self.results_dir,
                )
                return True
            if job.source_path:
                output_dir = resolve_hot_folder_output_dir(
                    base_dir=self.base_dir,
                    env=self.env,
                )
                if output_dir is not None:
                    export_hot_folder_transcript(
                        job=job,
                        result_path=result_path,
                        output_dir=output_dir,
                    )
            if self._is_cancel_requested(job.id):
                logger.info("Worker cancelled job %s before completion", job.id)
                self._mark_job_cancelled(job.id)
                cleanup_cancelled_job_artifacts(
                    job,
                    uploads_dir=self.uploads_dir,
                    results_dir=self.results_dir,
                )
                return True
            mark_job_done(
                self.db_path,
                job.id,
                completed_at=_now_utc(),
            )
            cleanup_upload_path(job.upload_path, self.uploads_dir, job.id)
            return True
        finally:
            self._clear_current_job(job.id)

    def _set_current_job(self, job, transcriber: Transcriber) -> None:
        with self._state_lock:
            self._current_job_id = job.id
            self._current_job_filename = job.filename
            self._current_job_started_at = job.started_at
            self._current_transcriber = transcriber
            self._cancel_requested = False

    def _clear_current_job(self, job_id: str) -> None:
        with self._state_lock:
            if self._current_job_id != job_id:
                return
            self._current_job_id = None
            self._current_job_filename = None
            self._current_job_started_at = None
            self._current_transcriber = None
            self._cancel_requested = False

    def _is_cancel_requested(self, job_id: str) -> bool:
        with self._state_lock:
            return self._current_job_id == job_id and self._cancel_requested

    def _mark_job_cancelled(self, job_id: str) -> None:
        update_job_status(
            self.db_path,
            job_id,
            "cancelled",
            completed_at=_now_utc(),
            error_message="",
        )


def start_worker(
    db_path: Path,
    uploads_dir: Path,
    results_dir: Path,
    poll_interval: float = 0.5,
    transcriber: Transcriber | None = None,
    effective_engine: str | None = None,
    effective_implementation_id: str | None = None,
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
            effective_implementation_id=effective_implementation_id,
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


def get_worker_snapshot() -> dict[str, object] | None:
    with _worker_lock:
        worker = _worker_instance
    if worker is None or not worker.is_running():
        return None
    return worker.snapshot()


def request_worker_cancel(job_id: str) -> dict[str, object] | None:
    with _worker_lock:
        worker = _worker_instance
    if worker is None or not worker.is_running():
        return None
    return worker.request_cancel(job_id)


def cleanup_cancelled_job_artifacts(
    job,
    *,
    uploads_dir: Path,
    results_dir: Path,
) -> None:
    result_state = remove_results_dir(results_dir, job.id)
    if result_state == "failed":
        logger.warning("Failed to remove results for cancelled job %s", job.id)
    restore_failed_hot_folder_upload(job)
    cleanup_upload_path(job.upload_path, uploads_dir, job.id)


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
        if resolved.implementation_id:
            transcriber = create_transcriber(
                resolved.engine_id,
                implementation_id=resolved.implementation_id,
                options=resolved.options,
            )
        else:
            transcriber = create_transcriber(
                resolved.engine_id,
                options=resolved.options,
            )
        cache[resolved.cache_key] = transcriber
    return transcriber


def _request_transcriber_cancel(transcriber: Transcriber | None, job_id: str) -> bool:
    cancel = getattr(transcriber, "cancel", None)
    if not callable(cancel):
        return False
    try:
        result = cancel(job_id)
    except TypeError:
        result = cancel()
    except Exception:
        logger.exception("Worker failed to signal cancellation for job %s", job_id)
        return False
    if isinstance(result, bool):
        return result
    return True
