from __future__ import annotations

from mlx_ui.engine_registry import (
    COHERE_ENGINE,
    DEFAULT_ENGINE_ID,
    PARAKEET_TDT_V3_ENGINE,
    WHISPER_CPU_ENGINE,
    WHISPER_MLX_ENGINE,
    get_selectable_engine_ids,
    list_engine_providers,
)
from mlx_ui.engines.parakeet_mlx_runtime import parakeet_mlx_supports_beam_decoding
from mlx_ui.languages import DEFAULT_LANGUAGE as DEFAULT_JOB_LANGUAGE
from mlx_ui.languages import parse_language
from mlx_ui.transcriber import DEFAULT_COHERE_MODEL, DEFAULT_WHISPER_MODEL
from mlx_ui.transcript_result import ALLOWED_OUTPUT_FORMATS

ENGINE_MLX = WHISPER_MLX_ENGINE
ENGINE_CPU = WHISPER_CPU_ENGINE
ENGINE_COHERE = COHERE_ENGINE
ENGINE_PARAKEET = PARAKEET_TDT_V3_ENGINE
ENGINE_CHOICES = tuple(provider.id for provider in list_engine_providers())
CONFIGURABLE_ENGINE_CHOICES = get_selectable_engine_ids()
COHERE_PRODUCT_NOTE = "Cohere runs in the cloud and needs network access. It is not a local/offline engine."
PARAKEET_DECODING_CHOICES = ("greedy", "beam")
DEFAULT_PARAKEET_MODEL = "mlx-community/parakeet-tdt-0.6b-v3"
LEGACY_PARAKEET_NEMO_MODEL = "nvidia/parakeet-tdt-0.6b-v3"
DEFAULT_PARAKEET_CHUNK_DURATION = 30
DEFAULT_PARAKEET_OVERLAP_DURATION = 5
DEFAULT_PARAKEET_DECODING_MODE = "greedy"
DEFAULT_PARAKEET_BATCH_SIZE = 1


def supported_parakeet_decoding_modes() -> tuple[str, ...]:
    if parakeet_mlx_supports_beam_decoding():
        return PARAKEET_DECODING_CHOICES
    return ("greedy",)


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


def normalize_log_level(value: str | None) -> str:
    if not value:
        return str(DEFAULT_SETTINGS["log_level"])
    candidate = value.strip().upper()
    if candidate in ALLOWED_LOG_LEVELS:
        return candidate
    return str(DEFAULT_SETTINGS["log_level"])


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
                f"parakeet_decoding_mode must be one of: {', '.join(PARAKEET_DECODING_CHOICES)}"
            )
        elif value not in supported_parakeet_decoding_modes():
            choices = supported_parakeet_decoding_modes()
            errors.append(
                f"parakeet_decoding_mode must be one of: {', '.join(choices)}"
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
