from __future__ import annotations

from datetime import datetime, timezone
import shutil
from pathlib import Path
from uuid import uuid4

from fastapi import (
    APIRouter,
    File,
    Form,
    HTTPException,
    Query,
    UploadFile,
)
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse

from mlx_ui.app_context import (
    get_base_dir,
    get_db_path,
    get_results_dir,
    get_uploads_dir,
)
from mlx_ui.db import (
    JobRecord,
    cancel_running_job,
    delete_history_job,
    delete_history_jobs,
    delete_queued_job,
    get_job,
    insert_job,
    list_history_jobs,
    list_jobs,
)
from mlx_ui.job_ui import queue_groups, serialize_job, split_jobs, worker_state
from mlx_ui.engine_registry import PARAKEET_TDT_V3_ENGINE
from mlx_ui.languages import (
    AUTO_LANGUAGE,
    DEFAULT_LANGUAGE,
    is_parakeet_tdt_v3_language_supported,
    normalize_language,
)
from mlx_ui.settings import (
    resolve_default_language_with_settings,
    resolve_requested_engine_with_settings,
)
from mlx_ui.storage import (
    ensure_directory,
    is_safe_path_component,
    list_result_files,
    pick_preview_result,
    remove_results_dir,
    safe_result_file_path,
    sanitize_display_path,
    sanitize_filename,
)
from mlx_ui.uploads import cleanup_upload_path
from mlx_ui.worker import cleanup_cancelled_job_artifacts, request_worker_cancel

router = APIRouter()


def _new_job_record(
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


def _build_results_index(jobs: list[JobRecord]) -> dict[str, list[str]]:
    results_dir = get_results_dir()
    return {job.id: list_result_files(results_dir, job.id) for job in jobs}


@router.post("/upload", response_class=HTMLResponse)
async def upload_files(
    files: list[UploadFile] = File(...),
    language: str | None = Form(None),
):
    uploads_dir = ensure_directory(get_uploads_dir())
    db_path = get_db_path()
    requested_engine = resolve_requested_engine_with_settings(base_dir=get_base_dir())
    default_language = resolve_default_language_with_settings(base_dir=get_base_dir())
    if requested_engine == PARAKEET_TDT_V3_ENGINE:
        default_language = AUTO_LANGUAGE
    batch_language = normalize_language(language, default=default_language)

    if (
        requested_engine == PARAKEET_TDT_V3_ENGINE
        and not is_parakeet_tdt_v3_language_supported(batch_language)
    ):
        return RedirectResponse(
            url=f"/?tab=queue&queue_error=parakeet_language&queue_error_language={batch_language}",
            status_code=303,
        )

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
            _new_job_record(
                job_id,
                display_name,
                destination,
                requested_engine=requested_engine,
                language=batch_language,
            ),
        )

    return RedirectResponse(url="/?tab=queue", status_code=303)


@router.get("/api/state")
def api_state() -> dict[str, object]:
    jobs = list_jobs(get_db_path())
    queue_jobs, history_jobs = split_jobs(jobs)
    running_job, queued_jobs = queue_groups(queue_jobs)
    return {
        "queue": [serialize_job(job) for job in queue_jobs],
        "queue_running": serialize_job(running_job) if running_job else None,
        "queue_pending": [serialize_job(job) for job in queued_jobs],
        "queue_counts": {
            "running": 1 if running_job else 0,
            "queued": len(queued_jobs),
        },
        "history": [serialize_job(job) for job in history_jobs],
        "results_by_job": _build_results_index(history_jobs),
        "worker": worker_state(jobs),
    }


@router.get("/results/{job_id}/{filename}")
def download_result(job_id: str, filename: str):
    file_path = safe_result_file_path(get_results_dir(), job_id, filename)
    if file_path is None and "\x00" in filename:
        file_path = safe_result_file_path(
            get_results_dir(), job_id, filename.replace("\x00", " ")
        )
    if file_path is None:
        raise HTTPException(status_code=404)

    return FileResponse(file_path)


@router.get("/api/jobs/{job_id}/preview")
def job_preview(
    job_id: str, chars: int = Query(300, ge=50, le=2000)
) -> dict[str, object]:
    if not is_safe_path_component(job_id):
        raise HTTPException(status_code=404)

    results_dir = get_results_dir()
    results = list_result_files(results_dir, job_id)
    filename = pick_preview_result(results)
    if not filename:
        return {"job_id": job_id, "filename": None, "snippet": "", "truncated": False}

    file_path = safe_result_file_path(results_dir, job_id, filename)
    if file_path is None:
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


@router.delete("/api/jobs/{job_id}")
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


@router.post("/api/jobs/{job_id}/cancel")
def cancel_job(job_id: str) -> dict[str, object]:
    if not is_safe_path_component(job_id):
        raise HTTPException(status_code=404)
    db_path = get_db_path()
    job = get_job(db_path, job_id)
    if job is None:
        raise HTTPException(status_code=404)
    if job.status not in {"running", "reserved"}:
        raise HTTPException(
            status_code=409,
            detail="Only running jobs can be stopped.",
        )
    cancel_snapshot = request_worker_cancel(job_id)
    if cancel_snapshot is not None:
        return {
            "ok": True,
            "state": "stopping",
            "interrupted": bool(cancel_snapshot.get("interrupted")),
            "already_requested": bool(cancel_snapshot.get("already_requested")),
        }
    if not cancel_running_job(db_path, job_id):
        raise HTTPException(
            status_code=409,
            detail="Job is no longer running.",
        )
    cleanup_cancelled_job_artifacts(
        job,
        uploads_dir=get_uploads_dir(),
        results_dir=get_results_dir(),
    )
    return {
        "ok": True,
        "state": "cancelled",
        "interrupted": False,
        "already_requested": False,
    }


@router.delete("/api/history/{job_id}")
def delete_history_item(job_id: str) -> dict[str, object]:
    if not is_safe_path_component(job_id):
        raise HTTPException(status_code=404)
    db_path = get_db_path()
    job = get_job(db_path, job_id)
    if job is None:
        raise HTTPException(status_code=404)
    if job.status not in {"done", "failed", "cancelled"}:
        raise HTTPException(
            status_code=409,
            detail="Only completed or cancelled jobs can be removed.",
        )
    result_state = remove_results_dir(get_results_dir(), job.id)
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


@router.post("/api/history/clear")
def clear_history() -> dict[str, object]:
    db_path = get_db_path()
    results_dir = get_results_dir()
    jobs = list_history_jobs(db_path)
    deletable_ids: list[str] = []
    deleted_results = 0
    failed_results = 0
    for job in jobs:
        result_state = remove_results_dir(results_dir, job.id)
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
