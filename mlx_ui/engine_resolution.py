from __future__ import annotations

from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
from typing import Mapping

from mlx_ui.engine_registry import (
    EngineFactoryOptions,
    create_transcriber,
    get_engine_provider,
    resolve_backend_implementation,
    resolve_backend_provider,
    resolve_runtime_engine,
    supported_backend_names,
)
from mlx_ui.settings_schema import (
    DEFAULT_SETTINGS,
    ENGINE_COHERE,
    ENGINE_CPU,
    ENGINE_MLX,
    ENGINE_PARAKEET,
)
from mlx_ui.settings_store import compute_effective_settings
from mlx_ui.transcriber import (
    BACKEND_ENV,
    COHERE_API_KEY_ENV,
    WHISPER_CACHE_DIR_ENV,
    WHISPER_DEVICE_ENV,
    WHISPER_FP16_ENV,
)


@dataclass(frozen=True)
class ResolvedTranscriberSettings:
    engine_id: str
    options: EngineFactoryOptions
    cache_key: tuple[object, ...]
    implementation_id: str | None = None


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
        provider, implementation = _resolve_requested_job_provider(requested_engine_id)
        backend_from_env = ""
    else:
        provider, implementation, backend_from_env = _resolve_current_job_provider(
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
        implementation_id=implementation.id,
        options=options,
        cache_key=_build_transcriber_cache_key(
            provider.id,
            implementation_id=implementation.id,
            options=options,
            env=env,
            backend_from_env=backend_from_env,
        ),
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
        implementation_id=resolved.implementation_id,
        options=resolved.options,
    )


def _resolve_requested_job_provider(requested_engine: str):
    provider = get_engine_provider(requested_engine)
    if provider is None:
        raise ValueError(f"Job requested unknown engine '{requested_engine}'.")
    implementation = next(
        (
            candidate
            for candidate in provider.implementations
            if candidate.is_implemented() and candidate.is_available()
        ),
        None,
    )
    if implementation is None:
        if not provider.is_available():
            raise ValueError(
                f"Job requested engine '{requested_engine}' but {provider.label} is unavailable: "
                f"{_provider_unavailable_detail(provider)}"
            )
        raise ValueError(
            f"Job requested engine '{requested_engine}' but {provider.label} is not implemented yet."
        )
    return provider, implementation


def _resolve_current_job_provider(
    *,
    effective: Mapping[str, object],
    sources: Mapping[str, str],
    env: Mapping[str, str],
):
    backend_from_env = env.get(BACKEND_ENV, "").strip().lower()
    if backend_from_env:
        resolved_backend = resolve_backend_implementation(backend_from_env)
        if resolved_backend is None:
            supported = "', '".join(supported_backend_names())
            raise ValueError(
                f"Unknown transcriber backend '{backend_from_env}'. Use '{supported}'."
            )
        provider, implementation = resolved_backend
        if not implementation.is_implemented():
            raise ValueError(
                f"Configured backend '{backend_from_env}' is not implemented yet."
            )
        return provider, implementation, backend_from_env
    engine = str(effective.get("engine") or DEFAULT_SETTINGS["engine"])
    resolved_engine = resolve_runtime_engine(
        engine,
        allow_fallback=True,
    )
    provider = resolved_engine.provider
    implementation = resolved_engine.implementation
    if not provider.is_available():
        source = sources.get("engine", "default")
        raise ValueError(
            f"Configured engine '{engine}' from {source} cannot be used because "
            f"{provider.label} is unavailable: {_provider_unavailable_detail(provider)}"
        )
    if not provider.is_implemented():
        raise ValueError(f"Configured engine '{engine}' is not implemented yet.")
    return provider, implementation, ""


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
            else (str(effective["whisper_model"]) if engine_id == ENGINE_CPU else None)
        ),
        api_key=(
            _resolve_cohere_api_key(file_settings=file_settings, env=env)
            if engine_id == ENGINE_COHERE
            else None
        ),
        device=device,
        repo_id=(
            str(effective["parakeet_model"]) if engine_id == ENGINE_PARAKEET else None
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
    implementation_id: str | None,
    options: EngineFactoryOptions,
    env: Mapping[str, str],
    backend_from_env: str,
) -> tuple[object, ...]:
    return (
        engine_id,
        implementation_id or "",
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


def _provider_unavailable_detail(provider) -> str:
    detail = (provider.unavailable_reason() or "not available.").strip()
    if detail.endswith("."):
        return detail[:-1]
    return detail


def _normalize_engine_id(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    if not normalized:
        return None
    return normalized
