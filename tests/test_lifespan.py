from __future__ import annotations

from pathlib import Path
import time

from fastapi.testclient import TestClient

import mlx_ui.app as app_module
import mlx_ui.worker as worker_module
import mlx_ui.result_retention as retention_module


def _configure_app(app, tmp_path: Path, *, worker_enabled: bool) -> None:  # type: ignore[no-untyped-def]
    app.state.base_dir = tmp_path
    app.state.uploads_dir = tmp_path / "uploads"
    app.state.results_dir = tmp_path / "results"
    app.state.db_path = tmp_path / "jobs.db"
    app.state.worker_enabled = worker_enabled
    app.state.update_check_enabled = False


def _wait_for_worker_start(timeout: float = 1.0) -> worker_module.Worker:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        worker = getattr(worker_module, "_worker_instance", None)
        if worker is not None and worker.is_running():
            return worker
        time.sleep(0.01)
    raise AssertionError("Timed out waiting for worker to start.")


def test_testclient_exit_stops_worker_cleanly(tmp_path: Path) -> None:
    app = app_module.create_app()
    _configure_app(app, tmp_path, worker_enabled=True)

    try:
        with TestClient(app):
            _wait_for_worker_start()
            assert worker_module._worker_instance is not None

        assert worker_module._worker_instance is None
    finally:
        worker_module.stop_worker(timeout=1)


def test_testclient_exit_stops_result_retention_service_cleanly(
    tmp_path: Path,
    monkeypatch,
) -> None:
    app = app_module.create_app()
    _configure_app(app, tmp_path, worker_enabled=True)
    services: list[retention_module.ResultRetentionService] = []

    class _TrackingRetentionService(retention_module.ResultRetentionService):
        def __init__(self, *args, **kwargs):  # type: ignore[no-untyped-def]
            super().__init__(*args, interval_seconds=0.02, **kwargs)
            services.append(self)

    monkeypatch.setattr(app_module, "ResultRetentionService", _TrackingRetentionService)
    monkeypatch.setattr(
        retention_module,
        "purge_expired_results_from_settings",
        lambda *_args, **_kwargs: retention_module.ResultRetentionSummary(
            retention_days=3,
            scanned=0,
            expired=0,
            deleted=0,
            missing=0,
            failed=0,
            batches=0,
        ),
    )

    try:
        with TestClient(app):
            deadline = time.monotonic() + 1
            while not services and time.monotonic() < deadline:
                time.sleep(0.01)
            assert services and services[0].is_running()

        assert services[0].is_running() is False
    finally:
        worker_module.stop_worker(timeout=1)


def test_result_retention_runs_when_queue_worker_is_disabled(
    tmp_path: Path,
    monkeypatch,
) -> None:
    app = app_module.create_app()
    _configure_app(app, tmp_path, worker_enabled=False)
    starts: list[bool] = []
    stops: list[bool] = []

    class _TrackingRetentionService:
        def __init__(self, *_args, **_kwargs):  # type: ignore[no-untyped-def]
            pass

        def start(self) -> None:
            starts.append(True)

        def stop(self) -> None:
            stops.append(True)

    monkeypatch.setattr(app_module, "ResultRetentionService", _TrackingRetentionService)

    with TestClient(app):
        assert starts == [True]

    assert stops == [True]


def test_repeated_startup_shutdown_does_not_reuse_stale_worker(tmp_path: Path) -> None:
    app = app_module.create_app()
    _configure_app(app, tmp_path, worker_enabled=True)

    worker_id1: int | None = None
    worker_id2: int | None = None
    try:
        with TestClient(app):
            worker = _wait_for_worker_start()
            worker_id1 = id(worker)

        assert worker_module._worker_instance is None

        with TestClient(app):
            worker = _wait_for_worker_start()
            worker_id2 = id(worker)

        assert worker_module._worker_instance is None
    finally:
        worker_module.stop_worker(timeout=1)

    assert worker_id1 is not None
    assert worker_id2 is not None
    assert worker_id1 != worker_id2


def test_lifespan_resets_live_service_on_shutdown(tmp_path: Path) -> None:
    app = app_module.create_app()
    _configure_app(app, tmp_path, worker_enabled=False)
    sentinel = object()
    app.state.live_service = sentinel

    with TestClient(app):
        assert app.state.live_service is sentinel

    assert app.state.live_service is None
