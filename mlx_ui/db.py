from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import sqlite3

from mlx_ui.languages import AUTO_LANGUAGE, LEGACY_AUTO_LANGUAGE, normalize_language


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
    queue_position: int | None = None
    requested_engine: str | None = None
    effective_engine: str | None = None


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
    error_message TEXT,
    queue_position INTEGER,
    requested_engine TEXT,
    effective_engine TEXT
);
"""


def _connect(db_path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    return connection


def _job_record_from_data(job_data: dict[str, object]) -> JobRecord:
    if job_data.get("status") == "reserved":
        job_data["status"] = "running"
    job_data["language"] = normalize_language(job_data.get("language"))
    return JobRecord(**job_data)


def _job_record_from_row(row: sqlite3.Row) -> JobRecord:
    return _job_record_from_data(dict(row))


def init_db(db_path: Path) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with _connect(db_path) as connection:
        connection.execute(SCHEMA)
        _migrate_schema(connection)
        connection.commit()


def _migrate_schema(connection: sqlite3.Connection) -> None:
    if not _table_has_column(connection, "jobs", "language"):
        connection.execute(
            f"ALTER TABLE jobs ADD COLUMN language TEXT NOT NULL DEFAULT '{AUTO_LANGUAGE}'"
        )
    if not _table_has_column(connection, "jobs", "started_at"):
        connection.execute("ALTER TABLE jobs ADD COLUMN started_at TEXT")
    if not _table_has_column(connection, "jobs", "completed_at"):
        connection.execute("ALTER TABLE jobs ADD COLUMN completed_at TEXT")
    if not _table_has_column(connection, "jobs", "error_message"):
        connection.execute("ALTER TABLE jobs ADD COLUMN error_message TEXT")
    if not _table_has_column(connection, "jobs", "queue_position"):
        connection.execute("ALTER TABLE jobs ADD COLUMN queue_position INTEGER")
    if not _table_has_column(connection, "jobs", "requested_engine"):
        connection.execute("ALTER TABLE jobs ADD COLUMN requested_engine TEXT")
    if not _table_has_column(connection, "jobs", "effective_engine"):
        connection.execute("ALTER TABLE jobs ADD COLUMN effective_engine TEXT")
    connection.execute(
        """
        UPDATE jobs
        SET language = ?
        WHERE language IS NULL
           OR TRIM(language) = ''
           OR LOWER(TRIM(language)) = ?
        """,
        (AUTO_LANGUAGE, LEGACY_AUTO_LANGUAGE),
    )
    _backfill_queue_positions(connection)


def _table_has_column(
    connection: sqlite3.Connection,
    table_name: str,
    column_name: str,
) -> bool:
    rows = connection.execute(f"PRAGMA table_info({table_name})").fetchall()
    for row in rows:
        name = row["name"] if isinstance(row, sqlite3.Row) else row[1]
        if name == column_name:
            return True
    return False


def _backfill_queue_positions(connection: sqlite3.Connection) -> None:
    rows = connection.execute(
        """
        SELECT id
        FROM jobs
        WHERE status = 'queued' AND queue_position IS NULL
        ORDER BY created_at ASC
        """
    ).fetchall()
    if not rows:
        return
    max_row = connection.execute(
        """
        SELECT MAX(queue_position)
        FROM jobs
        WHERE status = 'queued'
        """
    ).fetchone()
    start = max_row[0] if max_row and max_row[0] is not None else 0
    for offset, row in enumerate(rows, start=1):
        connection.execute(
            "UPDATE jobs SET queue_position = ? WHERE id = ?",
            (start + offset, row["id"]),
        )


def insert_job(db_path: Path, job: JobRecord) -> None:
    with _connect(db_path) as connection:
        queue_position = job.queue_position
        language = normalize_language(job.language)
        if job.status == "queued" and queue_position is None:
            row = connection.execute(
                """
                SELECT MAX(queue_position)
                FROM jobs
                WHERE status = 'queued'
                """
            ).fetchone()
            max_position = row[0] if row and row[0] is not None else 0
            queue_position = max_position + 1
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
                error_message,
                queue_position,
                requested_engine,
                effective_engine
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                job.id,
                job.filename,
                job.status,
                job.created_at,
                job.upload_path,
                language,
                job.started_at,
                job.completed_at,
                job.error_message,
                queue_position,
                job.requested_engine,
                job.effective_engine,
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
                error_message,
                queue_position,
                requested_engine,
                effective_engine
            FROM jobs
            ORDER BY
                CASE
                    WHEN status IN ('running', 'reserved') THEN 0
                    WHEN status = 'queued' THEN 1
                    ELSE 2
                END,
                CASE
                    WHEN status = 'queued' THEN queue_position IS NULL
                    ELSE 0
                END,
                CASE
                    WHEN status = 'queued' THEN queue_position
                    ELSE NULL
                END,
                created_at ASC
            """
        ).fetchall()

    return [_job_record_from_row(row) for row in rows]


