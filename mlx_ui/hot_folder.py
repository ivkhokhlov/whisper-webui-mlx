from __future__ import annotations

import logging
import mimetypes
import os
import shutil
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping
from uuid import uuid4

from mlx_ui.db import JobRecord, insert_job
from mlx_ui.engine_registry import PARAKEET_TDT_V3_ENGINE
from mlx_ui.languages import AUTO_LANGUAGE, normalize_language
from mlx_ui.settings import (
    resolve_default_language_with_settings,
    resolve_requested_engine_with_settings,
)
from mlx_ui.settings_store import compute_effective_settings
from mlx_ui.storage import sanitize_display_path, sanitize_filename

logger = logging.getLogger(__name__)

_ALLOWED_EXTENSIONS = {
    ".aac",
    ".aiff",
    ".alac",
    ".avi",
    ".flac",
    ".m4a",
    ".m4b",
    ".m4v",
    ".mka",
    ".mkv",
    ".mov",
    ".mp3",
    ".mp4",
    ".mpeg",
    ".mpg",
    ".ogg",
    ".opus",
    ".wav",
    ".webm",
    ".wma",
}

_SKIP_EXTENSIONS = {
    ".crdownload",
    ".download",
    ".part",
    ".partial",
    ".tmp",
}


@dataclass(frozen=True)
class HotFolderPaths:
    input_dir: Path
    output_dir: Path


@dataclass
class _CandidateState:
    size: int
    mtime: float
    stable_since: float


