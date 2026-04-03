from __future__ import annotations

from datetime import datetime, timezone
import os
from pathlib import Path

from mlx_ui.engine_registry import (
    get_engine_provider,
    is_whisper_available,
    is_wtm_available,
    resolve_runtime_engine,
)
from mlx_ui.runtime_metadata_engine_options import (
    build_registry_engine_options,
    find_engine_option,
)
from mlx_ui.runtime_metadata_integrations import (
    build_cohere_snapshot,
    build_telegram_snapshot,
)
from mlx_ui.runtime_metadata_live import build_live_transcription_snapshot
from mlx_ui.runtime_metadata_local_models import (
    build_local_model_visibility_for_settings,
)
from mlx_ui.settings_schema import DEFAULT_SETTINGS
from mlx_ui.settings_store import compute_effective_settings
from mlx_ui.transcriber import BACKEND_ENV, WtmTranscriber
from mlx_ui.update_check import read_local_version


def build_runtime_metadata(base_dir: Path | None = None) -> dict[str, object]:
    if base_dir is None:
        base_dir = Path(__file__).resolve().parent.parent
    telegram = build_telegram_snapshot(base_dir=base_dir)
    cohere = build_cohere_snapshot(base_dir=base_dir)
    live = build_live_transcription_snapshot(base_dir=base_dir)
    effective, sources, file_settings = compute_effective_settings(base_dir=base_dir)
    local_models = build_local_model_visibility_for_settings(
        effective=effective,
        sources=sources,
        file_settings=file_settings,
        env=os.environ,
    )
    engine_value = str(effective.get("engine") or DEFAULT_SETTINGS["engine"])
    engine_source = sources.get("engine", "default")
    version = read_local_version() or "unknown"
    build_date = read_build_date(base_dir)
    wtm_path = WtmTranscriber().wtm_path
    whisper_available = is_whisper_available()
    wtm_available = is_wtm_available()
    backend_env = os.getenv(BACKEND_ENV, "").strip()
    configured_provider = get_engine_provider(engine_value)
    if configured_provider is None:
        configured_provider = get_engine_provider(str(DEFAULT_SETTINGS["engine"]))
    if configured_provider is None:
        raise ValueError("Default engine registry entry is missing.")
    if backend_env:
        backend_value = backend_env
        backend_source = "env"
        resolved_engine = resolve_runtime_engine(
            configured_provider.id,
            allow_fallback=False,
        )
    else:
        resolved_engine = resolve_runtime_engine(
            configured_provider.id,
            allow_fallback=True,
        )
        backend_value = resolved_engine.implementation.id
        backend_source = engine_source
    active_provider = resolved_engine.provider
    engine_note = resolved_engine.note
    engine_options = build_registry_engine_options(
        configured_engine_id=configured_provider.id,
        active_engine_id=active_provider.id,
    )
    configured_engine = find_engine_option(
        engine_options,
        configured_provider.id,
    )
    active_engine = find_engine_option(engine_options, active_provider.id)
    if (
        configured_engine is not None
        and configured_engine.get("available") is False
        and active_provider.id == configured_provider.id
        and configured_engine.get("reason")
    ):
        engine_note = (
            f"{configured_provider.label} is unavailable. {configured_engine['reason']}"
        )
    return {
        "telegram": telegram,
        "cohere": cohere,
        "live": live,
        "local_models": local_models,
        "about": {
            "version": version,
            "build_date": build_date or "unknown",
            "wtm_path": wtm_path,
            "backend": backend_value,
            "backend_source": backend_source,
            "backend_env": BACKEND_ENV,
            "engine": engine_value,
            "engine_source": engine_source,
            "engine_label": configured_provider.label,
            "engine_active": active_provider.id,
            "engine_active_label": active_provider.label,
            "engine_note": engine_note,
            "configured_engine": configured_engine,
            "active_engine": active_engine,
            "selected_local_model": local_models["selected"],
            "engines": engine_options,
            "compat": {
                "whisper_available": whisper_available,
                "wtm_available": wtm_available,
            },
        },
    }


def read_build_date(base_dir: Path) -> str | None:
    env_value = os.getenv("BUILD_DATE") or os.getenv("APP_BUILD_DATE")
    if env_value:
        return env_value.strip() or None
    pyproject = Path(base_dir) / "pyproject.toml"
    if not pyproject.exists():
        return None
    try:
        timestamp = pyproject.stat().st_mtime
    except OSError:
        return None
    return datetime.fromtimestamp(timestamp, tz=timezone.utc).isoformat(
        timespec="seconds"
    )
