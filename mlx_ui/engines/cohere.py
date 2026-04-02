from __future__ import annotations

import json
import logging
import os
from pathlib import Path

from mlx_ui.db import JobRecord
from mlx_ui.engine_registry import COHERE_ENGINE
from mlx_ui.engines.common import (
    COHERE_API_KEY_ENV,
    COHERE_MODEL_ENV,
    DEFAULT_COHERE_MODEL,
    normalize_requested_output_formats,
    tail_text,
    write_transcript_result,
)
from mlx_ui.languages import AUTO_LANGUAGE, normalize_language
from mlx_ui.transcript_result import TranscriptResult

logger = logging.getLogger(__name__)

_COHERE_MAX_FILE_BYTES = 25 * 1024 * 1024
_COHERE_SUPPORTED_FILE_EXTENSIONS = (
    "flac",
    "mp3",
    "mpeg",
    "mpga",
    "ogg",
    "wav",
)
_COHERE_SUPPORTED_LANGUAGE_CODES = (
    "ar",
    "de",
    "el",
    "en",
    "es",
    "fr",
    "it",
    "ja",
    "ko",
    "nl",
    "pl",
    "pt",
    "vi",
    "zh",
)


def load_cohere_runtime():
    try:
        import cohere  # type: ignore[import-not-found]
        from cohere.core.api_error import ApiError  # type: ignore[import-not-found]
    except Exception as exc:
        raise RuntimeError(
            "Cohere backend selected but the optional 'cohere' Python SDK is not installed."
        ) from exc
    return cohere, ApiError


class CohereTranscriber:
    engine_id = COHERE_ENGINE

    def __init__(
        self,
        api_key: str | None = None,
        model_name: str | None = None,
        output_formats: tuple[str, ...] | None = None,
    ) -> None:
        self.api_key = (api_key or os.getenv(COHERE_API_KEY_ENV, "")).strip()
        self.model_name = (
            model_name or os.getenv(COHERE_MODEL_ENV, DEFAULT_COHERE_MODEL)
        ).strip() or DEFAULT_COHERE_MODEL
        self.output_formats = normalize_requested_output_formats(output_formats)
        self._client = None
        self._api_error_type = None

    def transcribe(self, job: JobRecord, results_dir: Path) -> Path:
        source_path = Path(job.upload_path)
        language = _validate_cohere_request(
            source_path,
            language=job.language,
            api_key=self.api_key,
            model_name=self.model_name,
        )
        client = self._ensure_client()
        logger.info(
            "Running Cohere for job %s (model=%s, language=%s)",
            job.id,
            self.model_name,
            language,
        )
        try:
            with source_path.open("rb") as audio_file:
                response = client.audio.transcriptions.create(
                    model=self.model_name,
                    language=language,
                    file=audio_file,
                )
        except Exception as exc:  # pragma: no cover - backend/network passthrough
            raise RuntimeError(
                _format_cohere_exception(exc, api_error_type=self._api_error_type)
            ) from exc
        transcript = TranscriptResult(
            text=_extract_cohere_text(response),
            engine_id=self.engine_id,
            model_id=self.model_name,
            language=language,
        )
        return write_transcript_result(
            result=transcript,
            results_dir=results_dir,
            job_id=job.id,
            source_name=job.filename,
            output_formats=self.output_formats,
        )

    def _ensure_client(self):
        if self._client is not None:
            return self._client
        if not self.api_key:
            raise RuntimeError(
                "Cohere backend selected but no API key is configured. "
                f"Set {COHERE_API_KEY_ENV} or save a Cohere API key in Settings."
            )
        from mlx_ui import transcriber as transcriber_module

        cohere_module, api_error_type = transcriber_module._load_cohere_runtime()
        try:
            self._client = cohere_module.ClientV2(api_key=self.api_key)
        except Exception as exc:  # pragma: no cover - SDK init passthrough
            raise RuntimeError(f"Failed to initialize Cohere client: {exc}") from exc
        self._api_error_type = api_error_type
        return self._client


