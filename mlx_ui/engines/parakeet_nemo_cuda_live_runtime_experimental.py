from __future__ import annotations

from dataclasses import dataclass
import importlib.util
import sys
from typing import Callable, Mapping


@dataclass(frozen=True)
class ParakeetNemoCudaLiveRuntime:
    torch: object
    ContextSize: type
    StreamingBatchedAudioBuffer: type
    batched_hyps_to_hypotheses: Callable[..., list[object]]


def parakeet_nemo_cuda_live_runtime_unavailability_reason(
    *,
    env: Mapping[str, str] | None = None,
) -> str | None:
    if not sys.platform.startswith("linux"):
        return "Parakeet NeMo/CUDA live backend requires Linux with an NVIDIA CUDA GPU."

    if importlib.util.find_spec("torch") is None:
        return "PyTorch is not installed."
    try:
        import torch  # type: ignore[import-not-found]
    except Exception:
        return "PyTorch could not be imported."
    if not torch.cuda.is_available():
        return "CUDA is not available in the current PyTorch environment."

    if importlib.util.find_spec("nemo.collections.asr") is None:
        return "NVIDIA NeMo ASR is not installed."
    if importlib.util.find_spec("omegaconf") is None:
        return "OmegaConf is not installed."
    if importlib.util.find_spec("nemo.collections.asr.parts.utils.rnnt_utils") is None:
        return "NVIDIA NeMo streaming utilities are not installed."
    if (
        importlib.util.find_spec("nemo.collections.asr.parts.utils.streaming_utils")
        is None
    ):
        return "NVIDIA NeMo streaming utilities are not installed."

    return None


def load_parakeet_nemo_cuda_live_runtime() -> tuple[
    object, object, ParakeetNemoCudaLiveRuntime
]:
    reason = parakeet_nemo_cuda_live_runtime_unavailability_reason()
    if reason:
        raise RuntimeError(f"Parakeet NeMo/CUDA live backend cannot run: {reason}")

    from mlx_ui.engines.parakeet_nemo_cuda_experimental import load_parakeet_runtime

    nemo_asr, open_dict = load_parakeet_runtime()
    try:
        import torch  # type: ignore[import-not-found]
        from nemo.collections.asr.parts.utils.rnnt_utils import (  # type: ignore[import-not-found]
            batched_hyps_to_hypotheses,
        )
        from nemo.collections.asr.parts.utils.streaming_utils import (  # type: ignore[import-not-found]
            ContextSize,
            StreamingBatchedAudioBuffer,
        )
    except Exception as exc:  # pragma: no cover - optional dep passthrough
        raise RuntimeError(
            "Parakeet NeMo/CUDA live backend requires NVIDIA NeMo streaming utilities and PyTorch."
        ) from exc
    return (
        nemo_asr,
        open_dict,
        ParakeetNemoCudaLiveRuntime(
            torch=torch,
            ContextSize=ContextSize,
            StreamingBatchedAudioBuffer=StreamingBatchedAudioBuffer,
            batched_hyps_to_hypotheses=batched_hyps_to_hypotheses,
        ),
    )
