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

    reason = _find_spec_unavailability_reason(
        "torch",
        missing_reason="PyTorch is not installed.",
        inspect_reason="PyTorch could not be inspected.",
    )
    if reason is not None:
        return reason
    try:
        import torch  # type: ignore[import-not-found]
    except Exception:
        return "PyTorch could not be imported."
    if not torch.cuda.is_available():
        return "CUDA is not available in the current PyTorch environment."

    for module_name, missing_reason, inspect_reason in (
        (
            "nemo.collections.asr",
            "NVIDIA NeMo ASR is not installed.",
            "NVIDIA NeMo ASR could not be inspected.",
        ),
        (
            "omegaconf",
            "OmegaConf is not installed.",
            "OmegaConf could not be inspected.",
        ),
        (
            "nemo.collections.asr.parts.utils.rnnt_utils",
            "NVIDIA NeMo streaming utilities are not installed.",
            "NVIDIA NeMo streaming utilities could not be inspected.",
        ),
        (
            "nemo.collections.asr.parts.utils.streaming_utils",
            "NVIDIA NeMo streaming utilities are not installed.",
            "NVIDIA NeMo streaming utilities could not be inspected.",
        ),
    ):
        reason = _find_spec_unavailability_reason(
            module_name,
            missing_reason=missing_reason,
            inspect_reason=inspect_reason,
        )
        if reason is not None:
            return reason

    return None


def _find_spec_unavailability_reason(
    module_name: str,
    *,
    missing_reason: str,
    inspect_reason: str,
) -> str | None:
    try:
        spec = importlib.util.find_spec(module_name)
    except Exception as exc:
        return f"{inspect_reason.rstrip('.')}: {type(exc).__name__}: {exc}"
    if spec is None:
        return missing_reason
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
