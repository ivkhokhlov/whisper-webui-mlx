import re
from pathlib import Path

from fastapi.testclient import TestClient

from mlx_ui.app import app
from mlx_ui.transcriber import BACKEND_ENV


def _configure_app(tmp_path: Path) -> None:
    app.state.base_dir = tmp_path
    app.state.uploads_dir = tmp_path / "uploads"
    app.state.results_dir = tmp_path / "results"
    app.state.db_path = tmp_path / "jobs.db"
    app.state.worker_enabled = False
    app.state.update_check_enabled = False
    app.state.live_service = None


def test_settings_prioritizes_transcription_defaults_before_optional_sections(
    tmp_path: Path,
) -> None:
    _configure_app(tmp_path)

    with TestClient(app) as client:
        response = client.get("/?tab=settings")

    assert response.status_code == 200
    text = response.text

    transcription_idx = text.index('id="settings-transcription-title"')
    integrations_idx = text.index('id="settings-integrations-title"')
    storage_idx = text.index('id="settings-storage-title"')
    about_idx = text.index('id="settings-about-title"')

    assert transcription_idx < integrations_idx < storage_idx < about_idx
    assert text.index('id="engine-select"') < text.index('id="cohere-api-key"')
    assert text.index('id="default-language"') < text.index('id="telegram-token"')


def test_settings_moves_low_frequency_controls_into_disclosures(
    tmp_path: Path,
) -> None:
    _configure_app(tmp_path)

    with TestClient(app) as client:
        response = client.get("/?tab=settings")

    assert response.status_code == 200
    assert 'data-settings-local-options' in response.text
    assert "Local engine options" in response.text
    assert "Advanced Cohere options" in response.text
    assert "More cleanup tools" in response.text

    advanced = re.search(
        r'<details[^>]*class="settings-disclosure is-advanced"[^>]*data-settings-advanced[^>]*>',
        response.text,
    )
    assert advanced is not None
    assert " open" not in advanced.group(0)


def test_settings_demotes_source_metadata_in_default_view(tmp_path: Path) -> None:
    _configure_app(tmp_path)

    with TestClient(app) as client:
        response = client.get("/?tab=settings")

    assert response.status_code == 200
    assert "data-settings-source-pill" not in response.text
    assert "data-cohere-source-pill" not in response.text
    assert "data-telegram-source-pill" not in response.text
    assert "Engine changes take effect after restart." in response.text
    assert "These changes apply after restart." in response.text


def test_settings_env_locked_fields_explain_why_controls_are_disabled(
    tmp_path: Path, monkeypatch
) -> None:
    _configure_app(tmp_path)
    monkeypatch.setenv(BACKEND_ENV, "whisper_mlx")

    with TestClient(app) as client:
        response = client.get("/?tab=settings")

    assert response.status_code == 200
    engine_select = re.search(r'<select[^>]*id="engine-select"[^>]*>', response.text)
    assert engine_select is not None
    assert "disabled" in engine_select.group(0)
    assert f"Managed by environment (<code>{BACKEND_ENV}</code>)." in response.text
