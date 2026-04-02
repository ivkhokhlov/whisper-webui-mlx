from __future__ import annotations

import importlib.util
from collections.abc import Callable
from dataclasses import dataclass
import sys
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from mlx_ui.transcriber import Transcriber

WHISPER_MLX_ENGINE = "whisper_mlx"
WHISPER_CPU_ENGINE = "whisper_cpu"
FAKE_ENGINE = "fake"
COHERE_ENGINE = "cohere"
PARAKEET_TDT_V3_ENGINE = "parakeet_tdt_v3"

WTM_BACKEND = "wtm"
WHISPER_BACKEND = "whisper"
FAKE_BACKEND = "fake"

DEFAULT_ENGINE_ID = WHISPER_MLX_ENGINE
DEFAULT_BACKEND = WTM_BACKEND


@dataclass(frozen=True)
class EngineFactoryOptions:
    quick: bool | None = None
    api_key: str | None = None
    model_name: str | None = None
    device: str | None = None
    repo_id: str | None = None
    chunk_duration: float | None = None
    overlap_duration: float | None = None
    decoding_mode: str | None = None
    batch_size: int | None = None
    output_formats: tuple[str, ...] | None = None


@dataclass(frozen=True)
class EngineProvider:
    id: str
    label: str
    mode: Literal["local", "cloud"]
    availability_probe: Callable[[], bool]
    factory: Callable[[EngineFactoryOptions], Transcriber] | None
    compatibility_note: str | None = None
    availability_reason: Callable[[], str | None] | None = None
    disabled_label: str | None = None
    backend: str | None = None
    backend_aliases: tuple[str, ...] = ()
    fallback_engine_id: str | None = None
    selectable: bool = True
    visible_in_settings: bool = True

    def is_available(self) -> bool:
        return self.availability_probe()

    def is_implemented(self) -> bool:
        return self.factory is not None

    def unavailable_reason(self) -> str | None:
        if self.availability_reason is not None:
            detail = self.availability_reason()
            if detail:
                return detail
        return self.compatibility_note


def is_whisper_available() -> bool:
    return importlib.util.find_spec("whisper") is not None


def is_wtm_available() -> bool:
    return importlib.util.find_spec("whisper_turbo") is not None


def cohere_availability_reason() -> str | None:
    if importlib.util.find_spec("cohere") is None:
        return "the optional 'cohere' Python SDK is not installed."
    return None


def is_cohere_available() -> bool:
    return cohere_availability_reason() is None


def parakeet_availability_reason() -> str | None:
    if not sys.platform.startswith("linux"):
        return "Parakeet currently requires Linux with an NVIDIA CUDA GPU."
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
    return None


def is_parakeet_available() -> bool:
    return parakeet_availability_reason() is None


def _create_wtm_transcriber(options: EngineFactoryOptions) -> Transcriber:
    from mlx_ui.transcriber import WtmTranscriber

    return WtmTranscriber(
        quick=options.quick,
        output_formats=options.output_formats,
    )


def _create_whisper_transcriber(options: EngineFactoryOptions) -> Transcriber:
    from mlx_ui.transcriber import WhisperTranscriber

    return WhisperTranscriber(
        model_name=options.model_name,
        device=options.device,
        output_formats=options.output_formats,
    )


def _create_fake_transcriber(options: EngineFactoryOptions) -> Transcriber:
    from mlx_ui.transcriber import FakeTranscriber

    return FakeTranscriber(output_formats=options.output_formats)


def _create_cohere_transcriber(options: EngineFactoryOptions) -> Transcriber:
    from mlx_ui.transcriber import CohereTranscriber

    return CohereTranscriber(
        api_key=options.api_key,
        model_name=options.model_name,
        output_formats=options.output_formats,
    )


def _create_parakeet_transcriber(options: EngineFactoryOptions) -> Transcriber:
    from mlx_ui.transcriber import ParakeetTranscriber

    return ParakeetTranscriber(
        repo_id=options.repo_id,
        chunk_duration=options.chunk_duration,
        overlap_duration=options.overlap_duration,
        decoding_mode=options.decoding_mode,
        batch_size=options.batch_size,
        output_formats=options.output_formats,
    )


