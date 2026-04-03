from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import platform
import shutil
from collections.abc import Callable
from dataclasses import dataclass
import sys
from typing import TYPE_CHECKING, Literal, Mapping

from mlx_ui.engines.parakeet_mlx_runtime import (
    is_parakeet_mlx_runtime_usable,
    parakeet_mlx_runtime_unavailability_reason,
)

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
PARAKEET_MLX_BACKEND = "parakeet_mlx"
PARAKEET_NEMO_CUDA_BACKEND = "parakeet_nemo_cuda"
PARAKEET_TDT_V3_NEMO_CUDA_BACKEND = "parakeet_tdt_v3_nemo_cuda"
PARAKEET_NEMO_CUDA_EXPERIMENTAL_ENV = "PARAKEET_NEMO_CUDA_EXPERIMENTAL"

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
class EngineImplementation:
    id: str
    availability_probe: Callable[[], bool]
    factory: Callable[[EngineFactoryOptions], Transcriber] | None
    compatibility_note: str | None = None
    availability_reason: Callable[[], str | None] | None = None
    disabled_label: str | None = None
    backend_aliases: tuple[str, ...] = ()

    def is_available(self) -> bool:
        if not self.is_implemented():
            return False
        if self.availability_reason is not None:
            detail = self.availability_reason()
            if detail:
                return False
        return self.availability_probe()

    def is_implemented(self) -> bool:
        return self.factory is not None

    def unavailable_reason(self) -> str | None:
        if self.availability_reason is not None:
            detail = self.availability_reason()
            if detail:
                return detail
        return self.compatibility_note


@dataclass(frozen=True)
class EngineProvider:
    id: str
    label: str
    mode: Literal["local", "cloud"]
    implementations: tuple[EngineImplementation, ...]
    fallback_engine_id: str | None = None
    selectable: bool = True
    visible_in_settings: bool = True

    def is_available(self) -> bool:
        return any(
            implementation.is_implemented() and implementation.is_available()
            for implementation in self.implementations
        )

    def is_implemented(self) -> bool:
        return any(
            implementation.is_implemented() for implementation in self.implementations
        )

    def unavailable_reason(self) -> str | None:
        if self.is_available():
            return None
        implementation = self.display_implementation()
        if implementation is None:
            return None
        return implementation.unavailable_reason()

    def display_implementation(self) -> EngineImplementation | None:
        if not self.implementations:
            return None
        if self.id == PARAKEET_TDT_V3_ENGINE:
            mlx_implementation = next(
                (
                    implementation
                    for implementation in self.implementations
                    if implementation.id == PARAKEET_MLX_BACKEND
                ),
                None,
            )
            nemo_implementation = next(
                (
                    implementation
                    for implementation in self.implementations
                    if implementation.id == PARAKEET_NEMO_CUDA_BACKEND
                ),
                None,
            )
            if _is_apple_silicon():
                return (
                    mlx_implementation
                    or nemo_implementation
                    or next(
                        (implementation for implementation in self.implementations),
                        None,
                    )
                )
            if is_parakeet_nemo_cuda_experimental_enabled():
                return (
                    nemo_implementation
                    or mlx_implementation
                    or next(
                        (implementation for implementation in self.implementations),
                        None,
                    )
                )
            return (
                mlx_implementation
                or nemo_implementation
                or next(
                    (implementation for implementation in self.implementations), None
                )
            )
        for implementation in self.implementations:
            if implementation.is_implemented():
                return implementation
        return self.implementations[0]

    def resolve_implementation(
        self,
        implementation_id: str | None = None,
        *,
        require_available: bool = False,
    ) -> EngineImplementation:
        if implementation_id is not None:
            normalized = implementation_id.strip().lower()
            for implementation in self.implementations:
                aliases = (implementation.id,) + implementation.backend_aliases
                if any(
                    alias.strip().lower() == normalized for alias in aliases if alias
                ):
                    if (
                        self.id == PARAKEET_TDT_V3_ENGINE
                        and implementation.id == PARAKEET_NEMO_CUDA_BACKEND
                        and not is_parakeet_nemo_cuda_experimental_enabled()
                    ):
                        raise ValueError(
                            "Parakeet NeMo/CUDA backend is experimental and disabled by default. "
                            f"Set {PARAKEET_NEMO_CUDA_EXPERIMENTAL_ENV}=1 to enable it."
                        )
                    if require_available and not implementation.is_available():
                        raise ValueError(
                            f"Backend '{implementation_id}' is not available for engine '{self.id}'."
                        )
                    if implementation.factory is None:
                        raise ValueError(
                            f"Backend '{implementation_id}' is not implemented for engine '{self.id}'."
                        )
                    return implementation
            raise ValueError(
                f"Unknown backend '{implementation_id}' for engine '{self.id}'."
            )
        if require_available:
            for implementation in self.implementations:
                if implementation.factory is not None and implementation.is_available():
                    return implementation
            raise ValueError(f"Engine '{self.id}' has no available backends.")
        for implementation in self.implementations:
            if implementation.factory is not None and implementation.is_available():
                return implementation
        for implementation in self.implementations:
            if implementation.factory is not None:
                return implementation
        raise ValueError(f"Engine '{self.id}' is not implemented.")

    @property
    def disabled_label(self) -> str | None:
        implementation = self.display_implementation()
        if implementation is None:
            return None
        return implementation.disabled_label


