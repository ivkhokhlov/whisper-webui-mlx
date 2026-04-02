from datetime import datetime, timezone
import json
import re
from pathlib import Path

from fastapi.testclient import TestClient

from mlx_ui.app import app
from mlx_ui.storage import sanitize_display_path
from mlx_ui.db import JobRecord, init_db, insert_job, list_jobs


def _fake_live_update(
    session_id: str,
    status: str,
    transcript: str,
    received_chunks: int,
    processed_windows: int,
) -> object:
    class _FakeUpdate:
        def to_dict(self_nonlocal) -> dict[str, object]:
            return {
                "session_id": session_id,
                "status": status,
                "transcript": transcript,
                "received_chunks": received_chunks,
                "processed_windows": processed_windows,
                "engine_id": "parakeet_tdt_v3",
                "engine_label": "Parakeet TDT v3",
                "model_id": "nvidia/parakeet-tdt-0.6b-v3",
                "experimental": True,
                "note": "Experimental local-only Parakeet streaming.",
                "error": None,
            }

    return _FakeUpdate()


def _configure_app(tmp_path: Path) -> None:
    app.state.base_dir = tmp_path
    app.state.uploads_dir = tmp_path / "uploads"
    app.state.results_dir = tmp_path / "results"
    app.state.db_path = tmp_path / "jobs.db"
    app.state.worker_enabled = False
    app.state.update_check_enabled = False
    app.state.live_service = None


def test_root_ok(tmp_path: Path) -> None:
    _configure_app(tmp_path)
    with TestClient(app) as client:
        response = client.get("/")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "Queue" in response.text
    assert "History" in response.text


def test_root_modal_hidden_attr_has_explicit_css_guard(tmp_path: Path) -> None:
    _configure_app(tmp_path)
    with TestClient(app) as client:
        response = client.get("/")

    assert response.status_code == 200
    assert ".modal[hidden]" in response.text
    assert "display: none;" in response.text
    assert 'id="preview-modal" hidden' in response.text
    assert 'id="confirm-modal" hidden' in response.text


def test_root_tab_param_sets_active_panel_and_nav(tmp_path: Path) -> None:
    _configure_app(tmp_path)
    with TestClient(app) as client:
        response = client.get("/?tab=history")

    assert response.status_code == 200
    history_link = re.search(r'<a[^>]*data-tab="history"[^>]*>', response.text)
    assert history_link is not None
    assert 'aria-current="page"' in history_link.group(0)

    queue_link = re.search(r'<a[^>]*data-tab="queue"[^>]*>', response.text)
    assert queue_link is not None
    assert 'aria-current="page"' not in queue_link.group(0)

    history_panel = re.search(r'<section[^>]*id="panel-history"[^>]*>', response.text)
    assert history_panel is not None
    assert "hidden" not in history_panel.group(0)

    queue_panel = re.search(r'<section[^>]*id="panel-queue"[^>]*>', response.text)
    assert queue_panel is not None
    assert "hidden" in queue_panel.group(0)


def test_root_unknown_tab_defaults_to_queue(tmp_path: Path) -> None:
    _configure_app(tmp_path)
    with TestClient(app) as client:
        response = client.get("/?tab=not-a-tab")

    assert response.status_code == 200
    queue_link = re.search(r'<a[^>]*data-tab="queue"[^>]*>', response.text)
    assert queue_link is not None
    assert 'aria-current="page"' in queue_link.group(0)

    queue_panel = re.search(r'<section[^>]*id="panel-queue"[^>]*>', response.text)
    assert queue_panel is not None
    assert "hidden" not in queue_panel.group(0)


def test_root_empty_states_visible_when_no_jobs(tmp_path: Path) -> None:
    _configure_app(tmp_path)
    with TestClient(app) as client:
        response = client.get("/")

    assert response.status_code == 200
    assert 'id="upload-title"' in response.text
    assert "Your queue is empty" in response.text

    history_placeholder = re.search(
        r'<div[^>]*id="history-placeholder"[^>]*>', response.text
    )
    assert history_placeholder is not None
    assert "display: none" not in history_placeholder.group(0)

    assert "Your queue is empty" in response.text
    assert "No completed jobs yet" in response.text


