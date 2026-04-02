from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Protocol

from mlx_ui.db import JobRecord
from mlx_ui.engine_registry import FAKE_ENGINE
from mlx_ui.transcript_result import (
    ALLOWED_OUTPUT_FORMATS,
    OUTPUT_FORMAT_TXT,
    TranscriptResult,
    transcript_output_stem,
    write_transcript_outputs,
)

BACKEND_ENV = "TRANSCRIBER_BACKEND"
COHERE_API_KEY_ENV = "COHERE_API_KEY"
COHERE_MODEL_ENV = "COHERE_MODEL"
WHISPER_MODEL_ENV = "WHISPER_MODEL"
WHISPER_DEVICE_ENV = "WHISPER_DEVICE"
WHISPER_FP16_ENV = "WHISPER_FP16"
WHISPER_CACHE_DIR_ENV = "WHISPER_CACHE_DIR"
DEFAULT_COHERE_MODEL = "cohere-transcribe-03-2026"
DEFAULT_WHISPER_MODEL = "large-v3-turbo"
DEFAULT_PARAKEET_MODEL = "nvidia/parakeet-tdt-0.6b-v3"
DEFAULT_PARAKEET_CHUNK_DURATION = 30.0
DEFAULT_PARAKEET_OVERLAP_DURATION = 5.0
DEFAULT_PARAKEET_DECODING_MODE = "greedy"
DEFAULT_PARAKEET_BATCH_SIZE = 1

_DEFAULT_OUTPUT_FORMATS = (OUTPUT_FORMAT_TXT,)


class Transcriber(Protocol):
    def transcribe(self, job: JobRecord, results_dir: Path) -> Path:
        raise NotImplementedError


def parse_bool_env(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    return default


def normalize_requested_output_formats(
    output_formats: tuple[str, ...] | None,
) -> tuple[str, ...]:
    if not output_formats:
        return _DEFAULT_OUTPUT_FORMATS
    normalized: list[str] = []
    seen: set[str] = set()
    for output_format in output_formats:
        candidate = output_format.strip().lower()
        if candidate not in ALLOWED_OUTPUT_FORMATS:
            continue
        if candidate in seen:
            continue
        seen.add(candidate)
        normalized.append(candidate)
    if OUTPUT_FORMAT_TXT not in seen:
        normalized.insert(0, OUTPUT_FORMAT_TXT)
    return tuple(normalized)


def write_transcript_result(
    *,
    result: TranscriptResult,
    results_dir: Path,
    job_id: str,
    source_name: str,
    output_formats: tuple[str, ...] | None = None,
) -> Path:
    output_dir = Path(results_dir) / job_id
    written = write_transcript_outputs(
        result,
        output_dir,
        base_name=transcript_output_stem(source_name),
        formats=normalize_requested_output_formats(output_formats),
    )
    return written[OUTPUT_FORMAT_TXT]


def tail_text(text: str | None, limit: int = 2000) -> str:
    if not text:
        return ""
    trimmed = text.strip()
    if len(trimmed) <= limit:
        return trimmed
    return trimmed[-limit:]


def cache_secret_key(secret: str | None) -> str | None:
    if not secret:
        return None
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()


class FakeTranscriber:
    engine_id = FAKE_ENGINE

    def __init__(self, output_formats: tuple[str, ...] | None = None) -> None:
        self.output_formats = normalize_requested_output_formats(output_formats)

    def transcribe(self, job: JobRecord, results_dir: Path) -> Path:
        content = f"Fake transcript for {job.filename} ({job.id})"
        result = TranscriptResult(
            text=content,
            engine_id=self.engine_id,
            language=job.language,
        )
        return write_transcript_result(
            result=result,
            results_dir=results_dir,
            job_id=job.id,
            source_name=job.filename,
            output_formats=self.output_formats,
        )