def _validate_cohere_request(
    source_path: Path,
    *,
    language: str | None,
    api_key: str,
    model_name: str,
) -> str:
    if not api_key.strip():
        raise RuntimeError(
            "Cohere backend selected but no API key is configured. "
            f"Set {COHERE_API_KEY_ENV} or save a Cohere API key in Settings."
        )
    if not model_name.strip():
        raise RuntimeError("Cohere backend selected but no model is configured.")
    normalized_language = normalize_language(language)
    if normalized_language == AUTO_LANGUAGE:
        raise RuntimeError(
            "Cohere requires an explicit language code; automatic language detection is not supported."
        )
    if normalized_language not in _COHERE_SUPPORTED_LANGUAGE_CODES:
        supported = ", ".join(_COHERE_SUPPORTED_LANGUAGE_CODES)
        raise RuntimeError(
            "Cohere does not support language "
            f"'{normalized_language}' for this transcription path. Supported ISO-639-1 "
            f"languages: {supported}."
        )
    if not source_path.is_file():
        raise RuntimeError(f"Cohere input file does not exist: {source_path}")
    extension = source_path.suffix.lower().lstrip(".")
    if extension not in _COHERE_SUPPORTED_FILE_EXTENSIONS:
        supported_exts = ", ".join(_COHERE_SUPPORTED_FILE_EXTENSIONS)
        raise RuntimeError(
            f"Cohere requires one of these audio formats: {supported_exts}. "
            f"Got '{source_path.suffix or '(no extension)'}'."
        )
    try:
        file_size = source_path.stat().st_size
    except OSError as exc:
        raise RuntimeError(f"Unable to inspect Cohere input file: {exc}") from exc
    if file_size > _COHERE_MAX_FILE_BYTES:
        max_size_mb = _COHERE_MAX_FILE_BYTES // (1024 * 1024)
        actual_size_mb = file_size / (1024 * 1024)
        raise RuntimeError(
            f"Cohere accepts audio uploads up to {max_size_mb} MB. "
            f"Got {actual_size_mb:.1f} MB."
        )
    return normalized_language


def _extract_cohere_text(response: object) -> str:
    text = None
    if isinstance(response, dict):
        text = response.get("text")
    else:
        text = getattr(response, "text", None)
    if isinstance(text, str):
        return text.strip()
    raise RuntimeError("Cohere returned a response without transcript text.")


def _format_cohere_exception(
    error: Exception,
    *,
    api_error_type,
) -> str:
    if api_error_type is not None and isinstance(error, api_error_type):
        return _format_cohere_api_error(error)
    error_name = error.__class__.__name__.lower()
    detail = tail_text(str(error) or error.__class__.__name__)
    if isinstance(error, TimeoutError) or "timeout" in error_name:
        return f"Cohere request timed out: {detail}"
    return f"Cohere transcription failed: {detail}"


def _format_cohere_api_error(error: Exception) -> str:
    status_code = getattr(error, "status_code", None)
    body = _cohere_error_body_text(getattr(error, "body", None))
    detail = tail_text(body or str(error) or error.__class__.__name__)
    prefix = "Cohere API request failed"
    if status_code in {400, 404, 422}:
        prefix = "Cohere request validation failed"
    elif status_code in {401, 403, 498}:
        prefix = "Cohere authentication failed"
    elif status_code == 429:
        prefix = "Cohere rate limit exceeded"
    elif isinstance(status_code, int) and (
        status_code in {500, 501, 503, 504} or 500 <= status_code < 600
    ):
        prefix = "Cohere service error"
    if isinstance(status_code, int):
        prefix = f"{prefix} (status {status_code})"
    if detail:
        return f"{prefix}: {detail}"
    return prefix


def _cohere_error_body_text(body: object) -> str:
    if body is None:
        return ""
    if isinstance(body, str):
        return body.strip()
    if isinstance(body, (dict, list)):
        return json.dumps(body, ensure_ascii=True, sort_keys=True)
    return str(body).strip()
