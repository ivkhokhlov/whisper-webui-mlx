from dataclasses import asdict
from datetime import datetime, timezone
import logging
import os
from pathlib import Path
import shutil
import threading
from uuid import uuid4

from fastapi import FastAPI, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from mlx_ui.db import (
    JobRecord,
    delete_history_job,
    delete_history_jobs,
    delete_queued_job,
    get_job,
    init_db,
    insert_job,
    list_history_jobs,
    list_jobs,
    recover_running_jobs,
)
from mlx_ui.engine_registry import get_engine_provider
from mlx_ui.live_transcription import (
    LiveSessionNotFound,
    LiveTranscriptionError,
    LiveTranscriptionService,
    ParakeetLiveConfig,
)
from mlx_ui.languages import (
    DEFAULT_LANGUAGE,
    language_label,
    normalize_language,
    parse_language,
)
from mlx_ui.logging_config import configure_logging
from mlx_ui.settings import (
    CONFIGURABLE_ENGINE_CHOICES,
    build_cohere_snapshot,
    build_live_transcription_snapshot,
    build_runtime_metadata,
    build_settings_snapshot,
    build_telegram_snapshot,
    normalize_log_level,
    PARAKEET_LIVE_CHUNK_SECS,
    PARAKEET_LIVE_LEFT_CONTEXT_SECS,
    PARAKEET_LIVE_RIGHT_CONTEXT_SECS,
    PARAKEET_LIVE_TIMESLICE_MS,
    resolve_default_language_with_settings,
    resolve_requested_engine_with_settings,
    update_settings_file,
    validate_settings_payload,
)
from mlx_ui.update_check import (
    DEFAULT_TIMEOUT,
    check_for_updates,
    is_update_check_disabled,
)
from mlx_ui.uploads import cleanup_upload_path
from mlx_ui.worker import start_worker

app = FastAPI(title="Whisper WebUI (MLX)")
templates = Jinja2Templates(
    directory=str(Path(__file__).resolve().parent / "templates")
)
BASE_DIR = Path(__file__).resolve().parent.parent
STATIC_DIR = Path(__file__).resolve().parent / "static"
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
DEFAULT_UPLOADS_DIR = BASE_DIR / "data" / "uploads"
DEFAULT_RESULTS_DIR = BASE_DIR / "data" / "results"
DEFAULT_DB_PATH = BASE_DIR / "data" / "jobs.db"
app.state.uploads_dir = DEFAULT_UPLOADS_DIR
app.state.results_dir = DEFAULT_RESULTS_DIR
app.state.db_path = DEFAULT_DB_PATH
app.state.base_dir = BASE_DIR
app.state.worker_enabled = True
app.state.update_check_enabled = True
app.state.live_service = None
logger = logging.getLogger(__name__)

_ENGINE_SHORT_LABELS = {
    "whisper_mlx": "MLX",
    "whisper_cpu": "Whisper CPU",
    "parakeet_tdt_v3": "Parakeet",
    "cohere": "Cohere",
    "fake": "Fake",
}


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


@app.get("/favicon.ico", include_in_schema=False)
def favicon() -> FileResponse:
    return FileResponse(STATIC_DIR / "favicon.ico")


