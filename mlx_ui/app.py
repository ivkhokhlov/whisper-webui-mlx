from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
import shutil
import threading
from uuid import uuid4

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.templating import Jinja2Templates

from mlx_ui.db import JobRecord, delete_queued_job, get_job, init_db, insert_job, list_jobs
from mlx_ui.logging_config import configure_logging
from mlx_ui.update_check import DEFAULT_TIMEOUT, check_for_updates, is_update_check_disabled
from mlx_ui.uploads import cleanup_upload_path
from mlx_ui.worker import start_worker

app = FastAPI(title="Whisper WebUI (MLX)")
templates = Jinja2Templates(directory=str(Path(__file__).resolve().parent / "templates"))
BASE_DIR = Path(__file__).resolve().parent.parent
DEFAULT_UPLOADS_DIR = BASE_DIR / "data" / "uploads"
DEFAULT_RESULTS_DIR = BASE_DIR / "data" / "results"
DEFAULT_DB_PATH = BASE_DIR / "data" / "jobs.db"
app.state.uploads_dir = DEFAULT_UPLOADS_DIR
app.state.results_dir = DEFAULT_RESULTS_DIR
app.state.db_path = DEFAULT_DB_PATH
app.state.worker_enabled = True
app.state.update_check_enabled = True
DEFAULT_LANGUAGE = "any"


@app.on_event("startup")
def startup() -> None:
    configure_logging(BASE_DIR)
    init_db(get_db_path())
    if getattr(app.state, "worker_enabled", True):
        start_worker(get_db_path(), get_uploads_dir(), get_results_dir())
    if (
        getattr(app.state, "update_check_enabled", True)
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


def get_db_path() -> Path:
    return Path(app.state.db_path)


def get_uploads_dir() -> Path:
    return Path(app.state.uploads_dir)


def get_results_dir() -> Path:
    return Path(app.state.results_dir)


def ensure_uploads_dir() -> Path:
    uploads_dir = get_uploads_dir()
    uploads_dir.mkdir(parents=True, exist_ok=True)
    return uploads_dir


def is_safe_path_component(value: str) -> bool:
    return value not in {"", ".", ".."} and Path(value).name == value


def sanitize_filename(filename: str) -> str:
    safe_name = Path(filename).name
    return safe_name or "upload.bin"


def list_result_files(job_id: str) -> list[str]:
    if not is_safe_path_component(job_id):
        return []
    job_dir = get_results_dir() / job_id
    if not job_dir.is_dir():
        return []
    return sorted(path.name for path in job_dir.iterdir() if path.is_file())


def build_results_index(jobs: list[JobRecord]) -> dict[str, list[str]]:
    return {job.id: list_result_files(job.id) for job in jobs}


def new_job_record(
    job_id: str,
    filename: str,
    upload_path: Path,
) -> JobRecord:
    return JobRecord(
        id=job_id,
        filename=filename,
        status="queued",
        created_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        upload_path=str(upload_path),
        language=DEFAULT_LANGUAGE,
    )


def _split_jobs(jobs: list[JobRecord]) -> tuple[list[JobRecord], list[JobRecord]]:
    queue_jobs = [job for job in jobs if job.status in {"queued", "running"}]
    history_jobs = [job for job in jobs if job.status in {"done", "failed"}]
    history_jobs.sort(key=_history_sort_key, reverse=True)
    return queue_jobs, history_jobs


def _history_sort_key(job: JobRecord) -> str:
    return job.completed_at or job.created_at


def _serialize_job(job: JobRecord) -> dict[str, str | None]:
    return asdict(job)


def _queue_groups(jobs: list[JobRecord]) -> tuple[JobRecord | None, list[JobRecord]]:
    running_job = next((job for job in jobs if job.status == "running"), None)
    queued_jobs = [job for job in jobs if job.status == "queued"]
    return running_job, queued_jobs


def _worker_state(jobs: list[JobRecord]) -> dict[str, object]:
    queued_count = sum(1 for job in jobs if job.status == "queued")
    running_job = next((job for job in jobs if job.status == "running"), None)
    if running_job:
        return {
            "status": "Running",
            "job_id": running_job.id,
            "filename": running_job.filename,
            "started_at": running_job.started_at,
            "queue_length": queued_count,
        }
    return {
        "status": "Idle",
        "job_id": None,
        "filename": None,
        "started_at": None,
        "queue_length": queued_count,
    }


@app.get("/", response_class=HTMLResponse)
def read_root(request: Request):
    jobs = get_job_store()
    queue_jobs, history_jobs = _split_jobs(jobs)
    queued_count = sum(1 for job in queue_jobs if job.status == "queued")
    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "queue_jobs": queue_jobs,
            "queued_count": queued_count,
            "history_jobs": history_jobs,
            "results_by_job": build_results_index(history_jobs),
            "worker": _worker_state(jobs),
        },
    )


@app.get("/live", response_class=HTMLResponse)
def read_live(request: Request):
    return templates.TemplateResponse(request, "live.html", {})


@app.post("/upload", response_class=HTMLResponse)
async def upload_files(
    request: Request,
    files: list[UploadFile] = File(...),
):
    uploads_dir = ensure_uploads_dir()
    db_path = get_db_path()

    for upload in files:
        if not upload.filename:
            continue
        safe_name = sanitize_filename(upload.filename)
        job_id = uuid4().hex
        job_dir = uploads_dir / job_id
        job_dir.mkdir(parents=True, exist_ok=True)
        destination = job_dir / safe_name
        try:
            with destination.open("wb") as outfile:
                shutil.copyfileobj(upload.file, outfile)
        finally:
            await upload.close()
        insert_job(db_path, new_job_record(job_id, safe_name, destination))

    jobs = list_jobs(db_path)
    queue_jobs, history_jobs = _split_jobs(jobs)
    queued_count = sum(1 for job in queue_jobs if job.status == "queued")

    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "queue_jobs": queue_jobs,
            "queued_count": queued_count,
            "history_jobs": history_jobs,
            "results_by_job": build_results_index(history_jobs),
            "worker": _worker_state(jobs),
        },
    )


@app.get("/api/state")
def api_state() -> dict[str, object]:
    jobs = get_job_store()
    queue_jobs, history_jobs = _split_jobs(jobs)
    running_job, queued_jobs = _queue_groups(queue_jobs)
    return {
        "queue": [_serialize_job(job) for job in queue_jobs],
        "queue_running": _serialize_job(running_job) if running_job else None,
        "queue_pending": [_serialize_job(job) for job in queued_jobs],
        "queue_counts": {"running": 1 if running_job else 0, "queued": len(queued_jobs)},
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