@dataclass(frozen=True)
class ResolvedEngine:
    provider: EngineProvider
    implementation: EngineImplementation
    note: str | None = None


def is_whisper_available() -> bool:
    return importlib.util.find_spec("whisper") is not None


def is_wtm_available() -> bool:
    wtm_path = os.getenv("WTM_PATH", "").strip()
    if wtm_path:
        candidate = Path(wtm_path)
        if candidate.is_file():
            return os.access(candidate, os.X_OK)
        return shutil.which(wtm_path) is not None

    venv_candidate = Path(sys.executable).resolve().parent / "wtm"
    if venv_candidate.is_file():
        return os.access(venv_candidate, os.X_OK)

    return shutil.which("wtm") is not None


def cohere_availability_reason() -> str | None:
    if importlib.util.find_spec("cohere") is None:
        return "the optional 'cohere' Python SDK is not installed."
    return None


def is_cohere_available() -> bool:
    return cohere_availability_reason() is None


def parakeet_availability_reason() -> str | None:
    return parakeet_nemo_cuda_availability_reason()


def parakeet_mlx_availability_reason() -> str | None:
    if is_parakeet_mlx_runtime_usable():
        return None
    return parakeet_mlx_runtime_unavailability_reason()


def parakeet_nemo_cuda_availability_reason() -> str | None:
    if not is_parakeet_nemo_cuda_experimental_enabled():
        return (
            "Parakeet NeMo/CUDA backend is experimental and disabled by default. "
            f"Set {PARAKEET_NEMO_CUDA_EXPERIMENTAL_ENV}=1 to enable it."
        )
    if not sys.platform.startswith("linux"):
        return "Parakeet NeMo CUDA backend requires Linux with an NVIDIA CUDA GPU."
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


def is_parakeet_nemo_cuda_experimental_enabled(
    env: Mapping[str, str] | None = None,
) -> bool:
    if env is None:
        env = os.environ
    raw = str(env.get(PARAKEET_NEMO_CUDA_EXPERIMENTAL_ENV, "")).strip().lower()
    return raw in {"1", "true", "yes", "on"}


def _is_apple_silicon() -> bool:
    return sys.platform == "darwin" and platform.machine().lower() in {
        "arm64",
        "aarch64",
    }


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


