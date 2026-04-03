from __future__ import annotations

import logging
import os
from pathlib import Path
import subprocess
import sys
import threading

from mlx_ui.db import JobRecord
from mlx_ui.engine_registry import WHISPER_MLX_ENGINE
from mlx_ui.engines.common import (
    normalize_requested_output_formats,
    parse_bool_env,
    tail_text,
    write_transcript_result,
)
from mlx_ui.transcript_result import TranscriptResult

logger = logging.getLogger(__name__)


class WtmTranscriber:
    engine_id = WHISPER_MLX_ENGINE

    def __init__(
        self,
        wtm_path: str | None = None,
        quick: bool | None = None,
        output_formats: tuple[str, ...] | None = None,
    ) -> None:
        self.wtm_path = _resolve_wtm_path(wtm_path)
        self.quick = quick if quick is not None else parse_bool_env("WTM_QUICK", False)
        self.output_formats = normalize_requested_output_formats(output_formats)
        self._process_lock = threading.Lock()
        self._current_process: subprocess.Popen[str] | None = None
        self._current_job_id: str | None = None

    def transcribe(self, job: JobRecord, results_dir: Path) -> Path:
        results_dir = Path(results_dir)
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
            process = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            self._set_current_process(process, job.id)
            stdout, stderr = process.communicate()
        except FileNotFoundError as exc:
            raise RuntimeError(
                f"wtm backend selected but '{self.wtm_path}' could not be executed. "
                "Install whisper-turbo-mlx or set WTM_PATH to a working binary."
            ) from exc
        finally:
            self._clear_current_process(job.id)
        if process.returncode != 0:
            error = subprocess.CalledProcessError(
                process.returncode,
                command,
                output=stdout,
                stderr=stderr,
            )
            message = _format_wtm_error(error)
            raise RuntimeError(message) from error
        transcript = TranscriptResult(
            text=(stdout or "").strip(),
            engine_id=self.engine_id,
            language=job.language,
        )
        return write_transcript_result(
            result=transcript,
            results_dir=results_dir,
            job_id=job.id,
            source_name=job.filename,
            output_formats=self.output_formats,
        )

    def cancel(self, job_id: str | None = None) -> bool:
        with self._process_lock:
            process = self._current_process
            current_job_id = self._current_job_id
        if process is None:
            return False
        if job_id and current_job_id and job_id != current_job_id:
            return False
        if process.poll() is not None:
            return False
        process.terminate()
        return True

    def _set_current_process(
        self,
        process: subprocess.Popen[str],
        job_id: str,
    ) -> None:
        with self._process_lock:
            self._current_process = process
            self._current_job_id = job_id

    def _clear_current_process(self, job_id: str) -> None:
        with self._process_lock:
            if self._current_job_id != job_id:
                return
            self._current_process = None
            self._current_job_id = None


def _format_wtm_error(error: subprocess.CalledProcessError) -> str:
    stdout = tail_text(error.stdout)
    stderr = tail_text(error.stderr)
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
