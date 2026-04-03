from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from mlx_ui.transcript_result import (
    TranscriptResult,
    TranscriptSegment,
    TranscriptWordTiming,
)


def normalize_parakeet_mlx_result(
    raw: object,
    *,
    engine_id: str,
    model_id: str,
    fallback_language: str,
) -> TranscriptResult:
    if raw is None:
        return TranscriptResult(
            text="",
            engine_id=engine_id,
            model_id=model_id,
            language=fallback_language,
        )
    if isinstance(raw, str):
        return TranscriptResult(
            text=raw.strip(),
            engine_id=engine_id,
            model_id=model_id,
            language=fallback_language,
        )
    if isinstance(raw, (list, tuple)):
        if not raw:
            return TranscriptResult(
                text="",
                engine_id=engine_id,
                model_id=model_id,
                language=fallback_language,
            )
        if len(raw) == 1:
            return normalize_parakeet_mlx_result(
                raw[0],
                engine_id=engine_id,
                model_id=model_id,
                fallback_language=fallback_language,
            )
        segments = _normalize_segments(list(raw))
        if segments:
            return TranscriptResult(
                text=_compose_text_from_segments(segments),
                engine_id=engine_id,
                model_id=model_id,
                language=fallback_language,
                segments=segments,
            )
        words = _normalize_words(list(raw))
        if words:
            return TranscriptResult(
                text=_compose_text_from_words(words),
                engine_id=engine_id,
                model_id=model_id,
                language=fallback_language,
                words=words,
            )
        return TranscriptResult(
            text=str(raw[0]).strip(),
            engine_id=engine_id,
            model_id=model_id,
            language=fallback_language,
        )

    exposed_model_id = (
        _string_field(raw, ("model_id", "model", "repo_id", "model_name")) or model_id
    )
    language = (
        _string_field(raw, ("language", "lang", "language_code")) or fallback_language
    )
    segments = _normalize_segments(
        _list_field(raw, ("segments", "sentences", "aligned_sentences", "chunks"))
    )
    words = _normalize_words(_list_field(raw, ("words", "tokens")))
    text = _string_field(raw, ("text", "transcript", "transcription", "output_text"))
    if not text:
        text = _compose_text_from_segments(segments) or _compose_text_from_words(words)

    return TranscriptResult(
        text=text or "",
        engine_id=engine_id,
        model_id=exposed_model_id,
        language=language,
        segments=segments,
        words=words,
    )


def _normalize_segments(items: object) -> tuple[TranscriptSegment, ...]:
    if not isinstance(items, list):
        return ()
    segments: list[TranscriptSegment] = []
    for index, item in enumerate(items):
        normalized = _normalize_segment(item, default_id=index)
        if normalized is None:
            continue
        if not normalized.text.strip() and not normalized.words:
            continue
        segments.append(normalized)
    return tuple(segments)


def _normalize_segment(item: object, *, default_id: int) -> TranscriptSegment | None:
    if item is None:
        return None
    if isinstance(item, str):
        return TranscriptSegment(id=default_id, text=item)

    segment_id = _int_field(item, ("id", "segment_id"))
    text = _string_field(item, ("text", "segment", "sentence", "utterance"))
    start = _timestamp_seconds(
        item, ("start", "start_time", "start_s", "start_sec", "start_ms")
    )
    end = _timestamp_seconds(item, ("end", "end_time", "end_s", "end_sec", "end_ms"))
    words = _normalize_words(_list_field(item, ("words", "tokens")))
    if not text:
        text = _compose_text_from_words(words)

    return TranscriptSegment(
        id=segment_id if segment_id is not None else default_id,
        text=text or "",
        start=start,
        end=end,
        words=words,
    )


def _normalize_words(items: object) -> tuple[TranscriptWordTiming, ...]:
    if not isinstance(items, list):
        return ()
    words: list[TranscriptWordTiming] = []
    for item in items:
        normalized = _normalize_word(item)
        if normalized is None:
            continue
        if not normalized.text.strip():
            continue
        words.append(normalized)
    return tuple(words)


def _normalize_word(item: object) -> TranscriptWordTiming | None:
    if item is None:
        return None
    if isinstance(item, str):
        return TranscriptWordTiming(text=item)

    text = _string_field(item, ("word", "text", "token"))
    start = _timestamp_seconds(
        item, ("start", "start_time", "start_s", "start_sec", "start_ms")
    )
    end = _timestamp_seconds(item, ("end", "end_time", "end_s", "end_sec", "end_ms"))
    return TranscriptWordTiming(
        text=text or "",
        start=start,
        end=end,
    )


def _compose_text_from_segments(segments: Iterable[TranscriptSegment]) -> str:
    parts = [segment.text.strip() for segment in segments if segment.text.strip()]
    return " ".join(parts)


def _compose_text_from_words(words: Iterable[TranscriptWordTiming]) -> str:
    parts = [word.text.strip() for word in words if word.text.strip()]
    return " ".join(parts)


def _string_field(obj: object, names: tuple[str, ...]) -> str:
    value = _field(obj, names)
    if not isinstance(value, str):
        return ""
    return value.strip()


def _int_field(obj: object, names: tuple[str, ...]) -> int | None:
    value = _field(obj, names)
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


def _list_field(obj: object, names: tuple[str, ...]) -> list[Any] | None:
    value = _field(obj, names)
    if isinstance(value, list):
        return value
    return None


def _field(obj: object, names: tuple[str, ...]) -> object:
    name, value = _field_with_name(obj, names)
    if name is None:
        return None
    return value


def _timestamp_seconds(obj: object, names: tuple[str, ...]) -> float | None:
    name, value = _field_with_name(obj, names)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    seconds = float(value)
    if name is not None and name.endswith("_ms"):
        return seconds / 1000.0
    return seconds


def _field_with_name(obj: object, names: tuple[str, ...]) -> tuple[str | None, object]:
    if isinstance(obj, dict):
        for name in names:
            if name in obj:
                return name, obj.get(name)
        return None, None
    for name in names:
        if not hasattr(obj, name):
            continue
        try:
            return name, getattr(obj, name)
        except Exception:
            continue
    return None, None
