from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import sqlite3


@dataclass
class JobRecord:
    id: str
    filename: str
    status: str
    created_at: str
    upload_path: str
    language: str
    started_at: str | None = None
    completed_at: str | None = None
    error_message: str | None = None


SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    filename TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    upload_path TEXT NOT NULL,
    language TEXT NOT NULL,
    started_at TEXT,
    completed_at TEXT,
    error_message TEXT
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
        _migrate_schema(connection)
        connection.commit()


def _migrate_schema(connection: sqlite3.Connection) -> None:
    columns = {
        row["name"] for row in connection.execute("PRAGMA table_info(jobs)").fetchall()
    }
    if "language" not in columns:
        connection.execute(
            "ALTER TABLE jobs ADD COLUMN language TEXT NOT NULL DEFAULT 'en'"
        )
    if "started_at" not in columns:
        connection.execute("ALTER TABLE jobs ADD COLUMN started_at TEXT")
    if "completed_at" not in columns:
        connection.execute("ALTER TABLE jobs ADD COLUMN completed_at TEXT")
    if "error_message" not in columns:
        connection.execute("ALTER TABLE jobs ADD COLUMN error_message TEXT")
    connection.execute(
        "UPDATE jobs SET language = 'en' WHERE language IS NULL OR language = ''"
    )


def insert_job(db_path: Path, job: JobRecord) -> None:
    with _connect(db_path) as connection:
        connection.execute(
            """
            INSERT INTO jobs (
                id,
                filename,
                status,
                created_at,
                upload_path,
                language,
                started_at,
                completed_at,
                error_message
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                job.id,
                job.filename,
                job.status,
                job.created_at,
                job.upload_path,
                job.language,
                job.started_at,
                job.completed_at,
                job.error_message,
            ),
        )
        connection.commit()


def list_jobs(db_path: Path) -> list[JobRecord]:
    with _connect(db_path) as connection:
        rows = connection.execute(
            """
            SELECT
                id,
                filename,
                status,
                created_at,
                upload_path,
                language,
                started_at,
                completed_at,
                error_message
            FROM jobs
            ORDER BY created_at ASC
            """
        ).fetchall()

    return [JobRecord(**dict(row)) for row in rows]


def update_job_status(
    db_path: Path,
    job_id: str,
    status: str,
    *,
    started_at: str | None = None,
    completed_at: str | None = None,
    error_message: str | None = None,
) -> None:
    updates: dict[str, str | None] = {"status": status}
    if started_at is not None:
        updates["started_at"] = started_at
    if completed_at is not None:
        updates["completed_at"] = completed_at
    if error_message is not None:
        updates["error_message"] = error_message
    set_clause = ", ".join(f"{column} = ?" for column in updates)
    values = list(updates.values()) + [job_id]
    with _connect(db_path) as connection:
        connection.execute(
            f"""
            UPDATE jobs
            SET {set_clause}
            WHERE id = ?
            """,
            values,
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
            SELECT
                id,
                filename,
                status,
                created_at,
                upload_path,
                language,
                started_at,
                completed_at,
                error_message
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
        started_at = _now_utc()
        connection.execute(
            """
            UPDATE jobs
            SET status = 'running', started_at = ?
            WHERE id = ?
            """,
            (started_at, job_id),
        )
        connection.execute("COMMIT")
        job_data = dict(row)
        job_data["status"] = "running"
        job_data["started_at"] = started_at
        return JobRecord(**job_data)
    except Exception:
        connection.execute("ROLLBACK")
        raise
    finally:
        connection.close()


def _now_utc() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