@app.on_event("startup")
def startup() -> None:
    base_dir = get_base_dir()
    configure_logging(base_dir)
    init_db(get_db_path())
    recovered = recover_running_jobs(get_db_path())
    if recovered:
        logger.warning("Recovered %s running job(s) after unclean shutdown.", recovered)
    if getattr(app.state, "worker_enabled", True):
        start_worker(
            get_db_path(),
            get_uploads_dir(),
            get_results_dir(),
            base_dir=base_dir,
        )
    settings_snapshot = build_settings_snapshot(base_dir=base_dir)
    update_check_enabled = bool(
        settings_snapshot.get("settings", {}).get("update_check_enabled", True)
    )
    if (
        getattr(app.state, "update_check_enabled", True)
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


def get_job_store() -> list[JobRecord]:
    return list_jobs(get_db_path())


def get_base_dir() -> Path:
    return Path(getattr(app.state, "base_dir", BASE_DIR))


def get_db_path() -> Path:
    return Path(app.state.db_path)


def get_uploads_dir() -> Path:
    return Path(app.state.uploads_dir)


def get_results_dir() -> Path:
    return Path(app.state.results_dir)


def get_live_service() -> LiveTranscriptionService:
    service = getattr(app.state, "live_service", None)
    if service is None:
        service = LiveTranscriptionService()
        app.state.live_service = service
    return service


def ensure_uploads_dir() -> Path:
    uploads_dir = get_uploads_dir()
    uploads_dir.mkdir(parents=True, exist_ok=True)
    return uploads_dir


def clear_directory(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    for entry in path.iterdir():
        try:
            if entry.is_dir():
                shutil.rmtree(entry)
            else:
                entry.unlink()
        except FileNotFoundError:
            continue
        except OSError as exc:
            logger.warning("Failed to remove %s: %s", entry, exc)


def remove_results_dir(job_id: str) -> str:
    if not is_safe_path_component(job_id):
        logger.warning("Refusing to remove results for unsafe job id %s", job_id)
        return "failed"
    results_dir = get_results_dir()
    job_dir = results_dir / job_id
    results_dir_resolved = results_dir.resolve()
    job_dir_resolved = job_dir.resolve()
    if not job_dir_resolved.is_relative_to(results_dir_resolved):
        logger.warning(
            "Refusing to remove results outside results dir for job %s", job_id
        )
        return "failed"
    if not job_dir_resolved.exists():
        return "missing"
    try:
        if job_dir_resolved.is_dir():
            shutil.rmtree(job_dir_resolved)
        else:
            job_dir_resolved.unlink()
        return "deleted"
    except Exception:
        logger.exception("Failed to remove results for job %s", job_id)
        return "failed"


def is_safe_path_component(value: str) -> bool:
    return value not in {"", ".", ".."} and Path(value).name == value


def sanitize_filename(filename: str) -> str:
    safe_name = Path(filename).name
    return safe_name or "upload.bin"


def sanitize_display_path(filename: str, fallback: str) -> str:
    normalized = filename.replace("\\", "/")
    parts = []
    for part in normalized.split("/"):
        if part in {"", ".", ".."}:
            continue
        if ":" in part:
            continue
        if not is_safe_path_component(part):
            continue
        parts.append(part)
    display = "/".join(parts)
    return display or fallback


def list_result_files(job_id: str) -> list[str]:
    if not is_safe_path_component(job_id):
        return []
    job_dir = get_results_dir() / job_id
    if not job_dir.is_dir():
        return []
    return sorted(path.name for path in job_dir.iterdir() if path.is_file())


def pick_preview_result(results: list[str]) -> str | None:
    if not results:
        return None
    for result in results:
        if result.lower().endswith(".txt"):
            return result
    for result in results:
        lower = result.lower()
        if lower.endswith((".srt", ".vtt", ".json")):
            return result
    return results[0]


def build_results_index(jobs: list[JobRecord]) -> dict[str, list[str]]:
    return {job.id: list_result_files(job.id) for job in jobs}


def new_job_record(
    job_id: str,
    filename: str,
    upload_path: Path,
    requested_engine: str | None = None,
    language: str = DEFAULT_LANGUAGE,
) -> JobRecord:
    return JobRecord(
        id=job_id,
        filename=filename,
        status="queued",
        created_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        upload_path=str(upload_path),
        language=language,
        requested_engine=requested_engine,
    )


def _split_jobs(jobs: list[JobRecord]) -> tuple[list[JobRecord], list[JobRecord]]:
    queue_jobs = [job for job in jobs if job.status in {"queued", "running"}]
    history_jobs = [job for job in jobs if job.status in {"done", "failed"}]
    history_jobs.sort(key=_history_sort_key, reverse=True)
    return queue_jobs, history_jobs


def _history_sort_key(job: JobRecord) -> str:
    return job.completed_at or job.created_at


def _serialize_job(job: JobRecord) -> dict[str, object]:
    payload = asdict(job)
    payload["ui"] = _build_job_ui(job)
    return payload


def _build_job_ui(job: JobRecord) -> dict[str, object]:
    requested_engine = _engine_ui(job.requested_engine)
    effective_engine = _engine_ui(job.effective_engine)
    language = _language_ui(job.language)
    engine_badges, engine_summary = _job_engine_badges(
        requested_engine=requested_engine,
        effective_engine=effective_engine,
    )
    preview_meta_parts = []
    if engine_summary:
        preview_meta_parts.append(engine_summary)
    preview_meta_parts.append(f"Language: {language['label']}")
    return {
        "requested_engine": requested_engine,
        "effective_engine": effective_engine,
        "engine_badges": engine_badges,
        "engine_summary": engine_summary,
        "language": language,
        "preview_meta": " · ".join(preview_meta_parts),
    }


def _engine_ui(engine_id: str | None) -> dict[str, object] | None:
    normalized = (engine_id or "").strip()
    if not normalized:
        return None
    provider = get_engine_provider(normalized)
    if provider is None:
        mode = "unknown"
        label = normalized
        short_label = normalized
        local = False
        cloud = False
    else:
        mode = provider.mode
        label = provider.label
        short_label = _ENGINE_SHORT_LABELS.get(provider.id, provider.label)
        local = provider.mode == "local"
        cloud = provider.mode == "cloud"
    return {
        "id": normalized,
        "label": label,
        "short_label": short_label,
        "mode": mode,
        "mode_label": mode if mode in {"local", "cloud"} else "unknown",
        "local": local,
        "cloud": cloud,
    }


def _language_ui(language: str | None) -> dict[str, str]:
    normalized = normalize_language(language)
    return {
        "id": normalized,
        "label": language_label(normalized),
        "short_label": _compact_language_label(normalized),
    }


def _compact_language_label(language: str) -> str:
    if language == "auto":
        return "Auto"
    return language.upper()


def _job_engine_badges(
    *,
    requested_engine: dict[str, object] | None,
    effective_engine: dict[str, object] | None,
) -> tuple[list[dict[str, str]], str | None]:
    if (
        requested_engine is not None
        and effective_engine is not None
        and requested_engine["id"] != effective_engine["id"]
    ):
        return (
            [
                _engine_badge(requested_engine, prefix="Requested", kind="requested"),
                _engine_badge(effective_engine, prefix="Used", kind="effective"),
            ],
            (
                f"Requested {_engine_text(requested_engine)}, "
                f"used {_engine_text(effective_engine)}"
            ),
        )
    engine = effective_engine or requested_engine
    if engine is None:
        return [], None
    return ([_engine_badge(engine, kind="engine")], f"Engine: {_engine_text(engine)}")


def _engine_badge(
    engine: dict[str, object],
    *,
    prefix: str | None = None,
    kind: str,
) -> dict[str, str]:
    label = f"{engine['short_label']} {engine['mode_label']}".strip()
    if prefix:
        label = f"{prefix} {label}"
    title = _engine_text(engine)
    if prefix:
        title = f"{prefix} engine: {title}"
    return {
        "label": label,
        "title": title,
        "kind": kind,
        "mode": str(engine["mode"]),
    }


def _engine_text(engine: dict[str, object]) -> str:
    mode = engine["mode_label"]
    if mode in {"local", "cloud"}:
        return f"{engine['label']} · {mode}"
    return str(engine["label"])


def _queue_groups(jobs: list[JobRecord]) -> tuple[JobRecord | None, list[JobRecord]]:
    running_job = next((job for job in jobs if job.status == "running"), None)
    queued_jobs = [job for job in jobs if job.status == "queued"]
    return running_job, queued_jobs


def _worker_state(jobs: list[JobRecord]) -> dict[str, object]:
    queued_count = sum(1 for job in jobs if job.status == "queued")
    running_job = next((job for job in jobs if job.status == "running"), None)
    if running_job:
        current_job_ui = _build_job_ui(running_job)
        return {
            "status": "Running",
            "job_id": running_job.id,
            "filename": running_job.filename,
            "started_at": running_job.started_at,
            "queue_length": queued_count,
            "current_job_ui": current_job_ui,
        }
    return {
        "status": "Idle",
        "job_id": None,
        "filename": None,
        "started_at": None,
        "queue_length": queued_count,
        "current_job_ui": None,
    }


@app.get("/", response_class=HTMLResponse)
def read_root(request: Request):
    jobs = get_job_store()
    queue_jobs, history_jobs = _split_jobs(jobs)
    queued_count = sum(1 for job in queue_jobs if job.status == "queued")
    job_views = {job.id: _build_job_ui(job) for job in jobs}
    base_dir = get_base_dir()
    settings_snapshot = build_settings_snapshot(base_dir=base_dir)
    cohere_snapshot = build_cohere_snapshot(base_dir=base_dir)
    telegram_snapshot = build_telegram_snapshot(base_dir=base_dir)
    runtime_snapshot = build_runtime_metadata(base_dir=base_dir)
    downloaded_models = list(
        settings_snapshot.get("local_models", {})
        .get("whisper", {})
        .get("models", [])
    )
    settings_saved = request.query_params.get("saved") == "1"
    tab_param = request.query_params.get("tab")
    active_tab = tab_param if tab_param in {"queue", "history", "settings"} else "queue"
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
            "results_by_job": build_results_index(history_jobs),
            "worker": _worker_state(jobs),
            "settings_snapshot": settings_snapshot,
            "cohere_snapshot": cohere_snapshot,
            "telegram_snapshot": telegram_snapshot,
            "runtime_snapshot": runtime_snapshot,
            "storage_snapshot": storage_snapshot,
            "downloaded_models": downloaded_models,
            "settings_saved": settings_saved,
            "active_tab": active_tab,
        },
    )


