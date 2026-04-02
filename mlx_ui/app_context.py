from __future__ import annotations

from contextvars import ContextVar
from pathlib import Path

from fastapi import FastAPI, Request

from mlx_ui.live_transcription import LiveTranscriptionService

BASE_DIR = Path(__file__).resolve().parent.parent
DEFAULT_UPLOADS_DIR = BASE_DIR / "data" / "uploads"
DEFAULT_RESULTS_DIR = BASE_DIR / "data" / "results"
DEFAULT_DB_PATH = BASE_DIR / "data" / "jobs.db"

_ACTIVE_APP: ContextVar[FastAPI | None] = ContextVar("mlx_ui_active_app", default=None)
_DEFAULT_APP: FastAPI | None = None


async def bind_active_app(request: Request, call_next):  # type: ignore[no-untyped-def]
    token = _ACTIVE_APP.set(request.app)
    try:
        return await call_next(request)
    finally:
        _ACTIVE_APP.reset(token)


def set_default_app(app: FastAPI) -> None:
    global _DEFAULT_APP
    _DEFAULT_APP = app


def init_app_state(app: FastAPI) -> None:
    app.state.uploads_dir = DEFAULT_UPLOADS_DIR
    app.state.results_dir = DEFAULT_RESULTS_DIR
    app.state.db_path = DEFAULT_DB_PATH
    app.state.base_dir = BASE_DIR
    app.state.worker_enabled = True
    app.state.update_check_enabled = True
    app.state.live_service = None


def set_paths(
    app: FastAPI,
    *,
    base_dir: Path | None = None,
    uploads_dir: Path | None = None,
    results_dir: Path | None = None,
    db_path: Path | None = None,
) -> None:
    if base_dir is not None:
        app.state.base_dir = Path(base_dir)
    if uploads_dir is not None:
        app.state.uploads_dir = Path(uploads_dir)
    if results_dir is not None:
        app.state.results_dir = Path(results_dir)
    if db_path is not None:
        app.state.db_path = Path(db_path)


def set_runtime_flags(
    app: FastAPI,
    *,
    worker_enabled: bool | None = None,
    update_check_enabled: bool | None = None,
) -> None:
    if worker_enabled is not None:
        app.state.worker_enabled = bool(worker_enabled)
    if update_check_enabled is not None:
        app.state.update_check_enabled = bool(update_check_enabled)


def _resolve_app(app: FastAPI | None) -> FastAPI:
    if app is not None:
        return app
    active = _ACTIVE_APP.get()
    if active is not None:
        return active
    if _DEFAULT_APP is not None:
        return _DEFAULT_APP
    raise RuntimeError("FastAPI application is not initialised yet.")


def get_base_dir(app: FastAPI | None = None) -> Path:
    resolved = _resolve_app(app)
    return Path(getattr(resolved.state, "base_dir", BASE_DIR))


def get_db_path(app: FastAPI | None = None) -> Path:
    resolved = _resolve_app(app)
    return Path(getattr(resolved.state, "db_path", DEFAULT_DB_PATH))


def get_uploads_dir(app: FastAPI | None = None) -> Path:
    resolved = _resolve_app(app)
    return Path(getattr(resolved.state, "uploads_dir", DEFAULT_UPLOADS_DIR))


def get_results_dir(app: FastAPI | None = None) -> Path:
    resolved = _resolve_app(app)
    return Path(getattr(resolved.state, "results_dir", DEFAULT_RESULTS_DIR))


def is_worker_enabled(app: FastAPI | None = None) -> bool:
    resolved = _resolve_app(app)
    return bool(getattr(resolved.state, "worker_enabled", True))


def is_update_check_enabled(app: FastAPI | None = None) -> bool:
    resolved = _resolve_app(app)
    return bool(getattr(resolved.state, "update_check_enabled", True))


def get_live_service(app: FastAPI | None = None) -> LiveTranscriptionService:
    resolved = _resolve_app(app)
    service = getattr(resolved.state, "live_service", None)
    if service is None:
        service = LiveTranscriptionService()
        resolved.state.live_service = service
    return service


def reset_live_service(app: FastAPI) -> None:
    app.state.live_service = None