def test_root_queue_empty_state_onboarding_copy(tmp_path: Path) -> None:
    _configure_app(tmp_path)
    with TestClient(app) as client:
        response = client.get("/")

    assert response.status_code == 200
    assert 'aria-label="How queue works"' in response.text
    assert "Select files" in response.text
    assert "Select folder" in response.text
    assert "Download transcripts from History when done." in response.text
    assert "1</strong> Select" in response.text
    assert "2</strong> Queue" in response.text
    assert "3</strong> Download" in response.text


def test_root_history_empty_state_has_queue_cta(tmp_path: Path) -> None:
    _configure_app(tmp_path)
    with TestClient(app) as client:
        response = client.get("/")

    assert response.status_code == 200
    assert "No completed jobs yet" in response.text
    assert "Go to Queue" in response.text
    assert "data-history-empty-cta" in response.text


def test_root_includes_upload_ui_structure(tmp_path: Path) -> None:
    _configure_app(tmp_path)
    with TestClient(app) as client:
        response = client.get("/")

    assert response.status_code == 200
    assert 'class="upload-card"' in response.text
    assert 'action="/upload"' in response.text
    assert 'method="post"' in response.text

    assert 'id="file-input"' in response.text
    assert 'name="files"' in response.text
    assert 'accept="audio/*,video/*"' in response.text
    assert 'id="folder-input"' in response.text
    assert "webkitdirectory" in response.text

    assert 'data-upload-pick="files"' in response.text
    assert "Select files" in response.text
    assert 'data-upload-pick="folder"' in response.text
    assert "Select folder" in response.text

    assert 'id="dropzone"' in response.text
    assert 'role="button"' in response.text
    assert "Prefer drag & drop?" in response.text
    assert "Drop files from Finder here." in response.text

    assert 'id="selection-summary"' in response.text
    assert 'id="upload-language"' in response.text
    assert 'name="language"' in response.text
    assert "Detect automatically" in response.text
    assert 'id="upload-submit"' in response.text
    assert 'id="clear-selection"' in response.text


def test_root_worker_card_has_status_and_mode_text(tmp_path: Path) -> None:
    _configure_app(tmp_path)
    with TestClient(app) as client:
        response = client.get("/")

    assert response.status_code == 200
    assert "Worker" in response.text
    assert 'id="worker-status"' in response.text
    assert 'id="worker-queued"' in response.text
    assert "queued" in response.text
    assert "One file at a time" in response.text


def test_root_history_filter_controls_present(tmp_path: Path) -> None:
    _configure_app(tmp_path)
    with TestClient(app) as client:
        response = client.get("/?tab=history")

    assert response.status_code == 200
    assert 'id="history-search"' in response.text
    assert 'id="history-status"' in response.text
    assert 'value="done"' in response.text
    assert 'value="failed"' in response.text
    assert 'id="history-sort"' in response.text
    assert 'value="newest"' in response.text
    assert 'value="oldest"' in response.text
    assert 'value="name"' in response.text
    assert "data-history-clear" in response.text
    assert 'id="history-filter-empty"' in response.text
    assert 'id="history-clear-filters"' in response.text


def test_root_settings_sections_present(tmp_path: Path) -> None:
    _configure_app(tmp_path)
    with TestClient(app) as client:
        response = client.get("/?tab=settings")

    assert response.status_code == 200
    assert 'id="settings-engine-title"' in response.text
    assert 'id="settings-transcription-title"' in response.text
    assert 'id="settings-cloud-title"' in response.text
    assert 'id="settings-notifications-title"' in response.text
    assert 'id="settings-storage-title"' in response.text
    assert 'id="settings-about-title"' in response.text

    assert 'id="engine-select"' in response.text
    assert 'id="default-language"' in response.text
    assert 'id="cohere-api-key"' in response.text
    assert 'id="cohere-model"' in response.text
    assert 'value="whisper_mlx"' in response.text
    assert 'value="whisper_cpu"' in response.text
    assert 'value="cohere"' in response.text
    assert "Cohere runs in the cloud and needs network access." in response.text


