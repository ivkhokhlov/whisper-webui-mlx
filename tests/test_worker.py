from datetime import datetime, timedelta, timezone
from pathlib import Path
import threading
import time

import mlx_ui.engine_registry as engine_registry
import mlx_ui.worker as worker_module
from mlx_ui.db import JobRecord, claim_next_job, init_db, insert_job, list_jobs
from mlx_ui.engine_registry import EngineFactoryOptions
from mlx_ui.engine_registry import FAKE_ENGINE
from mlx_ui.settings import ResolvedTranscriberSettings
from mlx_ui.worker import Worker, start_worker, stop_worker


class RecordingTranscriber:
    engine_id = FAKE_ENGINE

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
        result_path = job_dir / f"{Path(job.filename).stem}.txt"
        content = f"Fake transcript for {job.filename} ({job.id})\n"
        result_path.write_text(content, encoding="utf-8")

        with self._lock:
            self._active = False
        return result_path


def _make_job(
    job_id: str,
    filename: str,
    created_at: str,
    uploads_dir: Path,
    *,
    requested_engine: str | None = None,
) -> JobRecord:
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
        language="en",
        requested_engine=requested_engine,
    )


def _wait_for_jobs(
    db_path: Path, expected_count: int, timeout: float = 2.0
) -> list[JobRecord]:
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
        uploads_dir,
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
        result_path = results_dir / job.id / f"{Path(job.filename).stem}.txt"
        assert result_path.is_file()
        assert job.status == "done"
        assert job.started_at is not None
        assert job.completed_at is not None
        assert job.error_message is None
        assert job.effective_engine == FAKE_ENGINE
        assert job.filename in result_path.read_text(encoding="utf-8")
    assert not Path(job1.upload_path).exists()
    assert not Path(job2.upload_path).exists()


def test_worker_records_failure_metadata(tmp_path: Path) -> None:
    class FailingTranscriber:
        engine_id = FAKE_ENGINE

        def transcribe(self, job: JobRecord, results_dir: Path) -> Path:
            raise RuntimeError("boom")

    db_path = tmp_path / "jobs.db"
    uploads_dir = tmp_path / "uploads"
    results_dir = tmp_path / "results"
    init_db(db_path)
    uploads_dir.mkdir(parents=True, exist_ok=True)

    job = _make_job(
        "job1",
        "alpha.txt",
        datetime.now(timezone.utc).isoformat(timespec="seconds"),
        uploads_dir,
    )
    insert_job(db_path, job)

    worker = Worker(
        db_path=db_path,
        uploads_dir=uploads_dir,
        results_dir=results_dir,
        transcriber=FailingTranscriber(),
    )
    processed = worker.run_once()

    assert processed is True
    jobs = list_jobs(db_path)
    assert len(jobs) == 1
    failed_job = jobs[0]
    assert failed_job.status == "failed"
    assert failed_job.started_at is not None
    assert failed_job.completed_at is not None
    assert failed_job.error_message is not None
    assert failed_job.effective_engine == FAKE_ENGINE
    assert not Path(job.upload_path).exists()


