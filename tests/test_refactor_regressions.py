from __future__ import annotations

from datetime import datetime, timezone
import os
from pathlib import Path
import sqlite3
import subprocess
import sys

from fastapi.testclient import TestClient

import mlx_ui.app as app_module
import mlx_ui.app_context as app_context
import mlx_ui.engine_registry as engine_registry
import mlx_ui.engine_resolution as engine_resolution
import mlx_ui.runtime_metadata as runtime_metadata
import mlx_ui.settings as settings_facade
import mlx_ui.settings_schema as settings_schema
import mlx_ui.settings_store as settings_store
import mlx_ui.transcriber as transcriber_facade
from mlx_ui.db import (
    JobRecord,
    claim_next_job,
    init_db,
    insert_job,
    mark_job_running,
)


ROOT_DIR = Path(__file__).resolve().parents[1]


def test_run_sh_is_thin_wrapper_and_help_works() -> None:
    run_sh = ROOT_DIR / "run.sh"
    source = run_sh.read_text(encoding="utf-8")

    assert "scripts/setup_and_run.sh" in source
    assert '"$@"' in source
    assert "exec " in source

    result = subprocess.run(
        ["bash", str(run_sh), "--help"],
        capture_output=True,
        text=True,
        check=True,
    )
    assert "macOS arm64   -> Whisper MLX" in result.stdout
    assert "--with-cohere" in result.stdout