def _create_parakeet_mlx_transcriber(options: EngineFactoryOptions) -> Transcriber:
    from mlx_ui.transcriber import ParakeetMlxTranscriber

    return ParakeetMlxTranscriber(
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
        implementations=(
            EngineImplementation(
                id=WTM_BACKEND,
                availability_probe=lambda: is_wtm_available(),
                factory=_create_wtm_transcriber,
                compatibility_note="the 'wtm' CLI is not installed.",
                disabled_label="Not installed",
                backend_aliases=(WTM_BACKEND, "mlx", "wtm-cli"),
            ),
        ),
        fallback_engine_id=WHISPER_CPU_ENGINE,
    ),
    EngineProvider(
        id=WHISPER_CPU_ENGINE,
        label="Whisper (CPU)",
        mode="local",
        implementations=(
            EngineImplementation(
                id=WHISPER_BACKEND,
                availability_probe=lambda: is_whisper_available(),
                factory=_create_whisper_transcriber,
                compatibility_note=(
                    "the optional 'openai-whisper' dependency is not installed."
                ),
                disabled_label="Requires install",
                backend_aliases=(WHISPER_BACKEND, "openai-whisper", "openai"),
            ),
        ),
        fallback_engine_id=WHISPER_MLX_ENGINE,
    ),
    EngineProvider(
        id=FAKE_ENGINE,
        label="Fake",
        mode="local",
        implementations=(
            EngineImplementation(
                id=FAKE_BACKEND,
                availability_probe=lambda: True,
                factory=_create_fake_transcriber,
                compatibility_note="test backend",
                backend_aliases=(FAKE_BACKEND, "noop", "test"),
            ),
        ),
        selectable=False,
        visible_in_settings=False,
    ),
    EngineProvider(
        id=COHERE_ENGINE,
        label="Cohere",
        mode="cloud",
        implementations=(
            EngineImplementation(
                id=COHERE_ENGINE,
                availability_probe=lambda: is_cohere_available(),
                factory=_create_cohere_transcriber,
                compatibility_note="the optional 'cohere' Python SDK is not installed.",
                availability_reason=lambda: cohere_availability_reason(),
                disabled_label="Requires install",
                backend_aliases=(COHERE_ENGINE,),
            ),
        ),
        selectable=True,
    ),
    EngineProvider(
        id=PARAKEET_TDT_V3_ENGINE,
        label="Parakeet TDT v3",
        mode="local",
        implementations=(
            EngineImplementation(
                id=PARAKEET_MLX_BACKEND,
                availability_probe=lambda: is_parakeet_mlx_runtime_usable(),
                factory=_create_parakeet_mlx_transcriber,
                compatibility_note="Parakeet MLX backend requires Apple Silicon and the optional 'parakeet-mlx' dependency.",
                availability_reason=lambda: parakeet_mlx_availability_reason(),
                disabled_label="Requires install",
                backend_aliases=(PARAKEET_MLX_BACKEND,),
            ),
            EngineImplementation(
                id=PARAKEET_NEMO_CUDA_BACKEND,
                availability_probe=lambda: is_parakeet_available(),
                factory=_create_parakeet_transcriber,
                compatibility_note=(
                    "Experimental: Parakeet NeMo/CUDA backend requires Linux with CUDA, PyTorch, and NVIDIA NeMo ASR."
                ),
                availability_reason=lambda: parakeet_availability_reason(),
                disabled_label="Experimental CUDA",
                backend_aliases=(PARAKEET_TDT_V3_NEMO_CUDA_BACKEND,),
            ),
        ),
        selectable=True,
    ),
)

_PROVIDER_ALIASES = {
    "parakeet": PARAKEET_TDT_V3_ENGINE,
}

_PROVIDERS_BY_ID = {provider.id: provider for provider in _ENGINE_PROVIDERS}
_IMPLEMENTATIONS_BY_BACKEND: dict[str, tuple[EngineProvider, EngineImplementation]] = {}
for provider in _ENGINE_PROVIDERS:
    for implementation in provider.implementations:
        for alias in (implementation.id,) + implementation.backend_aliases:
            normalized = (alias or "").strip().lower()
            if normalized:
                _IMPLEMENTATIONS_BY_BACKEND[normalized] = (provider, implementation)


def list_engine_providers(*, visible_only: bool = False) -> tuple[EngineProvider, ...]:
    if not visible_only:
        return _ENGINE_PROVIDERS
    return tuple(
        provider for provider in _ENGINE_PROVIDERS if provider.visible_in_settings
    )


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
    resolved = resolve_backend_implementation(
        backend,
        include_hidden=include_hidden,
    )
    if resolved is None:
        return None
    provider, _implementation = resolved
    return provider