def get_job(db_path: Path, job_id: str) -> JobRecord | None:
    with _connect(db_path) as connection:
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
                error_message,
                queue_position,
                requested_engine,
                effective_engine
            FROM jobs
            WHERE id = ?
            """,
            (job_id,),
        ).fetchone()
    if row is None:
        return None
    return _job_record_from_row(row)


def delete_queued_job(db_path: Path, job_id: str) -> bool:
    with _connect(db_path) as connection:
        cursor = connection.execute(
            """
            DELETE FROM jobs
            WHERE id = ? AND status = 'queued'
            """,
            (job_id,),
        )
        connection.commit()
    return cursor.rowcount > 0


def delete_history_job(db_path: Path, job_id: str) -> bool:
    with _connect(db_path) as connection:
        cursor = connection.execute(
            """
            DELETE FROM jobs
            WHERE id = ? AND status IN ('done', 'failed')
            """,
            (job_id,),
        )
        connection.commit()
    return cursor.rowcount > 0


def list_history_jobs(db_path: Path) -> list[JobRecord]:
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
                error_message,
                queue_position,
                requested_engine,
                effective_engine
            FROM jobs
            WHERE status IN ('done', 'failed')
            """
        ).fetchall()
    return [_job_record_from_row(row) for row in rows]


def delete_history_jobs(db_path: Path, job_ids: list[str]) -> int:
    if not job_ids:
        return 0
    placeholders = ", ".join("?" for _ in job_ids)
    with _connect(db_path) as connection:
        cursor = connection.execute(
            f"""
            DELETE FROM jobs
            WHERE status IN ('done', 'failed')
              AND id IN ({placeholders})
            """,
            job_ids,
        )
        connection.commit()
    return cursor.rowcount


def reorder_queue(db_path: Path, job_ids: list[str]) -> bool:
    if not job_ids:
        with _connect(db_path) as connection:
            row = connection.execute(
                "SELECT COUNT(*) FROM jobs WHERE status = 'queued'"
            ).fetchone()
            queued_count = row[0] if row else 0
        return queued_count == 0
    if len(set(job_ids)) != len(job_ids):
        return False
    with _connect(db_path) as connection:
        queued_rows = connection.execute(
            """
            SELECT id
            FROM jobs
            WHERE status = 'queued'
            """
        ).fetchall()
        queued_ids = [row["id"] for row in queued_rows]
        if len(queued_ids) != len(job_ids):
            return False
        if set(queued_ids) != set(job_ids):
            return False
        for index, job_id in enumerate(job_ids, start=1):
            connection.execute(
                "UPDATE jobs SET queue_position = ? WHERE id = ?",
                (index, job_id),
            )
        connection.commit()
    return True


def cancel_running_job(db_path: Path, job_id: str) -> bool:
    completed_at = _now_utc()
    with _connect(db_path) as connection:
        cursor = connection.execute(
            """
            UPDATE jobs
            SET status = 'cancelled',
                completed_at = ?
            WHERE id = ? AND status IN ('running', 'reserved')
            """,
            (completed_at, job_id),
        )
        connection.commit()
    return cursor.rowcount > 0


