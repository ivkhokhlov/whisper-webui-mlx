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


def test_browser_history_rows_use_lighter_summary_and_single_primary_action(
    tmp_path: Path,
) -> None:
    _configure_app(tmp_path)
    db_path = Path(app.state.db_path)
    init_db(db_path)

    done_id = "job-done-row"
    done_dir = Path(app.state.uploads_dir) / done_id
    done_dir.mkdir(parents=True, exist_ok=True)
    done_path = done_dir / "meeting.wav"
    done_path.write_text("data", encoding="utf-8")
    completed_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    insert_job(
        db_path,
        JobRecord(
            id=done_id,
            filename="meeting.wav",
            status="done",
            created_at=completed_at,
            completed_at=completed_at,
            upload_path=str(done_path),
            language="fr",
            requested_engine="cohere",
        ),
    )
    done_results_dir = Path(app.state.results_dir) / done_id
    done_results_dir.mkdir(parents=True, exist_ok=True)
    (done_results_dir / "meeting.txt").write_text("transcript", encoding="utf-8")
    (done_results_dir / "meeting.srt").write_text("subtitles", encoding="utf-8")

    failed_id = "job-failed-row"
    failed_dir = Path(app.state.uploads_dir) / failed_id
    failed_dir.mkdir(parents=True, exist_ok=True)
    failed_path = failed_dir / "broken.wav"
    failed_path.write_text("data", encoding="utf-8")
    insert_job(
        db_path,
        JobRecord(
            id=failed_id,
            filename="broken.wav",
            status="failed",
            created_at=completed_at,
            completed_at=completed_at,
            upload_path=str(failed_path),
            language="auto",
            error_message="Decoder crashed on frame 1\nfull stack trace",
        ),
    )

    with TestClient(app) as client:
        response = client.get("/api/browser/history")

    assert response.status_code == 200
    payload = response.json()
    items = {item["id"]: item for item in payload["items"]}
    done_job = items[done_id]
    failed_job = items[failed_id]

    assert done_job["status"] == "done"
    assert failed_job["status"] == "failed"
    assert done_job["results"] == ["meeting.srt", "meeting.txt"]
    assert failed_job["error_message"].startswith("Decoder crashed on frame 1")
    assert done_job["ui"]["language"]["label"] == "French"


def test_browser_history_exposes_secondary_metadata_on_demand(
    tmp_path: Path,
) -> None:
    _configure_app(tmp_path)
    db_path = Path(app.state.db_path)
    init_db(db_path)

    done_id = "job-done-details"
    done_dir = Path(app.state.uploads_dir) / done_id
    done_dir.mkdir(parents=True, exist_ok=True)
    done_path = done_dir / "customer-call.wav"
    done_path.write_text("data", encoding="utf-8")
    completed_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    insert_job(
        db_path,
        JobRecord(
            id=done_id,
            filename="customer-call.wav",
            status="done",
            created_at=completed_at,
            started_at=completed_at,
            completed_at=completed_at,
            upload_path=str(done_path),
            language="fr",
            requested_engine="cohere",
            effective_engine="whisper_cpu",
            effective_implementation_id="whisper",
        ),
    )
    done_results_dir = Path(app.state.results_dir) / done_id
    done_results_dir.mkdir(parents=True, exist_ok=True)
    (done_results_dir / "customer-call.txt").write_text("transcript", encoding="utf-8")
    (done_results_dir / "customer-call.srt").write_text("subtitles", encoding="utf-8")

    failed_id = "job-failed-details"
    failed_dir = Path(app.state.uploads_dir) / failed_id
    failed_dir.mkdir(parents=True, exist_ok=True)
    failed_path = failed_dir / "decoder.mp4"
    failed_path.write_text("data", encoding="utf-8")
    insert_job(
        db_path,
        JobRecord(
            id=failed_id,
            filename="decoder.mp4",
            status="failed",
            created_at=completed_at,
            started_at=completed_at,
            completed_at=completed_at,
            upload_path=str(failed_path),
            language="en",
            requested_engine="cohere",
            error_message="Decoder crashed on frame 1\nfull stack trace",
        ),
    )

    with TestClient(app) as client:
        response = client.get("/api/browser/history")

    assert response.status_code == 200
    payload = response.json()
    items = {item["id"]: item for item in payload["items"]}
    done_job = items[done_id]
    failed_job = items[failed_id]

    assert done_job["ui"]["engine_summary"] == (
        "Requested Cohere · cloud, used Whisper (CPU) · local"
    )
    assert done_job["ui"]["language"]["label"] == "French"
    assert done_job["ui"]["effective_implementation"]["id"] == "whisper"
    assert done_job["results"] == ["customer-call.srt", "customer-call.txt"]
    assert failed_job["error_message"].startswith("Decoder crashed on frame 1")
