from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import logging
from pathlib import Path
import threading

from mlx_ui.db import list_expired_terminal_job_ids
from mlx_ui.settings_store import compute_effective_settings
from mlx_ui.storage import is_safe_path_component, remove_results_dir

logger = logging.getLogger(__name__)

RESULT_RETENTION_INTERVAL_SECONDS = 60 * 60
RESULT_RETENTION_BATCH_SIZE = 500


@dataclass(frozen=True)
class ResultRetentionSummary:
    retention_days: int
    scanned: int
    expired: int
    deleted: int
    missing: int
    failed: int
    batches: int


def purge_expired_results(
    db_path: Path,
    results_dir: Path,
    *,
    retention_days: int,
    now: datetime | None = None,
    batch_size: int = RESULT_RETENTION_BATCH_SIZE,
) -> ResultRetentionSummary:
    if retention_days < 1:
        raise ValueError("retention_days must be positive")
    if batch_size < 1:
        raise ValueError("batch_size must be positive")

    cutoff = (now or datetime.now(timezone.utc)) - timedelta(days=retention_days)
    cutoff_text = cutoff.astimezone(timezone.utc).isoformat(timespec="seconds")
    job_ids = _list_candidate_result_job_ids(results_dir)
    deleted = 0
    missing = 0
    failed = 0
    expired = 0
    batches = 0

    for start in range(0, len(job_ids), batch_size):
        batch = job_ids[start : start + batch_size]
        batches += 1
        expired_ids = list_expired_terminal_job_ids(
            db_path,
            batch,
            cutoff=cutoff_text,
        )
        expired += len(expired_ids)
        for job_id in sorted(expired_ids):
            result = remove_results_dir(results_dir, job_id)
            if result == "deleted":
                deleted += 1
            elif result == "missing":
                missing += 1
            else:
                failed += 1

    summary = ResultRetentionSummary(
        retention_days=retention_days,
        scanned=len(job_ids),
        expired=expired,
        deleted=deleted,
        missing=missing,
        failed=failed,
        batches=batches,
    )
    if summary.deleted or summary.failed:
        log = logger.warning if summary.failed else logger.info
        log(
            "Result retention cleanup finished: retention_days=%s scanned=%s "
            "expired=%s deleted=%s missing=%s failed=%s batches=%s",
            summary.retention_days,
            summary.scanned,
            summary.expired,
            summary.deleted,
            summary.missing,
            summary.failed,
            summary.batches,
        )
    return summary


def purge_expired_results_from_settings(
    db_path: Path,
    results_dir: Path,
    base_dir: Path,
) -> ResultRetentionSummary:
    effective, _sources, _file_settings = compute_effective_settings(base_dir=base_dir)
    retention_days = int(effective["results_retention_days"])
    return purge_expired_results(
        db_path,
        results_dir,
        retention_days=retention_days,
    )


class ResultRetentionService:
    def __init__(
        self,
        db_path: Path,
        results_dir: Path,
        base_dir: Path,
        *,
        interval_seconds: float = RESULT_RETENTION_INTERVAL_SECONDS,
    ) -> None:
        if interval_seconds <= 0:
            raise ValueError("interval_seconds must be positive")
        self.db_path = Path(db_path)
        self.results_dir = Path(results_dir)
        self.base_dir = Path(base_dir)
        self.interval_seconds = interval_seconds
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self.is_running():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run_loop,
            name="mlx-ui-result-retention",
            daemon=True,
        )
        self._thread.start()

    def stop(self, timeout: float | None = None) -> None:
        self._stop_event.set()
        thread = self._thread
        if thread is not None:
            thread.join(timeout=timeout)
        if thread is None or not thread.is_alive():
            self._thread = None

    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def run_once(self) -> ResultRetentionSummary | None:
        try:
            return purge_expired_results_from_settings(
                self.db_path,
                self.results_dir,
                self.base_dir,
            )
        except Exception:
            logger.exception("Result retention cleanup failed; it will be retried")
            return None

    def _run_loop(self) -> None:
        self.run_once()
        while not self._stop_event.wait(self.interval_seconds):
            self.run_once()


def _list_candidate_result_job_ids(results_dir: Path) -> list[str]:
    if not results_dir.is_dir():
        return []
    job_ids: list[str] = []
    try:
        entries = results_dir.iterdir()
        for entry in entries:
            if (
                is_safe_path_component(entry.name)
                and not entry.is_symlink()
                and entry.is_dir()
            ):
                job_ids.append(entry.name)
    except OSError:
        logger.exception("Failed to scan the results directory for retention cleanup")
        return []
    return sorted(job_ids)