def test_packaged_runtime_defaults_do_not_use_repo_root(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv(app_context.RUNTIME_MODE_ENV, "packaged")
    monkeypatch.setenv(app_context.PACKAGED_BUNDLE_ID_ENV, "com.whisperwebui.mlx.test")
    monkeypatch.setenv("HOME", str(tmp_path))

    expected = app_context.resolve_runtime_paths(
        env=dict(os.environ),
        platform=sys.platform,
        home_dir=tmp_path,
    )

    app = app_module.create_app()

    assert Path(app.state.base_dir) == expected.base_dir
    assert Path(app.state.db_path) == expected.db_path
    assert Path(app.state.uploads_dir) == expected.uploads_dir
    assert Path(app.state.results_dir) == expected.results_dir
    assert not Path(app.state.base_dir).is_relative_to(ROOT_DIR)


def test_create_app_lifespan_runs_startup_tasks(tmp_path: Path, monkeypatch) -> None:
    calls: list[tuple[str, object]] = []

    def _record(name: str, *args: object) -> None:
        calls.append((name, args))

    monkeypatch.setattr(
        app_module,
        "configure_logging",
        lambda base_dir: _record("configure_logging", Path(base_dir)),
    )
    monkeypatch.setattr(
        app_module,
        "init_db",
        lambda db_path: _record("init_db", Path(db_path)),
    )
    monkeypatch.setattr(
        app_module,
        "recover_running_jobs",
        lambda db_path: (_record("recover_running_jobs", Path(db_path)) or 0),
    )
    monkeypatch.setattr(
        app_module,
        "start_worker",
        lambda db_path, uploads_dir, results_dir, base_dir=None: _record(
            "start_worker",
            Path(db_path),
            Path(uploads_dir),
            Path(results_dir),
            Path(base_dir) if base_dir is not None else None,
        ),
    )
    monkeypatch.setattr(
        app_module,
        "build_settings_snapshot",
        lambda base_dir: (
            _record("build_settings_snapshot", Path(base_dir))
            or {"settings": {"update_check_enabled": True}}
        ),
    )
    monkeypatch.setattr(app_module, "is_update_check_disabled", lambda: False)

    thread_started = {"started": False}
    thread_created: dict[str, object] = {}

    class _DummyThread:
        def __init__(self, *, target, kwargs, name, daemon):  # type: ignore[no-untyped-def]
            thread_created.update(
                {
                    "target": target,
                    "kwargs": dict(kwargs or {}),
                    "name": name,
                    "daemon": daemon,
                }
            )

        def start(self) -> None:
            thread_started["started"] = True

    monkeypatch.setattr(app_module.threading, "Thread", _DummyThread)

    app = app_module.create_app()
    app.state.base_dir = tmp_path
    app.state.db_path = tmp_path / "jobs.db"
    app.state.uploads_dir = tmp_path / "uploads"
    app.state.results_dir = tmp_path / "results"
    app.state.worker_enabled = True
    app.state.update_check_enabled = True

    with TestClient(app) as client:
        client.get("/favicon.ico")

    call_names = [name for name, _args in calls]
    assert call_names[:3] == [
        "configure_logging",
        "init_db",
        "recover_running_jobs",
    ]
    assert "start_worker" in call_names
    assert "build_settings_snapshot" in call_names
    assert thread_started["started"] is True
    assert thread_created.get("name") == "mlx-ui-update-check"


def test_create_app_does_not_use_deprecated_on_event_startup() -> None:
    source = Path(app_module.__file__).read_text(encoding="utf-8")
    assert '.on_event("startup")' not in source
    assert "lifespan=_lifespan" in source


def test_app_includes_expected_routes_and_modules() -> None:
    paths = {}
    for route in app_module.app.router.routes:
        path = getattr(route, "path", None)
        methods = getattr(route, "methods", None)
        endpoint = getattr(route, "endpoint", None)
        if isinstance(path, str) and methods and endpoint:
            for method in methods:
                paths[(method, path)] = endpoint

    assert ("GET", "/") in paths
    assert ("GET", "/live") in paths
    assert ("GET", "/api/settings") in paths
    assert ("POST", "/api/settings") in paths
    assert ("GET", "/api/state") in paths
    assert ("POST", "/upload") in paths
    assert ("POST", "/api/live/session") in paths

    assert paths[("GET", "/")].__module__ == "mlx_ui.routers.pages"
    assert paths[("GET", "/api/settings")].__module__ == "mlx_ui.routers.settings_api"
    assert paths[("GET", "/api/state")].__module__ == "mlx_ui.routers.jobs_api"
    assert paths[("POST", "/api/live/session")].__module__ == "mlx_ui.routers.live_api"


def test_settings_facade_reexports_new_modules() -> None:
    assert (
        settings_facade.CONFIGURABLE_ENGINE_CHOICES
        is settings_schema.CONFIGURABLE_ENGINE_CHOICES
    )
    assert settings_facade.normalize_log_level is settings_schema.normalize_log_level
    assert (
        settings_facade.validate_settings_payload
        is settings_schema.validate_settings_payload
    )

    assert settings_facade.get_settings_path is settings_store.get_settings_path
    assert settings_facade.read_settings_file is settings_store.read_settings_file
    assert settings_facade.write_settings_file is settings_store.write_settings_file
    assert settings_facade.update_settings_file is settings_store.update_settings_file

    assert (
        settings_facade.build_runtime_metadata
        is runtime_metadata.build_runtime_metadata
    )
    assert (
        settings_facade.build_settings_snapshot
        is runtime_metadata.build_settings_snapshot
    )

    assert (
        settings_facade.ResolvedTranscriberSettings
        is engine_resolution.ResolvedTranscriberSettings
    )
    assert (
        settings_facade.resolve_job_transcriber_spec_with_settings
        is engine_resolution.resolve_job_transcriber_spec_with_settings
    )


def test_engine_registry_factories_return_provider_package_classes(monkeypatch) -> None:
    wtm = engine_registry.create_transcriber(
        engine_registry.WHISPER_MLX_ENGINE,
        implementation_id=engine_registry.WTM_BACKEND,
    )
    assert wtm.__class__.__module__ == "mlx_ui.engines.whisper_mlx"

    whisper_cpu = engine_registry.create_transcriber(
        engine_registry.WHISPER_CPU_ENGINE,
        implementation_id=engine_registry.WHISPER_BACKEND,
    )
    assert whisper_cpu.__class__.__module__ == "mlx_ui.engines.whisper_cpu"

    cohere = engine_registry.create_transcriber(
        engine_registry.COHERE_ENGINE,
        implementation_id=engine_registry.COHERE_ENGINE,
    )
    assert cohere.__class__.__module__ == "mlx_ui.engines.cohere"

    monkeypatch.setenv(engine_registry.PARAKEET_NEMO_CUDA_EXPERIMENTAL_ENV, "1")
    parakeet = engine_registry.create_transcriber(
        engine_registry.PARAKEET_TDT_V3_ENGINE,
        implementation_id=engine_registry.PARAKEET_NEMO_CUDA_BACKEND,
    )
    assert (
        parakeet.__class__.__module__
        == "mlx_ui.engines.parakeet_nemo_cuda_experimental"
    )

    parakeet_mlx = engine_registry.create_transcriber(
        engine_registry.PARAKEET_TDT_V3_ENGINE,
        implementation_id=engine_registry.PARAKEET_MLX_BACKEND,
    )
    assert parakeet_mlx.__class__.__module__ == "mlx_ui.engines.parakeet_mlx"

    assert transcriber_facade.WtmTranscriber is wtm.__class__
    assert transcriber_facade.WhisperTranscriber is whisper_cpu.__class__
    assert transcriber_facade.CohereTranscriber is cohere.__class__
    assert transcriber_facade.ParakeetNemoCudaTranscriber is parakeet.__class__
    assert transcriber_facade.ParakeetTranscriber is parakeet.__class__
    assert transcriber_facade.ParakeetMlxTranscriber is parakeet_mlx.__class__


def test_claim_next_job_reserves_without_setting_started_at(tmp_path: Path) -> None:
    db_path = tmp_path / "jobs.db"
    uploads_dir = tmp_path / "uploads" / "job-1"
    uploads_dir.mkdir(parents=True, exist_ok=True)
    upload_path = uploads_dir / "alpha.wav"
    upload_path.write_text("data", encoding="utf-8")
    init_db(db_path)
    insert_job(
        db_path,
        JobRecord(
            id="job-1",
            filename="alpha.wav",
            status="queued",
            created_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            upload_path=str(upload_path),
            language="en",
        ),
    )

    claimed = claim_next_job(db_path)
    assert claimed is not None
    assert claimed.status == "running"  # mapped from reserved for UI compatibility
    assert claimed.started_at is None
    assert claimed.effective_engine is None
    assert claimed.effective_implementation_id is None

    with sqlite3.connect(db_path) as connection:
        row = connection.execute(
            """
            SELECT status, started_at, effective_engine, effective_implementation_id
            FROM jobs
            WHERE id = ?
            """,
            ("job-1",),
        ).fetchone()
    assert row == ("reserved", None, None, None)

    started_at = "2024-01-01T00:00:00+00:00"
    assert mark_job_running(
        db_path,
        "job-1",
        started_at=started_at,
        effective_engine="whisper_mlx",
        effective_implementation_id="wtm",
    )

    with sqlite3.connect(db_path) as connection:
        row = connection.execute(
            """
            SELECT status, started_at, effective_engine, effective_implementation_id
            FROM jobs
            WHERE id = ?
            """,
            ("job-1",),
        ).fetchone()
    assert row == ("running", started_at, "whisper_mlx", "wtm")


def test_claim_next_job_blocks_when_reserved_exists(tmp_path: Path) -> None:
    db_path = tmp_path / "jobs.db"
    init_db(db_path)

    insert_job(
        db_path,
        JobRecord(
            id="job-reserved",
            filename="alpha.wav",
            status="reserved",
            created_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            upload_path="x",
            language="en",
        ),
    )
    insert_job(
        db_path,
        JobRecord(
            id="job-queued",
            filename="beta.wav",
            status="queued",
            created_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            upload_path="y",
            language="en",
        ),
    )

    assert claim_next_job(db_path) is None


def test_templates_wire_partials() -> None:
    templates_dir = ROOT_DIR / "mlx_ui" / "templates"
    index_template = templates_dir / "index.html"
    live_template = templates_dir / "live.html"

    index_source = index_template.read_text(encoding="utf-8")
    assert '{% include "partials/index/head.html" %}' in index_source
    assert '{% include "partials/index/panel_queue.html" %}' in index_source
    assert '{% include "partials/index/panel_history.html" %}' in index_source
    assert '{% include "partials/index/panel_settings.html" %}' in index_source
    assert '{% include "partials/index/modals.html" %}' in index_source
    assert '{% include "partials/index/script.html" %}' in index_source

    live_source = live_template.read_text(encoding="utf-8")
    assert '{% include "partials/live/head.html" %}' in live_source
    assert '{% include "partials/live/hero.html" %}' in live_source
    assert '{% include "partials/live/controls.html" %}' in live_source
    assert '{% include "partials/live/transcript_panel.html" %}' in live_source
    assert '{% include "partials/live/beta_notes.html" %}' in live_source
    assert '{% include "partials/live/script.html" %}' in live_source

    for relative in [
        "partials/index/head.html",
        "partials/index/shell_start.html",
        "partials/index/panel_queue.html",
        "partials/index/panel_history.html",
        "partials/index/panel_settings.html",
        "partials/index/modals.html",
        "partials/index/script.html",
        "partials/live/head.html",
        "partials/live/hero.html",
        "partials/live/controls.html",
        "partials/live/transcript_panel.html",
        "partials/live/beta_notes.html",
        "partials/live/script.html",
    ]:
        assert (templates_dir / relative).is_file()
