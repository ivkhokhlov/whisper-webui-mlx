from dataclasses import dataclass
from pathlib import Path
import sqlite3


@dataclass
class JobRecord:
    id: str
    filename: str
    status: str
    created_at: str
    upload_path: str


SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    filename TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    upload_path TEXT NOT NULL
);
"""


def _connect(db_path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    return connection


def init_db(db_path: Path) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with _connect(db_path) as connection:
        connection.execute(SCHEMA)
        connection.commit()


def insert_job(db_path: Path, job: JobRecord) -> None:
    with _connect(db_path) as connection:
        connection.execute(
            """
            INSERT INTO jobs (id, filename, status, created_at, upload_path)
            VALUES (?, ?, ?, ?, ?)
            """,
            (job.id, job.filename, job.status, job.created_at, job.upload_path),
        )
        connection.commit()


def list_jobs(db_path: Path) -> list[JobRecord]:
    with _connect(db_path) as connection:
        rows = connection.execute(
            """
            SELECT id, filename, status, created_at, upload_path
            FROM jobs
            ORDER BY created_at ASC
            """
        ).fetchall()

    return [JobRecord(**dict(row)) for row in rows]


def update_job_status(db_path: Path, job_id: str, status: str) -> None:
    with _connect(db_path) as connection:
        connection.execute(
            """
            UPDATE jobs
            SET status = ?
            WHERE id = ?
            """,
            (status, job_id),
        )
        connection.commit()


def claim_next_job(db_path: Path) -> JobRecord | None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(db_path, isolation_level=None)
    connection.row_factory = sqlite3.Row
    try:
        connection.execute("BEGIN IMMEDIATE")
        row = connection.execute(
            """
            SELECT id, filename, status, created_at, upload_path
            FROM jobs
            WHERE status = 'queued'
            ORDER BY created_at ASC
            LIMIT 1
            """
        ).fetchone()
        if row is None:
            connection.execute("COMMIT")
            return None
        job_id = row["id"]
        connection.execute(
            """
            UPDATE jobs
            SET status = 'running'
            WHERE id = ?
            """,
            (job_id,),
        )
        connection.execute("COMMIT")
        job_data = dict(row)
        job_data["status"] = "running"
        return JobRecord(**job_data)
    except Exception:
        connection.execute("ROLLBACK")
        raise
    finally:
        connection.close()
