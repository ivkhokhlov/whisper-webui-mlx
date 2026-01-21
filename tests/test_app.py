from datetime import datetime, timezone
from pathlib import Path

from fastapi.testclient import TestClient

from mlx_ui.app import app
from mlx_ui.db import JobRecord, init_db, insert_job, list_jobs


def _configure_app(tmp_path: Path) -> None:
    app.state.uploads_dir = tmp_path / "uploads"
    app.state.results_dir = tmp_path / "results"
    app.state.db_path = tmp_path / "jobs.db"
    app.state.worker_enabled = False


def test_root_ok(tmp_path: Path) -> None:
    _configure_app(tmp_path)
    with TestClient(app) as client:
        response = client.get("/")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "Queue" in response.text
    assert "History" in response.text


def test_upload_multiple_files_creates_jobs_and_files(tmp_path: Path) -> None:
    _configure_app(tmp_path)
    files = [
        ("files", ("alpha.txt", b"one", "text/plain")),
        ("files", ("beta.txt", b"two", "text/plain")),
    ]

    with TestClient(app) as client:
        response = client.post("/upload", files=files)

    assert response.status_code == 200
    jobs = list_jobs(Path(app.state.db_path))
    assert len(jobs) == 2
    uploads_dir = Path(app.state.uploads_dir)
    for job in jobs:
        job_path = Path(job.upload_path)
        assert job_path.is_file()
        assert job_path.name == job.filename
        assert job_path.parent.name == job.id
        assert job_path.is_relative_to(uploads_dir)
        assert job.status == "queued"


def test_jobs_persist_across_restart(tmp_path: Path) -> None:
    _configure_app(tmp_path)
    files = [("files", ("alpha.txt", b"one", "text/plain"))]

    with TestClient(app) as client:
        response = client.post("/upload", files=files)

    assert response.status_code == 200
    with TestClient(app) as client:
        response = client.get("/")

    assert response.status_code == 200
    jobs = list_jobs(Path(app.state.db_path))
    assert len(jobs) == 1
    assert "alpha.txt" in response.text


def test_history_lists_results_and_download_endpoint(tmp_path: Path) -> None:
    _configure_app(tmp_path)
    db_path = Path(app.state.db_path)
    init_db(db_path)

    job_id = "job-123"
    uploads_dir = Path(app.state.uploads_dir) / job_id
    uploads_dir.mkdir(parents=True, exist_ok=True)
    upload_path = uploads_dir / "alpha.txt"
    upload_path.write_text("data", encoding="utf-8")

    job = JobRecord(
        id=job_id,
        filename="alpha.txt",
        status="done",
        created_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        upload_path=str(upload_path),
    )
    insert_job(db_path, job)

    results_dir = Path(app.state.results_dir) / job_id
    results_dir.mkdir(parents=True, exist_ok=True)
    txt_path = results_dir / "alpha.txt"
    txt_path.write_text("transcript", encoding="utf-8")
    srt_path = results_dir / "alpha.srt"
    srt_path.write_text("subtitles", encoding="utf-8")

    with TestClient(app) as client:
        response = client.get("/")

        assert response.status_code == 200
        assert f"/results/{job_id}/alpha.txt" in response.text
        assert f"/results/{job_id}/alpha.srt" in response.text

        download = client.get(f"/results/{job_id}/alpha.txt")
        assert download.status_code == 200
        assert download.text == "transcript"
