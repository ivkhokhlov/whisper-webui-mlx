from pathlib import Path

from fastapi.testclient import TestClient

from mlx_ui.app import app
from mlx_ui.db import list_jobs


def _configure_app(tmp_path: Path) -> None:
    app.state.uploads_dir = tmp_path / "uploads"
    app.state.db_path = tmp_path / "jobs.db"


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
