from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
import shutil
import threading
from typing import Mapping

from mlx_ui.engine_registry import (
    COHERE_ENGINE,
    DEFAULT_ENGINE_ID,
    PARAKEET_TDT_V3_ENGINE,
    WHISPER_CPU_ENGINE,
    WHISPER_MLX_ENGINE,
    EngineFactoryOptions,
    create_transcriber,
    get_engine_provider,
    get_selectable_engine_ids,
    is_cohere_available as registry_is_cohere_available,
    is_whisper_available as registry_is_whisper_available,
    is_wtm_available as registry_is_wtm_available,
    list_engine_providers,
    resolve_backend_provider,
    resolve_runtime_engine,
    supported_backend_names,
)
from mlx_ui.languages import (
    DEFAULT_LANGUAGE as DEFAULT_JOB_LANGUAGE,
    build_language_options,
    parse_language,
)
from mlx_ui.telegram import mask_secret
from mlx_ui.transcript_result import ALLOWED_OUTPUT_FORMATS
from mlx_ui.update_check import (
    DISABLE_UPDATE_CHECK_ENV,
    is_update_check_disabled,
    read_local_version,
)
from mlx_ui.transcriber import (
    BACKEND_ENV,
    COHERE_API_KEY_ENV,
    COHERE_MODEL_ENV,
    DEFAULT_BACKEND,
    DEFAULT_COHERE_MODEL,
    DEFAULT_WHISPER_MODEL,
    WHISPER_CACHE_DIR_ENV,
    WHISPER_DEVICE_ENV,
    WHISPER_FP16_ENV,
    WHISPER_MODEL_ENV,
    WtmTranscriber,
)

ENGINE_MLX = WHISPER_MLX_ENGINE
ENGINE_CPU = WHISPER_CPU_ENGINE
ENGINE_COHERE = COHERE_ENGINE
ENGINE_PARAKEET = PARAKEET_TDT_V3_ENGINE
ENGINE_CHOICES = tuple(provider.id for provider in list_engine_providers())
CONFIGURABLE_ENGINE_CHOICES = get_selectable_engine_ids()
COHERE_PRODUCT_NOTE = (
    "Cohere runs in the cloud and needs network access. It is not a local/offline engine."
)
PARAKEET_DECODING_CHOICES = ("greedy", "beam")
DEFAULT_PARAKEET_MODEL = "nvidia/parakeet-tdt-0.6b-v3"
DEFAULT_PARAKEET_CHUNK_DURATION = 30
DEFAULT_PARAKEET_OVERLAP_DURATION = 5
DEFAULT_PARAKEET_DECODING_MODE = "greedy"
DEFAULT_PARAKEET_BATCH_SIZE = 1
PARAKEET_LIVE_BETA_ENV = "PARAKEET_LIVE_BETA"
PARAKEET_LIVE_LEFT_CONTEXT_SECS = 10.0
PARAKEET_LIVE_CHUNK_SECS = 2.0
PARAKEET_LIVE_RIGHT_CONTEXT_SECS = 2.0
PARAKEET_LIVE_TIMESLICE_MS = 1000


def is_whisper_available() -> bool:
    return registry_is_whisper_available()


def is_wtm_available() -> bool:
    return registry_is_wtm_available()


def is_cohere_available() -> bool:
    return registry_is_cohere_available()


DEFAULT_SETTINGS: dict[str, object] = {
    "engine": DEFAULT_ENGINE_ID,
    "update_check_enabled": True,
    "log_level": "INFO",
    "wtm_quick": False,
    "output_formats": ["txt"],
    "default_language": DEFAULT_JOB_LANGUAGE,
    "cohere_model": DEFAULT_COHERE_MODEL,
    "whisper_model": DEFAULT_WHISPER_MODEL,
    "parakeet_model": DEFAULT_PARAKEET_MODEL,
    "parakeet_chunk_duration": DEFAULT_PARAKEET_CHUNK_DURATION,
    "parakeet_overlap_duration": DEFAULT_PARAKEET_OVERLAP_DURATION,
    "parakeet_decoding_mode": DEFAULT_PARAKEET_DECODING_MODE,
    "parakeet_batch_size": DEFAULT_PARAKEET_BATCH_SIZE,
}

ALLOWED_LOG_LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")
_SETTINGS_LOCK = threading.Lock()


@dataclass(frozen=True)
class ResolvedTranscriberSettings:
    engine_id: str
    options: EngineFactoryOptions
    cache_key: tuple[object, ...]


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


def normalize_log_level(value: str | None) -> str:
    if not value:
        return DEFAULT_SETTINGS["log_level"]
    candidate = value.strip().upper()
    if candidate in ALLOWED_LOG_LEVELS:
        return candidate
    return DEFAULT_SETTINGS["log_level"]