def resolve_backend_implementation(
    backend: str | None,
    *,
    include_hidden: bool = True,
) -> tuple[EngineProvider, EngineImplementation] | None:
    normalized = (backend or "").strip().lower()
    if not normalized:
        return None
    resolved = _IMPLEMENTATIONS_BY_BACKEND.get(normalized)
    provider: EngineProvider | None = None
    implementation: EngineImplementation | None = None
    if resolved is not None:
        provider, implementation = resolved
    else:
        provider_id = _PROVIDER_ALIASES.get(normalized, normalized)
        provider = get_engine_provider(provider_id)
        if provider is None:
            return None
        implementation = provider.display_implementation()
        if implementation is None:
            return None
    if not include_hidden and not provider.selectable:
        return None
    return provider, implementation


def get_selectable_engine_ids() -> tuple[str, ...]:
    return tuple(provider.id for provider in _ENGINE_PROVIDERS if provider.selectable)


def build_engine_options() -> list[dict[str, object]]:
    options: list[dict[str, object]] = []
    for provider in list_engine_providers(visible_only=True):
        instantiable = provider.is_implemented()
        runtime_present = provider.is_available()
        available = instantiable and runtime_present
        reason = provider.unavailable_reason()
        options.append(
            {
                "id": provider.id,
                "label": provider.label,
                "mode": provider.mode,
                "local": provider.mode == "local",
                "cloud": provider.mode == "cloud",
                "available": available,
                "runtime_present": runtime_present,
                "instantiable": instantiable,
                "selectable": provider.selectable,
                "implemented": instantiable,
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
) -> ResolvedEngine:
    provider = require_engine_provider(engine_id)
    for implementation in provider.implementations:
        if implementation.is_implemented() and implementation.is_available():
            return ResolvedEngine(provider=provider, implementation=implementation)
    if allow_fallback and provider.fallback_engine_id:
        fallback = get_engine_provider(provider.fallback_engine_id)
        if fallback is not None:
            for implementation in fallback.implementations:
                if implementation.is_implemented() and implementation.is_available():
                    return ResolvedEngine(
                        provider=fallback,
                        implementation=implementation,
                        note=f"{provider.label} isn't available; using {fallback.label}.",
                    )
    reason = provider.unavailable_reason()
    implementation = provider.display_implementation()
    if implementation is None:
        raise ValueError(f"Engine '{provider.id}' has no runtime implementations.")
    if reason:
        return ResolvedEngine(
            provider=provider,
            implementation=implementation,
            note=f"{provider.label} is selected but {reason}",
        )
    return ResolvedEngine(provider=provider, implementation=implementation)


def create_transcriber(
    engine_id: str,
    *,
    implementation_id: str | None = None,
    options: EngineFactoryOptions | None = None,
) -> Transcriber:
    provider = require_engine_provider(engine_id)
    implementation = provider.resolve_implementation(implementation_id)
    if implementation.factory is None:
        raise ValueError(
            f"Engine '{provider.id}' backend '{implementation.id}' is not implemented."
        )
    return implementation.factory(options or EngineFactoryOptions())


def supported_backend_names() -> tuple[str, ...]:
    names: list[str] = []
    for provider in _ENGINE_PROVIDERS:
        names.append(provider.id)
        for implementation in provider.implementations:
            if implementation.factory is None:
                continue
            if (
                provider.id == PARAKEET_TDT_V3_ENGINE
                and implementation.id == PARAKEET_NEMO_CUDA_BACKEND
                and not is_parakeet_nemo_cuda_experimental_enabled()
            ):
                continue
            names.append(implementation.id)
            if provider.id in implementation.backend_aliases:
                names.append(provider.id)
    seen: set[str] = set()
    ordered: list[str] = []
    for name in names:
        if name and name not in seen:
            seen.add(name)
            ordered.append(name)
    return tuple(ordered)
