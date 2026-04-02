from __future__ import annotations

from dataclasses import dataclass
from typing import Callable


@dataclass(frozen=True)
class ParakeetLiveRuntime:
    torch: object
    ContextSize: type
    StreamingBatchedAudioBuffer: type
    batched_hyps_to_hypotheses: Callable[..., list[object]]


def load_parakeet_live_runtime():
    from mlx_ui.engines.parakeet_nemo import load_parakeet_runtime

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
    except Exception as exc:
        raise RuntimeError(
            "Parakeet live beta requires NVIDIA NeMo streaming utilities and PyTorch."
        ) from exc
    return (
        nemo_asr,
        open_dict,
        ParakeetLiveRuntime(
            torch=torch,
            ContextSize=ContextSize,
            StreamingBatchedAudioBuffer=StreamingBatchedAudioBuffer,
            batched_hyps_to_hypotheses=batched_hyps_to_hypotheses,
        ),
    )
