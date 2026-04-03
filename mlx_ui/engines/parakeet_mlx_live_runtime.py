from __future__ import annotations

from dataclasses import dataclass
import importlib
import importlib.util
import platform
import sys


PARAKEET_MLX_MODULE = "parakeet_mlx"


@dataclass(frozen=True)
class ParakeetMlxLiveRuntime:
    from_pretrained: object
    StreamingParakeet: type
    mx: object


def parakeet_mlx_live_runtime_unavailability_reason() -> str | None:
    platform_id = _platform()
    if platform_id != "darwin":
        return "Parakeet MLX live beta is supported on macOS only."

    machine = _machine().lower()
    if machine not in {"arm64", "aarch64"}:
        return "Parakeet MLX live beta is supported on Apple Silicon (arm64) only."

    if importlib.util.find_spec(PARAKEET_MLX_MODULE) is None:
        return (
            "The optional 'parakeet-mlx' dependency is not installed "
            f"(Python module '{PARAKEET_MLX_MODULE}')."
        )

    module = _import_parakeet_mlx()
    if module is None:
        return (
            "The optional 'parakeet-mlx' dependency is not installed "
            f"(Python module '{PARAKEET_MLX_MODULE}')."
        )

    streaming_cls = getattr(module, "StreamingParakeet", None)
    if streaming_cls is None:
        return (
            "The installed Parakeet MLX runtime does not expose a streaming API "
            "(missing StreamingParakeet)."
        )
    add_audio = getattr(streaming_cls, "add_audio", None)
    result = getattr(streaming_cls, "result", None)
    if not callable(add_audio) or result is None:
        return (
            "The installed Parakeet MLX runtime does not expose a usable streaming API "
            "(StreamingParakeet is missing required methods)."
        )

    if not callable(getattr(module, "from_pretrained", None)):
        return "The installed Parakeet MLX runtime is missing the expected from_pretrained() loader."

    return None


def is_parakeet_mlx_live_runtime_usable() -> bool:
    return parakeet_mlx_live_runtime_unavailability_reason() is None


def load_parakeet_mlx_live_runtime() -> ParakeetMlxLiveRuntime:
    reason = parakeet_mlx_live_runtime_unavailability_reason()
    if reason:
        raise RuntimeError(f"Parakeet MLX live backend cannot run: {reason}")
    module = _import_parakeet_mlx()
    if module is None:
        raise RuntimeError(
            "Parakeet MLX live backend selected but the optional 'parakeet-mlx' dependency is not installed."
        )
    try:
        from mlx import core as mx  # type: ignore[import-not-found]
    except Exception as exc:  # pragma: no cover - optional dep passthrough
        raise RuntimeError(
            "Parakeet MLX live backend selected but the optional 'mlx' runtime dependency is not installed."
        ) from exc
    from_pretrained = getattr(module, "from_pretrained", None)
    streaming_cls = getattr(module, "StreamingParakeet", None)
    if not callable(from_pretrained) or streaming_cls is None:
        raise RuntimeError(
            "Parakeet MLX live backend cannot load the expected runtime symbols."
        )
    return ParakeetMlxLiveRuntime(
        from_pretrained=from_pretrained,
        StreamingParakeet=streaming_cls,
        mx=mx,
    )


def _import_parakeet_mlx():
    try:
        return importlib.import_module(PARAKEET_MLX_MODULE)
    except Exception:
        return None


def _platform() -> str:
    return sys.platform


def _machine() -> str:
    return platform.machine()
