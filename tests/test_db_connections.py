from pathlib import Path
import sqlite3
import subprocess
import sys
import textwrap

import pytest

import mlx_ui.db as db


@pytest.mark.parametrize("failure", [None, "setup", "query", "body"])
def test_connection_closes_on_every_exit(tmp_path: Path, monkeypatch, failure) -> None:
    connect = sqlite3.connect
    opened: list[sqlite3.Connection] = []

    class Connection(sqlite3.Connection):
        def execute(self, sql, *args, **kwargs):  # type: ignore[no-untyped-def]
            if failure == "setup" and sql.startswith("PRAGMA"):
                raise sqlite3.OperationalError("setup failed")
            return super().execute(sql, *args, **kwargs)

    def tracked_connect(*args, **kwargs):  # type: ignore[no-untyped-def]
        connection = connect(*args, **kwargs, factory=Connection)
        opened.append(connection)
        return connection

    monkeypatch.setattr(db.sqlite3, "connect", tracked_connect)

    def operation() -> None:
        with db._connect(tmp_path / "jobs.db") as connection:
            if failure == "query":
                connection.execute("SELECT * FROM missing_table")
            if failure == "body":
                raise RuntimeError("body failed")
            assert connection.execute("SELECT 1").fetchone()[0] == 1

    if failure is None:
        operation()
    else:
        with pytest.raises((sqlite3.OperationalError, RuntimeError)):
            operation()
    assert len(opened) == 1
    with pytest.raises(sqlite3.ProgrammingError, match="closed"):
        opened[0].execute("SELECT 1")


def test_connection_commits_and_rolls_back(tmp_path: Path) -> None:
    path = tmp_path / "transactions.db"
    with db._connect(path) as connection:
        connection.execute("CREATE TABLE sample (value TEXT)")
        connection.execute("INSERT INTO sample VALUES ('committed')")

    with pytest.raises(RuntimeError):
        with db._connect(path) as connection:
            connection.execute("INSERT INTO sample VALUES ('rolled back')")
            raise RuntimeError("abort transaction")

    with db._connect(path) as connection:
        assert [row[0] for row in connection.execute("SELECT value FROM sample")] == [
            "committed"
        ]


def test_database_operations_do_not_exhaust_descriptors_without_gc(tmp_path: Path):
    pytest.importorskip("resource")
    script = textwrap.dedent(
        """
        import gc
        from pathlib import Path
        import resource
        import sys
        from mlx_ui import db

        path = Path(sys.argv[1])
        db.init_db(path)
        db.insert_job(path, db.JobRecord(
            id='job', filename='sample.wav', status='queued',
            created_at='2026-01-01T00:00:00+00:00',
            upload_path='/unused/sample.wav', language='auto',
        ))
        _, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
        resource.setrlimit(resource.RLIMIT_NOFILE, (min(128, hard), hard))
        gc.collect()
        gc.disable()
        for _ in range(2000):
            assert db.get_job(path, 'job').status == 'queued'
            assert len(db.list_active_jobs(path)) == 1
            db.update_job_status(path, 'job', 'queued')
        print('6000 operations completed')
        """
    )
    result = subprocess.run(
        [sys.executable, "-c", script, str(tmp_path / "jobs.db")],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "6000 operations completed" in result.stdout
