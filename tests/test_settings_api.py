import json
from pathlib import Path

from fastapi.testclient import TestClient

import mlx_ui.engine_registry as engine_registry
from mlx_ui.app import app
from mlx_ui.settings import (
    PARAKEET_LIVE_BETA_ENV,
    build_live_transcription_snapshot,
    build_runtime_metadata,
    list_downloaded_models,
)


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
    monkeypatch.delenv("TRANSCRIBER_BACKEND", raising=False)
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

    with TestClient(app) as client:
        response = client.get("/api/settings")

    assert response.status_code == 200
    payload = response.json()
    settings = payload["settings"]
    sources = payload["sources"]

    assert settings["engine"] == "whisper_mlx"
    assert settings["update_check_enabled"] is True
    assert settings["log_level"] == "INFO"
    assert settings["wtm_quick"] is False
    assert settings["output_formats"] == ["txt"]
    assert settings["default_language"] == "auto"
    assert settings["cohere_model"] == "cohere-transcribe-03-2026"
    assert settings["parakeet_model"] == "nvidia/parakeet-tdt-0.6b-v3"
    assert settings["parakeet_chunk_duration"] == 30
    assert settings["parakeet_overlap_duration"] == 5
    assert settings["parakeet_decoding_mode"] == "greedy"
    assert settings["parakeet_batch_size"] == 1

    assert sources["engine"] == "default"
    assert sources["update_check_enabled"] == "default"
    assert sources["log_level"] == "default"
    assert sources["wtm_quick"] == "default"
    assert sources["output_formats"] == "default"
    assert sources["default_language"] == "default"
    assert sources["cohere_model"] == "default"
    assert sources["parakeet_model"] == "default"
    assert sources["parakeet_chunk_duration"] == "default"
    assert sources["parakeet_overlap_duration"] == "default"
    assert sources["parakeet_decoding_mode"] == "default"
    assert sources["parakeet_batch_size"] == "default"

    assert payload["file"]["path"].endswith("data/settings.json")
    assert payload["options"]["languages"][0] == {
        "id": "auto",
        "label": "Detect automatically",
    }
    assert payload["options"]["parakeet_decoding_modes"] == ["greedy", "beam"]

    engines = {engine["id"]: engine for engine in payload["options"]["engines"]}
    assert engines["whisper_mlx"]["configured"] is True
    assert engines["whisper_mlx"]["local"] is True
    assert engines["cohere"]["available"] is False
    assert engines["cohere"]["cloud"] is True
    assert (
        engines["cohere"]["reason"]
        == "The optional 'cohere' Python SDK is not installed."
    )
    assert engines["parakeet_tdt_v3"]["available"] is False
    assert engines["parakeet_tdt_v3"]["local"] is True
    assert (
        engines["parakeet_tdt_v3"]["reason"]
        == "Parakeet currently requires Linux with an NVIDIA CUDA GPU."
    )
    assert payload["cohere_snapshot"]["configured"] is False
    assert payload["cohere_snapshot"]["available"] is False
    assert payload["cohere_snapshot"]["selected"] is False
    assert payload["cohere_snapshot"]["api_key_masked"] == ""
    assert (
        payload["cohere_snapshot"]["product_note"]
        == "Cohere runs in the cloud and needs network access. It is not a local/offline engine."
    )
    assert payload["local_models"]["whisper"]["configured_model"] == "large-v3-turbo"
    assert payload["local_models"]["whisper"]["configured_model_present"] is False
    assert (
        payload["local_models"]["parakeet"]["configured_model"]
        == "nvidia/parakeet-tdt-0.6b-v3"
    )
    assert payload["local_models"]["parakeet"]["configured_model_present"] is False
    assert payload["local_models"]["selected"] is None


