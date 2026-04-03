"""Compatibility shim for the experimental Parakeet NeMo/CUDA backend."""

from __future__ import annotations

from mlx_ui.engines.parakeet_nemo_cuda_experimental import (
    ParakeetNemoCudaTranscriber,
    ParakeetTranscriber,
    load_parakeet_runtime,
)

__all__ = [
    "ParakeetNemoCudaTranscriber",
    "ParakeetTranscriber",
    "load_parakeet_runtime",
]
