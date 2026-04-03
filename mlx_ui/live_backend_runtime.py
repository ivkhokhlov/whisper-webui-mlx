from __future__ import annotations

from dataclasses import dataclass
import os
import sys
from typing import Literal, Mapping

from mlx_ui.engine_registry import (
    PARAKEET_MLX_BACKEND,
    PARAKEET_NEMO_CUDA_BACKEND,
    PARAKEET_NEMO_CUDA_EXPERIMENTAL_ENV,
    is_parakeet_nemo_cuda_experimental_enabled,
)
from mlx_ui.engines.parakeet_mlx_live_runtime import (
    parakeet_mlx_live_runtime_unavailability_reason,
)

LiveBackendState = Literal["supported", "experimental", "unavailable"]


@dataclass(frozen=True)
class LiveBackendResolution:
    state: LiveBackendState
    implementation_id: str | None
    reason: str | None


def resolve_parakeet_live_backend(
    *,
    env: Mapping[str, str] | None = None,
) -> LiveBackendResolution:
    if env is None:
        env = os.environ

    if sys.platform == "darwin":
        reason = parakeet_mlx_live_runtime_unavailability_reason()
        if reason is None:
            return LiveBackendResolution(
                state="supported",
                implementation_id=PARAKEET_MLX_BACKEND,
                reason=None,
            )
        return LiveBackendResolution(
            state="unavailable",
            implementation_id=PARAKEET_MLX_BACKEND,
            reason=reason,
        )

    if not is_parakeet_nemo_cuda_experimental_enabled(env):
        return LiveBackendResolution(
            state="unavailable",
            implementation_id=None,
            reason=(
                "Parakeet live beta currently targets Apple Silicon (arm64) on macOS. "
                f"Internal Linux CUDA backends can be enabled with {PARAKEET_NEMO_CUDA_EXPERIMENTAL_ENV}=1."
            ),
        )

    nemo_reason = _parakeet_nemo_cuda_live_unavailability_reason(env)
    if nemo_reason is not None:
        return LiveBackendResolution(
            state="unavailable",
            implementation_id=PARAKEET_NEMO_CUDA_BACKEND,
            reason=nemo_reason,
        )

    return LiveBackendResolution(
        state="experimental",
        implementation_id=PARAKEET_NEMO_CUDA_BACKEND,
        reason=None,
    )


def _parakeet_nemo_cuda_live_unavailability_reason(
    env: Mapping[str, str],
) -> str | None:
    from mlx_ui.engines.parakeet_nemo_cuda_live_runtime_experimental import (
        parakeet_nemo_cuda_live_runtime_unavailability_reason,
    )

    return parakeet_nemo_cuda_live_runtime_unavailability_reason(env=env)