def test_settings_update_persists(tmp_path: Path, monkeypatch) -> None:
    _configure_app(tmp_path)
    monkeypatch.delenv("LOG_LEVEL", raising=False)
    monkeypatch.delenv("WTM_QUICK", raising=False)

    with TestClient(app) as client:
        response = client.post(
            "/api/settings",
            json={
                "engine": "whisper_cpu",
                "wtm_quick": True,
                "log_level": "DEBUG",
                "output_formats": ["txt", "srt"],
                "default_language": "ru",
                "cohere_model": "command-r",
            },
        )

    assert response.status_code == 200
    payload = response.json()
    settings = payload["settings"]

    assert settings["engine"] == "whisper_cpu"
    assert settings["wtm_quick"] is True
    assert settings["log_level"] == "DEBUG"
    assert "srt" in settings["output_formats"]
    assert settings["default_language"] == "ru"
    assert settings["cohere_model"] == "command-r"
    assert payload["sources"]["engine"] == "file"
    assert payload["sources"]["wtm_quick"] == "file"
    assert payload["sources"]["default_language"] == "file"
    assert payload["sources"]["cohere_model"] == "file"

    settings_path = tmp_path / "data" / "settings.json"
    persisted = json.loads(settings_path.read_text(encoding="utf-8"))
    assert persisted["engine"] == "whisper_cpu"
    assert persisted["wtm_quick"] is True
    assert persisted["log_level"] == "DEBUG"
    assert persisted["default_language"] == "ru"
    assert persisted["cohere_model"] == "command-r"


def test_settings_update_persists_parakeet_config(tmp_path: Path) -> None:
    _configure_app(tmp_path)

    with TestClient(app) as client:
        response = client.post(
            "/api/settings",
            json={
                "parakeet_model": "nvidia/parakeet-tdt-0.6b-v3",
                "parakeet_chunk_duration": 45,
                "parakeet_overlap_duration": 8,
                "parakeet_decoding_mode": "beam",
                "parakeet_batch_size": 2,
            },
        )

    assert response.status_code == 200
    payload = response.json()
    settings = payload["settings"]

    assert settings["parakeet_model"] == "nvidia/parakeet-tdt-0.6b-v3"
    assert settings["parakeet_chunk_duration"] == 45
    assert settings["parakeet_overlap_duration"] == 8
    assert settings["parakeet_decoding_mode"] == "beam"
    assert settings["parakeet_batch_size"] == 2
    assert payload["sources"]["parakeet_model"] == "file"
    assert payload["sources"]["parakeet_chunk_duration"] == "file"
    assert payload["sources"]["parakeet_overlap_duration"] == "file"
    assert payload["sources"]["parakeet_decoding_mode"] == "file"
    assert payload["sources"]["parakeet_batch_size"] == "file"

    settings_path = tmp_path / "data" / "settings.json"
    persisted = json.loads(settings_path.read_text(encoding="utf-8"))
    assert persisted["parakeet_model"] == "nvidia/parakeet-tdt-0.6b-v3"
    assert persisted["parakeet_chunk_duration"] == 45
    assert persisted["parakeet_overlap_duration"] == 8
    assert persisted["parakeet_decoding_mode"] == "beam"
    assert persisted["parakeet_batch_size"] == 2


def test_settings_allows_parakeet_engine_selection(tmp_path: Path) -> None:
    _configure_app(tmp_path)

    with TestClient(app) as client:
        response = client.post("/api/settings", json={"engine": "parakeet_tdt_v3"})

    assert response.status_code == 200
    settings_path = tmp_path / "data" / "settings.json"
    persisted = json.loads(settings_path.read_text(encoding="utf-8"))
    assert persisted["engine"] == "parakeet_tdt_v3"


def test_settings_env_override(tmp_path: Path, monkeypatch) -> None:
    _configure_app(tmp_path)
    monkeypatch.setenv("WTM_QUICK", "1")
    monkeypatch.setenv("LOG_LEVEL", "ERROR")
    monkeypatch.setenv("TRANSCRIBER_BACKEND", "whisper")
    monkeypatch.setenv("COHERE_MODEL", "command-r-plus")

    with TestClient(app) as client:
        response = client.get("/api/settings")

    assert response.status_code == 200
    payload = response.json()
    settings = payload["settings"]
    sources = payload["sources"]

    assert settings["engine"] == "whisper_cpu"
    assert settings["wtm_quick"] is True
    assert settings["log_level"] == "ERROR"
    assert settings["cohere_model"] == "command-r-plus"
    assert sources["engine"] == "env"
    assert sources["wtm_quick"] == "env"
    assert sources["log_level"] == "env"
    assert sources["cohere_model"] == "env"
    engines = {engine["id"]: engine for engine in payload["options"]["engines"]}
    assert engines["whisper_cpu"]["configured"] is True
    assert engines["whisper_mlx"]["configured"] is False


