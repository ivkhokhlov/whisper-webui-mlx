from __future__ import annotations

import os

from mlx_ui.engine_registry import (
    DEFAULT_BACKEND,
    create_transcriber,
    resolve_backend_implementation,
    supported_backend_names,
)
from mlx_ui.engines.common import (
    BACKEND_ENV,
    COHERE_API_KEY_ENV,
    COHERE_MODEL_ENV,
    DEFAULT_COHERE_MODEL,
    DEFAULT_PARAKEET_BATCH_SIZE,
    DEFAULT_PARAKEET_CHUNK_DURATION,
    DEFAULT_PARAKEET_DECODING_MODE,
    DEFAULT_PARAKEET_MODEL,
    DEFAULT_PARAKEET_OVERLAP_DURATION,
    DEFAULT_WHISPER_MODEL,
    WHISPER_CACHE_DIR_ENV,
    WHISPER_DEVICE_ENV,
    WHISPER_FP16_ENV,
    WHISPER_MODEL_ENV,
    FakeTranscriber,
    Transcriber,
)
from mlx_ui.engines.cohere import CohereTranscriber
from mlx_ui.engines.parakeet_nemo import ParakeetTranscriber
from mlx_ui.engines.whisper_cpu import WhisperTranscriber
from mlx_ui.engines.whisper_mlx import WtmTranscriber

_REEXPORTED = (
    BACKEND_ENV,
    COHERE_API_KEY_ENV,
    COHERE_MODEL_ENV,
    DEFAULT_COHERE_MODEL,
    DEFAULT_PARAKEET_BATCH_SIZE,
    DEFAULT_PARAKEET_CHUNK_DURATION,
    DEFAULT_PARAKEET_DECODING_MODE,
    DEFAULT_PARAKEET_MODEL,
    DEFAULT_PARAKEET_OVERLAP_DURATION,
    DEFAULT_WHISPER_MODEL,
    WHISPER_CACHE_DIR_ENV,
    WHISPER_DEVICE_ENV,
    WHISPER_FP16_ENV,
    WHISPER_MODEL_ENV,
    FakeTranscriber,
    Transcriber,
    CohereTranscriber,
    ParakeetTranscriber,
    WhisperTranscriber,
    WtmTranscriber,
)


def _load_cohere_runtime():
    from mlx_ui.engines.cohere import load_cohere_runtime

    return load_cohere_runtime()


def _load_parakeet_runtime():
    from mlx_ui.engines.parakeet_nemo import load_parakeet_runtime

    return load_parakeet_runtime()


def resolve_transcriber() -> Transcriber:
    backend = os.getenv(BACKEND_ENV, DEFAULT_BACKEND).strip().lower()
    resolved = resolve_backend_implementation(backend)
    if resolved is not None:
        provider, implementation = resolved
        return create_transcriber(provider.id, implementation_id=implementation.id)
    supported = "', '".join(supported_backend_names())
    raise ValueError(f"Unknown transcriber backend '{backend}'. Use '{supported}'.")