@app.get("/live", response_class=HTMLResponse)
def read_live(request: Request):
    live_snapshot = build_live_transcription_snapshot(base_dir=get_base_dir())
    return templates.TemplateResponse(
        request,
        "live.html",
        {
            "live_snapshot": live_snapshot,
        },
    )


@app.post("/api/live/session")
def api_live_start_session() -> dict[str, object]:
    live_snapshot = build_live_transcription_snapshot(base_dir=get_base_dir())
    if not live_snapshot.get("active"):
        raise HTTPException(
            status_code=409,
            detail=str(
                live_snapshot.get("reason")
                or "Parakeet live beta is not available in the current environment."
            ),
        )
    config = _build_parakeet_live_config(live_snapshot)
    try:
        update = get_live_service().open_session(config)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {
        "session": update.to_dict(),
        "live": live_snapshot,
    }


@app.post("/api/live/session/{session_id}/chunk")
async def api_live_append_chunk(
    session_id: str,
    file: UploadFile = File(...),
) -> dict[str, object]:
    try:
        payload = await file.read()
    finally:
        await file.close()
    try:
        update = get_live_service().append_chunk(
            session_id,
            payload,
            content_type=file.content_type,
        )
    except LiveSessionNotFound as exc:
        raise HTTPException(status_code=404, detail="Live session not found.") from exc
    except LiveTranscriptionError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {"session": update.to_dict()}