def test_settings_rejects_invalid_values(tmp_path: Path) -> None:
    _configure_app(tmp_path)

    with TestClient(app) as client:
        response = client.post("/api/settings", json={"log_level": "LOUD"})

    assert response.status_code == 422


def test_settings_rejects_invalid_default_language(tmp_path: Path) -> None:
    _configure_app(tmp_path)

    with TestClient(app) as client:
        response = client.post("/api/settings", json={"default_language": "??"})

    assert response.status_code == 422


def test_settings_accepts_and_masks_cohere_api_key(tmp_path: Path) -> None:
    _configure_app(tmp_path)
    api_key = "cohere-secret-key-123456"

    with TestClient(app) as client:
        response = client.post(
            "/api/settings",
            json={
                "cohere_api_key": api_key,
                "cohere_model": "command-r",
            },
        )

    assert response.status_code == 200
    payload = response.json()
    assert "cohere_api_key" not in payload["settings"]
    assert payload["cohere_snapshot"]["configured"] is True
    assert payload["cohere_snapshot"]["api_key_masked"] != api_key
    assert payload["cohere_snapshot"]["api_key_masked"].endswith("3456")

    settings_path = tmp_path / "data" / "settings.json"
    persisted = json.loads(settings_path.read_text(encoding="utf-8"))
    assert persisted["cohere_api_key"] == api_key


def test_settings_api_uses_env_overrides_for_cohere_snapshot(
    tmp_path: Path, monkeypatch
) -> None:
    _configure_app(tmp_path)
    monkeypatch.setenv("TRANSCRIBER_BACKEND", "cohere")
    monkeypatch.setenv("COHERE_API_KEY", "env-cohere-secret")
    monkeypatch.setenv("COHERE_MODEL", "env-command-r")

    with TestClient(app) as client:
        response = client.get("/api/settings")

    assert response.status_code == 200
    payload = response.json()
    assert payload["settings"]["engine"] == "cohere"
    assert payload["settings"]["cohere_model"] == "env-command-r"
    assert "cohere_api_key" not in payload["settings"]
    assert payload["cohere_snapshot"]["configured"] is True
    assert payload["cohere_snapshot"]["selected"] is True
    assert payload["cohere_snapshot"]["source"] == "env"
    assert payload["cohere_snapshot"]["api_key_masked"].endswith("cret")


def test_settings_rejects_invalid_parakeet_values(tmp_path: Path) -> None:
    _configure_app(tmp_path)

    with TestClient(app) as client:
        response = client.post(
            "/api/settings",
            json={
                "parakeet_chunk_duration": 10,
                "parakeet_overlap_duration": 10,
                "parakeet_decoding_mode": "fast",
                "parakeet_batch_size": 0,
            },
        )

    assert response.status_code == 422


def test_settings_accepts_cohere_engine_selection(tmp_path: Path) -> None:
    _configure_app(tmp_path)

    with TestClient(app) as client:
        response = client.post("/api/settings", json={"engine": "cohere"})

    assert response.status_code == 200
    settings_path = tmp_path / "data" / "settings.json"
    persisted = json.loads(settings_path.read_text(encoding="utf-8"))
    assert persisted["engine"] == "cohere"


