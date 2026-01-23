from datetime import datetime, timedelta, timezone
from pathlib import Path

from mlx_ui.db import JobRecord, cancel_running_job, init_db, insert_job, list_jobs, reorder_queue
from mlx_ui.worker import Worker
from mlx_ui.transcriber import FakeTranscriber


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
        language="en",
    )


def test_reorder_queue_updates_positions(tmp_path: Path) -> None:
    db_path = tmp_path / "jobs.db"
    uploads_dir = tmp_path / "uploads"
    init_db(db_path)
    uploads_dir.mkdir(parents=True, exist_ok=True)

    base_time = datetime(2024, 1, 1, tzinfo=timezone.utc)
    job_ids = ["job1", "job2", "job3"]
    for offset, job_id in enumerate(job_ids):
        job = _make_job(
            job_id,
            f"file-{job_id}.wav",
            (base_time + timedelta(seconds=offset)).isoformat(timespec="seconds"),
            uploads_dir,
        )
        insert_job(db_path, job)

    reordered = list(reversed(job_ids))
    assert reorder_queue(db_path, reordered) is True

    jobs = list_jobs(db_path)
    ordered_ids = [job.id for job in jobs if job.status == "queued"]
    assert ordered_ids == reordered
    positions = {job.id: job.queue_position for job in jobs}
    assert positions[reordered[0]] == 1
    assert positions[reordered[1]] == 2
    assert positions[reordered[2]] == 3


def test_reorder_queue_rejects_invalid_ids(tmp_path: Path) -> None:
    db_path = tmp_path / "jobs.db"
    uploads_dir = tmp_path / "uploads"
    init_db(db_path)
    uploads_dir.mkdir(parents=True, exist_ok=True)

    base_time = datetime(2024, 1, 1, tzinfo=timezone.utc)
    job1 = _make_job("job1", "alpha.wav", base_time.isoformat(timespec="seconds"), uploads_dir)
    job2 = _make_job("job2", "beta.wav", base_time.isoformat(timespec="seconds"), uploads_dir)
    insert_job(db_path, job1)
    insert_job(db_path, job2)

    assert reorder_queue(db_path, ["job1"]) is False
    assert reorder_queue(db_path, ["job1", "job3"]) is False


def test_cancel_running_job_sets_status(tmp_path: Path) -> None:
    db_path = tmp_path / "jobs.db"
    init_db(db_path)

    started_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    job = JobRecord(
        id="job-running",
        filename="run.wav",
        status="running",
        created_at=started_at,
        upload_path="/tmp/run.wav",
        language="en",
        started_at=started_at,
    )
    insert_job(db_path, job)

    assert cancel_running_job(db_path, job.id) is True

    updated = list_jobs(db_path)[0]
    assert updated.status == "cancelled"
    assert updated.completed_at is not None


def test_worker_pause_skips_claim(tmp_path: Path) -> None:
    db_path = tmp_path / "jobs.db"
    uploads_dir = tmp_path / "uploads"
    results_dir = tmp_path / "results"
    init_db(db_path)
    uploads_dir.mkdir(parents=True, exist_ok=True)

    job = _make_job(
        "job1",
        "alpha.wav",
        datetime.now(timezone.utc).isoformat(timespec="seconds"),
        uploads_dir,
    )
    insert_job(db_path, job)

    worker = Worker(
        db_path=db_path,
        uploads_dir=uploads_dir,
        results_dir=results_dir,
        transcriber=FakeTranscriber(),
    )
    worker.pause()

    assert worker.run_once() is False
    jobs = list_jobs(db_path)
    assert jobs[0].status == "queued"