_ENGINE_PROVIDERS: tuple[EngineProvider, ...] = (
    EngineProvider(
        id=WHISPER_MLX_ENGINE,
        label="Whisper (MLX / Metal)",
        mode="local",
        availability_probe=lambda: is_wtm_available(),
        factory=_create_wtm_transcriber,
        compatibility_note="WTM is not installed.",
        disabled_label="Not installed",
        backend=WTM_BACKEND,
        backend_aliases=(WTM_BACKEND, "mlx", "wtm-cli"),
        fallback_engine_id=WHISPER_CPU_ENGINE,
    ),
    EngineProvider(
        id=WHISPER_CPU_ENGINE,
        label="Whisper (CPU)",
        mode="local",
        availability_probe=lambda: is_whisper_available(),
        factory=_create_whisper_transcriber,
        compatibility_note=(
            "the optional 'openai-whisper' dependency is not installed."
        ),
        disabled_label="Requires install",
        backend=WHISPER_BACKEND,
        backend_aliases=(WHISPER_BACKEND, "openai-whisper", "openai"),
        fallback_engine_id=WHISPER_MLX_ENGINE,
    ),
    EngineProvider(
        id=FAKE_ENGINE,
        label="Fake",
        mode="local",
        availability_probe=lambda: True,
        factory=_create_fake_transcriber,
        compatibility_note="test backend",
        backend=FAKE_BACKEND,
        backend_aliases=(FAKE_BACKEND, "noop", "test"),
        selectable=False,
        visible_in_settings=False,
    ),
    EngineProvider(
        id=COHERE_ENGINE,
        label="Cohere",
        mode="cloud",
        availability_probe=lambda: is_cohere_available(),
        factory=_create_cohere_transcriber,
        compatibility_note="the optional 'cohere' Python SDK is not installed.",
        availability_reason=lambda: cohere_availability_reason(),
        disabled_label="Requires install",
        backend=COHERE_ENGINE,
        selectable=True,
    ),
    EngineProvider(
        id=PARAKEET_TDT_V3_ENGINE,
        label="Parakeet TDT v3",
        mode="local",
        availability_probe=lambda: is_parakeet_available(),
        factory=_create_parakeet_transcriber,
        compatibility_note="Parakeet requires Linux with CUDA, PyTorch, and NVIDIA NeMo ASR.",
        availability_reason=lambda: parakeet_availability_reason(),
        disabled_label="Requires CUDA",
        backend=PARAKEET_TDT_V3_ENGINE,
        backend_aliases=(PARAKEET_TDT_V3_ENGINE, "parakeet"),
        selectable=True,
    ),
)

_PROVIDERS_BY_ID = {provider.id: provider for provider in _ENGINE_PROVIDERS}
_PROVIDERS_BY_BACKEND = {
    alias: provider
    for provider in _ENGINE_PROVIDERS
    for alias in ((provider.backend,) if provider.backend else ()) + provider.backend_aliases
}


def list_engine_providers(*, visible_only: bool = False) -> tuple[EngineProvider, ...]:
    if not visible_only:
        return _ENGINE_PROVIDERS
    return tuple(provider for provider in _ENGINE_PROVIDERS if provider.visible_in_settings)


def get_engine_provider(engine_id: str) -> EngineProvider | None:
    normalized = engine_id.strip() if engine_id else ""
    return _PROVIDERS_BY_ID.get(normalized)


def require_engine_provider(engine_id: str) -> EngineProvider:
    provider = get_engine_provider(engine_id)
    if provider is None:
        raise ValueError(f"Unknown engine '{engine_id}'.")
    return provider


def resolve_backend_provider(
    backend: str | None,
    *,
    include_hidden: bool = True,
) -> EngineProvider | None:
    normalized = (backend or "").strip().lower()
    if not normalized:
        return None
    provider = _PROVIDERS_BY_BACKEND.get(normalized)
    if provider is None:
        return None
    if not include_hidden and not provider.selectable:
        return None
    return provider


def get_selectable_engine_ids() -> tuple[str, ...]:
    return tuple(provider.id for provider in _ENGINE_PROVIDERS if provider.selectable)


def build_engine_options() -> list[dict[str, object]]:
    options: list[dict[str, object]] = []
    for provider in list_engine_providers(visible_only=True):
        available = provider.is_implemented() and provider.is_available()
        reason = provider.unavailable_reason()
        options.append(
            {
                "id": provider.id,
                "label": provider.label,
                "mode": provider.mode,
                "local": provider.mode == "local",
                "cloud": provider.mode == "cloud",
                "available": available,
                "selectable": provider.selectable,
                "implemented": provider.is_implemented(),
                "disabled": (not provider.selectable) or not available,
                "disabled_label": provider.disabled_label,
                "compatibility_note": reason,
                "reason": reason,
                "note": reason,
            }
        )
    return options


def resolve_runtime_engine(
    engine_id: str,
    *,
    allow_fallback: bool,
) -> tuple[EngineProvider, str | None]:
    provider = require_engine_provider(engine_id)
    if provider.is_available():
        return provider, None
    if allow_fallback and provider.fallback_engine_id:
        fallback = get_engine_provider(provider.fallback_engine_id)
        if fallback is not None and fallback.is_available():
            return (
                fallback,
                f"{provider.label} isn't available; using {fallback.label}.",
            )
    reason = provider.unavailable_reason()
    if reason:
        return provider, f"{provider.label} is selected but {reason}"
    return provider, None


def create_transcriber(
    engine_id: str,
    *,
    options: EngineFactoryOptions | None = None,
) -> Transcriber:
    provider = require_engine_provider(engine_id)
    if provider.factory is None:
        raise ValueError(f"Engine '{provider.id}' is not implemented.")
    return provider.factory(options or EngineFactoryOptions())


def supported_backend_names() -> tuple[str, ...]:
    names = [
        provider.backend
        for provider in _ENGINE_PROVIDERS
        if provider.backend and provider.is_implemented()
    ]
    return tuple(names)