def test_runtime_metadata_explains_unavailable_configured_engine(
    tmp_path: Path, monkeypatch
) -> None:
    _configure_app(tmp_path)
    monkeypatch.setattr(
        engine_registry,
        "cohere_availability_reason",
        lambda: "the optional 'cohere' Python SDK is not installed.",
    )
    settings_path = tmp_path / "data" / "settings.json"
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    settings_path.write_text(json.dumps({"engine": "cohere"}), encoding="utf-8")

    metadata = build_runtime_metadata(base_dir=tmp_path)
    engines = {engine["id"]: engine for engine in metadata["about"]["engines"]}

    assert metadata["about"]["configured_engine"]["id"] == "cohere"
    assert (
        metadata["about"]["configured_engine"]["reason"]
        == "The optional 'cohere' Python SDK is not installed."
    )
    assert (
        metadata["about"]["engine_note"]
        == "Cohere is unavailable. The optional 'cohere' Python SDK is not installed."
    )
    assert engines["cohere"]["configured"] is True
    assert engines["cohere"]["available"] is False
    assert metadata["cohere"]["selected"] is True


def test_runtime_metadata_explains_unavailable_parakeet_environment(
    tmp_path: Path, monkeypatch
) -> None:
    _configure_app(tmp_path)
    monkeypatch.setattr(
        engine_registry,
        "parakeet_availability_reason",
        lambda: "Parakeet currently requires Linux with an NVIDIA CUDA GPU.",
    )
    settings_path = tmp_path / "data" / "settings.json"
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    settings_path.write_text(
        json.dumps({"engine": "parakeet_tdt_v3"}),
        encoding="utf-8",
    )

    metadata = build_runtime_metadata(base_dir=tmp_path)
    engines = {engine["id"]: engine for engine in metadata["about"]["engines"]}

    assert metadata["about"]["configured_engine"]["id"] == "parakeet_tdt_v3"
    assert (
        metadata["about"]["configured_engine"]["reason"]
        == "Parakeet currently requires Linux with an NVIDIA CUDA GPU."
    )
    assert (
        metadata["about"]["engine_note"]
        == "Parakeet TDT v3 is unavailable. Parakeet currently requires Linux with an NVIDIA CUDA GPU."
    )
    assert engines["parakeet_tdt_v3"]["configured"] is True
    assert engines["parakeet_tdt_v3"]["available"] is False
    assert engines["parakeet_tdt_v3"]["active"] is False


def test_live_snapshot_reports_flag_and_environment_requirements(
    tmp_path: Path, monkeypatch
) -> None:
    _configure_app(tmp_path)
    monkeypatch.delenv(PARAKEET_LIVE_BETA_ENV, raising=False)
    monkeypatch.setattr(
        engine_registry,
        "parakeet_availability_reason",
        lambda: "Parakeet currently requires Linux with an NVIDIA CUDA GPU.",
    )

    disabled = build_live_transcription_snapshot(base_dir=tmp_path)

    assert disabled["enabled"] is False
    assert disabled["active"] is False
    assert PARAKEET_LIVE_BETA_ENV in str(disabled["reason"])

    monkeypatch.setenv(PARAKEET_LIVE_BETA_ENV, "1")
    enabled = build_live_transcription_snapshot(base_dir=tmp_path)

    assert enabled["enabled"] is True
    assert enabled["supported"] is False
    assert enabled["active"] is False
    assert "Parakeet currently requires Linux with an NVIDIA CUDA GPU" in str(
        enabled["reason"]
    )


def test_downloaded_models_only_lists_whisper_models(
    tmp_path: Path, monkeypatch
) -> None:
    cache_root = tmp_path / "cache"
    whisper_cache = cache_root / "whisper"
    hf_cache = cache_root / "huggingface" / "hub"
    whisper_cache.mkdir(parents=True, exist_ok=True)
    hf_cache.mkdir(parents=True, exist_ok=True)
    (whisper_cache / "large-v3-turbo.pt").write_text("ok", encoding="utf-8")
    (hf_cache / "models--openai--whisper-large-v3").mkdir(parents=True, exist_ok=True)
    (hf_cache / "models--openai--whisper-large-v3" / "snapshots" / "abc123").mkdir(
        parents=True, exist_ok=True
    )
    (hf_cache / "models--nvidia--parakeet-tdt-0.6b-v3").mkdir(
        parents=True,
        exist_ok=True,
    )
    (hf_cache / "models--nvidia--parakeet-tdt-0.6b-v3" / "snapshots" / "def456").mkdir(
        parents=True, exist_ok=True
    )
    monkeypatch.setenv("XDG_CACHE_HOME", str(cache_root))

    models = list_downloaded_models()

    assert models == ["large-v3-turbo", "openai/whisper-large-v3"]