def test_root_settings_masks_cohere_api_key(tmp_path: Path) -> None:
    _configure_app(tmp_path)
    settings_path = tmp_path / "data" / "settings.json"
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    token = "cohere-secret-key-123456"
    settings_path.write_text(
        json.dumps({"cohere_api_key": token, "cohere_model": "command-r"}),
        encoding="utf-8",
    )

    with TestClient(app) as client:
        response = client.get("/?tab=settings")

    assert response.status_code == 200
    assert token not in response.text
    assert "*************3456" in response.text


def test_root_queue_hint_stays_local_by_default(tmp_path: Path) -> None:
    _configure_app(tmp_path)

    with TestClient(app) as client:
        response = client.get("/")

    assert response.status_code == 200
    assert "Processed locally. Nothing is uploaded." in response.text


def test_root_queue_hint_mentions_cloud_when_cohere_selected(tmp_path: Path) -> None:
    _configure_app(tmp_path)
    settings_path = tmp_path / "data" / "settings.json"
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    settings_path.write_text(json.dumps({"engine": "cohere"}), encoding="utf-8")

    with TestClient(app) as client:
        response = client.get("/")

    assert response.status_code == 200
    assert (
        "Cloud engine selected. It requires network access and is not local/offline."
        in response.text
    )


def test_root_uses_truthful_local_first_copy(tmp_path: Path) -> None:
    _configure_app(tmp_path)

    with TestClient(app) as client:
        response = client.get("/?tab=settings")

    assert response.status_code == 200
    assert "Local-first transcription" in response.text
    assert (
        "Files are stored here locally; cloud engines can send audio to their provider."
        in response.text
    )
    assert "Local-only transcription" not in response.text
    assert "Local storage and local transcription by default." in response.text


def test_engine_setting_reflects_in_settings_form(tmp_path: Path) -> None:
    _configure_app(tmp_path)
    settings_path = tmp_path / "data" / "settings.json"
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    settings_path.write_text(json.dumps({"engine": "whisper_cpu"}), encoding="utf-8")

    with TestClient(app) as client:
        response = client.get("/?tab=settings")

    assert response.status_code == 200
    option = re.search(r'<option[^>]*value="whisper_cpu"[^>]*>', response.text)
    assert option is not None
    assert "selected" in option.group(0)


def test_root_empty_states_hidden_when_jobs_exist(tmp_path: Path) -> None:
    _configure_app(tmp_path)
    db_path = Path(app.state.db_path)
    init_db(db_path)

    queued_id = "job-queued"
    queued_dir = Path(app.state.uploads_dir) / queued_id
    queued_dir.mkdir(parents=True, exist_ok=True)
    queued_path = queued_dir / "alpha.txt"
    queued_path.write_text("data", encoding="utf-8")
    insert_job(
        db_path,
        JobRecord(
            id=queued_id,
            filename="alpha.txt",
            status="queued",
            created_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            upload_path=str(queued_path),
            language="any",
        ),
    )

    done_id = "job-done"
    done_dir = Path(app.state.uploads_dir) / done_id
    done_dir.mkdir(parents=True, exist_ok=True)
    done_path = done_dir / "beta.txt"
    done_path.write_text("data", encoding="utf-8")
    insert_job(
        db_path,
        JobRecord(
            id=done_id,
            filename="beta.txt",
            status="done",
            created_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            completed_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            upload_path=str(done_path),
            language="any",
        ),
    )

    with TestClient(app) as client:
        response = client.get("/")

    assert response.status_code == 200
    assert 'id="upload-title"' in response.text
    assert "Start a transcription" in response.text

    history_placeholder = re.search(
        r'<div[^>]*id="history-placeholder"[^>]*>', response.text
    )
    assert history_placeholder is not None
    assert "display: none" in history_placeholder.group(0)

    assert "alpha.txt" in response.text
    assert "beta.txt" in response.text


