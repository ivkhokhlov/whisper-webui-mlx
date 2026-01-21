from datetime import datetime, timezone
from pathlib import Path
import shutil
from uuid import uuid4

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.templating import Jinja2Templates

from mlx_ui.db import JobRecord, init_db, insert_job, list_jobs
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


@app.on_event("startup")
def startup() -> None:
    init_db(get_db_path())
    if getattr(app.state, "worker_enabled", True):
        start_worker(get_db_path(), get_results_dir())


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


def new_job_record(job_id: str, filename: str, upload_path: Path) -> JobRecord:
    return JobRecord(
        id=job_id,
        filename=filename,
        status="queued",
        created_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        upload_path=str(upload_path),
    )


@app.get("/", response_class=HTMLResponse)
def read_root(request: Request):
    jobs = get_job_store()
    return templates.TemplateResponse(
        request,
        "index.html",
        {"jobs": jobs, "results_by_job": build_results_index(jobs)},
    )


@app.post("/upload", response_class=HTMLResponse)
async def upload_files(request: Request, files: list[UploadFile] = File(...)):
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

    return templates.TemplateResponse(
        request,
        "index.html",
        {"jobs": jobs, "results_by_job": build_results_index(jobs)},
    )


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
