import logging
import os
from pathlib import Path
import subprocess
import sys
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
        quick: bool | None = None,
    ) -> None:
        self.wtm_path = _resolve_wtm_path(wtm_path)
        self.quick = (
            quick if quick is not None else _parse_bool_env("WTM_QUICK", default=False)
        )

    def transcribe(self, job: JobRecord, results_dir: Path) -> Path:
        results_dir = Path(results_dir)
        results_dir.mkdir(parents=True, exist_ok=True)
        job_dir = results_dir / job.id
        job_dir.mkdir(parents=True, exist_ok=True)
        source_path = Path(job.upload_path)
        command = [
            self.wtm_path,
            "--path_audio",
            str(source_path),
            "--any_lang=True",
            f"--quick={'True' if self.quick else 'False'}",
        ]
        logger.info("Running wtm for job %s", job.id)
        try:
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                check=True,
            )
        except subprocess.CalledProcessError as exc:
            message = _format_wtm_error(exc)
            raise RuntimeError(message) from exc
        transcript = (result.stdout or "").strip()
        result_path = job_dir / "result.txt"
        result_path.write_text(transcript + ("\n" if transcript else ""), encoding="utf-8")
        return result_path


def _format_wtm_error(error: subprocess.CalledProcessError) -> str:
    stdout = _tail_text(error.stdout)
    stderr = _tail_text(error.stderr)
    message = f"wtm failed with exit code {error.returncode}"
    if stderr:
        message = f"{message}; stderr: {stderr}"
    if stdout:
        message = f"{message}; stdout: {stdout}"
    return message


def _resolve_wtm_path(explicit: str | None) -> str:
    if explicit:
        return explicit
    env_path = os.getenv("WTM_PATH")
    if env_path:
        return env_path
    candidate = Path(sys.executable).resolve().parent / "wtm"
    if candidate.exists():
        return str(candidate)
    return "wtm"


def _parse_bool_env(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    return default


def _tail_text(text: str | None, limit: int = 2000) -> str:
    if not text:
        return ""
    trimmed = text.strip()
    if len(trimmed) <= limit:
        return trimmed
    return trimmed[-limit:]
