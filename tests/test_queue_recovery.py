from pathlib import Path
import sqlite3

import pytest

import mlx_ui.db as db
import mlx_ui.worker as worker_module
from mlx_ui.worker import Worker


class Transcriber:
    engine_id = "fake"

    def __init__(self) -> None:
        self.seen: list[str] = []
        self.on_transcribe = None

    def transcribe(self, job: db.JobRecord, results_dir: Path) -> Path:
        self.seen.append(job.id)
        directory = results_dir / job.id
        directory.mkdir(parents=True)
        result = directory / "transcript.txt"
        result.write_text("test transcript", encoding="utf-8")
        if self.on_transcribe is not None:
            self.on_transcribe(job)
        return result


@pytest.fixture
def queue(tmp_path: Path):
    path = tmp_path / "jobs.db"
    db.init_db(path)
    jobs = []
    for index in (1, 2):
        upload = tmp_path / "uploads" / f"job{index}" / "sample.wav"
        upload.parent.mkdir(parents=True)
        upload.write_bytes(b"test media")
        job = db.JobRecord(
            id=f"job{index}",
            filename="sample.wav",
            status="queued",
            created_at=f"2026-01-01T00:00:0{index}+00:00",
            upload_path=str(upload),
            language="auto",
            client="callhub-transcription",
            client_job_id=f"caller-{index}",
        )
        db.insert_job(path, job)
        jobs.append(job)
    transcriber = Transcriber()
    worker = Worker(
        path,
        tmp_path / "uploads",
        tmp_path / "results",
        transcriber=transcriber,
        base_dir=tmp_path,
    )
    return worker, jobs, transcriber


def test_failed_start_requeues_same_job_and_preserves_upload(queue, monkeypatch):
    worker, jobs, transcriber = queue
    original = worker_module.mark_job_running
    attempts = 0

    def flaky_start(*args, **kwargs):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise sqlite3.OperationalError("unable to open database file")
        return original(*args, **kwargs)

    monkeypatch.setattr(worker_module, "mark_job_running", flaky_start)
    assert worker.run_once() is True
    stored = db.get_job(worker.db_path, jobs[0].id)
    assert stored.status == "queued"
    assert stored.started_at is None
    assert stored.client_job_id == jobs[0].client_job_id
    assert Path(stored.upload_path).is_file()
    assert transcriber.seen == []
    assert worker.snapshot() is None

    assert worker.run_once() is True
    assert worker.run_once() is True
    assert transcriber.seen == [job.id for job in jobs]
    assert all(job.status == "done" for job in db.list_jobs(worker.db_path))


def test_requeue_failure_is_retried_before_claiming_another_job(queue, monkeypatch):
    worker, jobs, transcriber = queue
    original_start = worker_module.mark_job_running
    original_requeue = worker_module.requeue_reserved_job
    attempts = 0

    def fail_start(*args, **kwargs):
        raise sqlite3.OperationalError("unable to open database file")

    def flaky_requeue(*args, **kwargs):
        nonlocal attempts
        attempts += 1
        if attempts <= 2:
            raise sqlite3.OperationalError("unable to open database file")
        return original_requeue(*args, **kwargs)

    monkeypatch.setattr(worker_module, "mark_job_running", fail_start)
    monkeypatch.setattr(worker_module, "requeue_reserved_job", flaky_requeue)
    assert worker.run_once() is False
    assert worker.run_once() is False
    assert transcriber.seen == []
    assert worker.snapshot()["job_id"] == jobs[0].id
    assert all(Path(job.upload_path).is_file() for job in jobs)

    assert worker.run_once() is True
    assert db.get_job(worker.db_path, jobs[0].id).status == "queued"
    assert worker.snapshot() is None
    monkeypatch.setattr(worker_module, "mark_job_running", original_start)
    assert worker.run_once() is True
    assert worker.run_once() is True
    assert transcriber.seen == [job.id for job in jobs]


@pytest.mark.parametrize("status", ["done", "failed", "cancelled"])
@pytest.mark.parametrize("error_type", [sqlite3.OperationalError, OSError])
def test_terminal_write_retries_preserve_artifacts_without_retranscribing(
    queue, monkeypatch, status, error_type
):
    worker, jobs, transcriber = queue

    def outcome(job):
        if job.id != jobs[0].id:
            return
        if status == "failed":
            raise RuntimeError("transcription failed")
        if status == "cancelled":
            worker.request_cancel(job.id)

    transcriber.on_transcribe = outcome
    operation_name = {
        "done": "mark_job_done",
        "failed": "mark_job_failed",
        "cancelled": "cancel_running_job",
    }[status]
    operation = getattr(worker_module, operation_name)
    attempts = 0

    def flaky_write(*args, **kwargs):
        nonlocal attempts
        attempts += 1
        if attempts <= 2:
            raise error_type("unable to open database file")
        return operation(*args, **kwargs)

    monkeypatch.setattr(worker_module, operation_name, flaky_write)
    for _ in range(2):
        assert worker.run_once() is False
        assert transcriber.seen == [jobs[0].id]
        assert Path(jobs[0].upload_path).is_file()
        assert (worker.results_dir / jobs[0].id / "transcript.txt").is_file()
    assert worker.run_once() is True
    assert worker.snapshot() is None
    assert db.get_job(worker.db_path, jobs[0].id).status == status
    assert not Path(jobs[0].upload_path).exists()
    if status == "cancelled":
        assert not (worker.results_dir / jobs[0].id).exists()
    assert worker.run_once() is True
    assert transcriber.seen == [job.id for job in jobs]
    assert db.get_job(worker.db_path, jobs[1].id).status == "done"


