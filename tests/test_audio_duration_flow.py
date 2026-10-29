from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi.testclient import TestClient
import pytest

from mlx_ui.app import create_app
from mlx_ui.app_context import set_runtime_flags, set_paths
from mlx_ui.db import JobRecord, get_job, init_db, insert_job
from mlx_ui.result_retention import purge_expired_results
from mlx_ui.transcriber import FakeTranscriber
from mlx_ui.worker import Worker
import wave


def write_wav(path: Path) -> None:
    with wave.open(str(path), "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(16000)
        audio.writeframes(b"\0\0" * 20000)


@pytest.mark.parametrize("probe_fails", [False, True])
def test_upload_worker_history_and_retention(
    tmp_path: Path, monkeypatch, probe_fails: bool
) -> None:
    app = create_app()
    db = tmp_path / "jobs.db"
    uploads = tmp_path / "uploads"
    results = tmp_path / "results"
    set_paths(
        app, base_dir=tmp_path, db_path=db, uploads_dir=uploads, results_dir=results
    )
    set_runtime_flags(app, worker_enabled=False, update_check_enabled=False)
    monkeypatch.setattr("mlx_ui.worker.maybe_send_telegram", lambda *a, **kw: None)
    if probe_fails:
        monkeypatch.setattr("mlx_ui.worker.probe_audio_duration", lambda path: None)
    source = tmp_path / "source.wav"
    write_wav(source)
    with TestClient(app) as client:
        with source.open("rb") as audio:
            response = client.post(
                "/upload",
                files={"files": ("source.wav", audio, "audio/wav")},
                follow_redirects=False,
            )
        assert response.status_code == 303
        worker = Worker(
            db, uploads, results, transcriber=FakeTranscriber(), base_dir=tmp_path
        )
        assert worker.run_once()
        item = client.get("/api/browser/history").json()["items"][0]
        job = get_job(db, item["id"])
        assert job.status == "done"
        assert not Path(job.upload_path).exists()
        expected = None if probe_fails else pytest.approx(1.25)
        assert job.audio_duration_seconds == expected
        assert item["audio_duration_seconds"] == expected
        init_db(db)
        assert get_job(db, job.id).audio_duration_seconds == expected
        purge_expired_results(
            db,
            results,
            retention_days=1,
            now=datetime.now(timezone.utc) + timedelta(days=3),
        )
        assert not (results / job.id).exists()
        retained = client.get("/api/browser/history").json()["items"][0]
        assert retained["audio_duration_seconds"] == expected
        assert retained["results"] == []


def test_duration_roundtrips_all_job_queries(tmp_path: Path) -> None:
    import mlx_ui.db as db_module

    db = tmp_path / "jobs.db"
    init_db(db)
    job = JobRecord(
        id="duration-job",
        filename="long.wav",
        status="queued",
        created_at="2026-10-29T00:00:00Z",
        upload_path="/missing",
        language="auto",
        client="test",
        client_job_id="long",
        audio_duration_seconds=3723.5,
    )
    insert_job(db, job)
    assert db_module.list_active_jobs(db)[0].audio_duration_seconds == 3723.5
    assert db_module.claim_next_job(db).audio_duration_seconds == 3723.5
    assert db_module.get_job(db, job.id).audio_duration_seconds == 3723.5
    assert (
        db_module.find_job_by_client_job_id(
            db, client="test", client_job_id="long"
        ).audio_duration_seconds
        == 3723.5
    )
    db_module.update_job_status(db, job.id, "done")
    for rows in [
        db_module.list_jobs(db),
        db_module.list_history_jobs(db),
        db_module.list_recent_history_jobs(db, limit=1),
        db_module.list_history_page(db, limit=1, offset=0)[0],
    ]:
        assert rows[0].audio_duration_seconds == 3723.5


def test_completion_retry_keeps_duration_without_reprobing(
    tmp_path: Path, monkeypatch
) -> None:
    import sqlite3
    import mlx_ui.worker as worker_module

    db = tmp_path / "jobs.db"
    init_db(db)
    source = tmp_path / "uploads" / "retry" / "source.wav"
    source.parent.mkdir(parents=True)
    write_wav(source)
    insert_job(
        db,
        JobRecord(
            id="retry",
            filename="source.wav",
            status="queued",
            created_at="2026-10-29T00:00:00Z",
            upload_path=str(source),
            language="auto",
        ),
    )
    worker = Worker(
        db,
        tmp_path / "uploads",
        tmp_path / "results",
        transcriber=FakeTranscriber(),
        base_dir=tmp_path,
    )
    original_probe = worker_module.probe_audio_duration
    original_done = worker_module.mark_job_done
    probes = []
    attempts = []

    def probe(path):
        probes.append(path)
        return original_probe(path)

    def complete(*args, **kwargs):
        attempts.append(kwargs["audio_duration_seconds"])
        if len(attempts) == 1:
            raise sqlite3.OperationalError("unable to open database file")
        return original_done(*args, **kwargs)

    monkeypatch.setattr(worker_module, "probe_audio_duration", probe)
    monkeypatch.setattr(worker_module, "mark_job_done", complete)
    monkeypatch.setattr(worker_module, "maybe_send_telegram", lambda *a, **kw: None)
    assert worker.run_once() is False
    assert source.exists()
    assert worker.run_once() is True
    assert len(probes) == 1
    assert attempts == [1.25, 1.25]
    assert get_job(db, "retry").audio_duration_seconds == 1.25
    assert not source.exists()
