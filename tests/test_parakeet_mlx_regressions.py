import json
from pathlib import Path

import mlx_ui.engine_registry as engine_registry
from mlx_ui.engine_resolution import (
    DEFAULT_PARAKEET_MLX_MODEL_ID,
    resolve_job_transcriber_spec_with_settings,
    resolve_requested_engine_with_settings,
)


def _write_settings(tmp_path: Path, payload: dict[str, object]) -> None:
    settings_path = tmp_path / "data" / "settings.json"
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    settings_path.write_text(json.dumps(payload), encoding="utf-8")


def test_parakeet_backend_alias_maps_to_family_engine() -> None:
    provider, implementation = engine_registry.resolve_backend_implementation(
        engine_registry.PARAKEET_MLX_BACKEND
    )
    assert provider.id == engine_registry.PARAKEET_TDT_V3_ENGINE
    assert implementation.id == engine_registry.PARAKEET_MLX_BACKEND
    assert engine_registry.resolve_backend_provider("parakeet").id == (
        engine_registry.PARAKEET_TDT_V3_ENGINE
    )


def test_env_override_parakeet_backend_returns_family_engine_id(tmp_path: Path) -> None:
    _write_settings(tmp_path, {"engine": "whisper_cpu"})
    assert (
        resolve_requested_engine_with_settings(
            base_dir=tmp_path,
            env={"TRANSCRIBER_BACKEND": engine_registry.PARAKEET_MLX_BACKEND},
        )
        == engine_registry.PARAKEET_TDT_V3_ENGINE
    )


def test_parakeet_resolution_keeps_family_id_and_sets_implementation_id(
    tmp_path: Path, monkeypatch
) -> None:
    _write_settings(tmp_path, {"engine": engine_registry.PARAKEET_TDT_V3_ENGINE})
    monkeypatch.setattr(engine_registry, "is_parakeet_mlx_runtime_usable", lambda: True)

    resolved = resolve_job_transcriber_spec_with_settings(base_dir=tmp_path, env={})

    assert resolved.engine_id == engine_registry.PARAKEET_TDT_V3_ENGINE
    assert resolved.implementation_id == engine_registry.PARAKEET_MLX_BACKEND


def test_parakeet_settings_legacy_nemo_default_model_is_migrated_to_mlx_on_parakeet_mlx(
    tmp_path: Path, monkeypatch
) -> None:
    _write_settings(
        tmp_path,
        {
            "engine": engine_registry.PARAKEET_TDT_V3_ENGINE,
            "parakeet_model": "nvidia/parakeet-tdt-0.6b-v3",
            "parakeet_chunk_duration": 30,
            "parakeet_overlap_duration": 5,
            "parakeet_decoding_mode": "greedy",
            "parakeet_batch_size": 1,
        },
    )
    monkeypatch.setattr(engine_registry, "is_parakeet_mlx_runtime_usable", lambda: True)

    resolved = resolve_job_transcriber_spec_with_settings(base_dir=tmp_path, env={})

    # Older settings files may still contain the legacy NeMo-style repo id; on Apple
    # Silicon we treat that as a previous default and switch to the MLX-compatible id.
    assert resolved.options.repo_id == DEFAULT_PARAKEET_MLX_MODEL_ID
