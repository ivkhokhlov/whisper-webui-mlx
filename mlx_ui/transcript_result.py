from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path
from typing import Sequence

OUTPUT_FORMAT_TXT = "txt"
OUTPUT_FORMAT_SRT = "srt"
OUTPUT_FORMAT_VTT = "vtt"
OUTPUT_FORMAT_JSON = "json"
ALLOWED_OUTPUT_FORMATS = (
    OUTPUT_FORMAT_TXT,
    OUTPUT_FORMAT_SRT,
    OUTPUT_FORMAT_VTT,
    OUTPUT_FORMAT_JSON,
)
_TIMED_OUTPUT_FORMATS = {OUTPUT_FORMAT_SRT, OUTPUT_FORMAT_VTT}


@dataclass(frozen=True)
class TranscriptWordTiming:
    text: str
    start: float | None = None
    end: float | None = None


@dataclass(frozen=True)
class TranscriptSegment:
    text: str
    start: float | None = None
    end: float | None = None
    id: int | None = None
    words: tuple[TranscriptWordTiming, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class TranscriptResult:
    text: str
    engine_id: str
    model_id: str | None = None
    language: str | None = None
    segments: tuple[TranscriptSegment, ...] = field(default_factory=tuple)
    words: tuple[TranscriptWordTiming, ...] = field(default_factory=tuple)


def transcript_output_stem(source_name: str) -> str:
    base = Path(source_name).stem.strip()
    if not base:
        return "transcript"
    return base


def has_timing_data(result: TranscriptResult) -> bool:
    return bool(_collect_timed_segments(result))


def write_transcript_txt(result: TranscriptResult, path: Path) -> Path:
    content = result.text.rstrip("\n")
    if content:
        content = f"{content}\n"
    return _write_text(path, content)


def write_transcript_srt(result: TranscriptResult, path: Path) -> Path:
    segments = _require_timed_segments(result)
    blocks = []
    for index, segment in enumerate(segments, start=1):
        blocks.append(
            "\n".join(
                [
                    str(index),
                    f"{_format_timestamp(segment.start, decimal=',')} --> "
                    f"{_format_timestamp(segment.end, decimal=',')}",
                    segment.text,
                ]
            )
        )
    return _write_text(path, "\n\n".join(blocks) + "\n")


def write_transcript_vtt(result: TranscriptResult, path: Path) -> Path:
    segments = _require_timed_segments(result)
    blocks = ["WEBVTT"]
    for segment in segments:
        blocks.append(
            "\n".join(
                [
                    f"{_format_timestamp(segment.start)} --> "
                    f"{_format_timestamp(segment.end)}",
                    segment.text,
                ]
            )
        )
    return _write_text(path, "\n\n".join(blocks) + "\n")


def write_transcript_json(result: TranscriptResult, path: Path) -> Path:
    payload = {
        "text": result.text,
        "engine_id": result.engine_id,
        "model_id": result.model_id,
        "language": result.language,
        "segments": [_serialize_segment(segment) for segment in result.segments],
        "words": [_serialize_word(word) for word in result.words],
    }
    return _write_text(path, json.dumps(payload, indent=2, sort_keys=True) + "\n")


def write_transcript_outputs(
    result: TranscriptResult,
    output_dir: Path,
    *,
    base_name: str,
    formats: Sequence[str],
) -> dict[str, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    requested_formats = _normalize_formats(formats)
    written: dict[str, Path] = {}
    for output_format in requested_formats:
        if output_format in _TIMED_OUTPUT_FORMATS and not has_timing_data(result):
            continue
        path = output_dir / f"{base_name}.{output_format}"
        if output_format == OUTPUT_FORMAT_TXT:
            written[output_format] = write_transcript_txt(result, path)
        elif output_format == OUTPUT_FORMAT_SRT:
            written[output_format] = write_transcript_srt(result, path)
        elif output_format == OUTPUT_FORMAT_VTT:
            written[output_format] = write_transcript_vtt(result, path)
        elif output_format == OUTPUT_FORMAT_JSON:
            written[output_format] = write_transcript_json(result, path)
    return written


@dataclass(frozen=True)
class _TimedSegment:
    text: str
    start: float
    end: float


def _collect_timed_segments(result: TranscriptResult) -> tuple[_TimedSegment, ...]:
    segments: list[_TimedSegment] = []
    for segment in result.segments:
        normalized = _timed_segment_from_segment(segment)
        if normalized is not None:
            segments.append(normalized)
    if segments:
        return tuple(segments)
    normalized_words = _timed_segment_from_words(result.words, fallback_text=result.text)
    if normalized_words is not None:
        return (normalized_words,)
    return ()


def _timed_segment_from_segment(segment: TranscriptSegment) -> _TimedSegment | None:
    if segment.start is not None and segment.end is not None and segment.end > segment.start:
        text = _segment_text(segment)
        if not text:
            return None
        return _TimedSegment(text=text, start=segment.start, end=segment.end)
    return _timed_segment_from_words(segment.words, fallback_text=segment.text)


def _timed_segment_from_words(
    words: tuple[TranscriptWordTiming, ...],
    *,
    fallback_text: str,
) -> _TimedSegment | None:
    timed_words = [
        word
        for word in words
        if word.start is not None and word.end is not None and word.end > word.start
    ]
    if not timed_words:
        return None
    text = _normalize_text(fallback_text) or _join_words(timed_words)
    if not text:
        return None
    start = min(word.start for word in timed_words if word.start is not None)
    end = max(word.end for word in timed_words if word.end is not None)
    return _TimedSegment(text=text, start=start, end=end)


def _require_timed_segments(result: TranscriptResult) -> tuple[_TimedSegment, ...]:
    segments = _collect_timed_segments(result)
    if segments:
        return segments
    raise ValueError("Timed transcript output requires segment or word timestamps.")


def _segment_text(segment: TranscriptSegment) -> str:
    return _normalize_text(segment.text) or _join_words(segment.words)


def _join_words(words: Sequence[TranscriptWordTiming]) -> str:
    return " ".join(part for part in (_normalize_text(word.text) for word in words) if part)


def _serialize_segment(segment: TranscriptSegment) -> dict[str, object]:
    return {
        "id": segment.id,
        "text": segment.text,
        "start": segment.start,
        "end": segment.end,
        "words": [_serialize_word(word) for word in segment.words],
    }


def _serialize_word(word: TranscriptWordTiming) -> dict[str, object]:
    return {
        "text": word.text,
        "start": word.start,
        "end": word.end,
    }


def _normalize_formats(formats: Sequence[str]) -> tuple[str, ...]:
    normalized: list[str] = []
    seen: set[str] = set()
    for output_format in formats:
        candidate = output_format.strip().lower()
        if candidate not in ALLOWED_OUTPUT_FORMATS:
            raise ValueError(f"Unknown transcript output format '{output_format}'.")
        if candidate in seen:
            continue
        seen.add(candidate)
        normalized.append(candidate)
    return tuple(normalized)


def _format_timestamp(seconds: float, *, decimal: str = ".") -> str:
    total_milliseconds = max(0, int(round(seconds * 1000)))
    hours, remainder = divmod(total_milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    secs, milliseconds = divmod(remainder, 1_000)
    return (
        f"{hours:02d}:{minutes:02d}:{secs:02d}{decimal}{milliseconds:03d}"
    )


def _normalize_text(text: str) -> str:
    normalized = text.replace("\r\n", "\n").strip()
    return normalized


def _write_text(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path