def test_root_shows_engine_and_language_metadata_in_queue_worker_and_history(
    tmp_path: Path,
) -> None:
    _configure_app(tmp_path)
    db_path = Path(app.state.db_path)
    init_db(db_path)

    queued_id = "job-queued"
    queued_dir = Path(app.state.uploads_dir) / queued_id
    queued_dir.mkdir(parents=True, exist_ok=True)
    queued_path = queued_dir / "alpha.wav"
    queued_path.write_text("data", encoding="utf-8")
    insert_job(
        db_path,
        JobRecord(
            id=queued_id,
            filename="alpha.wav",
            status="queued",
            created_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            upload_path=str(queued_path),
            language="fr",
            requested_engine="cohere",
        ),
    )

    running_id = "job-running"
    running_dir = Path(app.state.uploads_dir) / running_id
    running_dir.mkdir(parents=True, exist_ok=True)
    running_path = running_dir / "bravo.wav"
    running_path.write_text("data", encoding="utf-8")
    started_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    insert_job(
        db_path,
        JobRecord(
            id=running_id,
            filename="bravo.wav",
            status="running",
            created_at=started_at,
            started_at=started_at,
            upload_path=str(running_path),
            language="en",
            requested_engine="cohere",
            effective_engine="cohere",
        ),
    )

    done_id = "job-done"
    done_dir = Path(app.state.uploads_dir) / done_id
    done_dir.mkdir(parents=True, exist_ok=True)
    done_path = done_dir / "charlie.wav"
    done_path.write_text("data", encoding="utf-8")
    completed_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    insert_job(
        db_path,
        JobRecord(
            id=done_id,
            filename="charlie.wav",
            status="done",
            created_at=completed_at,
            completed_at=completed_at,
            upload_path=str(done_path),
            language="fr",
            requested_engine="cohere",
            effective_engine="whisper_cpu",
        ),
    )
    results_dir = Path(app.state.results_dir) / done_id
    results_dir.mkdir(parents=True, exist_ok=True)
    (results_dir / "charlie.txt").write_text("transcript", encoding="utf-8")

    with TestClient(app) as client:
        response = client.get("/")

    assert response.status_code == 200
    assert "Cohere cloud" in response.text
    assert "Whisper CPU local" in response.text
    assert "Requested Cohere cloud" in response.text
    assert "Used Whisper CPU local" in response.text
    assert 'id="worker-engine"' in response.text
    assert "Engine: Cohere · cloud" in response.text
    assert "Language: English" in response.text
    assert 'title="Language: French"' in response.text
    assert (
        'data-preview-meta="Requested Cohere · cloud, used Whisper (CPU) · local · Language: French"'
        in response.text
    )