class HotFolderWatcher:
    def __init__(
        self,
        *,
        db_path: Path,
        uploads_dir: Path,
        paths: HotFolderPaths,
        base_dir: Path,
        poll_interval: float = 1.0,
        settle_seconds: float = 2.0,
        recursive: bool = True,
        env: Mapping[str, str] | None = None,
    ) -> None:
        self.db_path = Path(db_path)
        self.uploads_dir = Path(uploads_dir)
        self.paths = paths
        self.base_dir = Path(base_dir)
        self.poll_interval = poll_interval
        self.settle_seconds = settle_seconds
        self.recursive = recursive
        self.env = env
        effective_env = os.environ if env is None else env
        self._requested_engine = resolve_requested_engine_with_settings(
            base_dir=base_dir,
            env=effective_env,
        )
        default_language = resolve_default_language_with_settings(
            base_dir=base_dir,
            env=effective_env,
        )
        if self._requested_engine == PARAKEET_TDT_V3_ENGINE:
            default_language = AUTO_LANGUAGE
        self._language = normalize_language(default_language)
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._candidates: dict[Path, _CandidateState] = {}

    def start(self) -> None:
        if self.is_running():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run_loop,
            name="mlx-ui-hot-folder",
            daemon=True,
        )
        self._thread.start()

    def stop(self, timeout: float | None = None) -> None:
        self._stop_event.set()
        thread = self._thread
        if thread is not None:
            thread.join(timeout=timeout)

    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def _run_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                enqueued = self.scan_once()
            except Exception:
                logger.exception("Hot folder scan failed")
                enqueued = 0
            if enqueued <= 0:
                self._stop_event.wait(self.poll_interval)

    def scan_once(self) -> int:
        input_dir = self.paths.input_dir
        input_dir.mkdir(parents=True, exist_ok=True)
        self.paths.output_dir.mkdir(parents=True, exist_ok=True)
        self.uploads_dir.mkdir(parents=True, exist_ok=True)

        seen: set[Path] = set()
        enqueued = 0

        for path in self._iter_files(input_dir):
            if self._stop_event.is_set():
                break
            seen.add(path)
            if not self._should_consider_file(path):
                self._candidates.pop(path, None)
                continue
            if not self._is_candidate_ready(path):
                continue
            if self._enqueue_path(path):
                enqueued += 1
            self._candidates.pop(path, None)

        stale = [path for path in self._candidates if path not in seen]
        for path in stale:
            self._candidates.pop(path, None)

        return enqueued

    def _iter_files(self, root: Path):
        if self.recursive:
            root_resolved = root.resolve()
            output_resolved = self.paths.output_dir.resolve()
            skip_output = output_resolved.is_relative_to(root_resolved)
            for dirpath, dirnames, filenames in os.walk(root):
                filtered: list[str] = []
                for dirname in dirnames:
                    if not dirname or dirname.startswith("."):
                        continue
                    if skip_output:
                        candidate = (Path(dirpath) / dirname).resolve()
                        if candidate.is_relative_to(output_resolved):
                            continue
                    filtered.append(dirname)
                dirnames[:] = filtered
                for filename in filenames:
                    if not filename or filename.startswith("."):
                        continue
                    path = Path(dirpath) / filename
                    if path.is_file():
                        yield path
        else:
            yield from (path for path in root.iterdir() if path.is_file())

    def _should_consider_file(self, path: Path) -> bool:
        name = path.name
        if not name:
            return False
        if name.startswith("."):
            return False
        suffix = path.suffix.lower()
        if suffix in _SKIP_EXTENSIONS:
            return False
        if suffix in _ALLOWED_EXTENSIONS:
            return True
        mime, _ = mimetypes.guess_type(name)
        return bool(mime and (mime.startswith("audio/") or mime.startswith("video/")))

    def _is_candidate_ready(self, path: Path) -> bool:
        try:
            stat = path.stat()
        except FileNotFoundError:
            self._candidates.pop(path, None)
            return False
        except OSError:
            return False

        previous = self._candidates.get(path)
        if previous is None:
            self._candidates[path] = _CandidateState(
                size=stat.st_size,
                mtime=stat.st_mtime,
                stable_since=time.monotonic(),
            )
            return False

        current_size = stat.st_size
        current_mtime = stat.st_mtime
        if current_size != previous.size or current_mtime != previous.mtime:
            self._candidates[path] = _CandidateState(
                size=current_size,
                mtime=current_mtime,
                stable_since=time.monotonic(),
            )
            return False

        self._candidates[path] = previous

        if (time.time() - current_mtime) < self.settle_seconds:
            return False

        if (time.monotonic() - previous.stable_since) < self.settle_seconds:
            return False

        return True

    def _enqueue_path(self, path: Path) -> bool:
        try:
            relative = path.relative_to(self.paths.input_dir)
        except ValueError:
            logger.warning("Hot folder saw file outside input dir: %s", path)
            return False

        source_path = str(path.resolve())
        source_relpath = relative.as_posix()
        safe_name = sanitize_filename(path.name)
        display_name = sanitize_display_path(source_relpath, safe_name)

        job_id = uuid4().hex
        job_dir = self.uploads_dir / job_id
        job_dir.mkdir(parents=True, exist_ok=True)
        destination = job_dir / safe_name

        try:
            _move_file(path, destination)
        except Exception:
            logger.exception("Hot folder failed to move %s", path)
            return False

        job = JobRecord(
            id=job_id,
            filename=display_name,
            status="queued",
            created_at=_now_utc(),
            upload_path=str(destination),
            language=self._language,
            requested_engine=self._requested_engine,
            source_path=source_path,
            source_relpath=source_relpath,
        )
        try:
            insert_job(self.db_path, job)
        except Exception:
            logger.exception("Hot folder failed to insert job for %s", source_path)
            try:
                destination.parent.mkdir(parents=True, exist_ok=True)
                _move_file(destination, Path(source_path))
            except Exception:
                logger.exception("Hot folder failed to restore %s after enqueue failure", source_path)
            return False

        logger.info("Hot folder queued %s as job %s", source_relpath, job_id)
        return True


