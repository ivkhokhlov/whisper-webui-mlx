from pathlib import Path
from typing import Protocol

from mlx_ui.db import JobRecord


class Transcriber(Protocol):
    def transcribe(self, job: JobRecord, results_dir: Path) -> Path:
        raise NotImplementedError


class FakeTranscriber:
    def transcribe(self, job: JobRecord, results_dir: Path) -> Path:
        results_dir = Path(results_dir)
        job_dir = results_dir / job.id
        job_dir.mkdir(parents=True, exist_ok=True)
        result_path = job_dir / "result.txt"
        content = f"Fake transcript for {job.filename} ({job.id})\n"
        result_path.write_text(content, encoding="utf-8")
        return result_path
