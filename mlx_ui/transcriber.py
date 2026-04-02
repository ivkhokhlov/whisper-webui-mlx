from contextlib import contextmanager
from dataclasses import dataclass
import json
import logging
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from typing import Protocol
import wave

from mlx_ui.db import JobRecord
from mlx_ui.engine_registry import (
    COHERE_ENGINE,
    DEFAULT_BACKEND,
    FAKE_ENGINE,
    PARAKEET_TDT_V3_ENGINE,
    WHISPER_CPU_ENGINE,
    WHISPER_MLX_ENGINE,
    create_transcriber,
    parakeet_availability_reason,
    resolve_backend_provider,
    supported_backend_names,
)
from mlx_ui.languages import AUTO_LANGUAGE, normalize_language
from mlx_ui.transcript_result import (
    ALLOWED_OUTPUT_FORMATS,
    OUTPUT_FORMAT_TXT,
    TranscriptResult,
    TranscriptSegment,
    TranscriptWordTiming,
    transcript_output_stem,
    write_transcript_outputs,
)

logger = logging.getLogger(__name__)

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
_PARAKEET_FRAME_STRIDE_MULTIPLIER = 8.0
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


class Transcriber(Protocol):
    def transcribe(self, job: JobRecord, results_dir: Path) -> Path:
        raise NotImplementedError


@dataclass(frozen=True)
class _ParakeetAudioChunk:
    path: Path
    offset_seconds: float
    keep_start_seconds: float
    keep_end_seconds: float


class FakeTranscriber:
    engine_id = FAKE_ENGINE

    def __init__(self, output_formats: tuple[str, ...] | None = None) -> None:
        self.output_formats = _normalize_requested_output_formats(output_formats)

    def transcribe(self, job: JobRecord, results_dir: Path) -> Path:
        content = f"Fake transcript for {job.filename} ({job.id})"
        result = TranscriptResult(
            text=content,
            engine_id=self.engine_id,
            language=job.language,
        )
        return _write_transcript_result(
            result=result,
            results_dir=results_dir,
            job_id=job.id,
            source_name=job.filename,
            output_formats=self.output_formats,
        )


class WtmTranscriber:
    engine_id = WHISPER_MLX_ENGINE

    def __init__(
        self,
        wtm_path: str | None = None,
        quick: bool | None = None,
        output_formats: tuple[str, ...] | None = None,
    ) -> None:
        self.wtm_path = _resolve_wtm_path(wtm_path)
        self.quick = (
            quick if quick is not None else _parse_bool_env("WTM_QUICK", default=False)
        )
        self.output_formats = _normalize_requested_output_formats(output_formats)

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
        except subprocess.CalledProcessError as exc:
            message = _format_wtm_error(exc)
            raise RuntimeError(message) from exc
        transcript = TranscriptResult(
            text=(result.stdout or "").strip(),
            engine_id=self.engine_id,
            language=job.language,
        )
        return _write_transcript_result(
            result=transcript,
            results_dir=results_dir,
            job_id=job.id,
            source_name=job.filename,
            output_formats=self.output_formats,
        )


