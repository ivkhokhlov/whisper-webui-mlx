from __future__ import annotations

from pathlib import Path
import shutil
from typing import Mapping

from mlx_ui.engine_registry import (
    is_cohere_available as registry_is_cohere_available,
    is_whisper_available as registry_is_whisper_available,
    is_wtm_available as registry_is_wtm_available,
)
from mlx_ui.runtime_metadata_about import (
    build_runtime_metadata as build_runtime_metadata,
    read_build_date as read_build_date,
)
from mlx_ui.runtime_metadata_integrations import (
    build_cohere_snapshot as build_cohere_snapshot,
    build_telegram_snapshot as build_telegram_snapshot,
)
from mlx_ui.runtime_metadata_live import (
    PARAKEET_LIVE_BETA_ENV as PARAKEET_LIVE_BETA_ENV,
    PARAKEET_LIVE_CHUNK_SECS as PARAKEET_LIVE_CHUNK_SECS,
    PARAKEET_LIVE_LEFT_CONTEXT_SECS as PARAKEET_LIVE_LEFT_CONTEXT_SECS,
    PARAKEET_LIVE_RIGHT_CONTEXT_SECS as PARAKEET_LIVE_RIGHT_CONTEXT_SECS,
    PARAKEET_LIVE_TIMESLICE_MS as PARAKEET_LIVE_TIMESLICE_MS,
)
from mlx_ui.runtime_metadata_local_models import (
    build_local_model_visibility as build_local_model_visibility,
    list_downloaded_models as list_downloaded_models,
    list_parakeet_models as list_parakeet_models,
    list_whisper_models as list_whisper_models,
)
from mlx_ui.runtime_metadata_settings_snapshot import (
    build_settings_snapshot as build_settings_snapshot,
)

from mlx_ui import runtime_metadata_live as _live


def is_whisper_available() -> bool:
    return registry_is_whisper_available()


def is_wtm_available() -> bool:
    return registry_is_wtm_available()


def is_cohere_available() -> bool:
    return registry_is_cohere_available()


def build_live_transcription_snapshot(
    base_dir: Path | None = None,
    env: Mapping[str, str] | None = None,
) -> dict[str, object]:
    # Compatibility wrapper: keep a stable monkeypatch target in tests by
    # explicitly threading runtime_metadata.shutil.which into the new module.
    return _live.build_live_transcription_snapshot(
        base_dir=base_dir,
        env=env,
        which=shutil.which,
    )
