from datetime import datetime, timezone
from pathlib import Path

from fastapi.testclient import TestClient

from mlx_ui.app import app
from mlx_ui.db import JobRecord, init_db, insert_job


def _configure_app(tmp_path: Path) -> None:
    app.state.base_dir = tmp_path
    app.state.uploads_dir = tmp_path / "uploads"
    app.state.results_dir = tmp_path / "results"
    app.state.db_path = tmp_path / "jobs.db"
    app.state.worker_enabled = False
    app.state.update_check_enabled = False
    app.state.live_service = None


def test_root_queue_rows_use_compact_summary(tmp_path: Path, monkeypatch) -> None:
    _configure_app(tmp_path)
    monkeypatch.setattr("mlx_ui.app.recover_running_jobs", lambda _db_path: 0)
    db_path = Path(app.state.db_path)
    init_db(db_path)

    running_id = "job-running-row"
    running_dir = Path(app.state.uploads_dir) / running_id
    running_dir.mkdir(parents=True, exist_ok=True)
    running_path = running_dir / "alpha.wav"
    running_path.write_text("data", encoding="utf-8")
    started_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    insert_job(
        db_path,
        JobRecord(
            id=running_id,
            filename="alpha.wav",
            status="running",
            created_at=started_at,
            started_at=started_at,
            upload_path=str(running_path),
            language="en",
            requested_engine="cohere",
            effective_engine="cohere",
        ),
    )

    queued_local_id = "job-queued-local"
    queued_local_dir = Path(app.state.uploads_dir) / queued_local_id
    queued_local_dir.mkdir(parents=True, exist_ok=True)
    queued_local_path = queued_local_dir / "bravo.wav"
    queued_local_path.write_text("data", encoding="utf-8")
    insert_job(
        db_path,
        JobRecord(
            id=queued_local_id,
            filename="bravo.wav",
            status="queued",
            created_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            upload_path=str(queued_local_path),
            language="auto",
            requested_engine="whisper_mlx",
        ),
    )

    queued_cloud_id = "job-queued-cloud"
    queued_cloud_dir = Path(app.state.uploads_dir) / queued_cloud_id
    queued_cloud_dir.mkdir(parents=True, exist_ok=True)
    queued_cloud_path = queued_cloud_dir / "charlie.wav"
    queued_cloud_path.write_text("data", encoding="utf-8")
    insert_job(
        db_path,
        JobRecord(
            id=queued_cloud_id,
            filename="charlie.wav",
            status="queued",
            created_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            upload_path=str(queued_cloud_path),
            language="fr",
            requested_engine="cohere",
        ),
    )

    with TestClient(app) as client:
        response = client.get("/")

    assert response.status_code == 200
    assert "Queue #" not in response.text
    assert "items ahead" not in response.text
    assert 'data-started-at="' in response.text
    assert 'class="spinner spinner--status"' in response.text
    assert "data-elapsed-label" in response.text
    assert "Elapsed …" in response.text
    assert "1 ahead" in response.text
    assert "2 ahead" in response.text
    assert "Cohere cloud · EN" in response.text
    assert "Cohere cloud · FR" in response.text
    assert "job-icon" not in response.text
    assert "job-chip" not in response.text
    assert 'data-job-id="job-queued-local"' in response.text
    assert 'data-job-id="job-queued-cloud"' in response.text