class WhisperTranscriber:
    engine_id = WHISPER_CPU_ENGINE

    def __init__(
        self,
        model_name: str | None = None,
        device: str | None = None,
        fp16: bool | None = None,
        output_formats: tuple[str, ...] | None = None,
    ) -> None:
        self.model_name = model_name or os.getenv(
            WHISPER_MODEL_ENV,
            DEFAULT_WHISPER_MODEL,
        )
        self.device = device or os.getenv(WHISPER_DEVICE_ENV, "cpu")
        self.fp16 = (
            fp16
            if fp16 is not None
            else _parse_bool_env(
                WHISPER_FP16_ENV,
                False,
            )
        )
        self.cache_dir = _resolve_whisper_cache_dir()
        self._model = None
        self._whisper = None
        self.output_formats = _normalize_requested_output_formats(output_formats)

    def transcribe(self, job: JobRecord, results_dir: Path) -> Path:
        results_dir = Path(results_dir)
        source_path = Path(job.upload_path)
        model = self._ensure_model()
        fp16 = self.fp16 and not self.device.lower().startswith("cpu")
        logger.info(
            "Running whisper for job %s (model=%s, device=%s)",
            job.id,
            self.model_name,
            self.device,
        )
        transcribe_kwargs: dict[str, object] = {
            "fp16": fp16,
        }
        if _should_request_whisper_word_timestamps(self.output_formats):
            transcribe_kwargs["word_timestamps"] = True
        try:
            result = model.transcribe(
                str(source_path),
                **transcribe_kwargs,
            )
        except Exception as exc:  # pragma: no cover - passthrough for backend errors
            raise RuntimeError(f"whisper failed: {exc}") from exc
        transcript = TranscriptResult(
            text=(result.get("text") or "").strip(),
            engine_id=self.engine_id,
            model_id=self.model_name,
            language=(result.get("language") or job.language),
            segments=_normalize_whisper_segments(result.get("segments")),
            words=_normalize_whisper_words(result.get("words")),
        )
        return _write_transcript_result(
            result=transcript,
            results_dir=results_dir,
            job_id=job.id,
            source_name=job.filename,
            output_formats=self.output_formats,
        )

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
            (model_name or os.getenv(COHERE_MODEL_ENV, DEFAULT_COHERE_MODEL)).strip()
            or DEFAULT_COHERE_MODEL
        )
        self.output_formats = _normalize_requested_output_formats(output_formats)
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
        return _write_transcript_result(
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
        cohere_module, api_error_type = _load_cohere_runtime()
        try:
            self._client = cohere_module.ClientV2(api_key=self.api_key)
        except Exception as exc:  # pragma: no cover - SDK init passthrough
            raise RuntimeError(f"Failed to initialize Cohere client: {exc}") from exc
        self._api_error_type = api_error_type
        return self._client


class ParakeetTranscriber:
    engine_id = PARAKEET_TDT_V3_ENGINE

    def __init__(
        self,
        repo_id: str | None = None,
        chunk_duration: float | None = None,
        overlap_duration: float | None = None,
        decoding_mode: str | None = None,
        batch_size: int | None = None,
        output_formats: tuple[str, ...] | None = None,
    ) -> None:
        self.repo_id = repo_id or DEFAULT_PARAKEET_MODEL
        self.chunk_duration = (
            float(chunk_duration)
            if chunk_duration is not None
            else DEFAULT_PARAKEET_CHUNK_DURATION
        )
        self.overlap_duration = (
            float(overlap_duration)
            if overlap_duration is not None
            else DEFAULT_PARAKEET_OVERLAP_DURATION
        )
        self.decoding_mode = (
            decoding_mode.strip().lower()
            if isinstance(decoding_mode, str) and decoding_mode.strip()
            else DEFAULT_PARAKEET_DECODING_MODE
        )
        if self.decoding_mode not in {"greedy", "beam"}:
            raise ValueError(
                "Parakeet decoding_mode must be either 'greedy' or 'beam'."
            )
        self.batch_size = max(1, int(batch_size or DEFAULT_PARAKEET_BATCH_SIZE))
        self.output_formats = _normalize_requested_output_formats(output_formats)
        self._model = None

    def transcribe(self, job: JobRecord, results_dir: Path) -> Path:
        source_path = Path(job.upload_path)
        model = self._ensure_model()
        logger.info(
            "Running Parakeet for job %s (model=%s, decoding=%s, batch_size=%s)",
            job.id,
            self.repo_id,
            self.decoding_mode,
            self.batch_size,
        )
        with _prepare_parakeet_audio_chunks(
            source_path,
            chunk_duration=self.chunk_duration,
            overlap_duration=self.overlap_duration,
        ) as chunks:
            try:
                hypotheses = _transcribe_with_parakeet_model(
                    model,
                    [str(chunk.path) for chunk in chunks],
                    batch_size=min(self.batch_size, len(chunks)),
                )
            except Exception as exc:  # pragma: no cover - backend passthrough
                raise RuntimeError(f"Parakeet transcription failed: {exc}") from exc
        transcript = _normalize_parakeet_transcript(
            model,
            hypotheses,
            chunks=chunks,
            model_id=self.repo_id,
            fallback_language=job.language,
        )
        return _write_transcript_result(
            result=transcript,
            results_dir=results_dir,
            job_id=job.id,
            source_name=job.filename,
            output_formats=self.output_formats,
        )

    def _ensure_model(self):
        if self._model is not None:
            return self._model
        nemo_asr, open_dict = _load_parakeet_runtime()
        try:
            model = nemo_asr.models.ASRModel.from_pretrained(self.repo_id)
        except Exception as exc:  # pragma: no cover - depends on optional backend
            raise RuntimeError(
                f"Failed to load Parakeet model '{self.repo_id}': {exc}"
            ) from exc
        _configure_parakeet_decoding(
            model,
            open_dict=open_dict,
            decoding_mode=self.decoding_mode,
        )
        self._model = model
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


def _write_transcript_result(
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
        formats=_normalize_requested_output_formats(output_formats),
    )
    return written[OUTPUT_FORMAT_TXT]


def _normalize_requested_output_formats(
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


def _should_request_whisper_word_timestamps(
    output_formats: tuple[str, ...],
) -> bool:
    return any(output_format in {"json", "srt", "vtt"} for output_format in output_formats)


def _load_cohere_runtime():
    try:
        import cohere  # type: ignore[import-not-found]
        from cohere.core.api_error import ApiError  # type: ignore[import-not-found]
    except Exception as exc:
        raise RuntimeError(
            "Cohere backend selected but the optional 'cohere' Python SDK is not installed."
        ) from exc
    return cohere, ApiError


def _load_parakeet_runtime():
    reason = parakeet_availability_reason()
    if reason:
        raise RuntimeError(f"Parakeet backend cannot run: {reason}")
    try:
        import nemo.collections.asr as nemo_asr  # type: ignore[import-not-found]
    except Exception as exc:
        raise RuntimeError(
            "Parakeet backend selected but NVIDIA NeMo ASR is not installed."
        ) from exc
    try:
        from omegaconf import open_dict  # type: ignore[import-not-found]
    except Exception as exc:
        raise RuntimeError(
            "Parakeet backend selected but OmegaConf is not installed."
        ) from exc
    return nemo_asr, open_dict


def _configure_parakeet_decoding(
    model,
    *,
    open_dict,
    decoding_mode: str,
) -> None:
    decoding_cfg = getattr(getattr(model, "cfg", None), "decoding", None)
    if decoding_cfg is None:
        raise RuntimeError("Parakeet model does not expose a decoding config.")
    strategy = "greedy_batch" if decoding_mode == "greedy" else "malsd_batch"
    try:
        with open_dict(decoding_cfg):
            decoding_cfg.strategy = strategy
            if hasattr(decoding_cfg, "compute_timestamps"):
                decoding_cfg.compute_timestamps = True
            if hasattr(decoding_cfg, "preserve_alignments"):
                decoding_cfg.preserve_alignments = True
            if hasattr(decoding_cfg, "rnnt_timestamp_type"):
                decoding_cfg.rnnt_timestamp_type = "all"
            if hasattr(decoding_cfg, "word_seperator"):
                decoding_cfg.word_seperator = " "
            if hasattr(decoding_cfg, "segment_seperators"):
                decoding_cfg.segment_seperators = [".", "?", "!"]
        model.change_decoding_strategy(decoding_cfg)
    except Exception as exc:
        raise RuntimeError(
            f"Failed to configure Parakeet decoding strategy '{decoding_mode}': {exc}"
        ) from exc


def _transcribe_with_parakeet_model(model, audio_paths: list[str], *, batch_size: int):
    kwargs = {
        "audio": audio_paths,
        "batch_size": batch_size,
        "return_hypotheses": True,
        "channel_selector": "average",
        "verbose": False,
    }
    try:
        return model.transcribe(timestamps=True, **kwargs)
    except TypeError:
        return model.transcribe(**kwargs)


def _normalize_parakeet_transcript(
    model,
    hypotheses: object,
    *,
    chunks: tuple[_ParakeetAudioChunk, ...],
    model_id: str,
    fallback_language: str,
) -> TranscriptResult:
    hypothesis_list = (
        list(hypotheses) if isinstance(hypotheses, (list, tuple)) else [hypotheses]
    )
    parts: list[TranscriptResult] = []
    for index, hypothesis in enumerate(hypothesis_list):
        if index >= len(chunks):
            break
        parts.append(
            _normalize_parakeet_hypothesis(
                model,
                hypothesis,
                chunk=chunks[index],
                model_id=model_id,
                fallback_language=fallback_language,
            )
        )
    if not parts:
        return TranscriptResult(
            text="",
            engine_id=PARAKEET_TDT_V3_ENGINE,
            model_id=model_id,
            language=fallback_language,
        )
    if len(parts) == 1:
        return parts[0]
    combined_segments = tuple(
        segment for part in parts for segment in part.segments if segment.text.strip()
    )
    combined_words = tuple(
        word for part in parts for word in part.words if word.text.strip()
    )
    text = _compose_transcript_text(parts, combined_segments, combined_words)
    language = next((part.language for part in parts if part.language), fallback_language)
    return TranscriptResult(
        text=text,
        engine_id=PARAKEET_TDT_V3_ENGINE,
        model_id=model_id,
        language=language,
        segments=combined_segments,
        words=combined_words,
    )


def _normalize_parakeet_hypothesis(
    model,
    hypothesis: object,
    *,
    chunk: _ParakeetAudioChunk,
    model_id: str,
    fallback_language: str,
) -> TranscriptResult:
    text = _normalize_text_value(_hypothesis_value(hypothesis, "text"))
    timestamp_map = _extract_timestamp_map(hypothesis)
    segments = _normalize_parakeet_segments(model, timestamp_map, chunk=chunk)
    words = _normalize_parakeet_words(model, timestamp_map, chunk=chunk)
    if not text:
        if segments:
            text = " ".join(segment.text for segment in segments if segment.text.strip())
        elif words:
            text = " ".join(word.text for word in words if word.text.strip())
    return TranscriptResult(
        text=text,
        engine_id=PARAKEET_TDT_V3_ENGINE,
        model_id=model_id,
        language=_extract_hypothesis_language(hypothesis) or fallback_language,
        segments=segments,
        words=words,
    )


def _normalize_parakeet_segments(
    model,
    timestamp_map: dict[str, object],
    *,
    chunk: _ParakeetAudioChunk,
) -> tuple[TranscriptSegment, ...]:
    raw_segments = timestamp_map.get("segment")
    if not isinstance(raw_segments, list):
        return ()
    segments: list[TranscriptSegment] = []
    for index, raw_segment in enumerate(raw_segments):
        if not isinstance(raw_segment, dict):
            continue
        start = _timestamp_seconds(model, raw_segment, "start")
        end = _timestamp_seconds(model, raw_segment, "end")
        if not _timestamp_in_window(start, end, chunk):
            continue
        text = _normalize_text_value(
            raw_segment.get("segment") or raw_segment.get("text") or ""
        )
        words = _normalize_parakeet_embedded_words(model, raw_segment, chunk=chunk)
        if not text:
            text = " ".join(word.text for word in words if word.text.strip())
        segments.append(
            TranscriptSegment(
                id=index,
                text=text,
                start=_offset_timestamp(start, chunk),
                end=_offset_timestamp(end, chunk),
                words=words,
            )
        )
    return tuple(segments)


def _normalize_parakeet_embedded_words(
    model,
    raw_segment: dict[str, object],
    *,
    chunk: _ParakeetAudioChunk,
) -> tuple[TranscriptWordTiming, ...]:
    raw_words = raw_segment.get("words")
    if not isinstance(raw_words, list):
        return ()
    words: list[TranscriptWordTiming] = []
    for raw_word in raw_words:
        if not isinstance(raw_word, dict):
            continue
        start = _timestamp_seconds(model, raw_word, "start")
        end = _timestamp_seconds(model, raw_word, "end")
        if not _timestamp_in_window(start, end, chunk):
            continue
        text = _normalize_text_value(
            raw_word.get("word") or raw_word.get("text") or ""
        )
        words.append(
            TranscriptWordTiming(
                text=text,
                start=_offset_timestamp(start, chunk),
                end=_offset_timestamp(end, chunk),
            )
        )
    return tuple(words)


def _normalize_parakeet_words(
    model,
    timestamp_map: dict[str, object],
    *,
    chunk: _ParakeetAudioChunk,
) -> tuple[TranscriptWordTiming, ...]:
    raw_words = timestamp_map.get("word")
    if not isinstance(raw_words, list):
        return ()
    words: list[TranscriptWordTiming] = []
    for raw_word in raw_words:
        if not isinstance(raw_word, dict):
            continue
        start = _timestamp_seconds(model, raw_word, "start")
        end = _timestamp_seconds(model, raw_word, "end")
        if not _timestamp_in_window(start, end, chunk):
            continue
        text = _normalize_text_value(raw_word.get("word") or raw_word.get("text") or "")
        words.append(
            TranscriptWordTiming(
                text=text,
                start=_offset_timestamp(start, chunk),
                end=_offset_timestamp(end, chunk),
            )
        )
    return tuple(words)


def _compose_transcript_text(
    parts: list[TranscriptResult],
    segments: tuple[TranscriptSegment, ...],
    words: tuple[TranscriptWordTiming, ...],
) -> str:
    if segments:
        return " ".join(segment.text for segment in segments if segment.text.strip()).strip()
    if words:
        return " ".join(word.text for word in words if word.text.strip()).strip()
    return " ".join(part.text for part in parts if part.text.strip()).strip()


def _extract_timestamp_map(hypothesis: object) -> dict[str, object]:
    candidate = _hypothesis_value(hypothesis, "timestamp")
    if isinstance(candidate, dict):
        return candidate
    candidate = _hypothesis_value(hypothesis, "timestep")
    if isinstance(candidate, dict):
        return candidate
    return {}


def _extract_hypothesis_language(hypothesis: object) -> str | None:
    candidate = _hypothesis_value(hypothesis, "language") or _hypothesis_value(
        hypothesis, "lang"
    )
    if isinstance(candidate, str) and candidate.strip():
        return candidate.strip()
    return None


def _hypothesis_value(hypothesis: object, field: str) -> object:
    if isinstance(hypothesis, dict):
        return hypothesis.get(field)
    return getattr(hypothesis, field, None)


def _timestamp_seconds(model, entry: dict[str, object], prefix: str) -> float | None:
    direct = entry.get(prefix)
    if isinstance(direct, (int, float)) and not isinstance(direct, bool):
        return float(direct)
    offset = entry.get(f"{prefix}_offset")
    if isinstance(offset, (int, float)) and not isinstance(offset, bool):
        scale = _parakeet_timestamp_scale(model)
        if scale is not None:
            return float(offset) * scale
    return None


def _parakeet_timestamp_scale(model) -> float | None:
    preprocessor = getattr(getattr(model, "cfg", None), "preprocessor", None)
    window_stride = getattr(preprocessor, "window_stride", None)
    if isinstance(window_stride, (int, float)) and not isinstance(window_stride, bool):
        return float(window_stride) * _PARAKEET_FRAME_STRIDE_MULTIPLIER
    return None


def _timestamp_in_window(
    start: float | None,
    end: float | None,
    chunk: _ParakeetAudioChunk,
) -> bool:
    if start is None or end is None:
        return False
    midpoint = (start + end) / 2.0
    return chunk.keep_start_seconds <= midpoint <= chunk.keep_end_seconds


def _offset_timestamp(
    value: float | None,
    chunk: _ParakeetAudioChunk,
) -> float | None:
    if value is None:
        return None
    return chunk.offset_seconds + value


@contextmanager
def _prepare_parakeet_audio_chunks(
    source_path: Path,
    *,
    chunk_duration: float,
    overlap_duration: float,
):
    try:
        with wave.open(str(source_path), "rb") as reader:
            frame_rate = reader.getframerate()
            total_frames = reader.getnframes()
            chunk_frames = int(chunk_duration * frame_rate)
            overlap_frames = int(overlap_duration * frame_rate)
            step_frames = chunk_frames - overlap_frames
            if chunk_frames <= 0 or step_frames <= 0 or total_frames <= chunk_frames:
                raise wave.Error("chunking not required")
            with tempfile.TemporaryDirectory(prefix="mlx-ui-parakeet-") as tmp_dir:
                chunks = _write_wave_chunks(
                    reader,
                    output_dir=Path(tmp_dir),
                    chunk_frames=chunk_frames,
                    step_frames=step_frames,
                    overlap_duration=overlap_duration,
                )
                if len(chunks) > 1:
                    yield chunks
                    return
    except (FileNotFoundError, OSError, wave.Error):
        pass
    yield (
        _ParakeetAudioChunk(
            path=Path(source_path),
            offset_seconds=0.0,
            keep_start_seconds=0.0,
            keep_end_seconds=float("inf"),
        ),
    )


def _write_wave_chunks(
    reader: wave.Wave_read,
    *,
    output_dir: Path,
    chunk_frames: int,
    step_frames: int,
    overlap_duration: float,
) -> tuple[_ParakeetAudioChunk, ...]:
    total_frames = reader.getnframes()
    frame_rate = reader.getframerate()
    channels = reader.getnchannels()
    sample_width = reader.getsampwidth()
    compression = reader.getcomptype()
    compression_name = reader.getcompname()
    half_overlap = max(0.0, overlap_duration / 2.0)
    chunks: list[_ParakeetAudioChunk] = []
    chunk_index = 0
    for start_frame in range(0, total_frames, step_frames):
        frames_to_read = min(chunk_frames, total_frames - start_frame)
        if frames_to_read <= 0:
            break
        reader.setpos(start_frame)
        frames = reader.readframes(frames_to_read)
        chunk_path = output_dir / f"chunk-{chunk_index:04d}.wav"
        with wave.open(str(chunk_path), "wb") as writer:
            writer.setnchannels(channels)
            writer.setsampwidth(sample_width)
            writer.setframerate(frame_rate)
            writer.setcomptype(compression, compression_name)
            writer.writeframes(frames)
        duration_seconds = frames_to_read / frame_rate
        is_first = chunk_index == 0
        is_last = start_frame + frames_to_read >= total_frames
        keep_start = 0.0 if is_first else min(half_overlap, duration_seconds)
        keep_end = (
            duration_seconds
            if is_last
            else max(keep_start, duration_seconds - half_overlap)
        )
        chunks.append(
            _ParakeetAudioChunk(
                path=chunk_path,
                offset_seconds=start_frame / frame_rate,
                keep_start_seconds=keep_start,
                keep_end_seconds=keep_end,
            )
        )
        chunk_index += 1
        if is_last:
            break
    return tuple(chunks)


def _normalize_whisper_segments(raw_segments: object) -> tuple[TranscriptSegment, ...]:
    if not isinstance(raw_segments, list):
        return ()
    segments: list[TranscriptSegment] = []
    for raw_segment in raw_segments:
        if not isinstance(raw_segment, dict):
            continue
        text = str(raw_segment.get("text") or "")
        start = _normalize_timestamp(raw_segment.get("start"))
        end = _normalize_timestamp(raw_segment.get("end"))
        segment_id = raw_segment.get("id")
        words = _normalize_whisper_words(raw_segment.get("words"))
        segments.append(
            TranscriptSegment(
                id=segment_id if isinstance(segment_id, int) else None,
                text=text,
                start=start,
                end=end,
                words=words,
            )
        )
    return tuple(segments)


def _normalize_whisper_words(raw_words: object) -> tuple[TranscriptWordTiming, ...]:
    if not isinstance(raw_words, list):
        return ()
    words: list[TranscriptWordTiming] = []
    for raw_word in raw_words:
        if not isinstance(raw_word, dict):
            continue
        text = str(raw_word.get("word") or raw_word.get("text") or "")
        words.append(
            TranscriptWordTiming(
                text=text,
                start=_normalize_timestamp(raw_word.get("start")),
                end=_normalize_timestamp(raw_word.get("end")),
            )
        )
    return tuple(words)


def _normalize_timestamp(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _normalize_text_value(value: object) -> str:
    if not isinstance(value, str):
        return ""
    return value.replace("\r\n", "\n").strip()


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
    detail = _tail_text(str(error) or error.__class__.__name__)
    if isinstance(error, TimeoutError) or "timeout" in error_name:
        return f"Cohere request timed out: {detail}"
    return f"Cohere transcription failed: {detail}"


def _format_cohere_api_error(error: Exception) -> str:
    status_code = getattr(error, "status_code", None)
    body = _cohere_error_body_text(getattr(error, "body", None))
    detail = _tail_text(body or str(error) or error.__class__.__name__)
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


def resolve_transcriber() -> Transcriber:
    backend = os.getenv(BACKEND_ENV, DEFAULT_BACKEND).strip().lower()
    provider = resolve_backend_provider(backend)
    if provider is not None:
        return create_transcriber(provider.id)
    supported = "', '".join(supported_backend_names())
    raise ValueError(
        f"Unknown transcriber backend '{backend}'. Use '{supported}'."
    )


def _tail_text(text: str | None, limit: int = 2000) -> str:
    if not text:
        return ""
    trimmed = text.strip()
    if len(trimmed) <= limit:
        return trimmed
    return trimmed[-limit:]