@app.post("/api/live/session/{session_id}/stop")
def api_live_stop_session(session_id: str) -> dict[str, object]:
    try:
        update = get_live_service().stop_session(session_id)
    except LiveSessionNotFound as exc:
        raise HTTPException(status_code=404, detail="Live session not found.") from exc
    except LiveTranscriptionError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {"session": update.to_dict()}


@app.get("/settings")
def read_settings_redirect() -> RedirectResponse:
    return RedirectResponse(url="/?tab=settings", status_code=302)


@app.post("/settings")
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


@app.get("/api/settings")
def api_settings() -> dict[str, object]:
    base_dir = get_base_dir()
    snapshot = build_settings_snapshot(base_dir=base_dir)
    snapshot["cohere_snapshot"] = build_cohere_snapshot(base_dir=base_dir)
    snapshot["telegram_snapshot"] = build_telegram_snapshot(base_dir=base_dir)
    return snapshot


@app.post("/api/settings")
async def api_update_settings(request: Request) -> dict[str, object]:
    payload = await request.json()
    updates, errors = validate_settings_payload(payload)
    if errors:
        raise HTTPException(status_code=422, detail=errors)
    if updates:
        update_settings_file(get_base_dir(), updates)
    base_dir = get_base_dir()
    snapshot = build_settings_snapshot(base_dir=base_dir)
    snapshot["cohere_snapshot"] = build_cohere_snapshot(base_dir=base_dir)
    snapshot["telegram_snapshot"] = build_telegram_snapshot(base_dir=base_dir)
    return snapshot


