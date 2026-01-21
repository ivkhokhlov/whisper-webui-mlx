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
