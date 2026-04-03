from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import logging
from pathlib import Path
import tempfile
import wave

from mlx_ui.db import JobRecord
from mlx_ui.engine_registry import PARAKEET_TDT_V3_ENGINE, parakeet_availability_reason
from mlx_ui.engines.common import (
    DEFAULT_PARAKEET_BATCH_SIZE,
    DEFAULT_PARAKEET_CHUNK_DURATION,
    DEFAULT_PARAKEET_DECODING_MODE,
    DEFAULT_PARAKEET_MODEL,
    DEFAULT_PARAKEET_OVERLAP_DURATION,
    normalize_requested_output_formats,
    write_transcript_result,
)
from mlx_ui.transcript_result import (
    TranscriptResult,
    TranscriptSegment,
    TranscriptWordTiming,
)

logger = logging.getLogger(__name__)

_PARAKEET_FRAME_STRIDE_MULTIPLIER = 8.0


def load_parakeet_runtime():
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


@dataclass(frozen=True)
class _ParakeetAudioChunk:
    path: Path
    offset_seconds: float
    keep_start_seconds: float
    keep_end_seconds: float


class ParakeetNemoCudaTranscriber:
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
        self.output_formats = normalize_requested_output_formats(output_formats)
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
        from mlx_ui import transcriber as transcriber_module

        nemo_asr, open_dict = transcriber_module._load_parakeet_runtime()
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
    language = next(
        (part.language for part in parts if part.language), fallback_language
    )
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
            text = " ".join(
                segment.text for segment in segments if segment.text.strip()
            )
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
        text = _normalize_text_value(raw_word.get("word") or raw_word.get("text") or "")
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
        return " ".join(
            segment.text for segment in segments if segment.text.strip()
        ).strip()
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


def _normalize_text_value(value: object) -> str:
    if not isinstance(value, str):
        return ""
    return value.replace("\r\n", "\n").strip()


ParakeetTranscriber = ParakeetNemoCudaTranscriber
