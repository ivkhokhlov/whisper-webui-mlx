import json
from pathlib import Path

import pytest

from mlx_ui.transcript_result import (
    OUTPUT_FORMAT_JSON,
    OUTPUT_FORMAT_SRT,
    OUTPUT_FORMAT_TXT,
    OUTPUT_FORMAT_VTT,
    TranscriptResult,
    TranscriptSegment,
    TranscriptWordTiming,
    has_timing_data,
    transcript_output_stem,
    write_transcript_json,
    write_transcript_outputs,
    write_transcript_srt,
    write_transcript_txt,
    write_transcript_vtt,
)


def test_transcript_output_stem_falls_back_for_blank_names() -> None:
    assert transcript_output_stem("sample.wav") == "sample"
    assert transcript_output_stem("   ") == "transcript"


def test_write_transcript_txt_adds_trailing_newline(tmp_path: Path) -> None:
    result = TranscriptResult(text="hello world", engine_id="whisper_cpu")

    path = write_transcript_txt(result, tmp_path / "alpha.txt")

    assert path.read_text(encoding="utf-8") == "hello world\n"


def test_write_transcript_srt_and_vtt_from_timed_segments(tmp_path: Path) -> None:
    result = TranscriptResult(
        text="hello world",
        engine_id="whisper_cpu",
        segments=(
            TranscriptSegment(text="Hello", start=0.0, end=1.25),
            TranscriptSegment(text="World", start=1.25, end=2.5),
        ),
    )

    srt_path = write_transcript_srt(result, tmp_path / "alpha.srt")
    vtt_path = write_transcript_vtt(result, tmp_path / "alpha.vtt")

    assert srt_path.read_text(encoding="utf-8") == (
        "1\n"
        "00:00:00,000 --> 00:00:01,250\n"
        "Hello\n\n"
        "2\n"
        "00:00:01,250 --> 00:00:02,500\n"
        "World\n"
    )
    assert vtt_path.read_text(encoding="utf-8") == (
        "WEBVTT\n\n"
        "00:00:00.000 --> 00:00:01.250\n"
        "Hello\n\n"
        "00:00:01.250 --> 00:00:02.500\n"
        "World\n"
    )


def test_write_transcript_srt_raises_without_timing() -> None:
    result = TranscriptResult(text="hello world", engine_id="whisper_cpu")

    with pytest.raises(ValueError, match="Timed transcript output requires"):
        write_transcript_srt(result, Path("ignored.srt"))


def test_write_transcript_outputs_skips_timed_formats_without_timestamps(
    tmp_path: Path,
) -> None:
    result = TranscriptResult(
        text="hello world",
        engine_id="whisper_cpu",
    )

    written = write_transcript_outputs(
        result,
        tmp_path,
        base_name="alpha",
        formats=(
            OUTPUT_FORMAT_TXT,
            OUTPUT_FORMAT_SRT,
            OUTPUT_FORMAT_VTT,
            OUTPUT_FORMAT_JSON,
        ),
    )

    assert has_timing_data(result) is False
    assert set(written) == {OUTPUT_FORMAT_TXT, OUTPUT_FORMAT_JSON}
    assert (tmp_path / "alpha.txt").is_file()
    assert (tmp_path / "alpha.json").is_file()
    assert not (tmp_path / "alpha.srt").exists()
    assert not (tmp_path / "alpha.vtt").exists()


def test_write_transcript_json_is_explicit(tmp_path: Path) -> None:
    result = TranscriptResult(
        text="hello world",
        engine_id="whisper_cpu",
        model_id="large-v3-turbo",
        language="en",
        segments=(
            TranscriptSegment(
                id=0,
                text="hello world",
                start=0.0,
                end=1.0,
                words=(
                    TranscriptWordTiming(text="hello", start=0.0, end=0.4),
                    TranscriptWordTiming(text="world", start=0.5, end=1.0),
                ),
            ),
        ),
        words=(
            TranscriptWordTiming(text="hello", start=0.0, end=0.4),
            TranscriptWordTiming(text="world", start=0.5, end=1.0),
        ),
    )

    path = write_transcript_json(result, tmp_path / "alpha.json")
    payload = json.loads(path.read_text(encoding="utf-8"))

    assert payload == {
        "engine_id": "whisper_cpu",
        "language": "en",
        "model_id": "large-v3-turbo",
        "segments": [
            {
                "end": 1.0,
                "id": 0,
                "start": 0.0,
                "text": "hello world",
                "words": [
                    {"end": 0.4, "start": 0.0, "text": "hello"},
                    {"end": 1.0, "start": 0.5, "text": "world"},
                ],
            }
        ],
        "text": "hello world",
        "words": [
            {"end": 0.4, "start": 0.0, "text": "hello"},
            {"end": 1.0, "start": 0.5, "text": "world"},
        ],
    }


def test_write_transcript_outputs_uses_word_timings_when_segments_are_missing(
    tmp_path: Path,
) -> None:
    result = TranscriptResult(
        text="hello world",
        engine_id="whisper_cpu",
        words=(
            TranscriptWordTiming(text="hello", start=0.0, end=0.4),
            TranscriptWordTiming(text="world", start=0.5, end=1.1),
        ),
    )

    written = write_transcript_outputs(
        result,
        tmp_path,
        base_name="alpha",
        formats=(OUTPUT_FORMAT_SRT,),
    )

    assert has_timing_data(result) is True
    assert written[OUTPUT_FORMAT_SRT].read_text(encoding="utf-8") == (
        "1\n"
        "00:00:00,000 --> 00:00:01,100\n"
        "hello world\n"
    )
