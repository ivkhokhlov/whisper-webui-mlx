from __future__ import annotations

import logging
import os
from pathlib import Path
import subprocess
import sys

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
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                check=True,
            )
        except FileNotFoundError as exc:
            raise RuntimeError(
                f"wtm backend selected but '{self.wtm_path}' could not be executed. "
                "Install whisper-turbo-mlx or set WTM_PATH to a working binary."
            ) from exc
        except subprocess.CalledProcessError as exc:
            message = _format_wtm_error(exc)
            raise RuntimeError(message) from exc
        transcript = TranscriptResult(
            text=(result.stdout or "").strip(),
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
