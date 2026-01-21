from __future__ import annotations

import logging
from pathlib import Path
import threading

from mlx_ui.db import claim_next_job, update_job_status
from mlx_ui.transcriber import Transcriber, WtmTranscriber

logger = logging.getLogger(__name__)

_worker_lock = threading.Lock()
_worker_instance: Worker | None = None


class Worker:
    def __init__(
        self,
        db_path: Path,
        results_dir: Path,
        poll_interval: float = 0.5,
        transcriber: Transcriber | None = None,
    ) -> None:
        self.db_path = Path(db_path)
        self.results_dir = Path(results_dir)
        self.poll_interval = poll_interval
        self.transcriber = transcriber or WtmTranscriber()
        self._stop_event = threading.Event()
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

    def _run_loop(self) -> None:
        while not self._stop_event.is_set():
            processed = self.run_once()
            if not processed:
                self._stop_event.wait(self.poll_interval)

    def run_once(self) -> bool:
        job = claim_next_job(self.db_path)
        if job is None:
            return False
        try:
            self.transcriber.transcribe(job, self.results_dir)
        except Exception:
            logger.exception("Worker failed to transcribe job %s", job.id)
            update_job_status(self.db_path, job.id, "failed")
            return True
        update_job_status(self.db_path, job.id, "done")
        return True


def start_worker(
    db_path: Path,
    results_dir: Path,
    poll_interval: float = 0.5,
    transcriber: Transcriber | None = None,
) -> Worker:
    global _worker_instance
    with _worker_lock:
        if _worker_instance and _worker_instance.is_running():
            return _worker_instance
        _worker_instance = Worker(
            db_path=db_path,
            results_dir=results_dir,
            poll_interval=poll_interval,
            transcriber=transcriber,
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
