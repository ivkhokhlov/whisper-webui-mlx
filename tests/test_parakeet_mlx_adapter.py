import json
from pathlib import Path

from mlx_ui.engines.parakeet_mlx_adapter import normalize_parakeet_mlx_result
from mlx_ui.transcript_result import (
    OUTPUT_FORMAT_JSON,
    OUTPUT_FORMAT_SRT,
    OUTPUT_FORMAT_TXT,
    OUTPUT_FORMAT_VTT,
    has_timing_data,
    write_transcript_outputs,
)


def test_adapter_normalizes_text_only_result_without_faking_timing(
    tmp_path: Path,
) -> None:
    result = normalize_parakeet_mlx_result(
        {"text": "hello world", "language": "en"},
        engine_id="parakeet_tdt_v3",
        model_id="mlx-community/parakeet-tdt-0.6b-v3",
        fallback_language="fr",
    )

    assert result.text == "hello world"
    assert result.engine_id == "parakeet_tdt_v3"
    assert result.model_id == "mlx-community/parakeet-tdt-0.6b-v3"
    assert result.language == "en"
    assert result.segments == ()
    assert result.words == ()
    assert has_timing_data(result) is False

    written = write_transcript_outputs(
        result,
        tmp_path,
        base_name="alpha",
        formats=(
            OUTPUT_FORMAT_TXT,
            OUTPUT_FORMAT_JSON,
            OUTPUT_FORMAT_SRT,
            OUTPUT_FORMAT_VTT,
        ),
    )
    assert set(written) == {OUTPUT_FORMAT_TXT, OUTPUT_FORMAT_JSON}
    assert (tmp_path / "alpha.txt").read_text(encoding="utf-8") == "hello world\n"
    payload = json.loads((tmp_path / "alpha.json").read_text(encoding="utf-8"))
    assert payload["text"] == "hello world"
    assert payload["segments"] == []
    assert payload["words"] == []


class _FakeWord:
    def __init__(self, token: str, start: float, end: float) -> None:
        self.token = token
        self.start_time = start
        self.end_time = end


class _FakeSegment:
    def __init__(
        self,
        sentence: str,
        start: float,
        end: float,
        words: list[_FakeWord],
    ) -> None:
        self.sentence = sentence
        self.start_time = start
        self.end_time = end
        self.tokens = words


class _FakeResult:
    def __init__(
        self,
        segments: list[_FakeSegment],
        *,
        language_code: str = "en",
        model_id: str = "runtime-model",
    ) -> None:
        self.aligned_sentences = segments
        self.language_code = language_code
        self.model_id = model_id


def test_adapter_maps_aligned_segments_and_word_timings(
    tmp_path: Path,
) -> None:
    raw = _FakeResult(
        [
            _FakeSegment(
                "hello",
                0.0,
                0.5,
                words=[_FakeWord("hello", 0.0, 0.5)],
            ),
            _FakeSegment(
                "world",
                0.5,
                1.0,
                words=[_FakeWord("world", 0.5, 1.0)],
            ),
        ],
        language_code="en",
        model_id="mlx-community/parakeet-tdt-0.6b-v3",
    )

    result = normalize_parakeet_mlx_result(
        raw,
        engine_id="parakeet_tdt_v3",
        model_id="fallback-model",
        fallback_language="fr",
    )

    assert result.text == "hello world"
    assert result.engine_id == "parakeet_tdt_v3"
    assert result.model_id == "mlx-community/parakeet-tdt-0.6b-v3"
    assert result.language == "en"
    assert len(result.segments) == 2
    assert result.segments[0].text == "hello"
    assert result.segments[0].start == 0.0
    assert result.segments[0].end == 0.5
    assert len(result.segments[0].words) == 1
    assert result.segments[0].words[0].text == "hello"
    assert result.segments[0].words[0].start == 0.0
    assert result.segments[0].words[0].end == 0.5
    assert has_timing_data(result) is True

    written = write_transcript_outputs(
        result,
        tmp_path,
        base_name="alpha",
        formats=(OUTPUT_FORMAT_TXT, OUTPUT_FORMAT_SRT),
    )
    assert (tmp_path / "alpha.srt").is_file()
    assert written[OUTPUT_FORMAT_TXT].read_text(encoding="utf-8") == "hello world\n"