def update_job_status(
    db_path: Path,
    job_id: str,
    status: str,
    *,
    started_at: str | None = None,
    completed_at: str | None = None,
    error_message: str | None = None,
    effective_engine: str | None = None,
) -> None:
    updates: dict[str, str | None] = {"status": status}
    if started_at is not None:
        updates["started_at"] = started_at
    if completed_at is not None:
        updates["completed_at"] = completed_at
    if error_message is not None:
        updates["error_message"] = error_message
    if effective_engine is not None:
        updates["effective_engine"] = effective_engine
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


def recover_running_jobs(
    db_path: Path,
    *,
    error_message: str = "Recovered after crash",
) -> int:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    completed_at = _now_utc()
    with _connect(db_path) as connection:
        cursor = connection.execute(
            """
            UPDATE jobs
            SET status = 'failed',
                completed_at = ?,
                error_message = CASE
                    WHEN error_message IS NULL OR error_message = '' THEN ?
                    ELSE error_message
                END
            WHERE status IN ('running', 'reserved')
            """,
            (completed_at, error_message),
        )
        connection.commit()
    return cursor.rowcount


def mark_job_running(
    db_path: Path,
    job_id: str,
    *,
    started_at: str | None = None,
    effective_engine: str | None = None,
) -> bool:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    started_at_value = started_at or _now_utc()
    with _connect(db_path) as connection:
        cursor = connection.execute(
            """
            UPDATE jobs
            SET status = 'running',
                started_at = ?,
                effective_engine = ?
            WHERE id = ? AND status = 'reserved'
            """,
            (started_at_value, effective_engine, job_id),
        )
        connection.commit()
    return cursor.rowcount > 0


def mark_job_done(
    db_path: Path,
    job_id: str,
    *,
    completed_at: str | None = None,
) -> bool:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    completed_at_value = completed_at or _now_utc()
    with _connect(db_path) as connection:
        cursor = connection.execute(
            """
            UPDATE jobs
            SET status = 'done',
                completed_at = ?
            WHERE id = ? AND status = 'running'
            """,
            (completed_at_value, job_id),
        )
        connection.commit()
    return cursor.rowcount > 0


def mark_job_failed(
    db_path: Path,
    job_id: str,
    *,
    completed_at: str | None = None,
    error_message: str | None = None,
) -> bool:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    completed_at_value = completed_at or _now_utc()
    with _connect(db_path) as connection:
        cursor = connection.execute(
            """
            UPDATE jobs
            SET status = 'failed',
                completed_at = ?,
                error_message = ?
            WHERE id = ? AND status IN ('running', 'reserved')
            """,
            (completed_at_value, error_message, job_id),
        )
        connection.commit()
    return cursor.rowcount > 0


def claim_next_job(
    db_path: Path,
    *,
    effective_engine: str | None = None,
) -> JobRecord | None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(db_path, isolation_level=None)
    connection.row_factory = sqlite3.Row
    try:
        connection.execute("BEGIN IMMEDIATE")
        running = connection.execute(
            """
            SELECT id
            FROM jobs
            WHERE status IN ('running', 'reserved')
            LIMIT 1
            """
        ).fetchone()
        if running is not None:
            connection.execute("COMMIT")
            return None
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
                error_message,
                queue_position,
                requested_engine,
                effective_engine
            FROM jobs
            WHERE status = 'queued'
            ORDER BY
                queue_position IS NULL,
                queue_position ASC,
                created_at ASC
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
            SET status = 'reserved'
            WHERE id = ?
            """,
            (job_id,),
        )
        connection.execute("COMMIT")
        job_data = dict(row)
        job_data["status"] = "reserved"
        return _job_record_from_data(job_data)
    except Exception:
        connection.execute("ROLLBACK")
        raise
    finally:
        connection.close()


def _now_utc() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