def test_worker_resolves_requested_engine_per_job_and_reuses_cache(
    tmp_path: Path, monkeypatch
) -> None:
    class EngineTranscriber:
        def __init__(self, engine_id: str) -> None:
            self.engine_id = engine_id

        def transcribe(self, job: JobRecord, results_dir: Path) -> Path:
            job_dir = Path(results_dir) / job.id
            job_dir.mkdir(parents=True, exist_ok=True)
            result_path = job_dir / f"{Path(job.filename).stem}.txt"
            result_path.write_text(self.engine_id, encoding="utf-8")
            return result_path

    db_path = tmp_path / "jobs.db"
    uploads_dir = tmp_path / "uploads"
    results_dir = tmp_path / "results"
    init_db(db_path)
    uploads_dir.mkdir(parents=True, exist_ok=True)

    base_time = datetime(2024, 1, 1, tzinfo=timezone.utc)
    jobs = [
        _make_job(
            "job1",
            "alpha.txt",
            base_time.isoformat(timespec="seconds"),
            uploads_dir,
            requested_engine="whisper_mlx",
        ),
        _make_job(
            "job2",
            "beta.txt",
            (base_time + timedelta(seconds=1)).isoformat(timespec="seconds"),
            uploads_dir,
            requested_engine="whisper_cpu",
        ),
        _make_job(
            "job3",
            "gamma.txt",
            (base_time + timedelta(seconds=2)).isoformat(timespec="seconds"),
            uploads_dir,
            requested_engine="whisper_mlx",
        ),
    ]
    for job in jobs:
        insert_job(db_path, job)

    resolved_requests: list[str | None] = []
    created_engines: list[str] = []

    def fake_resolve(
        requested_engine: str | None = None,
        *,
        base_dir: Path | None = None,
        env=None,
    ) -> ResolvedTranscriberSettings:
        resolved_requests.append(requested_engine)
        assert base_dir == tmp_path
        return ResolvedTranscriberSettings(
            engine_id=str(requested_engine),
            options=EngineFactoryOptions(),
            cache_key=(str(requested_engine),),
        )

    def fake_create(engine_id: str, *, options: EngineFactoryOptions):
        created_engines.append(engine_id)
        return EngineTranscriber(engine_id)

    monkeypatch.setattr(
        worker_module,
        "resolve_job_transcriber_spec_with_settings",
        fake_resolve,
    )
    monkeypatch.setattr(worker_module, "create_transcriber", fake_create)

    worker = Worker(
        db_path=db_path,
        uploads_dir=uploads_dir,
        results_dir=results_dir,
        base_dir=tmp_path,
    )

    assert worker.run_once() is True
    assert worker.run_once() is True
    assert worker.run_once() is True
    assert worker.run_once() is False

    stored_jobs = {job.id: job for job in list_jobs(db_path)}
    assert resolved_requests == ["whisper_mlx", "whisper_cpu", "whisper_mlx"]
    assert created_engines == ["whisper_mlx", "whisper_cpu"]
    assert stored_jobs["job1"].effective_engine == "whisper_mlx"
    assert stored_jobs["job2"].effective_engine == "whisper_cpu"
    assert stored_jobs["job3"].effective_engine == "whisper_mlx"
    assert (results_dir / "job1" / "alpha.txt").read_text(encoding="utf-8") == "whisper_mlx"
    assert (results_dir / "job2" / "beta.txt").read_text(encoding="utf-8") == "whisper_cpu"
    assert (results_dir / "job3" / "gamma.txt").read_text(encoding="utf-8") == "whisper_mlx"


def test_worker_fails_job_when_requested_engine_cannot_be_resolved(
    tmp_path: Path, monkeypatch
) -> None:
    db_path = tmp_path / "jobs.db"
    uploads_dir = tmp_path / "uploads"
    results_dir = tmp_path / "results"
    init_db(db_path)
    uploads_dir.mkdir(parents=True, exist_ok=True)

    job = _make_job(
        "job1",
        "alpha.txt",
        datetime.now(timezone.utc).isoformat(timespec="seconds"),
        uploads_dir,
        requested_engine="cohere",
    )
    insert_job(db_path, job)
    monkeypatch.setattr(
        engine_registry,
        "cohere_availability_reason",
        lambda: "the optional 'cohere' Python SDK is not installed.",
    )

    worker = Worker(
        db_path=db_path,
        uploads_dir=uploads_dir,
        results_dir=results_dir,
        base_dir=tmp_path,
    )

    assert worker.run_once() is True

    failed_job = list_jobs(db_path)[0]
    assert failed_job.status == "failed"
    assert failed_job.effective_engine is None
    assert failed_job.error_message is not None
    assert "cohere" in failed_job.error_message
    assert "optional 'cohere' Python SDK is not installed" in failed_job.error_message
    assert not Path(job.upload_path).exists()


def test_claim_next_job_blocks_when_running_exists(tmp_path: Path) -> None:
    db_path = tmp_path / "jobs.db"
    uploads_dir = tmp_path / "uploads"
    init_db(db_path)
    uploads_dir.mkdir(parents=True, exist_ok=True)

    base_time = datetime(2024, 1, 1, tzinfo=timezone.utc)
    running_job_base = _make_job(
        "job-running",
        "run.txt",
        base_time.isoformat(timespec="seconds"),
        uploads_dir,
    )
    running_job = JobRecord(
        id=running_job_base.id,
        filename=running_job_base.filename,
        status="running",
        created_at=running_job_base.created_at,
        upload_path=running_job_base.upload_path,
        language=running_job_base.language,
        started_at=running_job_base.created_at,
    )
    queued_job = _make_job(
        "job-queued",
        "queued.txt",
        (base_time + timedelta(seconds=1)).isoformat(timespec="seconds"),
        uploads_dir,
    )

    insert_job(db_path, running_job)
    insert_job(db_path, queued_job)

    claimed = claim_next_job(db_path)

    assert claimed is None
    jobs = {job.id: job for job in list_jobs(db_path)}
    assert jobs["job-running"].status == "running"
    assert jobs["job-queued"].status == "queued"