def _move_file(src: Path, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        src.rename(dest)
    except OSError:
        shutil.copy2(src, dest)
        src.unlink()


def _now_utc() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


_hot_folder_lock = threading.Lock()
_hot_folder_instance: HotFolderWatcher | None = None


def start_hot_folder(
    *,
    db_path: Path,
    uploads_dir: Path,
    paths: HotFolderPaths,
    base_dir: Path,
    poll_interval: float = 1.0,
    settle_seconds: float = 2.0,
    recursive: bool = True,
    env: Mapping[str, str] | None = None,
) -> HotFolderWatcher:
    global _hot_folder_instance
    with _hot_folder_lock:
        if _hot_folder_instance and _hot_folder_instance.is_running():
            return _hot_folder_instance
        _hot_folder_instance = HotFolderWatcher(
            db_path=db_path,
            uploads_dir=uploads_dir,
            paths=paths,
            base_dir=base_dir,
            poll_interval=poll_interval,
            settle_seconds=settle_seconds,
            recursive=recursive,
            env=env,
        )
        _hot_folder_instance.start()
        return _hot_folder_instance


def stop_hot_folder(timeout: float | None = None) -> None:
    global _hot_folder_instance
    with _hot_folder_lock:
        if not _hot_folder_instance:
            return
        _hot_folder_instance.stop(timeout=timeout)
        _hot_folder_instance = None


def resolve_hot_folder_paths(
    *,
    base_dir: Path,
    env: Mapping[str, str] | None = None,
) -> HotFolderPaths | None:
    effective, _sources, _file_settings = compute_effective_settings(
        base_dir=base_dir,
        env=env,
    )
    if not bool(effective.get("hot_folder_enabled", False)):
        return None
    raw_input_dir = str(effective.get("hot_folder_input_dir") or "").strip()
    raw_output_dir = str(effective.get("hot_folder_output_dir") or "").strip()
    if not raw_input_dir or not raw_output_dir:
        return None
    input_dir = Path(raw_input_dir).expanduser()
    if not input_dir.is_absolute():
        input_dir = (Path(base_dir) / input_dir).resolve()
    output_dir = Path(raw_output_dir).expanduser()
    if not output_dir.is_absolute():
        output_dir = (Path(base_dir) / output_dir).resolve()
    return HotFolderPaths(input_dir=input_dir, output_dir=output_dir)


def resolve_hot_folder_output_dir(
    *,
    base_dir: Path,
    env: Mapping[str, str] | None = None,
) -> Path | None:
    effective, _sources, _file_settings = compute_effective_settings(
        base_dir=base_dir,
        env=env,
    )
    raw_output_dir = str(effective.get("hot_folder_output_dir") or "").strip()
    if not raw_output_dir:
        return None
    output_dir = Path(raw_output_dir).expanduser()
    if not output_dir.is_absolute():
        output_dir = (Path(base_dir) / output_dir).resolve()
    return output_dir


def restore_failed_hot_folder_upload(job: JobRecord) -> Path | None:
    if not job.source_path:
        return None
    upload_path = Path(job.upload_path)
    if not upload_path.is_file():
        return None
    target = Path(job.source_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    resolved_target = _pick_unique_path(target, job.id)
    try:
        _move_file(upload_path, resolved_target)
    except Exception:
        logger.exception("Failed to restore hot-folder input for job %s", job.id)
        return None
    try:
        upload_path.parent.rmdir()
    except OSError:
        pass
    except Exception:
        logger.exception("Failed to remove hot-folder upload directory for job %s", job.id)
    return resolved_target


def export_hot_folder_transcript(
    *,
    job: JobRecord,
    result_path: Path,
    output_dir: Path,
) -> Path | None:
    if not job.source_path:
        return None
    if not result_path.is_file():
        return None

    relpath = (job.source_relpath or "").strip()
    if not relpath:
        relpath = Path(job.filename).name
    relpath = relpath.replace("\\", "/")
    parts = [part for part in relpath.split("/") if part not in {"", ".", ".."}]
    if not parts:
        parts = [Path(job.filename).name or f"{job.id}.txt"]
    target_rel = Path(*parts).with_suffix(".txt")

    output_dir.mkdir(parents=True, exist_ok=True)
    target = output_dir / target_rel
    target.parent.mkdir(parents=True, exist_ok=True)
    resolved_target = _pick_unique_path(target, job.id)
    try:
        shutil.copy2(result_path, resolved_target)
    except Exception:
        logger.exception("Failed to export hot-folder transcript for job %s", job.id)
        return None
    return resolved_target


def _pick_unique_path(path: Path, job_id: str) -> Path:
    if not path.exists():
        return path
    stem = path.stem
    suffix = path.suffix
    base = path.with_name(f"{stem}_{job_id[:8]}{suffix}")
    if not base.exists():
        return base
    for index in range(2, 1000):
        candidate = path.with_name(f"{stem}_{job_id[:8]}_{index}{suffix}")
        if not candidate.exists():
            return candidate
    return base
