import json
from pathlib import Path

import mlx_ui.settings as settings
from mlx_ui.settings import resolve_transcriber_with_settings
from mlx_ui.transcriber import WhisperTranscriber, WtmTranscriber


def _write_settings(tmp_path: Path, payload: dict[str, object]) -> None:
    settings_path = tmp_path / "data" / "settings.json"
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    settings_path.write_text(json.dumps(payload), encoding="utf-8")


def test_engine_setting_selects_mlx_backend(tmp_path: Path, monkeypatch) -> None:
    _write_settings(tmp_path, {"engine": "whisper_mlx"})
    monkeypatch.setattr(settings, "is_wtm_available", lambda: True)
    transcriber = resolve_transcriber_with_settings(base_dir=tmp_path, env={})
    assert isinstance(transcriber, WtmTranscriber)


def test_engine_setting_selects_cpu_backend(tmp_path: Path, monkeypatch) -> None:
    _write_settings(tmp_path, {"engine": "whisper_cpu"})
    monkeypatch.setattr(settings, "is_whisper_available", lambda: True)
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
