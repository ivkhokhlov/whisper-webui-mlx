from pathlib import Path

from fastapi.testclient import TestClient

from mlx_ui.app import app

client = TestClient(app)


def test_root_ok() -> None:
    response = client.get("/")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "Queue" in response.text
    assert "History" in response.text


def _cleanup_job_artifacts(jobs: list) -> None:
    for job in jobs:
        job_path = Path(job.upload_path)
        if job_path.is_file():
            job_path.unlink()
        job_dir = job_path.parent
        if job_dir.is_dir():
            try:
                job_dir.rmdir()
            except OSError:
                pass


def test_upload_multiple_files_creates_jobs_and_files() -> None:
    uploads_dir = Path(app.state.uploads_dir)
    data_dir = uploads_dir.parent
    had_uploads_dir = uploads_dir.exists()
    had_data_dir = data_dir.exists()
    app.state.jobs.clear()
    files = [
        ("files", ("alpha.txt", b"one", "text/plain")),
        ("files", ("beta.txt", b"two", "text/plain")),
    ]

    try:
        response = client.post("/upload", files=files)

        assert response.status_code == 200
        jobs = list(app.state.jobs)
        assert len(jobs) == 2
        for job in jobs:
            job_path = Path(job.upload_path)
            assert job_path.is_file()
            assert job_path.name == job.filename
            assert job_path.parent.name == job.id
            assert job_path.is_relative_to(uploads_dir)
            assert job.status == "queued"
    finally:
        _cleanup_job_artifacts(app.state.jobs)
        app.state.jobs.clear()
        if not had_uploads_dir:
            try:
                uploads_dir.rmdir()
            except OSError:
                pass
        if not had_data_dir:
            try:
                data_dir.rmdir()
            except OSError:
                pass
