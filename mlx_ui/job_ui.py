from __future__ import annotations

from dataclasses import asdict

from mlx_ui.db import JobRecord
from mlx_ui.engine_registry import (
    get_engine_provider,
    resolve_backend_implementation,
    resolve_backend_provider,
)
from mlx_ui.languages import language_label, normalize_language
from mlx_ui.worker import get_worker_snapshot

_ENGINE_SHORT_LABELS = {
    "whisper_mlx": "MLX",
    "whisper_cpu": "Whisper CPU",
    "parakeet_tdt_v3": "Parakeet",
    "cohere": "Cohere",
    "fake": "Fake",
}


def split_jobs(jobs: list[JobRecord]) -> tuple[list[JobRecord], list[JobRecord]]:
    queue_jobs = [job for job in jobs if job.status in {"queued", "running"}]
    history_jobs = [job for job in jobs if job.status in {"done", "failed", "cancelled"}]
    history_jobs.sort(key=_history_sort_key, reverse=True)
    return queue_jobs, history_jobs


def serialize_job(job: JobRecord) -> dict[str, object]:
    payload = asdict(job)
    payload["ui"] = build_job_ui(job)
    return payload


def build_job_ui(job: JobRecord) -> dict[str, object]:
    requested_engine = _engine_ui(job.requested_engine)
    effective_engine = _engine_ui(job.effective_engine)
    effective_implementation = _implementation_ui(
        engine_id=job.effective_engine,
        implementation_id=job.effective_implementation_id,
    )
    language = _language_ui(job.language)
    engine_badges, engine_summary = _job_engine_badges(
        requested_engine=requested_engine,
        effective_engine=effective_engine,
    )
    if effective_implementation is not None:
        backend_title = str(effective_implementation.get("title") or "")
        for badge in engine_badges:
            kind = str(badge.get("kind") or "")
            if kind not in {"effective", "engine"}:
                continue
            title = str(badge.get("title") or "")
            if backend_title and backend_title not in title:
                badge["title"] = f"{title} ({backend_title})".strip()
    preview_meta_parts = []
    if engine_summary:
        preview_meta_parts.append(engine_summary)
    preview_meta_parts.append(f"Language: {language['label']}")
    if effective_implementation is not None:
        note = str(effective_implementation.get("note") or "")
        if note:
            preview_meta_parts.append(note)
    return {
        "requested_engine": requested_engine,
        "effective_engine": effective_engine,
        "effective_implementation": effective_implementation,
        "engine_badges": engine_badges,
        "engine_summary": engine_summary,
        "language": language,
        "preview_meta": " · ".join(preview_meta_parts),
    }


def queue_groups(jobs: list[JobRecord]) -> tuple[JobRecord | None, list[JobRecord]]:
    running_job = next((job for job in jobs if job.status == "running"), None)
    queued_jobs = [job for job in jobs if job.status == "queued"]
    return running_job, queued_jobs


def worker_state(jobs: list[JobRecord]) -> dict[str, object]:
    queued_count = sum(1 for job in jobs if job.status == "queued")
    worker_snapshot = get_worker_snapshot()
    running_job = None
    if worker_snapshot is not None:
        snapshot_job_id = str(worker_snapshot.get("job_id") or "")
        running_job = next((job for job in jobs if job.id == snapshot_job_id), None)
    if running_job or worker_snapshot is not None:
        current_job_ui = build_job_ui(running_job) if running_job else None
        cancel_requested = bool(worker_snapshot and worker_snapshot.get("cancel_requested"))
        filename = (
            str(worker_snapshot.get("filename") or "")
            if worker_snapshot is not None
            else ""
        ) or (running_job.filename if running_job else None)
        started_at = (
            str(worker_snapshot.get("started_at") or "")
            if worker_snapshot is not None
            else ""
        ) or (running_job.started_at if running_job else None)
        return {
            "status": "Stopping" if cancel_requested else "Running",
            "job_id": (
                str(worker_snapshot.get("job_id"))
                if worker_snapshot is not None
                else running_job.id
            ),
            "filename": filename,
            "started_at": started_at,
            "queue_length": queued_count,
            "current_job_ui": current_job_ui,
            "can_cancel": not cancel_requested,
        }
    running_job = next((job for job in jobs if job.status == "running"), None)
    if running_job:
        current_job_ui = build_job_ui(running_job)
        return {
            "status": "Running",
            "job_id": running_job.id,
            "filename": running_job.filename,
            "started_at": running_job.started_at,
            "queue_length": queued_count,
            "current_job_ui": current_job_ui,
            "can_cancel": True,
        }
    return {
        "status": "Idle",
        "job_id": None,
        "filename": None,
        "started_at": None,
        "queue_length": queued_count,
        "current_job_ui": None,
        "can_cancel": False,
    }


def _history_sort_key(job: JobRecord) -> str:
    return job.completed_at or job.created_at


def _engine_ui(engine_id: str | None) -> dict[str, object] | None:
    normalized = (engine_id or "").strip()
    if not normalized:
        return None
    provider = get_engine_provider(normalized)
    if provider is None:
        provider = resolve_backend_provider(normalized)
        if provider is not None:
            normalized = provider.id
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


def _implementation_ui(
    *,
    engine_id: str | None,
    implementation_id: str | None,
) -> dict[str, str] | None:
    normalized_engine = (engine_id or "").strip()
    normalized_implementation = (implementation_id or "").strip()
    if normalized_implementation:
        normalized_implementation = normalized_implementation.lower()
        if normalized_engine.strip().lower() == normalized_implementation:
            return None
        return {
            "id": normalized_implementation,
            "note": f"Backend: {normalized_implementation}",
            "title": f"Backend: {normalized_implementation}",
        }

    normalized = normalized_engine.strip().lower()
    if not normalized:
        return None
    if get_engine_provider(normalized) is not None:
        return None
    resolved = resolve_backend_implementation(normalized)
    if resolved is None:
        return None
    _provider, implementation = resolved
    aliases = (implementation.id,) + tuple(implementation.backend_aliases)
    if not any(
        (alias or "").strip().lower() == normalized for alias in aliases if alias
    ):
        return None
    if implementation.id.strip().lower() == _provider.id.strip().lower():
        return None
    return {
        "id": implementation.id,
        "note": f"Backend: {implementation.id}",
        "title": f"Backend: {implementation.id}",
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
