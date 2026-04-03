import json
from pathlib import Path

from mlx_ui.db import init_db, list_jobs
from mlx_ui.engine_registry import FAKE_ENGINE
from mlx_ui.hot_folder import HotFolderPaths, HotFolderWatcher
from mlx_ui.worker import Worker


class SimpleTranscriber:
    engine_id = FAKE_ENGINE

    def __init__(self, content: str = "ok") -> None:
        self._content = content

    def transcribe(self, job, results_dir: Path) -> Path:  # type: ignore[no-untyped-def]
        job_dir = Path(results_dir) / job.id
        job_dir.mkdir(parents=True, exist_ok=True)
        result_path = job_dir / f"{Path(job.filename).stem}.txt"
        result_path.write_text(self._content, encoding="utf-8")
        return result_path


def _write_settings(tmp_path: Path, data: dict[str, object]) -> None:
    path = tmp_path / "data" / "settings.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


def test_hot_folder_moves_file_and_creates_job(tmp_path: Path) -> None:
    db_path = tmp_path / "data" / "jobs.db"
    uploads_dir = tmp_path / "data" / "uploads"
    init_db(db_path)

    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"
    input_dir.mkdir(parents=True, exist_ok=True)
    (input_dir / "hello.wav").write_text("data", encoding="utf-8")

    watcher = HotFolderWatcher(
        db_path=db_path,
        uploads_dir=uploads_dir,
        paths=HotFolderPaths(input_dir=input_dir, output_dir=output_dir),
        base_dir=tmp_path,
        settle_seconds=0.0,
        recursive=True,
    )

    assert watcher.scan_once() == 0
    assert watcher.scan_once() == 1

    jobs = list_jobs(db_path)
    assert len(jobs) == 1
    job = jobs[0]
    assert job.status == "queued"
    assert job.source_path is not None
    assert job.source_path.endswith("input/hello.wav")
    assert job.source_relpath == "hello.wav"
    assert Path(job.upload_path).is_file()
    assert not (input_dir / "hello.wav").exists()


def test_hot_folder_exports_transcript_on_success(tmp_path: Path) -> None:
    db_path = tmp_path / "data" / "jobs.db"
    uploads_dir = tmp_path / "data" / "uploads"
    results_dir = tmp_path / "data" / "results"
    init_db(db_path)

    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"
    nested_dir = input_dir / "nested"
    nested_dir.mkdir(parents=True, exist_ok=True)
    (nested_dir / "hello.wav").write_text("data", encoding="utf-8")

    _write_settings(tmp_path, {"hot_folder_output_dir": str(output_dir)})

    watcher = HotFolderWatcher(
        db_path=db_path,
        uploads_dir=uploads_dir,
        paths=HotFolderPaths(input_dir=input_dir, output_dir=output_dir),
        base_dir=tmp_path,
        settle_seconds=0.0,
        recursive=True,
    )
    watcher.scan_once()
    watcher.scan_once()

    worker = Worker(
        db_path=db_path,
        uploads_dir=uploads_dir,
        results_dir=results_dir,
        transcriber=SimpleTranscriber(content="hello"),
        base_dir=tmp_path,
    )
    assert worker.run_once() is True

    jobs = list_jobs(db_path)
    assert jobs[0].status == "done"
    exported = output_dir / "nested" / "hello.txt"
    assert exported.is_file()
    assert exported.read_text(encoding="utf-8") == "hello"


def test_hot_folder_restores_file_on_failure(tmp_path: Path) -> None:
    class FailingTranscriber:
        engine_id = FAKE_ENGINE

        def transcribe(self, job, results_dir: Path) -> Path:  # type: ignore[no-untyped-def]
            raise RuntimeError("boom")

    db_path = tmp_path / "data" / "jobs.db"
    uploads_dir = tmp_path / "data" / "uploads"
    results_dir = tmp_path / "data" / "results"
    init_db(db_path)

    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"
    input_dir.mkdir(parents=True, exist_ok=True)
    input_file = input_dir / "hello.wav"
    input_file.write_text("data", encoding="utf-8")

    watcher = HotFolderWatcher(
        db_path=db_path,
        uploads_dir=uploads_dir,
        paths=HotFolderPaths(input_dir=input_dir, output_dir=output_dir),
        base_dir=tmp_path,
        settle_seconds=0.0,
        recursive=True,
    )
    watcher.scan_once()
    watcher.scan_once()

    assert not input_file.exists()

    worker = Worker(
        db_path=db_path,
        uploads_dir=uploads_dir,
        results_dir=results_dir,
        transcriber=FailingTranscriber(),
        base_dir=tmp_path,
    )
    assert worker.run_once() is True

    jobs = list_jobs(db_path)
    assert jobs[0].status == "failed"
    assert input_file.is_file()
