from datetime import datetime, timezone
from pathlib import Path
import sqlite3

from mlx_ui.db import JobRecord, init_db, insert_job, list_jobs, recover_running_jobs


def test_init_db_adds_missing_columns(tmp_path: Path) -> None:
    db_path = tmp_path / "jobs.db"
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            """
            CREATE TABLE jobs (
                id TEXT PRIMARY KEY,
                filename TEXT NOT NULL,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                upload_path TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            INSERT INTO jobs (id, filename, status, created_at, upload_path)
            VALUES ('job-1', 'alpha.wav', 'queued', '2024-01-01T00:00:00Z', 'x')
            """
        )
        connection.commit()

    init_db(db_path)

    with sqlite3.connect(db_path) as connection:
        columns = {
            row[1] for row in connection.execute("PRAGMA table_info(jobs)").fetchall()
        }
        assert "language" in columns
        assert "started_at" in columns
        assert "completed_at" in columns
        assert "error_message" in columns
        row = connection.execute("SELECT language FROM jobs WHERE id = 'job-1'").fetchone()
        assert row is not None
        assert row[0] == "en"


def test_recover_running_jobs_marks_failed(tmp_path: Path) -> None:
    db_path = tmp_path / "jobs.db"
    init_db(db_path)

    started_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    job = JobRecord(
        id="job-1",
        filename="alpha.wav",
        status="running",
        created_at=started_at,
        upload_path="x",
        language="en",
        started_at=started_at,
    )
    insert_job(db_path, job)

    recovered = recover_running_jobs(db_path)

    assert recovered == 1
    jobs = list_jobs(db_path)
    assert len(jobs) == 1
    recovered_job = jobs[0]
    assert recovered_job.status == "failed"
    assert recovered_job.completed_at is not None
    assert recovered_job.error_message == "Recovered after crash"