def test_runtime_metadata_reports_local_model_visibility_and_selected_readiness(
    tmp_path: Path, monkeypatch
) -> None:
    _configure_app(tmp_path)
    monkeypatch.setattr(engine_registry, "is_whisper_available", lambda: True)
    monkeypatch.setattr(engine_registry, "parakeet_availability_reason", lambda: None)
    settings_path = tmp_path / "data" / "settings.json"
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    settings_path.write_text(
        json.dumps(
            {
                "engine": "whisper_cpu",
                "whisper_model": "large-v3-turbo",
                "parakeet_model": "nvidia/parakeet-tdt-0.6b-v3",
            }
        ),
        encoding="utf-8",
    )
    cache_root = tmp_path / "cache"
    whisper_cache = cache_root / "whisper"
    hf_cache = cache_root / "huggingface" / "hub"
    whisper_cache.mkdir(parents=True, exist_ok=True)
    hf_cache.mkdir(parents=True, exist_ok=True)
    (whisper_cache / "large-v3-turbo.pt").write_text("ok", encoding="utf-8")
    (hf_cache / "models--nvidia--parakeet-tdt-0.6b-v3" / "snapshots" / "def456").mkdir(
        parents=True, exist_ok=True
    )
    monkeypatch.setenv("XDG_CACHE_HOME", str(cache_root))

    metadata = build_runtime_metadata(base_dir=tmp_path)

    whisper = metadata["local_models"]["whisper"]
    parakeet = metadata["local_models"]["parakeet"]
    selected = metadata["about"]["selected_local_model"]

    assert whisper["models"] == ["large-v3-turbo"]
    assert whisper["configured_model_present"] is True
    assert whisper["selected"] is True
    assert parakeet["models"] == ["nvidia/parakeet-tdt-0.6b-v3"]
    assert parakeet["configured_model_present"] is True
    assert selected == {
        "family": "whisper",
        "engine_id": "whisper_cpu",
        "engine_label": "Whisper (CPU)",
        "model_id": "large-v3-turbo",
        "present": True,
        "note": "Configured Whisper model appears to be present locally.",
    }


def test_runtime_metadata_reports_missing_selected_local_model_download_need(
    tmp_path: Path, monkeypatch
) -> None:
    _configure_app(tmp_path)
    monkeypatch.setattr(engine_registry, "parakeet_availability_reason", lambda: None)
    settings_path = tmp_path / "data" / "settings.json"
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    settings_path.write_text(
        json.dumps(
            {
                "engine": "parakeet_tdt_v3",
                "parakeet_model": "nvidia/parakeet-tdt-0.6b-v3",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))

    metadata = build_runtime_metadata(base_dir=tmp_path)

    selected = metadata["about"]["selected_local_model"]
    assert selected["engine_id"] == "parakeet_tdt_v3"
    assert selected["present"] is False
    assert "may download on first use" in selected["note"]


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


def test_settings_api_includes_masked_telegram_snapshot(
    tmp_path: Path, monkeypatch
) -> None:
    _configure_app(tmp_path)
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)

    settings_path = tmp_path / "data" / "settings.json"
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    token = "123456:ABCDEFSECRET"
    chat_id = "-1001234567890"
    settings_path.write_text(
        json.dumps({"telegram_token": token, "telegram_chat_id": chat_id}),
        encoding="utf-8",
    )

    with TestClient(app) as client:
        response = client.get("/api/settings")

    assert response.status_code == 200
    payload = response.json()
    assert "telegram_snapshot" in payload
    assert "telegram_token" not in payload["settings"]
    assert "telegram_chat_id" not in payload["settings"]

    telegram = payload["telegram_snapshot"]
    assert telegram["configured"] is True
    assert telegram["source"] == "file"
    assert telegram["token_masked"] != token
    assert telegram["chat_id_masked"] != chat_id
