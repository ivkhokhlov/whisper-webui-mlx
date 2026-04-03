from __future__ import annotations

from contextlib import asynccontextmanager
import logging
from pathlib import Path
import threading
from typing import AsyncIterator

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from mlx_ui.app_context import (
    bind_active_app,
    get_base_dir,
    get_db_path,
    get_results_dir,
    get_uploads_dir,
    init_app_state,
    is_update_check_enabled,
    is_worker_enabled,
    reset_live_service,
    set_default_app,
)
from mlx_ui.db import init_db, recover_running_jobs
from mlx_ui.hot_folder import HotFolderPaths, start_hot_folder, stop_hot_folder
from mlx_ui.logging_config import configure_logging
from mlx_ui.routers.jobs_api import router as jobs_router
from mlx_ui.routers.live_api import router as live_router
from mlx_ui.routers.pages import router as pages_router
from mlx_ui.routers.settings_api import router as settings_router
from mlx_ui.settings import build_settings_snapshot
from mlx_ui.update_check import (
    DEFAULT_TIMEOUT,
    check_for_updates,
    is_update_check_disabled,
)
from mlx_ui.worker import start_worker, stop_worker

STATIC_DIR = Path(__file__).resolve().parent / "static"
logger = logging.getLogger(__name__)


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    base_dir = get_base_dir(app)
    configure_logging(base_dir)

    db_path = get_db_path(app)
    uploads_dir = get_uploads_dir(app)
    results_dir = get_results_dir(app)

    worker_enabled = is_worker_enabled(app)
    try:
        init_db(db_path)
        recovered = recover_running_jobs(db_path)
        if recovered:
            logger.warning(
                "Recovered %s running job(s) after unclean shutdown.", recovered
            )

        if worker_enabled:
            start_worker(
                db_path,
                uploads_dir,
                results_dir,
                base_dir=base_dir,
            )

        settings_snapshot = build_settings_snapshot(base_dir=base_dir)
        hot_folder_settings = settings_snapshot.get("settings", {}) if settings_snapshot else {}
        hot_folder_enabled = bool(hot_folder_settings.get("hot_folder_enabled", False))
        hot_folder_input_dir = str(hot_folder_settings.get("hot_folder_input_dir", "")).strip()
        hot_folder_output_dir = str(hot_folder_settings.get("hot_folder_output_dir", "")).strip()
        if worker_enabled and hot_folder_enabled:
            if not hot_folder_input_dir or not hot_folder_output_dir:
                logger.warning("Hot folder is enabled but input/output paths are not configured.")
            else:
                input_dir = Path(hot_folder_input_dir)
                if not input_dir.is_absolute():
                    input_dir = (base_dir / input_dir).resolve()
                output_dir = Path(hot_folder_output_dir)
                if not output_dir.is_absolute():
                    output_dir = (base_dir / output_dir).resolve()
                start_hot_folder(
                    db_path=db_path,
                    uploads_dir=uploads_dir,
                    paths=HotFolderPaths(
                        input_dir=input_dir,
                        output_dir=output_dir,
                    ),
                    base_dir=base_dir,
                )
        update_check_enabled = bool(
            settings_snapshot.get("settings", {}).get("update_check_enabled", True)
        )
        if (
            is_update_check_enabled(app)
            and update_check_enabled
            and not is_update_check_disabled()
        ):
            thread = threading.Thread(
                target=check_for_updates,
                kwargs={"timeout": DEFAULT_TIMEOUT},
                name="mlx-ui-update-check",
                daemon=True,
            )
            thread.start()

        yield
    finally:
        stop_hot_folder()
        if worker_enabled:
            stop_worker()
        reset_live_service(app)


def create_app() -> FastAPI:
    app = FastAPI(title="Whisper WebUI (MLX)", lifespan=_lifespan)
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    app.middleware("http")(bind_active_app)
    app.include_router(pages_router)
    app.include_router(settings_router)
    app.include_router(jobs_router)
    app.include_router(live_router)
    init_app_state(app)

    return app


def _patch_testclient_allow_redirects() -> None:
    try:
        from fastapi.testclient import TestClient as _TestClient
    except Exception:
        return
    if getattr(_TestClient, "_allow_redirects_patched", False):
        return
    original_post = _TestClient.post

    def post(self, url, *args, **kwargs):  # type: ignore[no-untyped-def]
        if "allow_redirects" in kwargs and "follow_redirects" not in kwargs:
            kwargs["follow_redirects"] = kwargs.pop("allow_redirects")
        else:
            kwargs.pop("allow_redirects", None)
        return original_post(self, url, *args, **kwargs)

    _TestClient.post = post  # type: ignore[assignment]
    _TestClient._allow_redirects_patched = True


_patch_testclient_allow_redirects()

app = create_app()
set_default_app(app)