def normalize_output_formats(value: object) -> list[str] | None:
    if not isinstance(value, list):
        return None
    seen: set[str] = set()
    for item in value:
        if not isinstance(item, str):
            return None
        normalized = item.strip().lower()
        if normalized in ALLOWED_OUTPUT_FORMATS:
            seen.add(normalized)
    seen.add("txt")
    return [fmt for fmt in ALLOWED_OUTPUT_FORMATS if fmt in seen]


def normalize_duration(value: object) -> int | float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if value <= 0:
        return None
    as_float = float(value)
    if as_float.is_integer():
        return int(as_float)
    return as_float


def normalize_non_negative_duration(value: object) -> int | float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if value < 0:
        return None
    as_float = float(value)
    if as_float.is_integer():
        return int(as_float)
    return as_float


def normalize_parakeet_decoding_mode(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    candidate = value.strip().lower()
    if candidate in PARAKEET_DECODING_CHOICES:
        return candidate
    return None


def normalize_positive_int(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    if value < 1:
        return None
    return value


def parse_bool(value: str | None) -> bool | None:
    if value is None:
        return None
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    return None


def compute_effective_settings(
    base_dir: Path | None = None,
    env: Mapping[str, str] | None = None,
) -> tuple[dict[str, object], dict[str, str], dict[str, object]]:
    if env is None:
        env = os.environ
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
        effective["parakeet_decoding_mode"] = DEFAULT_SETTINGS[
            "parakeet_decoding_mode"
        ]
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


def validate_settings_payload(payload: object) -> tuple[dict[str, object], list[str]]:
    if not isinstance(payload, dict):
        return {}, ["Payload must be a JSON object."]
    updates: dict[str, object] = {}
    errors: list[str] = []

    if "engine" in payload:
        value = payload["engine"]
        if isinstance(value, str) and value.strip() in CONFIGURABLE_ENGINE_CHOICES:
            updates["engine"] = value.strip()
        else:
            errors.append(
                f"engine must be one of: {', '.join(CONFIGURABLE_ENGINE_CHOICES)}"
            )

    if "update_check_enabled" in payload:
        value = payload["update_check_enabled"]
        if isinstance(value, bool):
            updates["update_check_enabled"] = value
        else:
            errors.append("update_check_enabled must be a boolean")

    if "log_level" in payload:
        value = payload["log_level"]
        if isinstance(value, str) and value.strip():
            candidate = value.strip().upper()
            if candidate in ALLOWED_LOG_LEVELS:
                updates["log_level"] = candidate
            else:
                errors.append(
                    "log_level must be one of: DEBUG, INFO, WARNING, ERROR, CRITICAL"
                )
        else:
            errors.append("log_level must be a string")

    if "wtm_quick" in payload:
        value = payload["wtm_quick"]
        if isinstance(value, bool):
            updates["wtm_quick"] = value
        else:
            errors.append("wtm_quick must be a boolean")

    if "output_formats" in payload:
        normalized_formats = normalize_output_formats(payload["output_formats"])
        if normalized_formats is None:
            errors.append("output_formats must be a list of strings")
        else:
            updates["output_formats"] = normalized_formats

    if "default_language" in payload:
        value = parse_language(payload["default_language"])
        if value is None:
            errors.append("default_language must be 'auto' or an ISO language code")
        else:
            updates["default_language"] = value

    if "cohere_model" in payload:
        value = payload["cohere_model"]
        if isinstance(value, str):
            updates["cohere_model"] = value.strip()
        else:
            errors.append("cohere_model must be a string")

    if "cohere_api_key" in payload:
        value = payload["cohere_api_key"]
        if isinstance(value, str):
            updates["cohere_api_key"] = value.strip()
        else:
            errors.append("cohere_api_key must be a string")

    if "whisper_model" in payload:
        value = payload["whisper_model"]
        if isinstance(value, str):
            updates["whisper_model"] = value.strip()
        else:
            errors.append("whisper_model must be a string")

    if "parakeet_model" in payload:
        value = payload["parakeet_model"]
        if isinstance(value, str) and value.strip():
            updates["parakeet_model"] = value.strip()
        else:
            errors.append("parakeet_model must be a non-empty string")

    if "parakeet_chunk_duration" in payload:
        value = normalize_duration(payload["parakeet_chunk_duration"])
        if value is None:
            errors.append("parakeet_chunk_duration must be a positive number")
        elif float(value) < 5 or float(value) > 300:
            errors.append("parakeet_chunk_duration must be between 5 and 300 seconds")
        else:
            updates["parakeet_chunk_duration"] = value

    if "parakeet_overlap_duration" in payload:
        value = normalize_non_negative_duration(payload["parakeet_overlap_duration"])
        if value is None:
            errors.append("parakeet_overlap_duration must be zero or a positive number")
        elif float(value) > 60:
            errors.append("parakeet_overlap_duration must be 60 seconds or less")
        else:
            updates["parakeet_overlap_duration"] = value

    if "parakeet_decoding_mode" in payload:
        value = normalize_parakeet_decoding_mode(payload["parakeet_decoding_mode"])
        if value is None:
            errors.append(
                "parakeet_decoding_mode must be one of: "
                f"{', '.join(PARAKEET_DECODING_CHOICES)}"
            )
        else:
            updates["parakeet_decoding_mode"] = value

    if "parakeet_batch_size" in payload:
        value = normalize_positive_int(payload["parakeet_batch_size"])
        if value is None:
            errors.append("parakeet_batch_size must be a positive integer")
        elif value > 16:
            errors.append("parakeet_batch_size must be 16 or less")
        else:
            updates["parakeet_batch_size"] = value

    if "telegram_token" in payload:
        value = payload["telegram_token"]
        if isinstance(value, str):
            updates["telegram_token"] = value.strip()
        else:
            errors.append("telegram_token must be a string")

    if "telegram_chat_id" in payload:
        value = payload["telegram_chat_id"]
        if isinstance(value, str):
            updates["telegram_chat_id"] = value.strip()
        else:
            errors.append("telegram_chat_id must be a string")

    chunk_duration = updates.get(
        "parakeet_chunk_duration",
        DEFAULT_SETTINGS["parakeet_chunk_duration"],
    )
    overlap_duration = updates.get(
        "parakeet_overlap_duration",
        DEFAULT_SETTINGS["parakeet_overlap_duration"],
    )
    if (
        isinstance(chunk_duration, (int, float))
        and isinstance(overlap_duration, (int, float))
        and float(overlap_duration) >= float(chunk_duration)
    ):
        errors.append(
            "parakeet_overlap_duration must be smaller than parakeet_chunk_duration"
        )

    return updates, errors


def build_settings_snapshot(
    base_dir: Path | None = None,
    env: Mapping[str, str] | None = None,
) -> dict[str, object]:
    path = get_settings_path(base_dir)
    effective, sources, _file_settings = compute_effective_settings(
        base_dir=base_dir,
        env=env,
    )
    local_models = _build_local_model_visibility(
        effective=effective,
        env=os.environ if env is None else env,
    )
    configured_engine_id = str(effective.get("engine") or DEFAULT_SETTINGS["engine"])
    configured_default_language = str(
        effective.get("default_language") or DEFAULT_SETTINGS["default_language"]
    )
    engine_options = _build_registry_engine_options(
        configured_engine_id=configured_engine_id,
    )
    configured_engine = _find_engine_option(engine_options, configured_engine_id)
    return {
        "settings": effective,
        "sources": sources,
        "defaults": DEFAULT_SETTINGS,
        "engine": {
            "configured": configured_engine,
        },
        "local_models": local_models,
        "compat": {
            "whisper_available": is_whisper_available(),
            "wtm_available": is_wtm_available(),
        },
        "file": {
            "path": str(path),
            "exists": path.exists(),
        },
        "options": {
            "log_levels": list(ALLOWED_LOG_LEVELS),
            "output_formats": list(ALLOWED_OUTPUT_FORMATS),
            "languages": build_language_options(configured_default_language),
            "parakeet_decoding_modes": list(PARAKEET_DECODING_CHOICES),
            "engines": engine_options,
        },
        "meta": {
            "env_vars": {
                "cohere_api_key": COHERE_API_KEY_ENV,
                "cohere_model": COHERE_MODEL_ENV,
                "engine": BACKEND_ENV,
                "update_check_enabled": DISABLE_UPDATE_CHECK_ENV,
                "log_level": "LOG_LEVEL",
                "wtm_quick": "WTM_QUICK",
                "whisper_model": WHISPER_MODEL_ENV,
            }
        },
    }


def build_telegram_snapshot(
    base_dir: Path | None = None,
    env: Mapping[str, str] | None = None,
) -> dict[str, object]:
    if env is None:
        env = os.environ
    path = get_settings_path(base_dir)
    file_settings = read_settings_file(path)
    token_env = env.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat_env = env.get("TELEGRAM_CHAT_ID", "").strip()
    token_file = str(file_settings.get("telegram_token", "")).strip()
    chat_file = str(file_settings.get("telegram_chat_id", "")).strip()

    if token_env and chat_env:
        source = "env"
        token = token_env
        chat_id = chat_env
        configured = True
    elif token_file and chat_file:
        source = "file"
        token = token_file
        chat_id = chat_file
        configured = True
    else:
        source = "missing"
        token = token_env or token_file
        chat_id = chat_env or chat_file
        configured = False

    return {
        "configured": configured,
        "source": source,
        "token_masked": mask_secret(token),
        "chat_id_masked": mask_secret(chat_id, visible=3),
        "env": {
            "token": bool(token_env),
            "chat_id": bool(chat_env),
        },
        "file": {
            "token": bool(token_file),
            "chat_id": bool(chat_file),
        },
    }


def build_cohere_snapshot(
    base_dir: Path | None = None,
    env: Mapping[str, str] | None = None,
) -> dict[str, object]:
    if env is None:
        env = os.environ
    path = get_settings_path(base_dir)
    file_settings = read_settings_file(path)
    effective, sources, _file_settings = compute_effective_settings(
        base_dir=base_dir,
        env=env,
    )
    provider = get_engine_provider(ENGINE_COHERE)
    if provider is None:
        raise ValueError("Cohere engine registry entry is missing.")

    api_key_env = env.get(COHERE_API_KEY_ENV, "").strip()
    api_key_file = str(file_settings.get("cohere_api_key", "")).strip()
    model = str(effective.get("cohere_model") or DEFAULT_COHERE_MODEL)
    model_source = sources.get("cohere_model", "default")
    selected_engine = str(effective.get("engine") or DEFAULT_SETTINGS["engine"])
    available = provider.is_implemented() and provider.is_available()
    reason = _engine_unavailable_reason(provider, available=available)

    if api_key_env:
        api_key = api_key_env
        api_key_source = "env"
    elif api_key_file:
        api_key = api_key_file
        api_key_source = "file"
    else:
        api_key = ""
        api_key_source = "missing"

    configured = bool(api_key) and bool(model)

    return {
        "available": available,
        "implemented": provider.is_implemented(),
        "configured": configured,
        "selected": selected_engine == ENGINE_COHERE,
        "source": api_key_source,
        "api_key_masked": mask_secret(api_key),
        "api_key_source": api_key_source,
        "model": model,
        "model_source": model_source,
        "local": False,
        "cloud": True,
        "product_note": COHERE_PRODUCT_NOTE,
        "reason": reason,
        "note": reason,
        "env": {
            "api_key": bool(api_key_env),
            "model": bool(env.get(COHERE_MODEL_ENV, "").strip()),
        },
        "file": {
            "api_key": bool(api_key_file),
            "model": bool(str(file_settings.get("cohere_model", "")).strip()),
        },
    }


def list_downloaded_models(env: Mapping[str, str] | None = None) -> list[str]:
    return list_whisper_models(env=env)


def list_whisper_models(env: Mapping[str, str] | None = None) -> list[str]:
    if env is None:
        env = os.environ
    models: set[str] = set()
    models.update(_list_whisper_cache_models(env))
    models.update(_list_hf_cache_models(env, family="whisper"))
    return sorted(models)


def list_parakeet_models(env: Mapping[str, str] | None = None) -> list[str]:
    if env is None:
        env = os.environ
    return _list_hf_cache_models(env, family="parakeet")


def build_local_model_visibility(
    base_dir: Path | None = None,
    env: Mapping[str, str] | None = None,
) -> dict[str, object]:
    if env is None:
        env = os.environ
    effective, _sources, _file_settings = compute_effective_settings(
        base_dir=base_dir,
        env=env,
    )
    return _build_local_model_visibility(
        effective=effective,
        env=env,
    )


def _build_local_model_visibility(
    *,
    effective: Mapping[str, object],
    env: Mapping[str, str],
) -> dict[str, object]:
    selected_engine_id = str(effective.get("engine") or DEFAULT_SETTINGS["engine"])
    whisper_snapshot = _build_local_model_family_snapshot(
        family="whisper",
        engine_id=ENGINE_CPU,
        configured_model=str(
            effective.get("whisper_model") or DEFAULT_SETTINGS["whisper_model"]
        ),
        models=list_whisper_models(env=env),
        cache_dirs=(
            _resolve_whisper_cache_dir(env),
            _resolve_hf_cache_dir(env),
        ),
        selected=selected_engine_id == ENGINE_CPU,
    )
    parakeet_snapshot = _build_local_model_family_snapshot(
        family="parakeet",
        engine_id=ENGINE_PARAKEET,
        configured_model=str(
            effective.get("parakeet_model") or DEFAULT_SETTINGS["parakeet_model"]
        ),
        models=list_parakeet_models(env=env),
        cache_dirs=(_resolve_hf_cache_dir(env),),
        selected=selected_engine_id == ENGINE_PARAKEET,
    )
    return {
        "whisper": whisper_snapshot,
        "parakeet": parakeet_snapshot,
        "selected": _selected_local_model_snapshot(
            whisper_snapshot,
            parakeet_snapshot,
        ),
    }


def _build_local_model_family_snapshot(
    *,
    family: str,
    engine_id: str,
    configured_model: str,
    models: list[str],
    cache_dirs: tuple[Path, ...],
    selected: bool,
) -> dict[str, object]:
    provider = get_engine_provider(engine_id)
    engine_label = provider.label if provider is not None else engine_id
    configured_model_present = _model_appears_present(
        configured_model,
        models,
        family=family,
    )
    family_label = "Whisper" if family == "whisper" else "Parakeet"
    if configured_model_present:
        note = f"Configured {family_label} model appears to be present locally."
    else:
        note = (
            f"Configured {family_label} model was not found in local caches and may "
            "download on first use."
        )
    return {
        "family": family,
        "engine_id": engine_id,
        "engine_label": engine_label,
        "configured_model": configured_model,
        "configured_model_present": configured_model_present,
        "selected": selected,
        "models": models,
        "cache_dirs": [
            {
                "path": str(path),
                "exists": path.is_dir(),
            }
            for path in _dedupe_paths(cache_dirs)
        ],
        "note": note,
    }


def _selected_local_model_snapshot(
    whisper_snapshot: Mapping[str, object],
    parakeet_snapshot: Mapping[str, object],
) -> dict[str, object] | None:
    for snapshot in (whisper_snapshot, parakeet_snapshot):
        if snapshot.get("selected"):
            return {
                "family": snapshot["family"],
                "engine_id": snapshot["engine_id"],
                "engine_label": snapshot["engine_label"],
                "model_id": snapshot["configured_model"],
                "present": snapshot["configured_model_present"],
                "note": snapshot["note"],
            }
    return None


def _dedupe_paths(paths: tuple[Path, ...]) -> tuple[Path, ...]:
    unique: list[Path] = []
    seen: set[Path] = set()
    for path in paths:
        if path in seen:
            continue
        seen.add(path)
        unique.append(path)
    return tuple(unique)


def _list_whisper_cache_models(env: Mapping[str, str]) -> list[str]:
    cache_dir = _resolve_whisper_cache_dir(env)
    if not cache_dir.is_dir():
        return []
    models: set[str] = set()
    try:
        for entry in cache_dir.iterdir():
            if entry.is_file() and entry.suffix == ".pt":
                models.add(entry.stem)
    except OSError:
        return []
    return sorted(models)


def _resolve_whisper_cache_dir(env: Mapping[str, str]) -> Path:
    env_dir = env.get(WHISPER_CACHE_DIR_ENV)
    if env_dir:
        return Path(env_dir)
    xdg_cache = env.get("XDG_CACHE_HOME")
    if xdg_cache:
        return Path(xdg_cache) / "whisper"
    return Path.home() / ".cache" / "whisper"


def _list_hf_cache_models(
    env: Mapping[str, str],
    *,
    family: str | None = None,
) -> list[str]:
    cache_dir = _resolve_hf_cache_dir(env)
    if not cache_dir.is_dir():
        return []
    models: set[str] = set()
    try:
        for entry in cache_dir.iterdir():
            if not entry.is_dir():
                continue
            name = entry.name
            if not name.startswith("models--"):
                continue
            if not _hf_cache_entry_looks_ready(entry):
                continue
            parts = name[len("models--") :].split("--")
            if len(parts) >= 2:
                model = f"{parts[0]}/{parts[1]}"
                if family == "whisper" and "whisper" in model.lower():
                    models.add(model)
                elif family == "parakeet" and "parakeet" in model.lower():
                    models.add(model)
                elif family is None:
                    models.add(model)
    except OSError:
        return []
    return sorted(models)


def _hf_cache_entry_looks_ready(entry: Path) -> bool:
    return any((entry / name).exists() for name in ("snapshots", "refs", "blobs"))


def _resolve_hf_cache_dir(env: Mapping[str, str]) -> Path:
    hub_cache = env.get("HUGGINGFACE_HUB_CACHE") or env.get("HF_HUB_CACHE")
    if hub_cache:
        return Path(hub_cache)
    hf_home = env.get("HF_HOME")
    if hf_home:
        return Path(hf_home) / "hub"
    xdg_cache = env.get("XDG_CACHE_HOME")
    if xdg_cache:
        return Path(xdg_cache) / "huggingface" / "hub"
    return Path.home() / ".cache" / "huggingface" / "hub"


def build_runtime_metadata(base_dir: Path | None = None) -> dict[str, object]:
    if base_dir is None:
        base_dir = Path(__file__).resolve().parent.parent
    telegram = build_telegram_snapshot(base_dir=base_dir)
    cohere = build_cohere_snapshot(base_dir=base_dir)
    live = build_live_transcription_snapshot(base_dir=base_dir)
    effective, sources, _file_settings = compute_effective_settings(base_dir=base_dir)
    local_models = _build_local_model_visibility(
        effective=effective,
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
    active_provider = configured_provider
    engine_note = None
    if backend_env:
        backend_value = backend_env
        backend_source = "env"
        active_provider, engine_note = resolve_runtime_engine(
            configured_provider.id,
            allow_fallback=False,
        )
    else:
        active_provider, engine_note = resolve_runtime_engine(
            configured_provider.id,
            allow_fallback=True,
        )
        backend_value = active_provider.backend or DEFAULT_BACKEND
        backend_source = engine_source
    engine_options = _build_registry_engine_options(
        configured_engine_id=configured_provider.id,
        active_engine_id=active_provider.id,
    )
    configured_engine = _find_engine_option(
        engine_options,
        configured_provider.id,
    )
    active_engine = _find_engine_option(engine_options, active_provider.id)
    if (
        configured_engine is not None
        and configured_engine.get("available") is False
        and active_provider.id == configured_provider.id
        and configured_engine.get("reason")
    ):
        engine_note = (
            f"{configured_provider.label} is unavailable. "
            f"{configured_engine['reason']}"
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


def build_live_transcription_snapshot(
    base_dir: Path | None = None,
    env: Mapping[str, str] | None = None,
) -> dict[str, object]:
    if env is None:
        env = os.environ
    effective, _sources, _file_settings = compute_effective_settings(
        base_dir=base_dir,
        env=env,
    )
    provider = get_engine_provider(ENGINE_PARAKEET)
    if provider is None:
        raise ValueError("Parakeet engine registry entry is missing.")
    enabled = parse_bool(env.get(PARAKEET_LIVE_BETA_ENV))
    flag_enabled = enabled is True
    ffmpeg_available = shutil.which("ffmpeg") is not None
    configured_model = str(
        effective.get("parakeet_model") or DEFAULT_SETTINGS["parakeet_model"]
    )
    decoding_mode = str(
        effective.get("parakeet_decoding_mode")
        or DEFAULT_SETTINGS["parakeet_decoding_mode"]
    )
    supported = (
        provider.is_available() and ffmpeg_available and decoding_mode == "greedy"
    )
    reason = None
    if not flag_enabled:
        reason = (
            f"Experimental flag is off. Set {PARAKEET_LIVE_BETA_ENV}=1 to try the "
            "Parakeet live beta on a supported Linux + CUDA machine."
        )
    elif not provider.is_available():
        reason = _provider_unavailable_detail(provider)
    elif not ffmpeg_available:
        reason = "ffmpeg is required to decode browser audio chunks for the live beta."
    elif decoding_mode != "greedy":
        reason = (
            "Parakeet live beta currently requires greedy decoding. "
            "Switch Parakeet decoding mode back to greedy in Settings."
        )
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


def resolve_requested_engine_with_settings(
    base_dir: Path | None = None,
    env: Mapping[str, str] | None = None,
) -> str:
    if env is None:
        env = os.environ
    backend_from_env = env.get(BACKEND_ENV, "").strip().lower()
    if backend_from_env:
        provider = resolve_backend_provider(backend_from_env)
        if provider is not None:
            return provider.id
    effective, _sources, _file_settings = compute_effective_settings(
        base_dir=base_dir,
        env=env,
    )
    engine = str(effective.get("engine") or DEFAULT_SETTINGS["engine"])
    if get_engine_provider(engine) is not None:
        return engine
    return str(DEFAULT_SETTINGS["engine"])


def resolve_default_language_with_settings(
    base_dir: Path | None = None,
    env: Mapping[str, str] | None = None,
) -> str:
    effective, _sources, _file_settings = compute_effective_settings(
        base_dir=base_dir,
        env=env,
    )
    return str(
        effective.get("default_language") or DEFAULT_SETTINGS["default_language"]
    )


def resolve_job_transcriber_spec_with_settings(
    requested_engine: str | None = None,
    *,
    base_dir: Path | None = None,
    env: Mapping[str, str] | None = None,
) -> ResolvedTranscriberSettings:
    if env is None:
        env = os.environ
    effective, sources, file_settings = compute_effective_settings(
        base_dir=base_dir,
        env=env,
    )
    requested_engine_id = _normalize_engine_id(requested_engine)
    if requested_engine_id is not None:
        provider = _resolve_requested_job_provider(requested_engine_id)
        backend_from_env = ""
    else:
        provider, backend_from_env = _resolve_current_job_provider(
            effective=effective,
            sources=sources,
            env=env,
        )
    options = _build_engine_factory_options(
        provider.id,
        effective=effective,
        file_settings=file_settings,
        env=env,
        backend_from_env=backend_from_env,
        explicit_request=requested_engine_id is not None,
    )
    return ResolvedTranscriberSettings(
        engine_id=provider.id,
        options=options,
        cache_key=_build_transcriber_cache_key(
            provider.id,
            options=options,
            env=env,
            backend_from_env=backend_from_env,
        ),
    )


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


def resolve_transcriber_with_settings(
    base_dir: Path | None = None,
    env: Mapping[str, str] | None = None,
):
    resolved = resolve_job_transcriber_spec_with_settings(
        base_dir=base_dir,
        env=env,
    )
    return create_transcriber(
        resolved.engine_id,
        options=resolved.options,
    )


def _resolve_requested_job_provider(requested_engine: str):
    provider = get_engine_provider(requested_engine)
    if provider is None:
        raise ValueError(f"Job requested unknown engine '{requested_engine}'.")
    if not provider.is_available():
        raise ValueError(
            f"Job requested engine '{requested_engine}' but {provider.label} is unavailable: "
            f"{_provider_unavailable_detail(provider)}"
        )
    if not provider.is_implemented():
        raise ValueError(
            f"Job requested engine '{requested_engine}' but {provider.label} is not implemented yet."
        )
    return provider


def _resolve_current_job_provider(
    *,
    effective: Mapping[str, object],
    sources: Mapping[str, str],
    env: Mapping[str, str],
):
    backend_from_env = env.get(BACKEND_ENV, "").strip().lower()
    if backend_from_env:
        provider = resolve_backend_provider(backend_from_env)
        if provider is None:
            supported = "', '".join(supported_backend_names())
            raise ValueError(
                f"Unknown transcriber backend '{backend_from_env}'. Use '{supported}'."
            )
        if not provider.is_available():
            raise ValueError(
                f"Configured backend '{backend_from_env}' cannot be used because "
                f"{provider.label} is unavailable: {_provider_unavailable_detail(provider)}"
            )
        if not provider.is_implemented():
            raise ValueError(
                f"Configured backend '{backend_from_env}' is not implemented yet."
            )
        return provider, backend_from_env
    engine = str(effective.get("engine") or DEFAULT_SETTINGS["engine"])
    provider, _engine_note = resolve_runtime_engine(
        engine,
        allow_fallback=True,
    )
    if not provider.is_available():
        source = sources.get("engine", "default")
        raise ValueError(
            f"Configured engine '{engine}' from {source} cannot be used because "
            f"{provider.label} is unavailable: {_provider_unavailable_detail(provider)}"
        )
    if not provider.is_implemented():
        raise ValueError(f"Configured engine '{engine}' is not implemented yet.")
    return provider, ""


def _build_engine_factory_options(
    engine_id: str,
    *,
    effective: Mapping[str, object],
    file_settings: Mapping[str, object],
    env: Mapping[str, str],
    backend_from_env: str,
    explicit_request: bool,
) -> EngineFactoryOptions:
    device = None
    if engine_id == ENGINE_CPU and (explicit_request or not backend_from_env):
        device = "cpu"
    return EngineFactoryOptions(
        quick=bool(effective["wtm_quick"]) if engine_id == ENGINE_MLX else None,
        model_name=(
            str(effective["cohere_model"])
            if engine_id == ENGINE_COHERE
            else (
                str(effective["whisper_model"]) if engine_id == ENGINE_CPU else None
            )
        ),
        api_key=(
            _resolve_cohere_api_key(file_settings=file_settings, env=env)
            if engine_id == ENGINE_COHERE
            else None
        ),
        device=device,
        repo_id=(
            str(effective["parakeet_model"])
            if engine_id == ENGINE_PARAKEET
            else None
        ),
        chunk_duration=(
            float(effective["parakeet_chunk_duration"])
            if engine_id == ENGINE_PARAKEET
            else None
        ),
        overlap_duration=(
            float(effective["parakeet_overlap_duration"])
            if engine_id == ENGINE_PARAKEET
            else None
        ),
        decoding_mode=(
            str(effective["parakeet_decoding_mode"])
            if engine_id == ENGINE_PARAKEET
            else None
        ),
        batch_size=(
            int(effective["parakeet_batch_size"])
            if engine_id == ENGINE_PARAKEET
            else None
        ),
        output_formats=tuple(str(fmt) for fmt in effective["output_formats"]),
    )


def _build_transcriber_cache_key(
    engine_id: str,
    *,
    options: EngineFactoryOptions,
    env: Mapping[str, str],
    backend_from_env: str,
) -> tuple[object, ...]:
    return (
        engine_id,
        options.quick,
        _cache_secret_key(options.api_key),
        options.model_name,
        options.device,
        options.repo_id,
        options.chunk_duration,
        options.overlap_duration,
        options.decoding_mode,
        options.batch_size,
        options.output_formats,
        backend_from_env,
        env.get("WTM_PATH", ""),
        env.get(WHISPER_DEVICE_ENV, ""),
        env.get(WHISPER_FP16_ENV, ""),
        env.get(WHISPER_CACHE_DIR_ENV, ""),
        env.get("XDG_CACHE_HOME", ""),
    )


def _resolve_cohere_api_key(
    *,
    file_settings: Mapping[str, object],
    env: Mapping[str, str],
) -> str | None:
    from_env = env.get(COHERE_API_KEY_ENV, "").strip()
    if from_env:
        return from_env
    from_file = str(file_settings.get("cohere_api_key", "")).strip()
    if from_file:
        return from_file
    return None


def _cache_secret_key(secret: str | None) -> str | None:
    if not secret:
        return None
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()


def _model_appears_present(
    configured_model: str,
    models: list[str],
    *,
    family: str,
) -> bool:
    normalized_models = {model.strip().lower() for model in models if model.strip()}
    return any(
        candidate in normalized_models
        for candidate in _configured_model_candidates(configured_model, family=family)
    )


def _configured_model_candidates(
    configured_model: str,
    *,
    family: str,
) -> tuple[str, ...]:
    normalized = configured_model.strip().lower()
    if not normalized:
        return ()
    candidates = {normalized}
    if "/" in normalized:
        candidates.add(normalized.rsplit("/", 1)[-1])
    if family == "whisper":
        if normalized.startswith("openai/whisper-"):
            candidates.add(normalized.removeprefix("openai/whisper-"))
        if normalized.startswith("whisper-"):
            candidates.add(normalized.removeprefix("whisper-"))
    return tuple(sorted(candidates))


def _build_registry_engine_options(
    *,
    configured_engine_id: str | None = None,
    active_engine_id: str | None = None,
) -> list[dict[str, object]]:
    options: list[dict[str, object]] = []
    for provider in list_engine_providers(visible_only=True):
        available = provider.is_implemented() and provider.is_available()
        reason = _engine_unavailable_reason(provider, available=available)
        options.append(
            {
                "id": provider.id,
                "label": provider.label,
                "mode": provider.mode,
                "local": provider.mode == "local",
                "cloud": provider.mode == "cloud",
                "available": available,
                "configured": provider.id == configured_engine_id,
                "active": provider.id == active_engine_id and available,
                "selectable": provider.selectable and available,
                "implemented": provider.is_implemented(),
                "reason": reason,
                "note": reason,
                "disabled": (not provider.selectable) or not available,
                "disabled_label": _engine_disabled_label(provider, available=available),
            }
        )
    return options


def _find_engine_option(
    options: list[dict[str, object]],
    engine_id: str,
) -> dict[str, object] | None:
    for option in options:
        if option["id"] == engine_id:
            return option
    return None


def _engine_unavailable_reason(provider, *, available: bool) -> str | None:
    if available:
        return None
    detail = provider.unavailable_reason()
    if not provider.is_available() and detail:
        return _normalize_unavailable_reason(detail)
    if not provider.is_implemented():
        return "Not implemented yet."
    if detail:
        return _normalize_unavailable_reason(detail)
    return "Not available."


def _engine_disabled_label(provider, *, available: bool) -> str | None:
    if available and provider.selectable:
        return None
    if not provider.is_implemented():
        return provider.disabled_label or "Unavailable"
    if not provider.selectable:
        return provider.disabled_label or "Unavailable"
    return provider.disabled_label


def _provider_unavailable_detail(provider) -> str:
    detail = (provider.unavailable_reason() or "not available.").strip()
    if detail.endswith("."):
        return detail[:-1]
    return detail


def _normalize_unavailable_reason(detail: str) -> str:
    normalized = detail.strip()
    if not normalized:
        return "Not available."
    return normalized[0].upper() + normalized[1:]


def _normalize_engine_id(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    if not normalized:
        return None
    return normalized
