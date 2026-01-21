from datetime import datetime, timedelta, timezone
from pathlib import Path
import threading
import time

from mlx_ui.db import JobRecord, init_db, insert_job, list_jobs
from mlx_ui.worker import start_worker, stop_worker


class RecordingTranscriber:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._active = False
        self.concurrent_detected = False
        self.seen: list[str] = []

    def transcribe(self, job: JobRecord, results_dir: Path) -> Path:
        with self._lock:
            if self._active:
                self.concurrent_detected = True
            self._active = True
            self.seen.append(job.id)

        time.sleep(0.05)

        job_dir = Path(results_dir) / job.id
        job_dir.mkdir(parents=True, exist_ok=True)
        result_path = job_dir / "result.txt"
        content = f"Fake transcript for {job.filename} ({job.id})\n"
        result_path.write_text(content, encoding="utf-8")

        with self._lock:
            self._active = False
        return result_path


def _make_job(job_id: str, filename: str, created_at: str, uploads_dir: Path) -> JobRecord:
    job_dir = uploads_dir / job_id
    job_dir.mkdir(parents=True, exist_ok=True)
    upload_path = job_dir / filename
    upload_path.write_text("data", encoding="utf-8")
    return JobRecord(
        id=job_id,
        filename=filename,
        status="queued",
        created_at=created_at,
        upload_path=str(upload_path),
    )


def _wait_for_jobs(db_path: Path, expected_count: int, timeout: float = 2.0) -> list[JobRecord]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        jobs = list_jobs(db_path)
        if len(jobs) == expected_count and all(job.status == "done" for job in jobs):
            return jobs
        time.sleep(0.01)
    raise AssertionError("Timed out waiting for jobs to complete.")


def test_worker_processes_jobs_sequentially(tmp_path: Path) -> None:
    db_path = tmp_path / "jobs.db"
    uploads_dir = tmp_path / "uploads"
    results_dir = tmp_path / "results"
    init_db(db_path)
    uploads_dir.mkdir(parents=True, exist_ok=True)

    base_time = datetime(2024, 1, 1, tzinfo=timezone.utc)
    job1 = _make_job(
        "job1",
        "alpha.txt",
        base_time.isoformat(timespec="seconds"),
        uploads_dir,
    )
    job2 = _make_job(
        "job2",
        "beta.txt",
        (base_time + timedelta(seconds=1)).isoformat(timespec="seconds"),
        uploads_dir,
    )
    insert_job(db_path, job1)
    insert_job(db_path, job2)

    transcriber = RecordingTranscriber()
    start_worker(
        db_path,
        results_dir,
        poll_interval=0.01,
        transcriber=transcriber,
    )
    try:
        jobs = _wait_for_jobs(db_path, expected_count=2)
    finally:
        stop_worker(timeout=1)

    assert transcriber.concurrent_detected is False
    assert transcriber.seen == [job1.id, job2.id]
    for job in jobs:
        result_path = results_dir / job.id / "result.txt"
        assert result_path.is_file()
        assert job.status == "done"
        assert job.filename in result_path.read_text(encoding="utf-8")
