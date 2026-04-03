from __future__ import annotations

import os
from pathlib import Path
from typing import Mapping

from mlx_ui.engine_registry import get_engine_provider
from mlx_ui.engine_resolution import resolve_effective_parakeet_repo_id
from mlx_ui.settings_schema import (
    DEFAULT_SETTINGS,
    ENGINE_CPU,
    ENGINE_PARAKEET,
)
from mlx_ui.settings_store import compute_effective_settings
from mlx_ui.transcriber import WHISPER_CACHE_DIR_ENV


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
    effective, sources, file_settings = compute_effective_settings(
        base_dir=base_dir,
        env=env,
    )
    return build_local_model_visibility_for_settings(
        effective=effective,
        sources=sources,
        file_settings=file_settings,
        env=env,
    )


def build_local_model_visibility_for_settings(
    *,
    effective: Mapping[str, object],
    sources: Mapping[str, str],
    file_settings: Mapping[str, object],
    env: Mapping[str, str],
) -> dict[str, object]:
    return _build_local_model_visibility(
        effective=effective,
        sources=sources,
        file_settings=file_settings,
        env=env,
    )


def _build_local_model_visibility(
    *,
    effective: Mapping[str, object],
    sources: Mapping[str, str],
    file_settings: Mapping[str, object],
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
        configured_model=resolve_parakeet_configured_model(
            effective=effective,
            sources=sources,
            file_settings=file_settings,
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


def resolve_parakeet_configured_model(
    *,
    effective: Mapping[str, object],
    sources: Mapping[str, str],
    file_settings: Mapping[str, object] | None = None,
) -> str:
    configured = str(
        effective.get("parakeet_model") or DEFAULT_SETTINGS["parakeet_model"]
    )
    source = sources.get("parakeet_model", "default")
    provider = get_engine_provider(ENGINE_PARAKEET)
    if provider is None:
        return configured
    implementation = provider.display_implementation()
    if implementation is None:
        return configured
    return resolve_effective_parakeet_repo_id(
        configured_model=configured,
        source=source,
        implementation_id=implementation.id,
        file_settings=file_settings,
    )


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
