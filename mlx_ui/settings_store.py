from __future__ import annotations

import json
import os
from collections.abc import Mapping
from pathlib import Path
import threading

from mlx_ui.engine_registry import resolve_backend_provider
from mlx_ui.languages import parse_language
from mlx_ui.settings_schema import (
    ENGINE_CHOICES,
    DEFAULT_SETTINGS,
    parse_bool,
    normalize_duration,
    normalize_log_level,
    normalize_non_negative_duration,
    normalize_output_formats,
    normalize_parakeet_decoding_mode,
    normalize_positive_int,
)
from mlx_ui.transcriber import (
    BACKEND_ENV,
    COHERE_MODEL_ENV,
    DEFAULT_BACKEND,
    WHISPER_MODEL_ENV,
)
from mlx_ui.update_check import DISABLE_UPDATE_CHECK_ENV, is_update_check_disabled

_SETTINGS_LOCK = threading.Lock()

_HOT_FOLDER_ENABLED_ENV = "HOT_FOLDER_ENABLED"
_HOT_FOLDER_INPUT_ENV = "HOT_FOLDER_INPUT_DIR"
_HOT_FOLDER_OUTPUT_ENV = "HOT_FOLDER_OUTPUT_DIR"


def _resolve_repo_hot_folder_defaults(base_dir: Path) -> tuple[bool, str, str] | None:
    repo_marker = (base_dir / "mlx_ui").is_dir() and (base_dir / "run.sh").is_file()
    if not repo_marker:
        return None
    if not (base_dir / "input").is_dir() or not (base_dir / "output").is_dir():
        return None
    return True, "input", "output"


def get_settings_path(base_dir: Path | None = None) -> Path:
    if base_dir is None:
        base_dir = Path(__file__).resolve().parent.parent
    return Path(base_dir) / "data" / "settings.json"


def read_settings_file(path: Path) -> dict[str, object]:
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(payload, dict):
        return {}
    parsed: dict[str, object] = {}
    engine = payload.get("engine")
    if isinstance(engine, str):
        normalized = engine.strip()
        if normalized in ENGINE_CHOICES:
            parsed["engine"] = normalized
    update_check = payload.get("update_check_enabled")
    if isinstance(update_check, bool):
        parsed["update_check_enabled"] = update_check
    log_level = payload.get("log_level")
    if isinstance(log_level, str):
        parsed["log_level"] = normalize_log_level(log_level)
    wtm_quick = payload.get("wtm_quick")
    if isinstance(wtm_quick, bool):
        parsed["wtm_quick"] = wtm_quick
    output_formats = payload.get("output_formats")
    if output_formats is not None:
        normalized_formats = normalize_output_formats(output_formats)
        if normalized_formats is not None:
            parsed["output_formats"] = normalized_formats
    default_language = parse_language(payload.get("default_language"))
    if default_language is not None:
        parsed["default_language"] = default_language
    hot_folder_enabled = payload.get("hot_folder_enabled")
    if isinstance(hot_folder_enabled, bool):
        parsed["hot_folder_enabled"] = hot_folder_enabled
    hot_folder_input_dir = payload.get("hot_folder_input_dir")
    if isinstance(hot_folder_input_dir, str):
        parsed["hot_folder_input_dir"] = hot_folder_input_dir.strip()
    hot_folder_output_dir = payload.get("hot_folder_output_dir")
    if isinstance(hot_folder_output_dir, str):
        parsed["hot_folder_output_dir"] = hot_folder_output_dir.strip()
    cohere_model = payload.get("cohere_model")
    if isinstance(cohere_model, str):
        parsed["cohere_model"] = cohere_model.strip()
    cohere_api_key = payload.get("cohere_api_key")
    if isinstance(cohere_api_key, str):
        cleaned = cohere_api_key.strip()
        if cleaned:
            parsed["cohere_api_key"] = cleaned
    whisper_model = payload.get("whisper_model")
    if isinstance(whisper_model, str):
        cleaned = whisper_model.strip()
        if cleaned:
            parsed["whisper_model"] = cleaned
    parakeet_model = payload.get("parakeet_model")
    if isinstance(parakeet_model, str):
        cleaned = parakeet_model.strip()
        if cleaned:
            parsed["parakeet_model"] = cleaned
    parakeet_chunk_duration = normalize_duration(payload.get("parakeet_chunk_duration"))
    if parakeet_chunk_duration is not None:
        parsed["parakeet_chunk_duration"] = parakeet_chunk_duration
    parakeet_overlap_duration = normalize_non_negative_duration(
        payload.get("parakeet_overlap_duration")
    )
    if parakeet_overlap_duration is not None:
        parsed["parakeet_overlap_duration"] = parakeet_overlap_duration
    parakeet_decoding_mode = normalize_parakeet_decoding_mode(
        payload.get("parakeet_decoding_mode")
    )
    if parakeet_decoding_mode is not None:
        parsed["parakeet_decoding_mode"] = parakeet_decoding_mode
    parakeet_batch_size = normalize_positive_int(payload.get("parakeet_batch_size"))
    if parakeet_batch_size is not None:
        parsed["parakeet_batch_size"] = parakeet_batch_size
    telegram_token = payload.get("telegram_token")
    if isinstance(telegram_token, str):
        cleaned = telegram_token.strip()
        if cleaned:
            parsed["telegram_token"] = cleaned
    telegram_chat_id = payload.get("telegram_chat_id")
    if isinstance(telegram_chat_id, str):
        cleaned = telegram_chat_id.strip()
        if cleaned:
            parsed["telegram_chat_id"] = cleaned
    return parsed


