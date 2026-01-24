from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
import threading
from typing import Mapping

from mlx_ui.telegram import mask_secret
from mlx_ui.update_check import (
    DISABLE_UPDATE_CHECK_ENV,
    is_update_check_disabled,
    read_local_version,
)
from mlx_ui.transcriber import (
    BACKEND_ENV,
    DEFAULT_BACKEND,
    DEFAULT_WHISPER_MODEL,
    WHISPER_CACHE_DIR_ENV,
    WHISPER_MODEL_ENV,
    FakeTranscriber,
    WhisperTranscriber,
    WtmTranscriber,
)

DEFAULT_SETTINGS: dict[str, object] = {
    "update_check_enabled": True,
    "log_level": "INFO",
    "wtm_quick": False,
    "output_formats": ["txt"],
    "whisper_model": DEFAULT_WHISPER_MODEL,
}

ALLOWED_LOG_LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")
ALLOWED_OUTPUT_FORMATS = ("txt", "srt", "vtt", "json")

_SETTINGS_LOCK = threading.Lock()


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
    whisper_model = payload.get("whisper_model")
    if isinstance(whisper_model, str):
        cleaned = whisper_model.strip()
        if cleaned:
            parsed["whisper_model"] = cleaned
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

    return effective, sources, file_settings


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

    if "whisper_model" in payload:
        value = payload["whisper_model"]
        if isinstance(value, str):
            updates["whisper_model"] = value.strip()
        else:
            errors.append("whisper_model must be a string")

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
    return {
        "settings": effective,
        "sources": sources,
        "defaults": DEFAULT_SETTINGS,
        "file": {
            "path": str(path),
            "exists": path.exists(),
        },
        "options": {
            "log_levels": list(ALLOWED_LOG_LEVELS),
            "output_formats": list(ALLOWED_OUTPUT_FORMATS),
        },
        "meta": {
            "env_vars": {
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


def list_downloaded_models(env: Mapping[str, str] | None = None) -> list[str]:
    if env is None:
        env = os.environ
    models: set[str] = set()
    models.update(_list_whisper_cache_models(env))
    models.update(_list_hf_cache_models(env))
    return sorted(models)


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


def _list_hf_cache_models(env: Mapping[str, str]) -> list[str]:
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
            parts = name[len("models--") :].split("--")
            if len(parts) >= 2:
                model = f"{parts[0]}/{parts[1]}"
                if "whisper" in model.lower():
                    models.add(model)
    except OSError:
        return []
    return sorted(models)


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
    version = read_local_version() or "unknown"
    build_date = read_build_date(base_dir)
    wtm_path = WtmTranscriber().wtm_path
    return {
        "telegram": telegram,
        "about": {
            "version": version,
            "build_date": build_date or "unknown",
            "wtm_path": wtm_path,
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


def resolve_transcriber_with_settings(
    base_dir: Path | None = None,
    env: Mapping[str, str] | None = None,
):
    if env is None:
        env = os.environ
    effective, _sources, _file_settings = compute_effective_settings(
        base_dir=base_dir,
        env=env,
    )
    backend = env.get(BACKEND_ENV, DEFAULT_BACKEND).strip().lower()
    if backend in {"wtm", "mlx", "wtm-cli"}:
        return WtmTranscriber(quick=bool(effective["wtm_quick"]))
    if backend in {"whisper", "openai-whisper", "openai"}:
        return WhisperTranscriber(model_name=str(effective["whisper_model"]))
    if backend in {"fake", "noop", "test"}:
        return FakeTranscriber()
    raise ValueError(
        f"Unknown transcriber backend '{backend}'. Use 'wtm', 'whisper', or 'fake'."
    )
