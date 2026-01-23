import logging
import os
from pathlib import Path
import subprocess
import sys
from typing import Protocol

from mlx_ui.db import JobRecord

logger = logging.getLogger(__name__)

BACKEND_ENV = "TRANSCRIBER_BACKEND"
DEFAULT_BACKEND = "wtm"
WHISPER_MODEL_ENV = "WHISPER_MODEL"
WHISPER_DEVICE_ENV = "WHISPER_DEVICE"
WHISPER_FP16_ENV = "WHISPER_FP16"
WHISPER_CACHE_DIR_ENV = "WHISPER_CACHE_DIR"
DEFAULT_WHISPER_MODEL = "small"


class Transcriber(Protocol):
    def transcribe(self, job: JobRecord, results_dir: Path) -> Path:
        raise NotImplementedError


class FakeTranscriber:
    def transcribe(self, job: JobRecord, results_dir: Path) -> Path:
        results_dir = Path(results_dir)
        job_dir = results_dir / job.id
        job_dir.mkdir(parents=True, exist_ok=True)
        result_path = job_dir / _result_filename(job.filename)
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
        result_path = job_dir / _result_filename(job.filename)
        result_path.write_text(
            transcript + ("\n" if transcript else ""),
            encoding="utf-8",
        )
        return result_path


class WhisperTranscriber:
    def __init__(
        self,
        model_name: str | None = None,
        device: str | None = None,
        fp16: bool | None = None,
    ) -> None:
        self.model_name = model_name or os.getenv(
            WHISPER_MODEL_ENV,
            DEFAULT_WHISPER_MODEL,
        )
        self.device = device or os.getenv(WHISPER_DEVICE_ENV, "cpu")
        self.fp16 = fp16 if fp16 is not None else _parse_bool_env(
            WHISPER_FP16_ENV,
            False,
        )
        self.cache_dir = _resolve_whisper_cache_dir()
        self._model = None
        self._whisper = None

    def transcribe(self, job: JobRecord, results_dir: Path) -> Path:
        results_dir = Path(results_dir)
        results_dir.mkdir(parents=True, exist_ok=True)
        job_dir = results_dir / job.id
        job_dir.mkdir(parents=True, exist_ok=True)
        source_path = Path(job.upload_path)
        model = self._ensure_model()
        fp16 = self.fp16 and not self.device.lower().startswith("cpu")
        logger.info(
            "Running whisper for job %s (model=%s, device=%s)",
            job.id,
            self.model_name,
            self.device,
        )
        try:
            result = model.transcribe(
                str(source_path),
                fp16=fp16,
            )
        except Exception as exc:  # pragma: no cover - passthrough for backend errors
            raise RuntimeError(f"whisper failed: {exc}") from exc
        transcript = (result.get("text") or "").strip()
        result_path = job_dir / _result_filename(job.filename)
        result_path.write_text(
            transcript + ("\n" if transcript else ""),
            encoding="utf-8",
        )
        return result_path

    def _ensure_model(self):
        if self._model is not None:
            return self._model
        try:
            import whisper  # type: ignore[import-not-found]
        except Exception as exc:  # pragma: no cover - depends on optional dep
            raise RuntimeError(
                "Whisper backend selected but 'openai-whisper' is not installed. "
                "Install requirements-docker.txt or set TRANSCRIBER_BACKEND=wtm."
            ) from exc
        self._whisper = whisper
        try:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            self._model = whisper.load_model(
                self.model_name,
                device=self.device,
                download_root=str(self.cache_dir),
            )
        except Exception as exc:  # pragma: no cover - depends on backend download
            raise RuntimeError(
                f"Failed to load Whisper model '{self.model_name}': {exc}"
            ) from exc
        return self._model


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


def _resolve_whisper_cache_dir() -> Path:
    env_dir = os.getenv(WHISPER_CACHE_DIR_ENV)
    if env_dir:
        return Path(env_dir)
    xdg_cache = os.getenv("XDG_CACHE_HOME")
    if xdg_cache:
        return Path(xdg_cache) / "whisper"
    return Path.home() / ".cache" / "whisper"


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


def _result_filename(source_name: str) -> str:
    base = Path(source_name).stem.strip()
    if not base:
        base = "transcript"
    return f"{base}.txt"


def resolve_transcriber() -> Transcriber:
    backend = os.getenv(BACKEND_ENV, DEFAULT_BACKEND).strip().lower()
    if backend in {"wtm", "mlx", "wtm-cli"}:
        return WtmTranscriber()
    if backend in {"whisper", "openai-whisper", "openai"}:
        return WhisperTranscriber()
    if backend in {"fake", "noop", "test"}:
        return FakeTranscriber()
    raise ValueError(
        f"Unknown transcriber backend '{backend}'. "
        "Use 'wtm', 'whisper', or 'fake'."
    )


def _tail_text(text: str | None, limit: int = 2000) -> str:
    if not text:
        return ""
    trimmed = text.strip()
    if len(trimmed) <= limit:
        return trimmed
    return trimmed[-limit:]
