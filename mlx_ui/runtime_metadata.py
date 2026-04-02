from __future__ import annotations

from datetime import datetime, timezone
import os
from pathlib import Path
import shutil
from typing import Mapping

from mlx_ui.engine_registry import (
    get_engine_provider,
    is_cohere_available as registry_is_cohere_available,
    is_whisper_available as registry_is_whisper_available,
    is_wtm_available as registry_is_wtm_available,
    list_engine_providers,
    resolve_runtime_engine,
)
from mlx_ui.languages import build_language_options
from mlx_ui.settings_schema import (
    ALLOWED_LOG_LEVELS,
    COHERE_PRODUCT_NOTE,
    DEFAULT_SETTINGS,
    ENGINE_COHERE,
    ENGINE_CPU,
    ENGINE_PARAKEET,
    PARAKEET_DECODING_CHOICES,
    parse_bool,
)
from mlx_ui.settings_store import (
    compute_effective_settings,
    get_settings_path,
    read_settings_file,
)
from mlx_ui.telegram import mask_secret
from mlx_ui.transcriber import (
    BACKEND_ENV,
    COHERE_API_KEY_ENV,
    COHERE_MODEL_ENV,
    DEFAULT_COHERE_MODEL,
    WHISPER_CACHE_DIR_ENV,
    WHISPER_MODEL_ENV,
    WtmTranscriber,
)
from mlx_ui.transcript_result import ALLOWED_OUTPUT_FORMATS
from mlx_ui.update_check import (
    DISABLE_UPDATE_CHECK_ENV,
    read_local_version,
)

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
    resolved_engine = None
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
        instantiable = provider.is_implemented()
        runtime_present = provider.is_available()
        available = instantiable and runtime_present
        reason = _engine_unavailable_reason(provider, available=available)
        options.append(
            {
                "id": provider.id,
                "label": provider.label,
                "mode": provider.mode,
                "local": provider.mode == "local",
                "cloud": provider.mode == "cloud",
                "available": available,
                "runtime_present": runtime_present,
                "instantiable": instantiable,
                "configured": provider.id == configured_engine_id,
                "active": provider.id == active_engine_id and available,
                "selectable": provider.selectable and available,
                "selectable_flag": provider.selectable,
                "implemented": instantiable,
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
