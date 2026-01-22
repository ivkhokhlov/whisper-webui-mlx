from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def cleanup_upload_path(
    upload_path: Path | str,
    uploads_root: Path | str,
    job_id: str | None = None,
) -> None:
    resolved_upload = Path(upload_path).resolve()
    resolved_root = Path(uploads_root).resolve()
    if not resolved_upload.is_relative_to(resolved_root):
        logger.warning("Refusing to remove upload outside uploads dir%s", _job_suffix(job_id))
        return
    if not resolved_upload.exists():
        return
    try:
        if resolved_upload.is_file() or resolved_upload.is_symlink():
            resolved_upload.unlink()
        else:
            logger.warning("Upload path is not a file%s", _job_suffix(job_id))
            return
    except Exception:
        logger.exception("Failed to remove upload%s", _job_suffix(job_id))
        return
    parent = resolved_upload.parent
    try:
        parent.rmdir()
    except OSError:
        return
    except Exception:
        logger.exception("Failed to remove upload directory%s", _job_suffix(job_id))


def _job_suffix(job_id: str | None) -> str:
    return f" for job {job_id}" if job_id else ""
