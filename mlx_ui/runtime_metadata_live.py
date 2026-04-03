from __future__ import annotations

import os
from pathlib import Path
from typing import Callable, Mapping

from mlx_ui.engine_registry import get_engine_provider
from mlx_ui.live_backend_runtime import resolve_parakeet_live_backend
from mlx_ui.runtime_metadata_engine_options import provider_unavailable_detail
from mlx_ui.runtime_metadata_local_models import resolve_parakeet_configured_model
from mlx_ui.settings_schema import (
    DEFAULT_SETTINGS,
    ENGINE_PARAKEET,
    parse_bool,
)
from mlx_ui.settings_store import compute_effective_settings

PARAKEET_LIVE_BETA_ENV = "PARAKEET_LIVE_BETA"
PARAKEET_LIVE_LEFT_CONTEXT_SECS = 10.0
PARAKEET_LIVE_CHUNK_SECS = 2.0
PARAKEET_LIVE_RIGHT_CONTEXT_SECS = 2.0
PARAKEET_LIVE_TIMESLICE_MS = 1000


def build_live_transcription_snapshot(
    base_dir: Path | None = None,
    env: Mapping[str, str] | None = None,
    *,
    which: Callable[[str], str | None] | None = None,
) -> dict[str, object]:
    if env is None:
        env = os.environ
    if which is None:
        import shutil

        which = shutil.which
    effective, sources, file_settings = compute_effective_settings(
        base_dir=base_dir,
        env=env,
    )
    provider = get_engine_provider(ENGINE_PARAKEET)
    if provider is None:
        raise ValueError("Parakeet engine registry entry is missing.")
    enabled = parse_bool(env.get(PARAKEET_LIVE_BETA_ENV))
    flag_enabled = enabled is True
    ffmpeg_available = which("ffmpeg") is not None
    configured_model = resolve_parakeet_configured_model(
        effective=effective,
        sources=sources,
        file_settings=file_settings,
    )
    decoding_mode = str(
        effective.get("parakeet_decoding_mode")
        or DEFAULT_SETTINGS["parakeet_decoding_mode"]
    )
    backend = resolve_parakeet_live_backend(env=env)
    supports_live = (
        backend.state in {"supported", "experimental"} and backend.reason is None
    )

    supported = supports_live and ffmpeg_available and decoding_mode == "greedy"
    reason = None
    if not flag_enabled:
        reason = (
            f"Experimental flag is off. Set {PARAKEET_LIVE_BETA_ENV}=1 to try the "
            "Parakeet live beta on a supported machine (experimental)."
        )
    elif not ffmpeg_available:
        reason = "ffmpeg is required to decode browser audio chunks for the live beta."
    elif decoding_mode != "greedy":
        reason = (
            "Parakeet live beta currently requires greedy decoding. "
            "Switch Parakeet decoding mode back to greedy in Settings."
        )
    elif not supports_live:
        reason = backend.reason or provider_unavailable_detail(provider)
    return {
        "enabled": flag_enabled,
        "supported": supported,
        "active": flag_enabled and supported,
        "experimental": True,
        "engine_id": provider.id,
        "engine_label": provider.label,
        "local": True,
        "cloud": False,
        "configured_model": configured_model,
        "decoding_mode": decoding_mode,
        "left_context_secs": PARAKEET_LIVE_LEFT_CONTEXT_SECS,
        "chunk_secs": PARAKEET_LIVE_CHUNK_SECS,
        "right_context_secs": PARAKEET_LIVE_RIGHT_CONTEXT_SECS,
        "timeslice_ms": PARAKEET_LIVE_TIMESLICE_MS,
        "latency_secs": PARAKEET_LIVE_CHUNK_SECS + PARAKEET_LIVE_RIGHT_CONTEXT_SECS,
        "flag_env": PARAKEET_LIVE_BETA_ENV,
        "ffmpeg_available": ffmpeg_available,
        "reason": reason,
        "note": (
            "Experimental local-only Parakeet streaming. Browser microphone capture, "
            "chunk delivery, and partial updates are beta-quality and may still be fragile."
        ),
    }
