import json
from pathlib import Path

from fastapi.testclient import TestClient

from mlx_ui.app import app


def _configure_app(tmp_path: Path) -> None:
    app.state.uploads_dir = tmp_path / "data" / "uploads"
    app.state.results_dir = tmp_path / "data" / "results"
    app.state.db_path = tmp_path / "data" / "jobs.db"
    app.state.worker_enabled = False
    app.state.update_check_enabled = False
    app.state.base_dir = tmp_path


def test_settings_defaults(tmp_path: Path, monkeypatch) -> None:
    _configure_app(tmp_path)
    monkeypatch.delenv("DISABLE_UPDATE_CHECK", raising=False)
    monkeypatch.delenv("LOG_LEVEL", raising=False)
    monkeypatch.delenv("WTM_QUICK", raising=False)

    with TestClient(app) as client:
        response = client.get("/api/settings")

    assert response.status_code == 200
    payload = response.json()
    settings = payload["settings"]
    sources = payload["sources"]

    assert settings["update_check_enabled"] is True
    assert settings["log_level"] == "INFO"
    assert settings["wtm_quick"] is False
    assert settings["output_formats"] == ["txt"]

    assert sources["update_check_enabled"] == "default"
    assert sources["log_level"] == "default"
    assert sources["wtm_quick"] == "default"
    assert sources["output_formats"] == "default"

    assert payload["file"]["path"].endswith("data/settings.json")


def test_settings_update_persists(tmp_path: Path, monkeypatch) -> None:
    _configure_app(tmp_path)
    monkeypatch.delenv("LOG_LEVEL", raising=False)
    monkeypatch.delenv("WTM_QUICK", raising=False)

    with TestClient(app) as client:
        response = client.post(
            "/api/settings",
            json={
                "wtm_quick": True,
                "log_level": "DEBUG",
                "output_formats": ["txt", "srt"],
            },
        )

    assert response.status_code == 200
    payload = response.json()
    settings = payload["settings"]

    assert settings["wtm_quick"] is True
    assert settings["log_level"] == "DEBUG"
    assert "srt" in settings["output_formats"]
    assert payload["sources"]["wtm_quick"] == "file"

    settings_path = tmp_path / "data" / "settings.json"
    persisted = json.loads(settings_path.read_text(encoding="utf-8"))
    assert persisted["wtm_quick"] is True
    assert persisted["log_level"] == "DEBUG"


def test_settings_env_override(tmp_path: Path, monkeypatch) -> None:
    _configure_app(tmp_path)
    monkeypatch.setenv("WTM_QUICK", "1")
    monkeypatch.setenv("LOG_LEVEL", "ERROR")

    with TestClient(app) as client:
        response = client.get("/api/settings")

    assert response.status_code == 200
    payload = response.json()
    settings = payload["settings"]
    sources = payload["sources"]

    assert settings["wtm_quick"] is True
    assert settings["log_level"] == "ERROR"
    assert sources["wtm_quick"] == "env"
    assert sources["log_level"] == "env"


def test_settings_rejects_invalid_values(tmp_path: Path) -> None:
    _configure_app(tmp_path)

    with TestClient(app) as client:
        response = client.post("/api/settings", json={"log_level": "LOUD"})

    assert response.status_code == 422


def test_clear_storage_paths(tmp_path: Path) -> None:
    _configure_app(tmp_path)
    uploads_dir = Path(app.state.uploads_dir)
    results_dir = Path(app.state.results_dir)

    (uploads_dir / "job1").mkdir(parents=True, exist_ok=True)
    (uploads_dir / "job1" / "alpha.wav").write_text("data", encoding="utf-8")
    (results_dir / "job1").mkdir(parents=True, exist_ok=True)
    (results_dir / "job1" / "alpha.txt").write_text("data", encoding="utf-8")

    with TestClient(app) as client:
        upload_resp = client.post("/api/settings/clear-uploads")
        results_resp = client.post("/api/settings/clear-results")

    assert upload_resp.status_code == 200
    assert results_resp.status_code == 200
    assert list(uploads_dir.iterdir()) == []
    assert list(results_dir.iterdir()) == []