def test_live_page_ok(tmp_path: Path, monkeypatch) -> None:
    _configure_app(tmp_path)
    monkeypatch.setattr(
        "mlx_ui.routers.pages.build_live_transcription_snapshot",
        lambda base_dir: {
            "active": False,
            "enabled": False,
            "supported": False,
            "reason": "Experimental flag is off. Set PARAKEET_LIVE_BETA=1 to try the live beta.",
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
    assert "experimental Parakeet beta" in response.text
    assert "Preview only" in response.text
    assert "Start live capture" in response.text
    assert "Use Queue instead" in response.text
    assert "Experimental flag is off" in response.text


def test_live_page_shows_active_beta_when_enabled(tmp_path: Path, monkeypatch) -> None:
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
    assert "Experimental beta" in response.text
    assert "Ready for experimental capture." in response.text
    assert "Stop capture" in response.text


def test_live_api_uses_injected_service(tmp_path: Path, monkeypatch) -> None:
    _configure_app(tmp_path)

    live_snapshot = {
        "active": True,
        "enabled": True,
        "supported": True,
        "reason": None,
        "note": "Experimental local-only Parakeet streaming.",
        "engine_label": "Parakeet TDT v3",
        "configured_model": "nvidia/parakeet-tdt-0.6b-v3",
        "left_context_secs": 10.0,
        "chunk_secs": 2.0,
        "right_context_secs": 2.0,
        "timeslice_ms": 1000,
        "latency_secs": 4.0,
    }
    monkeypatch.setattr(
        "mlx_ui.routers.live_api.build_live_transcription_snapshot",
        lambda base_dir: live_snapshot,
    )

    class FakeLiveService:
        def __init__(self) -> None:
            self.chunks: list[bytes] = []

        def open_session(self, config):  # type: ignore[no-untyped-def]
            assert config.repo_id == "nvidia/parakeet-tdt-0.6b-v3"
            return _fake_live_update("live-1", "ready", "", 0, 0)

        def append_chunk(self, session_id, payload, *, content_type):  # type: ignore[no-untyped-def]
            assert session_id == "live-1"
            assert content_type == "audio/webm"
            self.chunks.append(payload)
            return _fake_live_update(
                session_id,
                "running",
                "hello world",
                len(self.chunks),
                len(self.chunks),
            )

        def stop_session(self, session_id):  # type: ignore[no-untyped-def]
            assert session_id == "live-1"
            return _fake_live_update("live-1", "stopped", "hello world", 1, 1)

    app.state.live_service = FakeLiveService()

    with TestClient(app) as client:
        start_response = client.post("/api/live/session")
        chunk_response = client.post(
            "/api/live/session/live-1/chunk",
            files={"file": ("chunk.webm", b"abc", "audio/webm")},
        )
        stop_response = client.post("/api/live/session/live-1/stop")

    assert start_response.status_code == 200
    assert start_response.json()["session"]["status"] == "ready"
    assert chunk_response.status_code == 200
    assert chunk_response.json()["session"]["transcript"] == "hello world"
    assert stop_response.status_code == 200
    assert stop_response.json()["session"]["status"] == "stopped"


def test_root_does_not_include_live_nav_entrypoint(tmp_path: Path) -> None:
    _configure_app(tmp_path)
    with TestClient(app) as client:
        response = client.get("/")

    assert response.status_code == 200
    assert 'href="/live"' not in response.text


def test_favicon_ok(tmp_path: Path) -> None:
    _configure_app(tmp_path)
    with TestClient(app) as client:
        response = client.get("/favicon.ico")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("image/")
    assert response.content


def test_settings_update_persists(tmp_path: Path) -> None:
    _configure_app(tmp_path)
    payload = {
        "default_language": "ru",
        "wtm_quick": "1",
        "whisper_model": "base",
        "telegram_token": "token-123",
        "telegram_chat_id": "456",
    }

    with TestClient(app) as client:
        response = client.post("/settings", data=payload, allow_redirects=False)

    assert response.status_code == 303
    settings_path = tmp_path / "data" / "settings.json"
    assert settings_path.exists()
    stored = json.loads(settings_path.read_text(encoding="utf-8"))
    assert stored["default_language"] == "ru"
    assert stored["wtm_quick"] is True
    assert stored["whisper_model"] == "base"
    assert stored["telegram_token"] == "token-123"
    assert stored["telegram_chat_id"] == "456"


def test_settings_update_persists_update_checks_and_log_level(tmp_path: Path) -> None:
    _configure_app(tmp_path)
    payload = {
        "engine": "whisper_cpu",
        "update_check_enabled_present": "1",
        "update_check_enabled": "1",
        "log_level": "debug",
    }

    with TestClient(app) as client:
        response = client.post("/settings", data=payload, allow_redirects=False)

    assert response.status_code == 303
    settings_path = tmp_path / "data" / "settings.json"
    stored = json.loads(settings_path.read_text(encoding="utf-8"))
    assert stored["engine"] == "whisper_cpu"
    assert stored["update_check_enabled"] is True
    assert stored["log_level"] == "DEBUG"


def test_clear_uploads_and_results_endpoints_remove_files(tmp_path: Path) -> None:
    _configure_app(tmp_path)
    uploads_dir = Path(app.state.uploads_dir)
    results_dir = Path(app.state.results_dir)
    uploads_dir.mkdir(parents=True, exist_ok=True)
    results_dir.mkdir(parents=True, exist_ok=True)

    (uploads_dir / "job-a").mkdir(parents=True, exist_ok=True)
    (uploads_dir / "job-a" / "alpha.txt").write_text("data", encoding="utf-8")
    (results_dir / "job-b").mkdir(parents=True, exist_ok=True)
    (results_dir / "job-b" / "beta.txt").write_text("result", encoding="utf-8")

    with TestClient(app) as client:
        uploads_response = client.post("/api/settings/clear-uploads")
        results_response = client.post("/api/settings/clear-results")

    assert uploads_response.status_code == 200
    assert results_response.status_code == 200
    assert list(uploads_dir.iterdir()) == []
    assert list(results_dir.iterdir()) == []


def test_upload_multiple_files_creates_jobs_and_files(tmp_path: Path) -> None:
    _configure_app(tmp_path)
    files = [
        ("files", ("alpha.txt", b"one", "text/plain")),
        ("files", ("beta.txt", b"two", "text/plain")),
    ]

    with TestClient(app) as client:
        response = client.post("/upload", files=files)

    assert response.status_code == 200
    jobs = list_jobs(Path(app.state.db_path))
    assert len(jobs) == 2
    uploads_dir = Path(app.state.uploads_dir)
    for job in jobs:
        job_path = Path(job.upload_path)
        assert job_path.is_file()
        assert job_path.name == Path(job.filename).name
        assert job_path.parent.name == job.id
        assert job_path.is_relative_to(uploads_dir)
        assert job.status == "queued"
        assert job.language == "auto"


def test_upload_persists_requested_engine_from_settings(tmp_path: Path) -> None:
    _configure_app(tmp_path)
    settings_path = tmp_path / "data" / "settings.json"
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    settings_path.write_text(json.dumps({"engine": "whisper_cpu"}), encoding="utf-8")

    with TestClient(app) as client:
        response = client.post(
            "/upload",
            files=[("files", ("alpha.txt", b"one", "text/plain"))],
        )

    assert response.status_code == 200
    jobs = list_jobs(Path(app.state.db_path))
    assert len(jobs) == 1
    assert jobs[0].requested_engine == "whisper_cpu"
    assert jobs[0].effective_engine is None


def test_sanitize_display_path_preserves_relative() -> None:
    assert (
        sanitize_display_path("folder/sub/file.mkv", "file.mkv")
        == "folder/sub/file.mkv"
    )


def test_sanitize_display_path_strips_parent_refs() -> None:
    assert sanitize_display_path("../evil.mkv", "evil.mkv") == "evil.mkv"


def test_sanitize_display_path_windows_path() -> None:
    assert (
        sanitize_display_path(r"C:\\Users\\x\\file.mp3", "file.mp3")
        == "Users/x/file.mp3"
    )


def test_upload_without_language(tmp_path: Path) -> None:
    _configure_app(tmp_path)
    files = [("files", ("alpha.txt", b"one", "text/plain"))]

    with TestClient(app) as client:
        response = client.post("/upload", files=files)

    assert response.status_code == 200
    jobs = list_jobs(Path(app.state.db_path))
    assert len(jobs) == 1
    assert jobs[0].language == "auto"


def test_upload_persists_selected_language(tmp_path: Path) -> None:
    _configure_app(tmp_path)

    with TestClient(app) as client:
        response = client.post(
            "/upload",
            data={"language": "ru"},
            files=[("files", ("alpha.txt", b"one", "text/plain"))],
        )

    assert response.status_code == 200
    jobs = list_jobs(Path(app.state.db_path))
    assert len(jobs) == 1
    assert jobs[0].language == "ru"


def test_upload_uses_saved_default_language_when_form_omits_it(tmp_path: Path) -> None:
    _configure_app(tmp_path)
    settings_path = tmp_path / "data" / "settings.json"
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    settings_path.write_text(json.dumps({"default_language": "fr"}), encoding="utf-8")

    with TestClient(app) as client:
        response = client.post(
            "/upload",
            files=[("files", ("alpha.txt", b"one", "text/plain"))],
        )

    assert response.status_code == 200
    jobs = list_jobs(Path(app.state.db_path))
    assert len(jobs) == 1
    assert jobs[0].language == "fr"


def test_delete_queued_job_removes_upload(tmp_path: Path) -> None:
    _configure_app(tmp_path)
    db_path = Path(app.state.db_path)
    init_db(db_path)

    job_id = "job-123"
    uploads_dir = Path(app.state.uploads_dir) / job_id
    uploads_dir.mkdir(parents=True, exist_ok=True)
    upload_path = uploads_dir / "alpha.txt"
    upload_path.write_text("data", encoding="utf-8")

    job = JobRecord(
        id=job_id,
        filename="alpha.txt",
        status="queued",
        created_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        upload_path=str(upload_path),
        language="any",
    )
    insert_job(db_path, job)

    with TestClient(app) as client:
        response = client.delete(f"/api/jobs/{job_id}")

    assert response.status_code == 200
    assert list_jobs(db_path) == []
    assert not upload_path.exists()
    assert not uploads_dir.exists()


def test_delete_history_job_removes_results(tmp_path: Path) -> None:
    _configure_app(tmp_path)
    db_path = Path(app.state.db_path)
    init_db(db_path)

    job_id = "job-history"
    uploads_dir = Path(app.state.uploads_dir) / job_id
    uploads_dir.mkdir(parents=True, exist_ok=True)
    upload_path = uploads_dir / "alpha.txt"
    upload_path.write_text("data", encoding="utf-8")

    job = JobRecord(
        id=job_id,
        filename="alpha.txt",
        status="done",
        created_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        upload_path=str(upload_path),
        language="any",
        completed_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
    )
    insert_job(db_path, job)

    results_dir = Path(app.state.results_dir) / job_id
    results_dir.mkdir(parents=True, exist_ok=True)
    (results_dir / "alpha.txt").write_text("transcript", encoding="utf-8")

    with TestClient(app) as client:
        response = client.delete(f"/api/history/{job_id}")

    assert response.status_code == 200
    assert list_jobs(db_path) == []
    assert not results_dir.exists()
    assert not upload_path.exists()
    assert not uploads_dir.exists()


def test_delete_history_job_rejects_queue(tmp_path: Path) -> None:
    _configure_app(tmp_path)
    db_path = Path(app.state.db_path)
    init_db(db_path)

    job_id = "job-queued"
    uploads_dir = Path(app.state.uploads_dir) / job_id
    uploads_dir.mkdir(parents=True, exist_ok=True)
    upload_path = uploads_dir / "alpha.txt"
    upload_path.write_text("data", encoding="utf-8")

    job = JobRecord(
        id=job_id,
        filename="alpha.txt",
        status="queued",
        created_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        upload_path=str(upload_path),
        language="any",
    )
    insert_job(db_path, job)

    with TestClient(app) as client:
        response = client.delete(f"/api/history/{job_id}")

    assert response.status_code == 409
    jobs = list_jobs(db_path)
    assert len(jobs) == 1
    assert jobs[0].id == job_id


def test_clear_history_removes_completed(tmp_path: Path) -> None:
    _configure_app(tmp_path)
    db_path = Path(app.state.db_path)
    init_db(db_path)

    done_id = "job-done"
    failed_id = "job-failed"
    queued_id = "job-queued"

    for job_id, status in (
        (done_id, "done"),
        (failed_id, "failed"),
        (queued_id, "queued"),
    ):
        uploads_dir = Path(app.state.uploads_dir) / job_id
        uploads_dir.mkdir(parents=True, exist_ok=True)
        upload_path = uploads_dir / "alpha.txt"
        upload_path.write_text("data", encoding="utf-8")
        job = JobRecord(
            id=job_id,
            filename="alpha.txt",
            status=status,
            created_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            upload_path=str(upload_path),
            language="any",
            completed_at=datetime.now(timezone.utc).isoformat(timespec="seconds")
            if status in {"done", "failed"}
            else None,
        )
        insert_job(db_path, job)
        if status in {"done", "failed"}:
            results_dir = Path(app.state.results_dir) / job_id
            results_dir.mkdir(parents=True, exist_ok=True)
            (results_dir / "alpha.txt").write_text("transcript", encoding="utf-8")

    with TestClient(app) as client:
        response = client.post("/api/history/clear")

    assert response.status_code == 200
    payload = response.json()
    assert payload["deleted_jobs"] == 2
    assert payload["deleted_results"] == 2
    assert payload["failed_results"] == 0

    jobs = list_jobs(db_path)
    assert len(jobs) == 1
    assert jobs[0].id == queued_id
    assert not (Path(app.state.results_dir) / done_id).exists()
    assert not (Path(app.state.results_dir) / failed_id).exists()


def test_jobs_persist_across_restart(tmp_path: Path) -> None:
    _configure_app(tmp_path)
    files = [("files", ("alpha.txt", b"one", "text/plain"))]

    with TestClient(app) as client:
        response = client.post("/upload", files=files)

    assert response.status_code == 200
    with TestClient(app) as client:
        response = client.get("/")

    assert response.status_code == 200
    jobs = list_jobs(Path(app.state.db_path))
    assert len(jobs) == 1
    assert "alpha.txt" in response.text


def test_history_lists_results_and_download_endpoint(tmp_path: Path) -> None:
    _configure_app(tmp_path)
    db_path = Path(app.state.db_path)
    init_db(db_path)

    job_id = "job-123"
    uploads_dir = Path(app.state.uploads_dir) / job_id
    uploads_dir.mkdir(parents=True, exist_ok=True)
    upload_path = uploads_dir / "alpha.txt"
    upload_path.write_text("data", encoding="utf-8")

    job = JobRecord(
        id=job_id,
        filename="alpha.txt",
        status="done",
        created_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        upload_path=str(upload_path),
        language="any",
    )
    insert_job(db_path, job)

    results_dir = Path(app.state.results_dir) / job_id
    results_dir.mkdir(parents=True, exist_ok=True)
    txt_path = results_dir / "alpha.txt"
    txt_path.write_text("transcript", encoding="utf-8")
    srt_path = results_dir / "alpha.srt"
    srt_path.write_text("subtitles", encoding="utf-8")

    with TestClient(app) as client:
        response = client.get("/")

        assert response.status_code == 200
        assert f"/results/{job_id}/alpha.txt" in response.text
        assert f"/results/{job_id}/alpha.srt" in response.text

        download = client.get(f"/results/{job_id}/alpha.txt")
        assert download.status_code == 200
        assert download.text == "transcript"


def test_preview_endpoint_returns_snippet(tmp_path: Path) -> None:
    _configure_app(tmp_path)
    db_path = Path(app.state.db_path)
    init_db(db_path)

    job_id = "job-123"
    uploads_dir = Path(app.state.uploads_dir) / job_id
    uploads_dir.mkdir(parents=True, exist_ok=True)
    upload_path = uploads_dir / "alpha.txt"
    upload_path.write_text("data", encoding="utf-8")

    job = JobRecord(
        id=job_id,
        filename="alpha.txt",
        status="done",
        created_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        upload_path=str(upload_path),
        language="any",
    )
    insert_job(db_path, job)

    results_dir = Path(app.state.results_dir) / job_id
    results_dir.mkdir(parents=True, exist_ok=True)
    content = "a" * 120
    txt_path = results_dir / "alpha.txt"
    txt_path.write_text(content, encoding="utf-8")
    srt_path = results_dir / "alpha.srt"
    srt_path.write_text("subtitles", encoding="utf-8")

    with TestClient(app) as client:
        response = client.get(f"/api/jobs/{job_id}/preview?chars=60")

    assert response.status_code == 200
    payload = response.json()
    assert payload["filename"] == "alpha.txt"
    assert payload["snippet"] == "a" * 60
    assert payload["truncated"] is True


def test_preview_endpoint_handles_missing_results(tmp_path: Path) -> None:
    _configure_app(tmp_path)
    db_path = Path(app.state.db_path)
    init_db(db_path)

    job_id = "job-456"
    uploads_dir = Path(app.state.uploads_dir) / job_id
    uploads_dir.mkdir(parents=True, exist_ok=True)
    upload_path = uploads_dir / "beta.txt"
    upload_path.write_text("data", encoding="utf-8")

    job = JobRecord(
        id=job_id,
        filename="beta.txt",
        status="done",
        created_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        upload_path=str(upload_path),
        language="any",
    )
    insert_job(db_path, job)

    with TestClient(app) as client:
        response = client.get(f"/api/jobs/{job_id}/preview")

    assert response.status_code == 200
    payload = response.json()
    assert payload["filename"] is None
    assert payload["snippet"] == ""
    assert payload["truncated"] is False
