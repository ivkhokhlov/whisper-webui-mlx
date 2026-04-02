from __future__ import annotations

import logging
import os
from pathlib import Path

from mlx_ui.db import JobRecord
from mlx_ui.engine_registry import WHISPER_CPU_ENGINE
from mlx_ui.engines.common import (
    DEFAULT_WHISPER_MODEL,
    WHISPER_CACHE_DIR_ENV,
    WHISPER_DEVICE_ENV,
    WHISPER_FP16_ENV,
    WHISPER_MODEL_ENV,
    normalize_requested_output_formats,
    parse_bool_env,
    write_transcript_result,
)
from mlx_ui.transcript_result import (
    TranscriptResult,
    TranscriptSegment,
    TranscriptWordTiming,
)

logger = logging.getLogger(__name__)


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
            fp16 if fp16 is not None else parse_bool_env(WHISPER_FP16_ENV, False)
        )
        self.cache_dir = _resolve_whisper_cache_dir()
        self._model = None
        self._whisper = None
        self.output_formats = normalize_requested_output_formats(output_formats)

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
        return write_transcript_result(
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


def _resolve_whisper_cache_dir() -> Path:
    env_dir = os.getenv(WHISPER_CACHE_DIR_ENV)
    if env_dir:
        return Path(env_dir)
    xdg_cache = os.getenv("XDG_CACHE_HOME")
    if xdg_cache:
        return Path(xdg_cache) / "whisper"
    return Path.home() / ".cache" / "whisper"


def _should_request_whisper_word_timestamps(
    output_formats: tuple[str, ...],
) -> bool:
    return any(
        output_format in {"json", "srt", "vtt"} for output_format in output_formats
    )


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
