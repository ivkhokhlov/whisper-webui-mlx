from __future__ import annotations

import logging
from pathlib import Path
import shutil

logger = logging.getLogger(__name__)


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


def ensure_directory(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


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


def safe_result_file_path(
    results_dir: Path,
    job_id: str,
    filename: str,
) -> Path | None:
    if not is_safe_path_component(job_id) or not is_safe_path_component(filename):
        return None

    job_dir = results_dir / job_id
    results_dir_resolved = results_dir.resolve()
    job_dir_resolved = job_dir.resolve()
    file_path = (job_dir / filename).resolve()

    if not job_dir_resolved.is_relative_to(results_dir_resolved):
        return None

    if not file_path.is_file() or not file_path.is_relative_to(job_dir_resolved):
        return None

    return file_path


def remove_results_dir(results_dir: Path, job_id: str) -> str:
    if not is_safe_path_component(job_id):
        logger.warning("Refusing to remove results for unsafe job id %s", job_id)
        return "failed"
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


def list_result_files(results_dir: Path, job_id: str) -> list[str]:
    if not is_safe_path_component(job_id):
        return []
    job_dir = results_dir / job_id
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