@app.post("/api/settings/clear-uploads")
def api_clear_uploads() -> dict[str, str]:
    clear_directory(get_uploads_dir())
    return {"status": "ok"}


@app.post("/api/settings/clear-results")
def api_clear_results() -> dict[str, str]:
    clear_directory(get_results_dir())
    return {"status": "ok"}


@app.post("/upload", response_class=HTMLResponse)
async def upload_files(
    files: list[UploadFile] = File(...),
    language: str | None = Form(None),
):
    uploads_dir = ensure_uploads_dir()
    db_path = get_db_path()
    batch_language = normalize_language(
        language,
        default=resolve_default_language_with_settings(base_dir=get_base_dir()),
    )
    requested_engine = resolve_requested_engine_with_settings(base_dir=get_base_dir())

    for upload in files:
        if not upload.filename:
            continue
        safe_name = sanitize_filename(upload.filename)
        display_name = sanitize_display_path(upload.filename, safe_name)
        job_id = uuid4().hex
        job_dir = uploads_dir / job_id
        job_dir.mkdir(parents=True, exist_ok=True)
        destination = job_dir / safe_name
        try:
            with destination.open("wb") as outfile:
                shutil.copyfileobj(upload.file, outfile)
        finally:
            await upload.close()
        insert_job(
            db_path,
            new_job_record(
                job_id,
                display_name,
                destination,
                requested_engine=requested_engine,
                language=batch_language,
            ),
        )

    return RedirectResponse(url="/?tab=queue", status_code=303)


@app.get("/api/state")
def api_state() -> dict[str, object]:
    jobs = get_job_store()
    queue_jobs, history_jobs = _split_jobs(jobs)
    running_job, queued_jobs = _queue_groups(queue_jobs)
    return {
        "queue": [_serialize_job(job) for job in queue_jobs],
        "queue_running": _serialize_job(running_job) if running_job else None,
        "queue_pending": [_serialize_job(job) for job in queued_jobs],
        "queue_counts": {
            "running": 1 if running_job else 0,
            "queued": len(queued_jobs),
        },
        "history": [_serialize_job(job) for job in history_jobs],
        "results_by_job": build_results_index(history_jobs),
        "worker": _worker_state(jobs),
    }


@app.get("/results/{job_id}/{filename}")
def download_result(job_id: str, filename: str):
    if not is_safe_path_component(job_id) or not is_safe_path_component(filename):
        raise HTTPException(status_code=404)

    results_dir = get_results_dir()
    job_dir = results_dir / job_id
    results_dir_resolved = results_dir.resolve()
    job_dir_resolved = job_dir.resolve()
    file_path = (job_dir / filename).resolve()

    if not job_dir_resolved.is_relative_to(results_dir_resolved):
        raise HTTPException(status_code=404)

    if not file_path.is_file() or not file_path.is_relative_to(job_dir_resolved):
        raise HTTPException(status_code=404)

    return FileResponse(file_path)


@app.get("/api/jobs/{job_id}/preview")
def job_preview(
    job_id: str, chars: int = Query(300, ge=50, le=2000)
) -> dict[str, object]:
    if not is_safe_path_component(job_id):
        raise HTTPException(status_code=404)

    results = list_result_files(job_id)
    filename = pick_preview_result(results)
    if not filename:
        return {"job_id": job_id, "filename": None, "snippet": "", "truncated": False}

    results_dir = get_results_dir()
    job_dir = results_dir / job_id
    results_dir_resolved = results_dir.resolve()
    job_dir_resolved = job_dir.resolve()
    file_path = (job_dir / filename).resolve()

    if not job_dir_resolved.is_relative_to(results_dir_resolved):
        raise HTTPException(status_code=404)

    if not file_path.is_file() or not file_path.is_relative_to(job_dir_resolved):
        raise HTTPException(status_code=404)

    snippet, truncated = _read_preview(file_path, chars)
    return {
        "job_id": job_id,
        "filename": filename,
        "snippet": snippet,
        "truncated": truncated,
    }


