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


def test_live_page_uses_one_clear_beta_notice_without_extra_metrics(
    tmp_path: Path, monkeypatch
) -> None:
    _configure_app(tmp_path)
    monkeypatch.setattr(
        "mlx_ui.routers.pages.build_live_transcription_snapshot",
        lambda base_dir: {
            "active": False,
            "enabled": False,
            "supported": False,
            "reason": "Experimental flag is off. Set PARAKEET_LIVE_BETA=1 to try the Parakeet live beta on a supported machine (experimental).",
            "note": "Experimental local-only Parakeet streaming.",
            "engine_label": "Parakeet TDT v3",
            "configured_model": "nvidia/parakeet-tdt-0.6b-v3",
            "latency_secs": 4.0,
            "timeslice_ms": 1000,
        },
    )

    with TestClient(app) as client:
        response = client.get("/live")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "Live preview" in response.text
    assert "Not saved to History yet." in response.text
    assert "Supported local setups only." in response.text
    assert "Set PARAKEET_LIVE_BETA=1" in response.text
    assert "Chunks:" not in response.text
    assert "Windows:" not in response.text
    assert "theoretical latency" not in response.text
    assert "~4.0s latency" not in response.text


def test_live_page_active_state_keeps_one_status_action_and_transcript_area(
    tmp_path: Path, monkeypatch
) -> None:
    _configure_app(tmp_path)
    monkeypatch.setattr(
        "mlx_ui.routers.pages.build_live_transcription_snapshot",
        lambda base_dir: {
            "active": True,
            "enabled": True,
            "supported": True,
            "reason": None,
            "note": "Experimental local-only Parakeet streaming.",
            "engine_label": "Parakeet TDT v3",
            "configured_model": "nvidia/parakeet-tdt-0.6b-v3",
            "latency_secs": 4.0,
            "timeslice_ms": 1000,
        },
    )

    with TestClient(app) as client:
        response = client.get("/live")

    assert response.status_code == 200
    assert "Ready locally" in response.text
    assert "Ready for live capture." in response.text
    assert "Allow microphone access, then speak." in response.text
    assert "Waiting for microphone input." in response.text
    assert "Parakeet TDT v3 · Local session only" in response.text
    assert "Saved transcripts" in response.text
    assert "Current beta scope" not in response.text
    assert "theoretical latency" not in response.text
    assert "~4.0s latency" not in response.text
    assert "Chunks:" not in response.text
    assert "Windows:" not in response.text
