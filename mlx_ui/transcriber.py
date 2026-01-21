import logging
import os
from pathlib import Path
import subprocess
from typing import Protocol

from mlx_ui.db import JobRecord

logger = logging.getLogger(__name__)


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


class WtmTranscriber:
    def __init__(
        self,
        wtm_path: str | None = None,
        language: str | None = None,
    ) -> None:
        self.wtm_path = wtm_path or os.getenv("WTM_PATH") or "wtm"
        self.language = (language or os.getenv("WTM_LANGUAGE") or "en").strip() or "en"

    def transcribe(self, job: JobRecord, results_dir: Path) -> Path:
        results_dir = Path(results_dir)
        results_dir.mkdir(parents=True, exist_ok=True)
        job_dir = results_dir / job.id
        job_dir.mkdir(parents=True, exist_ok=True)
        source_path = Path(job.upload_path)
        language = getattr(job, "language", None) or self.language
        command = [
            self.wtm_path,
            str(source_path),
            "--language",
            language,
            "--output_dir",
            str(job_dir),
        ]
        logger.info("Running wtm for job %s", job.id)
        try:
            subprocess.run(
                command,
                capture_output=True,
                text=True,
                check=True,
            )
        except subprocess.CalledProcessError as exc:
            message = _format_wtm_error(exc)
            raise RuntimeError(message) from exc

        txt_results = sorted(job_dir.glob("*.txt"))
        if not txt_results:
            raise FileNotFoundError(
                f"wtm completed but no .txt output found in {job_dir}"
            )
        return txt_results[0]


def _format_wtm_error(error: subprocess.CalledProcessError) -> str:
    stdout = _tail_text(error.stdout)
    stderr = _tail_text(error.stderr)
    message = f"wtm failed with exit code {error.returncode}"
    if stderr:
        message = f"{message}; stderr: {stderr}"
    if stdout:
        message = f"{message}; stdout: {stdout}"
    return message


def _tail_text(text: str | None, limit: int = 2000) -> str:
    if not text:
        return ""
    trimmed = text.strip()
    if len(trimmed) <= limit:
        return trimmed
    return trimmed[-limit:]