def _read_preview(file_path: Path, limit: int) -> tuple[str, bool]:
    with file_path.open("r", encoding="utf-8", errors="replace") as handle:
        data = handle.read(limit + 1)
    truncated = len(data) > limit
    return data[:limit], truncated


def _build_parakeet_live_config(live_snapshot: dict[str, object]) -> ParakeetLiveConfig:
    return ParakeetLiveConfig(
        repo_id=str(live_snapshot.get("configured_model") or ""),
        decoding_mode="greedy",
        left_context_secs=float(
            live_snapshot.get("left_context_secs") or PARAKEET_LIVE_LEFT_CONTEXT_SECS
        ),
        chunk_secs=float(
            live_snapshot.get("chunk_secs") or PARAKEET_LIVE_CHUNK_SECS
        ),
        right_context_secs=float(
            live_snapshot.get("right_context_secs")
            or PARAKEET_LIVE_RIGHT_CONTEXT_SECS
        ),
        timeslice_ms=int(
            live_snapshot.get("timeslice_ms") or PARAKEET_LIVE_TIMESLICE_MS
        ),
    )


@app.delete("/api/jobs/{job_id}")
def delete_job_from_queue(job_id: str) -> dict[str, bool]:
    if not is_safe_path_component(job_id):
        raise HTTPException(status_code=404)
    db_path = get_db_path()
    job = get_job(db_path, job_id)
    if job is None:
        raise HTTPException(status_code=404)
    if job.status != "queued":
        raise HTTPException(
            status_code=409,
            detail="Only queued jobs can be removed.",
        )
    if not delete_queued_job(db_path, job_id):
        raise HTTPException(
            status_code=409,
            detail="Job is no longer queued.",
        )
    cleanup_upload_path(job.upload_path, get_uploads_dir(), job.id)
    return {"ok": True}


@app.delete("/api/history/{job_id}")
def delete_history_item(job_id: str) -> dict[str, object]:
    if not is_safe_path_component(job_id):
        raise HTTPException(status_code=404)
    db_path = get_db_path()
    job = get_job(db_path, job_id)
    if job is None:
        raise HTTPException(status_code=404)
    if job.status not in {"done", "failed"}:
        raise HTTPException(
            status_code=409,
            detail="Only completed jobs can be removed.",
        )
    result_state = remove_results_dir(job.id)
    if result_state == "failed":
        raise HTTPException(
            status_code=500,
            detail="Failed to remove stored outputs.",
        )
    cleanup_upload_path(job.upload_path, get_uploads_dir(), job.id)
    deleted = delete_history_job(db_path, job_id)
    if not deleted:
        return {
            "ok": True,
            "warnings": ["History entry was already removed."],
        }
    return {"ok": True}


@app.post("/api/history/clear")
def clear_history() -> dict[str, object]:
    db_path = get_db_path()
    jobs = list_history_jobs(db_path)
    deletable_ids: list[str] = []
    deleted_results = 0
    failed_results = 0
    for job in jobs:
        result_state = remove_results_dir(job.id)
        if result_state == "deleted":
            deleted_results += 1
        elif result_state == "failed":
            failed_results += 1
            continue
        cleanup_upload_path(job.upload_path, get_uploads_dir(), job.id)
        deletable_ids.append(job.id)
    deleted_jobs = delete_history_jobs(db_path, deletable_ids)
    response: dict[str, object] = {
        "ok": True,
        "deleted_jobs": deleted_jobs,
        "deleted_results": deleted_results,
        "failed_results": failed_results,
    }
    if deleted_jobs != len(deletable_ids):
        response["warnings"] = ["Some history entries were already removed."]
    return response