@pytest.mark.parametrize("pending_status", ["queued", "done"])
def test_cancel_while_waiting_for_database_does_not_restart_job(
    queue, monkeypatch, pending_status
):
    worker, jobs, transcriber = queue

    def unavailable(*args, **kwargs):
        raise sqlite3.OperationalError("unable to open database file")

    if pending_status == "queued":
        original_start = worker_module.mark_job_running

        def fail_first_job_start(path, job_id, **kwargs):
            if job_id == jobs[0].id:
                return unavailable()
            return original_start(path, job_id, **kwargs)

        monkeypatch.setattr(worker_module, "mark_job_running", fail_first_job_start)
        monkeypatch.setattr(worker_module, "requeue_reserved_job", unavailable)
    else:
        monkeypatch.setattr(worker_module, "mark_job_done", unavailable)

    assert worker.run_once() is False
    snapshot = worker.request_cancel(jobs[0].id)
    assert snapshot["cancel_requested"] is True
    assert snapshot["interrupted"] is False
    assert worker.run_once() is True
    assert worker.snapshot() is None
    assert db.get_job(worker.db_path, jobs[0].id).status == "cancelled"
    assert not Path(jobs[0].upload_path).exists()
    assert not (worker.results_dir / jobs[0].id).exists()
    assert transcriber.seen == ([] if pending_status == "queued" else [jobs[0].id])


def test_cancel_is_checked_between_busy_retries(queue, monkeypatch):
    worker, jobs, transcriber = queue
    original_done = worker_module.mark_job_done

    def cancel_before_retry(*args, **kwargs):
        if args[1] == jobs[0].id:
            worker.request_cancel(jobs[0].id)
            raise sqlite3.OperationalError("database is locked")
        return original_done(*args, **kwargs)

    monkeypatch.setattr(worker_module, "mark_job_done", cancel_before_retry)
    monkeypatch.setattr(worker_module, "_SQLITE_BUSY_RETRY_BASE_SECONDS", 0.001)
    assert worker.run_once() is True
    assert db.get_job(worker.db_path, jobs[0].id).status == "cancelled"
    assert worker.snapshot() is None
    assert not (worker.results_dir / jobs[0].id).exists()
    assert worker.run_once() is True
    assert transcriber.seen == [job.id for job in jobs]


def test_resolution_failure_cannot_orphan_reservation(queue, monkeypatch):
    worker, jobs, transcriber = queue
    original_resolve = worker._resolve_transcriber_for_job
    original_failed = worker_module.mark_job_failed
    attempts = 0

    def resolve(job):
        if job.id == jobs[0].id:
            raise ValueError("backend unavailable")
        return original_resolve(job)

    def fail_once(*args, **kwargs):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise sqlite3.OperationalError("unable to open database file")
        return original_failed(*args, **kwargs)

    monkeypatch.setattr(worker, "_resolve_transcriber_for_job", resolve)
    monkeypatch.setattr(worker_module, "mark_job_failed", fail_once)
    assert worker.run_once() is False
    assert Path(jobs[0].upload_path).is_file()
    assert worker.run_once() is True
    assert db.get_job(worker.db_path, jobs[0].id).error_message == "backend unavailable"
    assert worker.snapshot() is None
    assert worker.run_once() is True
    assert transcriber.seen == [jobs[1].id]


def test_cancel_during_resolution_prevents_inference(queue, monkeypatch):
    worker, jobs, transcriber = queue
    original = worker._resolve_transcriber_for_job

    def resolve(job):
        worker.request_cancel(job.id)
        return original(job)

    monkeypatch.setattr(worker, "_resolve_transcriber_for_job", resolve)
    assert worker.run_once() is True
    assert db.get_job(worker.db_path, jobs[0].id).status == "cancelled"
    assert transcriber.seen == []
    assert worker.snapshot() is None


@pytest.mark.parametrize("status", ["reserved", "running", "cancelled", "done"])
def test_requeue_only_changes_reserved_jobs(queue, status):
    worker, jobs, _ = queue
    db.update_job_status(worker.db_path, jobs[0].id, status)
    assert db.requeue_reserved_job(worker.db_path, jobs[0].id) is (status == "reserved")
    stored = db.get_job(worker.db_path, jobs[0].id)
    assert stored.status == ("queued" if status == "reserved" else status)
    assert stored.client_job_id == jobs[0].client_job_id
    assert stored.queue_position == 1
    assert Path(stored.upload_path).is_file()
