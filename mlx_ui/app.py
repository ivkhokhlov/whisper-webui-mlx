from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import shutil
from uuid import uuid4

from fastapi import FastAPI, File, Request, UploadFile
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

app = FastAPI(title="Whisper WebUI (MLX)")
templates = Jinja2Templates(directory=str(Path(__file__).resolve().parent / "templates"))
BASE_DIR = Path(__file__).resolve().parent.parent
DEFAULT_UPLOADS_DIR = BASE_DIR / "data" / "uploads"
app.state.uploads_dir = DEFAULT_UPLOADS_DIR
app.state.jobs = []


@dataclass
class JobRecord:
    id: str
    filename: str
    status: str
    created_at: str
    upload_path: str


def get_job_store() -> list[JobRecord]:
    return app.state.jobs


def get_uploads_dir() -> Path:
    return Path(app.state.uploads_dir)


def ensure_uploads_dir() -> Path:
    uploads_dir = get_uploads_dir()
    uploads_dir.mkdir(parents=True, exist_ok=True)
    return uploads_dir


def sanitize_filename(filename: str) -> str:
    safe_name = Path(filename).name
    return safe_name or "upload.bin"


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
    return templates.TemplateResponse(
        request,
        "index.html",
        {"jobs": get_job_store()},
    )


@app.post("/upload", response_class=HTMLResponse)
async def upload_files(request: Request, files: list[UploadFile] = File(...)):
    jobs = get_job_store()
    uploads_dir = ensure_uploads_dir()

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
        jobs.append(new_job_record(job_id, safe_name, destination))

    return templates.TemplateResponse(
        request,
        "index.html",
        {"jobs": jobs},
    )
