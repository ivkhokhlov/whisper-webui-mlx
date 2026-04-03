import re
from pathlib import Path

from fastapi.testclient import TestClient

from mlx_ui.app import app


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
