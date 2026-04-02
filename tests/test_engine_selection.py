import json
from pathlib import Path

import mlx_ui.engine_registry as engine_registry
from mlx_ui.settings import resolve_transcriber_with_settings
from mlx_ui.transcriber import (
    CohereTranscriber,
    FakeTranscriber,
    ParakeetTranscriber,
    WhisperTranscriber,
    WtmTranscriber,
    resolve_transcriber,
)


def _write_settings(tmp_path: Path, payload: dict[str, object]) -> None:
    settings_path = tmp_path / "data" / "settings.json"
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    settings_path.write_text(json.dumps(payload), encoding="utf-8")


def test_engine_setting_selects_mlx_backend(tmp_path: Path, monkeypatch) -> None:
    _write_settings(tmp_path, {"engine": "whisper_mlx"})
    monkeypatch.setattr(engine_registry, "is_wtm_available", lambda: True)
    transcriber = resolve_transcriber_with_settings(base_dir=tmp_path, env={})
    assert isinstance(transcriber, WtmTranscriber)


def test_engine_setting_selects_cpu_backend(tmp_path: Path, monkeypatch) -> None:
    _write_settings(tmp_path, {"engine": "whisper_cpu"})
    monkeypatch.setattr(engine_registry, "is_whisper_available", lambda: True)
    transcriber = resolve_transcriber_with_settings(base_dir=tmp_path, env={})
    assert isinstance(transcriber, WhisperTranscriber)
    assert transcriber.device == "cpu"


def test_engine_env_override_takes_precedence(tmp_path: Path) -> None:
    _write_settings(tmp_path, {"engine": "whisper_cpu"})
    transcriber = resolve_transcriber_with_settings(
        base_dir=tmp_path,
        env={"TRANSCRIBER_BACKEND": "wtm"},
    )
    assert isinstance(transcriber, WtmTranscriber)


def test_engine_registry_exposes_visible_settings_engines(monkeypatch) -> None:
    monkeypatch.setattr(engine_registry, "is_wtm_available", lambda: True)
    monkeypatch.setattr(engine_registry, "is_whisper_available", lambda: True)
    monkeypatch.setattr(
        engine_registry,
        "cohere_availability_reason",
        lambda: "the optional 'cohere' Python SDK is not installed.",
    )
    monkeypatch.setattr(
        engine_registry,
        "parakeet_availability_reason",
        lambda: "Parakeet currently requires Linux with an NVIDIA CUDA GPU.",
    )

    options = engine_registry.build_engine_options()

    assert [option["id"] for option in options] == [
        "whisper_mlx",
        "whisper_cpu",
        "cohere",
        "parakeet_tdt_v3",
    ]
    assert [option["label"] for option in options] == [
        "Whisper (MLX / Metal)",
        "Whisper (CPU)",
        "Cohere",
        "Parakeet TDT v3",
    ]
    assert options[0]["local"] is True
    assert options[2]["cloud"] is True
    assert options[2]["implemented"] is True
    assert options[3]["available"] is False
    assert options[3]["implemented"] is True
    assert (
        options[2]["reason"]
        == "the optional 'cohere' Python SDK is not installed."
    )
    assert (
        options[3]["reason"]
        == "Parakeet currently requires Linux with an NVIDIA CUDA GPU."
    )


def test_engine_setting_selects_parakeet_backend(tmp_path: Path, monkeypatch) -> None:
    _write_settings(
        tmp_path,
        {"engine": "parakeet_tdt_v3", "output_formats": ["txt", "json"]},
    )
    monkeypatch.setattr(engine_registry, "parakeet_availability_reason", lambda: None)

    transcriber = resolve_transcriber_with_settings(base_dir=tmp_path, env={})

    assert isinstance(transcriber, ParakeetTranscriber)
    assert transcriber.output_formats == ("txt", "json")


def test_engine_setting_selects_cohere_backend(tmp_path: Path, monkeypatch) -> None:
    _write_settings(
        tmp_path,
        {
            "engine": "cohere",
            "cohere_model": "cohere-transcribe-03-2026",
            "cohere_api_key": "cohere-secret-key",
            "output_formats": ["txt", "json"],
        },
    )
    monkeypatch.setattr(engine_registry, "cohere_availability_reason", lambda: None)

    transcriber = resolve_transcriber_with_settings(base_dir=tmp_path, env={})

    assert isinstance(transcriber, CohereTranscriber)
    assert transcriber.model_name == "cohere-transcribe-03-2026"
    assert transcriber.api_key == "cohere-secret-key"
    assert transcriber.output_formats == ("txt", "json")


def test_backend_aliases_resolve_through_registry() -> None:
    assert engine_registry.resolve_backend_provider("wtm").id == "whisper_mlx"
    assert engine_registry.resolve_backend_provider("openai-whisper").id == "whisper_cpu"
    assert engine_registry.resolve_backend_provider("fake").id == "fake"
    assert engine_registry.resolve_backend_provider("fake", include_hidden=False) is None


def test_resolve_transcriber_supports_legacy_backend_aliases(monkeypatch) -> None:
    monkeypatch.setenv("TRANSCRIBER_BACKEND", "wtm")
    assert isinstance(resolve_transcriber(), WtmTranscriber)

    monkeypatch.setenv("TRANSCRIBER_BACKEND", "whisper")
    assert isinstance(resolve_transcriber(), WhisperTranscriber)

    monkeypatch.setenv("TRANSCRIBER_BACKEND", "fake")
    assert isinstance(resolve_transcriber(), FakeTranscriber)
