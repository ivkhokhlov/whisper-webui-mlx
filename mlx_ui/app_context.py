from __future__ import annotations

from collections.abc import Mapping
from contextvars import ContextVar
from dataclasses import dataclass
import os
from pathlib import Path
import sys

from fastapi import FastAPI, Request

from mlx_ui.live_transcription import LiveTranscriptionService

REPO_DIR = Path(__file__).resolve().parent.parent

RUNTIME_MODE_ENV = "MLX_UI_RUNTIME_MODE"
RUNTIME_MODE_DEV = "dev"
RUNTIME_MODE_PACKAGED = "packaged"

PACKAGED_BUNDLE_ID_ENV = "MLX_UI_BUNDLE_ID"
DEFAULT_BUNDLE_ID = "com.whisperwebui.mlx"


@dataclass(frozen=True)
class RuntimePaths:
    mode: str
    base_dir: Path
    uploads_dir: Path
    results_dir: Path
    db_path: Path


def resolve_runtime_paths(
    env: Mapping[str, str] | None = None,
    *,
    platform: str | None = None,
    home_dir: Path | None = None,
) -> RuntimePaths:
    if env is None:
        env = os.environ
    if platform is None:
        platform = sys.platform
    if home_dir is None:
        home_dir = Path.home()

    mode_value = env.get(RUNTIME_MODE_ENV, "").strip().lower()
    mode = (
        RUNTIME_MODE_PACKAGED
        if mode_value == RUNTIME_MODE_PACKAGED
        else RUNTIME_MODE_DEV
    )

    if mode == RUNTIME_MODE_PACKAGED:
        bundle_id = env.get(PACKAGED_BUNDLE_ID_ENV, "").strip() or DEFAULT_BUNDLE_ID
        if platform == "darwin":
            base_dir = home_dir / "Library" / "Application Support" / bundle_id
        elif platform.startswith("win"):
            base_dir = Path(env.get("APPDATA") or home_dir) / bundle_id
        else:
            xdg_state = env.get("XDG_STATE_HOME") or env.get("XDG_DATA_HOME")
            if xdg_state:
                base_dir = Path(xdg_state) / bundle_id
            else:
                base_dir = home_dir / ".local" / "state" / bundle_id
    else:
        base_dir = REPO_DIR

    uploads_dir = base_dir / "data" / "uploads"
    results_dir = base_dir / "data" / "results"
    db_path = base_dir / "data" / "jobs.db"
    return RuntimePaths(
        mode=mode,
        base_dir=base_dir,
        uploads_dir=uploads_dir,
        results_dir=results_dir,
        db_path=db_path,
    )


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
    paths = resolve_runtime_paths()
    app.state.runtime_mode = paths.mode
    app.state.uploads_dir = paths.uploads_dir
    app.state.results_dir = paths.results_dir
    app.state.db_path = paths.db_path
    app.state.base_dir = paths.base_dir
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
    return Path(getattr(resolved.state, "base_dir", resolve_runtime_paths().base_dir))


def get_db_path(app: FastAPI | None = None) -> Path:
    resolved = _resolve_app(app)
    return Path(getattr(resolved.state, "db_path", resolve_runtime_paths().db_path))


def get_uploads_dir(app: FastAPI | None = None) -> Path:
    resolved = _resolve_app(app)
    return Path(
        getattr(resolved.state, "uploads_dir", resolve_runtime_paths().uploads_dir)
    )


def get_results_dir(app: FastAPI | None = None) -> Path:
    resolved = _resolve_app(app)
    return Path(
        getattr(resolved.state, "results_dir", resolve_runtime_paths().results_dir)
    )


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
