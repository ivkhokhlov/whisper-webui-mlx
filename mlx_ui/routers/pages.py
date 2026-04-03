from __future__ import annotations

import os
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from mlx_ui.app_context import (
    get_base_dir,
    get_db_path,
    get_results_dir,
    get_uploads_dir,
)
from mlx_ui.db import list_jobs
from mlx_ui.job_ui import build_job_ui, split_jobs, worker_state
from mlx_ui.settings import (
    CONFIGURABLE_ENGINE_CHOICES,
    build_cohere_snapshot,
    build_live_transcription_snapshot,
    build_runtime_metadata,
    build_settings_snapshot,
    build_telegram_snapshot,
    normalize_log_level,
    update_settings_file,
)
from mlx_ui.languages import (
    language_label,
    list_parakeet_tdt_v3_supported_languages,
    parse_language,
)
from mlx_ui.storage import list_result_files

router = APIRouter()

_PACKAGE_DIR = Path(__file__).resolve().parents[1]
STATIC_DIR = _PACKAGE_DIR / "static"
templates = Jinja2Templates(directory=str(_PACKAGE_DIR / "templates"))


@router.get("/favicon.ico", include_in_schema=False)
def favicon() -> FileResponse:
    return FileResponse(STATIC_DIR / "favicon.ico")


def _build_results_index(job_ids: list[str]) -> dict[str, list[str]]:
    results_dir = get_results_dir()
    return {job_id: list_result_files(results_dir, job_id) for job_id in job_ids}


@router.get("/", response_class=HTMLResponse)
def read_root(request: Request):
    jobs = list_jobs(get_db_path())
    queue_jobs, history_jobs = split_jobs(jobs)
    queued_count = sum(1 for job in queue_jobs if job.status == "queued")
    job_views = {job.id: build_job_ui(job) for job in jobs}
    base_dir = get_base_dir()
    settings_snapshot = build_settings_snapshot(base_dir=base_dir)
    cohere_snapshot = build_cohere_snapshot(base_dir=base_dir)
    telegram_snapshot = build_telegram_snapshot(base_dir=base_dir)
    runtime_snapshot = build_runtime_metadata(base_dir=base_dir)
    downloaded_models = list(
        settings_snapshot.get("local_models", {}).get("whisper", {}).get("models", [])
    )
    settings_saved = request.query_params.get("saved") == "1"
    tab_param = request.query_params.get("tab")
    active_tab = tab_param if tab_param in {"queue", "history", "settings"} else "queue"
    queue_error_message = None
    queue_error = request.query_params.get("queue_error")
    queue_error_language = request.query_params.get("queue_error_language")
    if queue_error == "parakeet_language" and queue_error_language:
        supported = ", ".join(list_parakeet_tdt_v3_supported_languages())
        chosen_label = language_label(queue_error_language)
        queue_error_message = (
            "Parakeet TDT v3 supports automatic language detection (auto) and 25 "
            f"European languages ({supported}). You selected {chosen_label} "
            f"({queue_error_language}). Choose auto or switch to a different engine."
        )
    storage_snapshot = {
        "uploads_dir": str(get_uploads_dir()),
        "results_dir": str(get_results_dir()),
        "db_path": str(get_db_path()),
        "log_dir": str(Path(os.getenv("LOG_DIR", base_dir / "data" / "logs"))),
    }
    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "queue_jobs": queue_jobs,
            "queued_count": queued_count,
            "history_jobs": history_jobs,
            "job_views": job_views,
            "results_by_job": _build_results_index([job.id for job in history_jobs]),
            "worker": worker_state(jobs),
            "settings_snapshot": settings_snapshot,
            "cohere_snapshot": cohere_snapshot,
            "telegram_snapshot": telegram_snapshot,
            "runtime_snapshot": runtime_snapshot,
            "storage_snapshot": storage_snapshot,
            "downloaded_models": downloaded_models,
            "settings_saved": settings_saved,
            "active_tab": active_tab,
            "queue_error_message": queue_error_message,
        },
    )


@router.get("/live", response_class=HTMLResponse)
def read_live(request: Request):
    live_snapshot = build_live_transcription_snapshot(base_dir=get_base_dir())
    return templates.TemplateResponse(
        request,
        "live.html",
        {
            "live_snapshot": live_snapshot,
        },
    )


@router.get("/settings")
def read_settings_redirect() -> RedirectResponse:
    return RedirectResponse(url="/?tab=settings", status_code=302)


@router.post("/settings")
async def update_settings(request: Request) -> RedirectResponse:
    form = await request.form()
    updates: dict[str, object] = {}

    engine = str(form.get("engine", "")).strip()
    if engine in CONFIGURABLE_ENGINE_CHOICES:
        updates["engine"] = engine

    if "wtm_quick_present" in form or "wtm_quick" in form:
        updates["wtm_quick"] = "wtm_quick" in form

    default_language = parse_language(form.get("default_language"))
    if default_language is not None:
        updates["default_language"] = default_language

    if "cohere_model" in form:
        updates["cohere_model"] = str(form.get("cohere_model", "")).strip()

    whisper_model = str(form.get("whisper_model", "")).strip()
    if whisper_model:
        updates["whisper_model"] = whisper_model

    if "update_check_enabled_present" in form or "update_check_enabled" in form:
        updates["update_check_enabled"] = "update_check_enabled" in form

    log_level = str(form.get("log_level", "")).strip()
    if log_level:
        updates["log_level"] = normalize_log_level(log_level)

    cohere_api_key = str(form.get("cohere_api_key", "")).strip()
    if cohere_api_key:
        updates["cohere_api_key"] = cohere_api_key
    if "clear_cohere_api_key" in form:
        updates["cohere_api_key"] = ""

    telegram_token = str(form.get("telegram_token", "")).strip()
    if telegram_token:
        updates["telegram_token"] = telegram_token
    if "clear_telegram_token" in form:
        updates["telegram_token"] = ""

    telegram_chat_id = str(form.get("telegram_chat_id", "")).strip()
    if telegram_chat_id:
        updates["telegram_chat_id"] = telegram_chat_id
    if "clear_telegram_chat_id" in form:
        updates["telegram_chat_id"] = ""

    if updates:
        update_settings_file(get_base_dir(), updates)

    return RedirectResponse(url="/?tab=settings&saved=1", status_code=303)
