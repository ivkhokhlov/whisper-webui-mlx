from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import time

from fastapi.testclient import TestClient

import mlx_ui.result_retention as retention_module
from mlx_ui.app import app
from mlx_ui.db import JobRecord, get_job, init_db, insert_job
from mlx_ui.result_retention import ResultRetentionService, purge_expired_results


def _timestamp(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="seconds")


def _insert_job(
    db_path: Path,
    *,
    job_id: str,
    status: str,
    created_at: datetime,
    completed_at: datetime | None = None,
    client_job_id: str | None = None,
) -> None:
    insert_job(
        db_path,
        JobRecord(
            id=job_id,
            filename=f"{job_id}.wav",
            status=status,
            created_at=_timestamp(created_at),
            completed_at=_timestamp(completed_at) if completed_at else None,
            upload_path=f"/uploads/{job_id}.wav",
            language="auto",
            client="callhub-transcription" if client_job_id else None,
            client_job_id=client_job_id,
        ),
    )


def _write_result(results_dir: Path, job_id: str) -> None:
    job_dir = results_dir / job_id
    job_dir.mkdir(parents=True, exist_ok=True)
    (job_dir / f"{job_id}.json").write_text("{}", encoding="utf-8")


def test_purge_removes_only_expired_terminal_result_directories(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "jobs.db"
    results_dir = tmp_path / "results"
    init_db(db_path)
    now = datetime(2026, 7, 21, 12, 0, tzinfo=timezone.utc)

    _insert_job(
        db_path,
        job_id="old-done",
        status="done",
        created_at=now - timedelta(days=10),
        completed_at=now - timedelta(days=4),
    )
    _insert_job(
        db_path,
        job_id="old-failed",
        status="failed",
        created_at=now - timedelta(days=6),
        completed_at=now - timedelta(days=3, seconds=1),
    )
    _insert_job(
        db_path,
        job_id="at-cutoff",
        status="done",
        created_at=now - timedelta(days=4),
        completed_at=now - timedelta(days=3),
    )
    _insert_job(
        db_path,
        job_id="recent-done",
        status="done",
        created_at=now - timedelta(days=2),
        completed_at=now - timedelta(days=1),
    )
    _insert_job(
        db_path,
        job_id="active-running",
        status="running",
        created_at=now - timedelta(days=10),
    )
    _insert_job(
        db_path,
        job_id="active-queued",
        status="queued",
        created_at=now - timedelta(days=10),
    )
    for job_id in (
        "old-done",
        "old-failed",
        "at-cutoff",
        "recent-done",
        "active-running",
        "active-queued",
        "orphan-result",
    ):
        _write_result(results_dir, job_id)
    (results_dir / "root-file.txt").write_text("keep", encoding="utf-8")
    (results_dir / "linked-result").symlink_to(results_dir / "recent-done")

    summary = purge_expired_results(
        db_path,
        results_dir,
        retention_days=3,
        now=now,
        batch_size=2,
    )

    assert summary.scanned == 7
    assert summary.expired == 2
    assert summary.deleted == 2
    assert summary.failed == 0
    assert not (results_dir / "old-done").exists()
    assert not (results_dir / "old-failed").exists()
    assert (results_dir / "at-cutoff").is_dir()
    assert (results_dir / "recent-done").is_dir()
    assert (results_dir / "active-running").is_dir()
    assert (results_dir / "active-queued").is_dir()
    assert (results_dir / "orphan-result").is_dir()
    assert (results_dir / "root-file.txt").is_file()
    assert (results_dir / "linked-result").is_symlink()
    assert get_job(db_path, "old-done") is not None
    assert get_job(db_path, "old-failed") is not None


def test_expired_machine_job_keeps_contract_with_empty_results(tmp_path: Path) -> None:
    app.state.base_dir = tmp_path
    app.state.uploads_dir = tmp_path / "uploads"
    app.state.results_dir = tmp_path / "results"
    app.state.db_path = tmp_path / "jobs.db"
    app.state.worker_enabled = False
    app.state.update_check_enabled = False
    init_db(Path(app.state.db_path))
    now = datetime.now(timezone.utc)
    _insert_job(
        Path(app.state.db_path),
        job_id="expired-machine-job",
        status="done",
        created_at=now - timedelta(days=5),
        completed_at=now - timedelta(days=4),
        client_job_id="command-expired",
    )
    _write_result(Path(app.state.results_dir), "expired-machine-job")

    purge_expired_results(
        Path(app.state.db_path),
        Path(app.state.results_dir),
        retention_days=3,
        now=now,
    )

    with TestClient(app) as client:
        response = client.get("/api/machine/jobs/callhub-transcription/command-expired")
        state_response = client.get("/api/state")

    assert response.status_code == 200
    assert response.json()["status"] == "done"
    assert response.json()["results"] == []
    assert state_response.status_code == 200
    assert state_response.json()["history"][0]["id"] == "expired-machine-job"
    assert state_response.json()["results_by_job"]["expired-machine-job"] == []


def test_service_reloads_setting_and_runs_immediately_then_periodically(
    tmp_path: Path,
    monkeypatch,
) -> None:
    calls: list[int] = []
    settings_path = tmp_path / "data" / "settings.json"
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    settings_path.write_text(
        json.dumps({"results_retention_days": 3}), encoding="utf-8"
    )

    def _record(_db_path, _results_dir, *, retention_days, **_kwargs):  # type: ignore[no-untyped-def]
        calls.append(retention_days)
        return retention_module.ResultRetentionSummary(
            retention_days=retention_days,
            scanned=0,
            expired=0,
            deleted=0,
            missing=0,
            failed=0,
            batches=0,
        )

    monkeypatch.setattr(retention_module, "purge_expired_results", _record)
    service = ResultRetentionService(
        tmp_path / "jobs.db",
        tmp_path / "results",
        tmp_path,
        interval_seconds=0.02,
    )
    service.start()
    deadline = time.monotonic() + 1
    while len(calls) < 1 and time.monotonic() < deadline:
        time.sleep(0.005)
    settings_path.write_text(
        json.dumps({"results_retention_days": 7}), encoding="utf-8"
    )
    while 7 not in calls and time.monotonic() < deadline:
        time.sleep(0.005)
    service.stop(timeout=1)

    assert calls[0] == 3
    assert 7 in calls
    assert service.is_running() is False
