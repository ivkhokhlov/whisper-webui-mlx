from __future__ import annotations

import inspect
import logging
from pathlib import Path

from mlx_ui.db import JobRecord
from mlx_ui.engine_registry import PARAKEET_TDT_V3_ENGINE
from mlx_ui.engines.common import (
    DEFAULT_PARAKEET_BATCH_SIZE,
    DEFAULT_PARAKEET_CHUNK_DURATION,
    DEFAULT_PARAKEET_DECODING_MODE,
    DEFAULT_PARAKEET_OVERLAP_DURATION,
    normalize_requested_output_formats,
    write_transcript_result,
)
from mlx_ui.engines.parakeet_mlx_runtime import (
    build_parakeet_mlx_decoding_config,
    parakeet_mlx_runtime_unavailability_reason,
    parakeet_mlx_supports_beam_decoding,
)
from mlx_ui.engines.parakeet_mlx_adapter import normalize_parakeet_mlx_result

logger = logging.getLogger(__name__)

DEFAULT_PARAKEET_MLX_MODEL_ID = "mlx-community/parakeet-tdt-0.6b-v3"


def load_parakeet_mlx_runtime():
    reason = parakeet_mlx_runtime_unavailability_reason()
    if reason:
        raise RuntimeError(f"Parakeet MLX backend cannot run: {reason}")
    try:
        from parakeet_mlx import from_pretrained  # type: ignore[import-not-found]
    except Exception as exc:
        raise RuntimeError(
            "Parakeet MLX backend selected but the optional 'parakeet-mlx' dependency is not installed."
        ) from exc
    return from_pretrained


class ParakeetMlxTranscriber:
    engine_id = PARAKEET_TDT_V3_ENGINE

    def __init__(
        self,
        model_id: str | None = None,
        *,
        repo_id: str | None = None,
        chunk_duration: float | None = None,
        overlap_duration: float | None = None,
        decoding_mode: str | None = None,
        batch_size: int | None = None,
        output_formats: tuple[str, ...] | None = None,
    ) -> None:
        resolved_model_id = model_id or repo_id or DEFAULT_PARAKEET_MLX_MODEL_ID
        self.model_id = resolved_model_id
        self.chunk_duration = (
            float(chunk_duration)
            if chunk_duration is not None
            else float(DEFAULT_PARAKEET_CHUNK_DURATION)
        )
        self.overlap_duration = (
            float(overlap_duration)
            if overlap_duration is not None
            else float(DEFAULT_PARAKEET_OVERLAP_DURATION)
        )
        normalized_decoding_mode = (
            decoding_mode.strip().lower()
            if isinstance(decoding_mode, str) and decoding_mode.strip()
            else DEFAULT_PARAKEET_DECODING_MODE
        )
        self.decoding_mode = normalized_decoding_mode
        self.batch_size = max(1, int(batch_size or DEFAULT_PARAKEET_BATCH_SIZE))
        self.output_formats = normalize_requested_output_formats(output_formats)
        self._model = None

    def transcribe(self, job: JobRecord, results_dir: Path) -> Path:
        source_path = Path(job.upload_path)
        model = self._ensure_model()
        logger.info(
            "Running Parakeet MLX for job %s (model=%s)",
            job.id,
            self.model_id,
        )
        try:
            raw = _transcribe_with_model(
                model,
                source_path,
                chunk_duration=self.chunk_duration,
                overlap_duration=self.overlap_duration,
                decoding_mode=self.decoding_mode,
                batch_size=self.batch_size,
            )
        except Exception as exc:  # pragma: no cover - backend passthrough
            raise RuntimeError(f"Parakeet MLX transcription failed: {exc}") from exc
        transcript = normalize_parakeet_mlx_result(
            raw,
            engine_id=self.engine_id,
            model_id=self.model_id,
            fallback_language=job.language,
        )
        return write_transcript_result(
            result=transcript,
            results_dir=results_dir,
            job_id=job.id,
            source_name=job.filename,
            output_formats=self.output_formats,
        )

    def _ensure_model(self):
        if self._model is not None:
            return self._model
        from mlx_ui import transcriber as transcriber_module

        from_pretrained = transcriber_module._load_parakeet_mlx_runtime()
        try:
            self._model = from_pretrained(self.model_id)
        except Exception as exc:  # pragma: no cover - depends on optional dep
            raise RuntimeError(
                f"Failed to load Parakeet MLX model '{self.model_id}': {exc}"
            ) from exc
        return self._model