def write_settings_file(path: Path, data: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(data, indent=2, sort_keys=True)
    tmp_path = path.with_suffix(".tmp")
    tmp_path.write_text(payload + "\n", encoding="utf-8")
    tmp_path.replace(path)


def update_settings_file(
    base_dir: Path | None,
    updates: dict[str, object],
) -> dict[str, object]:
    path = get_settings_path(base_dir)
    with _SETTINGS_LOCK:
        current = read_settings_file(path)
        current.update(updates)
        write_settings_file(path, current)
        return current


def compute_effective_settings(
    base_dir: Path | None = None,
    env: Mapping[str, str] | None = None,
) -> tuple[dict[str, object], dict[str, str], dict[str, object]]:
    if env is None:
        env = os.environ
    resolved_base_dir = (
        Path(__file__).resolve().parent.parent if base_dir is None else Path(base_dir)
    )
    repo_hot_folder_defaults = _resolve_repo_hot_folder_defaults(resolved_base_dir)
    path = get_settings_path(base_dir)
    file_settings = read_settings_file(path)
    effective: dict[str, object] = {}
    sources: dict[str, str] = {}

    backend_env = env.get(BACKEND_ENV, "")
    if backend_env is not None and backend_env.strip() != "":
        effective["engine"] = _engine_from_backend_env(env)
        sources["engine"] = "env"
    elif "engine" in file_settings:
        effective["engine"] = str(file_settings["engine"])
        sources["engine"] = "file"
    else:
        effective["engine"] = DEFAULT_SETTINGS["engine"]
        sources["engine"] = "default"

    disable_value = env.get(DISABLE_UPDATE_CHECK_ENV)
    if disable_value is not None and disable_value.strip() != "":
        effective["update_check_enabled"] = not is_update_check_disabled(env)
        sources["update_check_enabled"] = "env"
    elif "update_check_enabled" in file_settings:
        effective["update_check_enabled"] = bool(file_settings["update_check_enabled"])
        sources["update_check_enabled"] = "file"
    else:
        effective["update_check_enabled"] = DEFAULT_SETTINGS["update_check_enabled"]
        sources["update_check_enabled"] = "default"

    log_level_env = env.get("LOG_LEVEL")
    if log_level_env is not None and log_level_env.strip() != "":
        effective["log_level"] = normalize_log_level(log_level_env)
        sources["log_level"] = "env"
    elif "log_level" in file_settings:
        effective["log_level"] = normalize_log_level(str(file_settings["log_level"]))
        sources["log_level"] = "file"
    else:
        effective["log_level"] = DEFAULT_SETTINGS["log_level"]
        sources["log_level"] = "default"

    quick_env = env.get("WTM_QUICK")
    if quick_env is not None and quick_env.strip() != "":
        parsed = parse_bool(quick_env)
        effective["wtm_quick"] = (
            parsed if parsed is not None else DEFAULT_SETTINGS["wtm_quick"]
        )
        sources["wtm_quick"] = "env"
    elif "wtm_quick" in file_settings:
        effective["wtm_quick"] = bool(file_settings["wtm_quick"])
        sources["wtm_quick"] = "file"
    else:
        effective["wtm_quick"] = DEFAULT_SETTINGS["wtm_quick"]
        sources["wtm_quick"] = "default"

    if "output_formats" in file_settings:
        effective["output_formats"] = list(file_settings["output_formats"])
        sources["output_formats"] = "file"
    else:
        effective["output_formats"] = list(DEFAULT_SETTINGS["output_formats"])
        sources["output_formats"] = "default"

    if "default_language" in file_settings:
        effective["default_language"] = str(file_settings["default_language"])
        sources["default_language"] = "file"
    else:
        effective["default_language"] = DEFAULT_SETTINGS["default_language"]
        sources["default_language"] = "default"

    hot_folder_enabled_env = env.get(_HOT_FOLDER_ENABLED_ENV)
    if hot_folder_enabled_env is not None and hot_folder_enabled_env.strip() != "":
        parsed = parse_bool(hot_folder_enabled_env)
        effective["hot_folder_enabled"] = (
            parsed if parsed is not None else DEFAULT_SETTINGS["hot_folder_enabled"]
        )
        sources["hot_folder_enabled"] = "env"
    elif "hot_folder_enabled" in file_settings:
        effective["hot_folder_enabled"] = bool(file_settings["hot_folder_enabled"])
        sources["hot_folder_enabled"] = "file"
    else:
        default_enabled = (
            repo_hot_folder_defaults[0]
            if repo_hot_folder_defaults is not None
            else DEFAULT_SETTINGS["hot_folder_enabled"]
        )
        effective["hot_folder_enabled"] = default_enabled
        sources["hot_folder_enabled"] = "default"

    hot_folder_input_env = env.get(_HOT_FOLDER_INPUT_ENV)
    if hot_folder_input_env is not None and hot_folder_input_env.strip() != "":
        effective["hot_folder_input_dir"] = hot_folder_input_env.strip()
        sources["hot_folder_input_dir"] = "env"
    elif "hot_folder_input_dir" in file_settings:
        effective["hot_folder_input_dir"] = str(file_settings["hot_folder_input_dir"])
        sources["hot_folder_input_dir"] = "file"
    else:
        default_input = (
            repo_hot_folder_defaults[1]
            if repo_hot_folder_defaults is not None
            else DEFAULT_SETTINGS["hot_folder_input_dir"]
        )
        effective["hot_folder_input_dir"] = default_input
        sources["hot_folder_input_dir"] = "default"

    hot_folder_output_env = env.get(_HOT_FOLDER_OUTPUT_ENV)
    if hot_folder_output_env is not None and hot_folder_output_env.strip() != "":
        effective["hot_folder_output_dir"] = hot_folder_output_env.strip()
        sources["hot_folder_output_dir"] = "env"
    elif "hot_folder_output_dir" in file_settings:
        effective["hot_folder_output_dir"] = str(file_settings["hot_folder_output_dir"])
        sources["hot_folder_output_dir"] = "file"
    else:
        default_output = (
            repo_hot_folder_defaults[2]
            if repo_hot_folder_defaults is not None
            else DEFAULT_SETTINGS["hot_folder_output_dir"]
        )
        effective["hot_folder_output_dir"] = default_output
        sources["hot_folder_output_dir"] = "default"

    cohere_model_env = env.get(COHERE_MODEL_ENV)
    if cohere_model_env is not None and cohere_model_env.strip() != "":
        effective["cohere_model"] = cohere_model_env.strip()
        sources["cohere_model"] = "env"
    elif "cohere_model" in file_settings:
        effective["cohere_model"] = str(file_settings["cohere_model"])
        sources["cohere_model"] = "file"
    else:
        effective["cohere_model"] = DEFAULT_SETTINGS["cohere_model"]
        sources["cohere_model"] = "default"

    model_env = env.get(WHISPER_MODEL_ENV)
    if model_env is not None and model_env.strip() != "":
        effective["whisper_model"] = model_env.strip()
        sources["whisper_model"] = "env"
    elif "whisper_model" in file_settings:
        effective["whisper_model"] = str(file_settings["whisper_model"])
        sources["whisper_model"] = "file"
    else:
        effective["whisper_model"] = DEFAULT_SETTINGS["whisper_model"]
        sources["whisper_model"] = "default"

    if "parakeet_model" in file_settings:
        effective["parakeet_model"] = str(file_settings["parakeet_model"])
        sources["parakeet_model"] = "file"
    else:
        effective["parakeet_model"] = DEFAULT_SETTINGS["parakeet_model"]
        sources["parakeet_model"] = "default"

    if "parakeet_chunk_duration" in file_settings:
        effective["parakeet_chunk_duration"] = file_settings["parakeet_chunk_duration"]
        sources["parakeet_chunk_duration"] = "file"
    else:
        effective["parakeet_chunk_duration"] = DEFAULT_SETTINGS[
            "parakeet_chunk_duration"
        ]
        sources["parakeet_chunk_duration"] = "default"

    if "parakeet_overlap_duration" in file_settings:
        effective["parakeet_overlap_duration"] = file_settings[
            "parakeet_overlap_duration"
        ]
        sources["parakeet_overlap_duration"] = "file"
    else:
        effective["parakeet_overlap_duration"] = DEFAULT_SETTINGS[
            "parakeet_overlap_duration"
        ]
        sources["parakeet_overlap_duration"] = "default"

    if "parakeet_decoding_mode" in file_settings:
        effective["parakeet_decoding_mode"] = str(
            file_settings["parakeet_decoding_mode"]
        )
        sources["parakeet_decoding_mode"] = "file"
    else:
        effective["parakeet_decoding_mode"] = DEFAULT_SETTINGS["parakeet_decoding_mode"]
        sources["parakeet_decoding_mode"] = "default"

    if "parakeet_batch_size" in file_settings:
        effective["parakeet_batch_size"] = file_settings["parakeet_batch_size"]
        sources["parakeet_batch_size"] = "file"
    else:
        effective["parakeet_batch_size"] = DEFAULT_SETTINGS["parakeet_batch_size"]
        sources["parakeet_batch_size"] = "default"

    return effective, sources, file_settings


def _engine_from_backend_env(env: Mapping[str, str]) -> str:
    provider = resolve_backend_provider(
        env.get(BACKEND_ENV, DEFAULT_BACKEND),
        include_hidden=True,
    )
    if provider is not None and provider.visible_in_settings:
        return provider.id
    # Unknown or hidden backend: keep UI stable and use default engine label.
    return str(DEFAULT_SETTINGS["engine"])
