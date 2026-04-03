from __future__ import annotations

import os
from pathlib import Path
from typing import Mapping

from mlx_ui.engine_registry import (
    PARAKEET_MLX_BACKEND,
    PARAKEET_NEMO_CUDA_BACKEND,
    is_whisper_available as registry_is_whisper_available,
    is_wtm_available as registry_is_wtm_available,
)
from mlx_ui.engine_resolution import resolve_effective_parakeet_repo_id
from mlx_ui.languages import build_language_options
from mlx_ui.runtime_metadata_engine_options import (
    build_registry_engine_options,
    find_engine_option,
)
from mlx_ui.runtime_metadata_local_models import (
    build_local_model_visibility_for_settings,
)
from mlx_ui.settings_schema import (
    ALLOWED_LOG_LEVELS,
    DEFAULT_SETTINGS,
    ENGINE_PARAKEET,
    supported_parakeet_decoding_modes,
)
from mlx_ui.settings_store import compute_effective_settings, get_settings_path
from mlx_ui.transcriber import (
    BACKEND_ENV,
    COHERE_API_KEY_ENV,
    COHERE_MODEL_ENV,
    WHISPER_MODEL_ENV,
)
from mlx_ui.transcript_result import ALLOWED_OUTPUT_FORMATS
from mlx_ui.update_check import DISABLE_UPDATE_CHECK_ENV


def build_settings_snapshot(
    base_dir: Path | None = None,
    env: Mapping[str, str] | None = None,
) -> dict[str, object]:
    path = get_settings_path(base_dir)
    effective, sources, file_settings = compute_effective_settings(
        base_dir=base_dir,
        env=env,
    )
    env_value = os.environ if env is None else env
    local_models = build_local_model_visibility_for_settings(
        effective=effective,
        sources=sources,
        file_settings=file_settings,
        env=env_value,
    )
    configured_engine_id = str(effective.get("engine") or DEFAULT_SETTINGS["engine"])
    configured_default_language = str(
        effective.get("default_language") or DEFAULT_SETTINGS["default_language"]
    )
    engine_options = build_registry_engine_options(
        configured_engine_id=configured_engine_id,
    )
    configured_engine = find_engine_option(engine_options, configured_engine_id)
    parakeet_decoding_modes = list(supported_parakeet_decoding_modes())
    supports_beam_decoding = "beam" in parakeet_decoding_modes

    configured_parakeet_model = str(
        effective.get("parakeet_model") or DEFAULT_SETTINGS["parakeet_model"]
    )
    parakeet_effective_model_id = configured_parakeet_model
    parakeet_model_note = None
    parakeet_model_source = sources.get("parakeet_model", "default")
    parakeet_implementation_id = None
    parakeet_engine = find_engine_option(engine_options, ENGINE_PARAKEET)
    implementation_value = (
        None if parakeet_engine is None else parakeet_engine.get("implementation_id")
    )
    if isinstance(implementation_value, str) and implementation_value.strip():
        parakeet_implementation_id = implementation_value
        parakeet_effective_model_id = resolve_effective_parakeet_repo_id(
            configured_model=configured_parakeet_model,
            source=parakeet_model_source,
            implementation_id=implementation_value,
            file_settings=file_settings,
        )
        if parakeet_effective_model_id != configured_parakeet_model:
            if (
                implementation_value == PARAKEET_NEMO_CUDA_BACKEND
                and parakeet_model_source == "default"
            ):
                parakeet_model_note = "Using the experimental NVIDIA NeMo/CUDA Parakeet default model id for this backend."
            elif (
                implementation_value == PARAKEET_MLX_BACKEND
                and parakeet_model_source == "file"
            ):
                parakeet_model_note = (
                    "Detected a legacy Parakeet model id from an older settings file; "
                    "using the MLX default model id instead."
                )

    return {
        "settings": effective,
        "sources": sources,
        "defaults": DEFAULT_SETTINGS,
        "engine": {
            "configured": configured_engine,
        },
        "local_models": local_models,
        "compat": {
            "whisper_available": registry_is_whisper_available(),
            "wtm_available": registry_is_wtm_available(),
        },
        "file": {
            "path": str(path),
            "exists": path.exists(),
        },
        "options": {
            "log_levels": list(ALLOWED_LOG_LEVELS),
            "output_formats": list(ALLOWED_OUTPUT_FORMATS),
            "languages": build_language_options(configured_default_language),
            "parakeet_decoding_modes": parakeet_decoding_modes,
            "parakeet": {
                "implementation_id": parakeet_implementation_id,
                "effective_model_id": parakeet_effective_model_id,
                "model_note": parakeet_model_note,
                "supports_beam_decoding": supports_beam_decoding,
                "batch_size_control_active": parakeet_implementation_id
                == PARAKEET_NEMO_CUDA_BACKEND,
            },
            "engines": engine_options,
        },
        "meta": {
            "env_vars": {
                "cohere_api_key": COHERE_API_KEY_ENV,
                "cohere_model": COHERE_MODEL_ENV,
                "engine": BACKEND_ENV,
                "hot_folder_enabled": "HOT_FOLDER_ENABLED",
                "hot_folder_input_dir": "HOT_FOLDER_INPUT_DIR",
                "hot_folder_output_dir": "HOT_FOLDER_OUTPUT_DIR",
                "update_check_enabled": DISABLE_UPDATE_CHECK_ENV,
                "log_level": "LOG_LEVEL",
                "wtm_quick": "WTM_QUICK",
                "whisper_model": WHISPER_MODEL_ENV,
            }
        },
    }