def _transcribe_with_model(
    model,
    source_path: Path,
    *,
    chunk_duration: float | None,
    overlap_duration: float | None,
    decoding_mode: str | None,
    batch_size: int | None,
):
    transcribe = getattr(model, "transcribe", None)
    if transcribe is None:
        raise RuntimeError("Parakeet MLX model does not expose a transcribe() method.")

    kwargs = _filter_supported_kwargs(
        transcribe,
        {
            **_resolve_chunking_kwargs(transcribe, chunk_duration, overlap_duration),
            **_resolve_decoding_kwargs(transcribe, decoding_mode),
            **_resolve_batch_kwargs(transcribe, batch_size),
        },
    )
    return _call_transcribe(transcribe, str(source_path), kwargs)


def _call_transcribe(transcribe, source_path: str, kwargs: dict[str, object]):
    try:
        return transcribe(source_path, **kwargs)
    except TypeError:
        for name in ("audio_path", "audio", "path", "file", "filename", "input"):
            try:
                return transcribe(**{name: source_path, **kwargs})
            except TypeError:
                continue
        raise


def _filter_supported_kwargs(
    func,
    kwargs: dict[str, object],
) -> dict[str, object]:
    supported = _supported_parameter_names(func)
    if supported is None:
        return {key: value for key, value in kwargs.items() if value is not None}
    return {
        key: value
        for key, value in kwargs.items()
        if value is not None and key in supported
    }


def _supported_parameter_names(func) -> set[str] | None:
    try:
        signature = inspect.signature(func)
    except (TypeError, ValueError):
        return None
    if any(param.kind == param.VAR_KEYWORD for param in signature.parameters.values()):
        return None
    names = {name for name in signature.parameters if name != "self"}
    return names


def _resolve_chunking_kwargs(
    func,
    chunk_duration: float | None,
    overlap_duration: float | None,
) -> dict[str, object]:
    supported = _supported_parameter_names(func)
    if supported is None:
        return {}
    resolved: dict[str, object] = {}
    _set_first_supported(
        resolved,
        supported,
        chunk_duration,
        (
            "chunk_duration",
            "chunk_length_s",
            "chunk_length",
            "chunk_size_s",
            "chunk_size",
        ),
    )
    _set_first_supported(
        resolved,
        supported,
        overlap_duration,
        (
            "overlap_duration",
            "overlap_length_s",
            "overlap_length",
            "stride_length_s",
            "stride_length",
        ),
    )
    return resolved


def _resolve_decoding_kwargs(func, decoding_mode: str | None) -> dict[str, object]:
    normalized = (
        decoding_mode.strip().lower()
        if isinstance(decoding_mode, str) and decoding_mode.strip()
        else DEFAULT_PARAKEET_DECODING_MODE
    )
    supported = _supported_parameter_names(func)
    resolved: dict[str, object] = {}
    if normalized == "beam":
        if not parakeet_mlx_supports_beam_decoding():
            raise RuntimeError(
                "Beam decoding requested but the installed Parakeet MLX runtime does not expose a usable beam API."
            )
        config = build_parakeet_mlx_decoding_config("beam")
        if config is None:
            raise RuntimeError(
                "Beam decoding requested but Parakeet MLX decoding config could not be constructed."
            )
        if supported is None:
            return {"decoding_config": config}
        _set_first_supported(
            resolved,
            supported,
            config,
            (
                "decoding_config",
                "decoding_cfg",
                "decoding",
                "decode_config",
                "decode_cfg",
                "decoder",
            ),
        )
        if not resolved:
            raise RuntimeError(
                "Beam decoding requested but Parakeet MLX model does not accept a decoding config parameter."
            )
        return resolved

    if supported is None:
        return {}
    _set_first_supported(
        resolved,
        supported,
        normalized,
        ("decoding_mode", "decoding", "decode", "mode"),
    )
    return resolved


def _resolve_batch_kwargs(func, batch_size: int | None) -> dict[str, object]:
    supported = _supported_parameter_names(func)
    if supported is None:
        return {}
    resolved: dict[str, object] = {}
    _set_first_supported(
        resolved,
        supported,
        batch_size,
        ("batch_size",),
    )
    return resolved


def _set_first_supported(
    output: dict[str, object],
    supported: set[str],
    value: object,
    names: tuple[str, ...],
) -> None:
    if value is None:
        return
    for name in names:
        if name in supported:
            output[name] = value
            return
