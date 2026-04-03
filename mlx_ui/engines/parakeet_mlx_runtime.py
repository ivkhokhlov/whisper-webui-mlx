from __future__ import annotations

import importlib
import importlib.util
import platform
import sys


PARAKEET_MLX_MODULE = "parakeet_mlx"
_DEFAULT_BEAM_SIZE = 4


def parakeet_mlx_runtime_unavailability_reason() -> str | None:
    platform_id = _platform()
    if platform_id != "darwin":
        return "Parakeet MLX runtime is supported on macOS only."

    machine = _machine().lower()
    if machine not in {"arm64", "aarch64"}:
        return "Parakeet MLX runtime is supported on Apple Silicon (arm64) only."

    if importlib.util.find_spec(PARAKEET_MLX_MODULE) is None:
        return (
            "The optional 'parakeet-mlx' dependency is not installed "
            f"(Python module '{PARAKEET_MLX_MODULE}')."
        )

    return None


def is_parakeet_mlx_runtime_usable() -> bool:
    return parakeet_mlx_runtime_unavailability_reason() is None


def parakeet_mlx_exposes_advanced_decoding_config_types() -> bool:
    if not is_parakeet_mlx_runtime_usable():
        return False
    module = _import_parakeet_mlx()
    if module is None:
        return False
    return all(
        hasattr(module, name)
        for name in (
            "DecodingConfig",
            "Beam",
            "Greedy",
        )
    )


def build_parakeet_mlx_decoding_config(
    mode: str,
    *,
    beam_size: int = _DEFAULT_BEAM_SIZE,
) -> object | None:
    if not is_parakeet_mlx_runtime_usable():
        return None
    module = _import_parakeet_mlx()
    if module is None:
        return None
    decoding_config = getattr(module, "DecodingConfig", None)
    beam_cls = getattr(module, "Beam", None)
    greedy_cls = getattr(module, "Greedy", None)
    if not all(callable(obj) for obj in (decoding_config, beam_cls, greedy_cls)):
        return None

    normalized_mode = mode.strip().lower()
    if normalized_mode == "beam":
        strategy = _try_construct(
            beam_cls,
            candidates=(
                ((), {}),
                ((), {"beam_size": beam_size}),
                ((), {"num_beams": beam_size}),
                ((), {"width": beam_size}),
                ((), {"beam_width": beam_size}),
            ),
        )
    else:
        strategy = _try_construct(
            greedy_cls,
            candidates=(((), {}),),
        )
    if strategy is None:
        return None

    return _try_construct(
        decoding_config,
        candidates=(
            ((strategy,), {}),
            ((), {"strategy": strategy}),
            ((), {"decoding": strategy}),
            ((), {"decoder": strategy}),
            ((), {"mode": strategy}),
        ),
    )


def parakeet_mlx_supports_beam_decoding() -> bool:
    return build_parakeet_mlx_decoding_config("beam") is not None


def _try_construct(
    constructor,
    *,
    candidates: tuple[tuple[tuple[object, ...], dict[str, object]], ...],
) -> object | None:
    for args, kwargs in candidates:
        try:
            return constructor(*args, **kwargs)
        except Exception:
            continue
    return None


def _import_parakeet_mlx():
    try:
        return importlib.import_module(PARAKEET_MLX_MODULE)
    except Exception:
        return None


def _platform() -> str:
    return sys.platform


def _machine() -> str:
    return platform.machine()
