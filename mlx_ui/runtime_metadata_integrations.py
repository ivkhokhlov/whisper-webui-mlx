from __future__ import annotations

import os
from pathlib import Path
from typing import Mapping

from mlx_ui.engine_registry import get_engine_provider
from mlx_ui.runtime_metadata_engine_options import engine_unavailable_reason
from mlx_ui.settings_schema import (
    COHERE_PRODUCT_NOTE,
    DEFAULT_SETTINGS,
    ENGINE_COHERE,
)
from mlx_ui.settings_store import (
    compute_effective_settings,
    get_settings_path,
    read_settings_file,
)
from mlx_ui.telegram import mask_secret
from mlx_ui.transcriber import (
    COHERE_API_KEY_ENV,
    COHERE_MODEL_ENV,
    DEFAULT_COHERE_MODEL,
)


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
    reason = engine_unavailable_reason(provider, available=available)

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
