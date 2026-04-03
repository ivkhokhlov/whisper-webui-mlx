from __future__ import annotations

from array import array
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from pathlib import Path
import shutil
import subprocess
import tempfile
import threading
from typing import TYPE_CHECKING, Callable, Protocol
from uuid import uuid4

from mlx_ui.engine_registry import (
    PARAKEET_MLX_BACKEND,
    PARAKEET_NEMO_CUDA_BACKEND,
    PARAKEET_TDT_V3_ENGINE,
)
from mlx_ui.engines.parakeet_mlx_live_runtime import (
    ParakeetMlxLiveRuntime,
    load_parakeet_mlx_live_runtime,
)
from mlx_ui.live_backend_runtime import resolve_parakeet_live_backend

if TYPE_CHECKING:
    from mlx_ui.engines.parakeet_nemo_cuda_live_runtime_experimental import (
        ParakeetNemoCudaLiveRuntime,
    )


@dataclass(frozen=True)
class ParakeetLiveConfig:
    repo_id: str
    decoding_mode: str = "greedy"
    left_context_secs: float = 10.0
    chunk_secs: float = 2.0
    right_context_secs: float = 2.0
    timeslice_ms: int = 1000

    def cache_key(self) -> tuple[object, ...]:
        return (
            self.repo_id,
            self.decoding_mode,
            self.left_context_secs,
            self.chunk_secs,
            self.right_context_secs,
            self.timeslice_ms,
        )


@dataclass
class LiveTranscriptionUpdate:
    session_id: str
    status: str
    transcript: str
    received_chunks: int
    processed_windows: int
    engine_id: str
    engine_label: str
    model_id: str
    experimental: bool = True
    note: str | None = None
    error: str | None = None

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


class LiveSessionNotFound(KeyError):
    pass


class LiveTranscriptionError(RuntimeError):
    pass


class LiveSession(Protocol):
    def snapshot(self) -> LiveTranscriptionUpdate:
        raise NotImplementedError

    def push_chunk(
        self, chunk_bytes: bytes, *, content_type: str | None
    ) -> LiveTranscriptionUpdate:
        raise NotImplementedError

    def finish(self) -> LiveTranscriptionUpdate:
        raise NotImplementedError

    def mark_error(self, message: str) -> None:
        raise NotImplementedError


class LiveBackend(Protocol):
    def create_session(self, session_id: str) -> LiveSession:
        raise NotImplementedError


def _default_backend_factory(config: ParakeetLiveConfig) -> LiveBackend:
    resolved = resolve_parakeet_live_backend()
    if resolved.implementation_id == PARAKEET_MLX_BACKEND:
        if resolved.reason:
            raise RuntimeError(resolved.reason)
        return ParakeetMlxLiveBackend(config)
    if resolved.implementation_id == PARAKEET_NEMO_CUDA_BACKEND:
        if resolved.reason:
            raise RuntimeError(resolved.reason)
        return ParakeetNemoCudaLiveBackend(config)
    raise RuntimeError(
        resolved.reason
        or "Parakeet live beta is not available in the current environment."
    )


class LiveTranscriptionService:
    def __init__(
        self,
        backend_factory: Callable[[ParakeetLiveConfig], LiveBackend] | None = None,
    ) -> None:
        self._backend_factory = backend_factory or _default_backend_factory
        self._backends: dict[tuple[object, ...], LiveBackend] = {}
        self._sessions: dict[str, LiveSession] = {}
        self._lock = threading.Lock()

    def open_session(self, config: ParakeetLiveConfig) -> LiveTranscriptionUpdate:
        backend = self._get_backend(config)
        session_id = uuid4().hex
        session = backend.create_session(session_id)
        with self._lock:
            self._sessions[session_id] = session
        return session.snapshot()

    def append_chunk(
        self,
        session_id: str,
        chunk_bytes: bytes,
        *,
        content_type: str | None,
    ) -> LiveTranscriptionUpdate:
        session = self._require_session(session_id)
        try:
            return session.push_chunk(chunk_bytes, content_type=content_type)
        except Exception as exc:
            session.mark_error(str(exc))
            raise

    def stop_session(self, session_id: str) -> LiveTranscriptionUpdate:
        with self._lock:
            session = self._sessions.pop(session_id, None)
        if session is None:
            raise LiveSessionNotFound(session_id)
        try:
            return session.finish()
        except Exception as exc:
            session.mark_error(str(exc))
            raise

    def _get_backend(self, config: ParakeetLiveConfig) -> LiveBackend:
        cache_key = config.cache_key()
        with self._lock:
            backend = self._backends.get(cache_key)
            if backend is None:
                backend = self._backend_factory(config)
                self._backends[cache_key] = backend
            return backend

    def _require_session(self, session_id: str) -> LiveSession:
        with self._lock:
            session = self._sessions.get(session_id)
        if session is None:
            raise LiveSessionNotFound(session_id)
        return session


class ParakeetMlxLiveBackend:
    engine_id = PARAKEET_TDT_V3_ENGINE
    engine_label = "Parakeet TDT v3"

    def __init__(
        self,
        config: ParakeetLiveConfig,
        *,
        runtime_loader: Callable[[], ParakeetMlxLiveRuntime] | None = None,
    ) -> None:
        self.config = config
        self._runtime_loader = runtime_loader or load_parakeet_mlx_live_runtime
        self._infer_lock = threading.Lock()
        self._runtime = self._runtime_loader()
        self._model = self._load_model()
        self.model_id = config.repo_id
        self.sample_rate = 16_000
        self.note = (
            "Experimental Parakeet MLX live streaming with approximately "
            f"{config.chunk_secs + config.right_context_secs:.1f}s theoretical latency."
        )

    def create_session(self, session_id: str) -> "ParakeetMlxLiveSession":
        return ParakeetMlxLiveSession(session_id=session_id, backend=self)

    def create_streamer(self):
        cls = self._runtime.StreamingParakeet
        model = self._model
        for args, kwargs in (
            ((model,), {}),
            ((), {"model": model}),
        ):
            try:
                return cls(*args, **kwargs)
            except TypeError:
                continue
        raise RuntimeError(
            "The installed Parakeet MLX runtime could not construct a streaming helper."
        )

    def decode_chunk(
        self,
        chunk_bytes: bytes,
        *,
        content_type: str | None,
    ) -> list[float]:
        return _decode_browser_audio_chunk(
            chunk_bytes,
            content_type=content_type,
            sample_rate=self.sample_rate,
        )

    def stream_text(self, streamer) -> str:
        result = getattr(streamer, "result", None)
        if callable(result):
            result = result()
        text = getattr(result, "text", None)
        if isinstance(text, str):
            return text.strip()
        if isinstance(result, str):
            return result.strip()
        return ""

    def add_audio(self, streamer, samples: list[float]) -> str:
        mx = self._runtime.mx
        dtype = getattr(mx, "float32", None)
        audio = (
            mx.array(samples, dtype=dtype) if dtype is not None else mx.array(samples)
        )
        with self._infer_lock:
            streamer.add_audio(audio)
            return self.stream_text(streamer)

    def _load_model(self):
        from_pretrained = self._runtime.from_pretrained
        try:
            return from_pretrained(self.config.repo_id)
        except Exception as exc:  # pragma: no cover - optional dep passthrough
            raise RuntimeError(
                f"Failed to load Parakeet MLX model '{self.config.repo_id}': {exc}"
            ) from exc


class ParakeetMlxLiveSession:
    def __init__(self, *, session_id: str, backend: ParakeetMlxLiveBackend) -> None:
        self.session_id = session_id
        self.backend = backend
        self.status = "ready"
        self.transcript = ""
        self.received_chunks = 0
        self.processed_windows = 0
        self.error: str | None = None
        self._streamer = backend.create_streamer()
        self._lock = threading.Lock()

    def snapshot(self) -> LiveTranscriptionUpdate:
        return LiveTranscriptionUpdate(
            session_id=self.session_id,
            status=self.status,
            transcript=self.transcript,
            received_chunks=self.received_chunks,
            processed_windows=self.processed_windows,
            engine_id=self.backend.engine_id,
            engine_label=self.backend.engine_label,
            model_id=self.backend.model_id,
            note=self.backend.note,
            error=self.error,
        )

    def push_chunk(
        self,
        chunk_bytes: bytes,
        *,
        content_type: str | None,
    ) -> LiveTranscriptionUpdate:
        samples = self.backend.decode_chunk(chunk_bytes, content_type=content_type)
        with self._lock:
            self.status = "running"
            self.received_chunks += 1
            if samples:
                self.transcript = self.backend.add_audio(self._streamer, samples)
                self.processed_windows += 1
            return self.snapshot()

    def finish(self) -> LiveTranscriptionUpdate:
        with self._lock:
            if self.status != "error":
                finalize = getattr(self._streamer, "finalize", None)
                if callable(finalize):
                    try:
                        finalize()
                    except Exception:
                        pass
                self.status = "stopped"
            return self.snapshot()

    def mark_error(self, message: str) -> None:
        with self._lock:
            self.status = "error"
            self.error = message


class ParakeetNemoCudaLiveBackend:
    engine_id = PARAKEET_TDT_V3_ENGINE
    engine_label = "Parakeet TDT v3"

    def __init__(
        self,
        config: ParakeetLiveConfig,
        *,
        runtime_loader: Callable[
            [], tuple[object, object, "ParakeetNemoCudaLiveRuntime"]
        ]
        | None = None,
    ) -> None:
        self.config = config
        if runtime_loader is None:
            from mlx_ui.engines.parakeet_nemo_cuda_live_runtime_experimental import (
                load_parakeet_nemo_cuda_live_runtime,
            )

            runtime_loader = load_parakeet_nemo_cuda_live_runtime
        self._runtime_loader = runtime_loader
        self._infer_lock = threading.Lock()
        self._model, self._runtime = self._load_model()
        self.model_id = config.repo_id
        self.device = _coalesce_device(self._model, self._runtime)
        self.sample_rate = _parakeet_sample_rate(self._model)
        self.encoder_frame2audio_samples = _parakeet_encoder_frame_span(
            self._model,
            sample_rate=self.sample_rate,
        )
        self.context_samples = _parakeet_context_samples(
            runtime=self._runtime,
            model=self._model,
            config=config,
            sample_rate=self.sample_rate,
            encoder_frame2audio_samples=self.encoder_frame2audio_samples,
        )
        self.initial_window_samples = (
            self.context_samples.chunk + self.context_samples.right
        )
        self.increment_samples = self.context_samples.chunk
        self.max_final_window_samples = (
            self.context_samples.chunk + self.context_samples.right
        )
        self.note = (
            "Internal experimental Parakeet NeMo/CUDA live streaming with approximately "
            f"{config.chunk_secs + config.right_context_secs:.1f}s theoretical latency."
        )
        decoding = getattr(getattr(self._model, "decoding", None), "decoding", None)
        self._decoding_computer = getattr(decoding, "decoding_computer", None)
        if self._decoding_computer is None:
            raise LiveTranscriptionError(
                "Parakeet live beta could not access the streaming decoding computer."
            )

    def create_session(self, session_id: str) -> "ParakeetNemoCudaLiveSession":
        return ParakeetNemoCudaLiveSession(session_id=session_id, backend=self)

    def create_buffer(self):
        return self._runtime.StreamingBatchedAudioBuffer(
            batch_size=1,
            context_samples=self.context_samples,
            dtype=self._runtime.torch.float32,
            device=self.device,
        )

    def decode_chunk(
        self,
        chunk_bytes: bytes,
        *,
        content_type: str | None,
    ) -> list[float]:
        return _decode_browser_audio_chunk(
            chunk_bytes,
            content_type=content_type,
            sample_rate=self.sample_rate,
        )

    def transcribe_window(
        self,
        buffer,
        *,
        samples: list[float],
        is_final: bool,
        state: object,
        current_hyps: object,
    ) -> tuple[object, object, str]:
        torch = self._runtime.torch
        audio_batch = torch.tensor([samples], dtype=torch.float32, device=self.device)
        audio_lengths = torch.tensor(
            [len(samples)], dtype=torch.long, device=self.device
        )
        is_last_chunk_batch = torch.tensor(
            [is_final], dtype=torch.bool, device=self.device
        )
        buffer.add_audio_batch_(
            audio_batch,
            audio_lengths=audio_lengths,
            is_last_chunk=is_final,
            is_last_chunk_batch=is_last_chunk_batch,
        )
        with (
            self._infer_lock,
            _optional_torch_mode(torch, "no_grad"),
            _optional_torch_mode(torch, "inference_mode"),
        ):
            encoder_output, encoder_output_len = self._model(
                input_signal=buffer.samples,
                input_signal_length=buffer.context_size_batch.total(),
            )
            encoder_output = encoder_output.transpose(1, 2)
            encoder_context = buffer.context_size.subsample(
                factor=self.encoder_frame2audio_samples
            )
            encoder_context_batch = buffer.context_size_batch.subsample(
                factor=self.encoder_frame2audio_samples
            )
            encoder_output = encoder_output[:, encoder_context.left :]
            out_len = torch.where(
                is_last_chunk_batch,
                encoder_output_len - encoder_context_batch.left,
                encoder_context_batch.chunk,
            )
            chunk_hyps, _, next_state = self._decoding_computer(
                x=encoder_output,
                out_len=out_len,
                prev_batched_state=state,
            )
        if current_hyps is None:
            current_hyps = chunk_hyps
        else:
            current_hyps.merge_(chunk_hyps)
        return current_hyps, next_state, self._hypotheses_to_text(current_hyps)

    def _hypotheses_to_text(self, current_hyps: object) -> str:
        if current_hyps is None:
            return ""
        hypotheses = self._runtime.batched_hyps_to_hypotheses(
            current_hyps,
            None,
            batch_size=1,
        )
        if not hypotheses:
            return ""
        first = hypotheses[0]
        text = getattr(first, "text", None)
        if isinstance(text, str) and text.strip():
            return text.strip()
        tokenizer = getattr(self._model, "tokenizer", None)
        if tokenizer is None or not hasattr(tokenizer, "ids_to_text"):
            return ""
        y_sequence = getattr(first, "y_sequence", None)
        if y_sequence is None:
            return ""
        if hasattr(y_sequence, "tolist"):
            token_ids = y_sequence.tolist()
        else:
            token_ids = list(y_sequence)
        return str(tokenizer.ids_to_text(token_ids)).strip()

    def _load_model(self):
        nemo_asr, open_dict, runtime = self._runtime_loader()
        try:
            model = nemo_asr.models.ASRModel.from_pretrained(self.config.repo_id)
        except Exception as exc:
            raise LiveTranscriptionError(
                f"Failed to load Parakeet live model '{self.config.repo_id}': {exc}"
            ) from exc
        _configure_parakeet_live_decoding(
            model,
            open_dict=open_dict,
            decoding_mode=self.config.decoding_mode,
        )
        if hasattr(model, "freeze"):
            model.freeze()
        if hasattr(model, "eval"):
            model.eval()
        if hasattr(model, "to"):
            moved_model = model.to(_coalesce_device(model, runtime))
            if moved_model is not None:
                model = moved_model
        return model, runtime


class ParakeetNemoCudaLiveSession:
    def __init__(
        self, *, session_id: str, backend: ParakeetNemoCudaLiveBackend
    ) -> None:
        self.session_id = session_id
        self.backend = backend
        self.status = "ready"
        self.transcript = ""
        self.received_chunks = 0
        self.processed_windows = 0
        self.error: str | None = None
        self._buffer = backend.create_buffer()
        self._state = None
        self._current_hyps = None
        self._pending_samples: list[float] = []
        self._lock = threading.Lock()

    def snapshot(self) -> LiveTranscriptionUpdate:
        return LiveTranscriptionUpdate(
            session_id=self.session_id,
            status=self.status,
            transcript=self.transcript,
            received_chunks=self.received_chunks,
            processed_windows=self.processed_windows,
            engine_id=self.backend.engine_id,
            engine_label=self.backend.engine_label,
            model_id=self.backend.model_id,
            note=self.backend.note,
            error=self.error,
        )

    def push_chunk(
        self,
        chunk_bytes: bytes,
        *,
        content_type: str | None,
    ) -> LiveTranscriptionUpdate:
        samples = self.backend.decode_chunk(chunk_bytes, content_type=content_type)
        with self._lock:
            self.status = "running"
            self.received_chunks += 1
            if samples:
                self._pending_samples.extend(samples)
                self._drain_pending(final=False)
            return self.snapshot()

    def finish(self) -> LiveTranscriptionUpdate:
        with self._lock:
            if self.status != "error":
                self._drain_pending(final=True)
                self.status = "stopped"
            return self.snapshot()

    def mark_error(self, message: str) -> None:
        with self._lock:
            self.status = "error"
            self.error = message

    def _drain_pending(self, *, final: bool) -> None:
        if not final:
            while self._has_ready_nonfinal_window():
                self._process_window(
                    self._take_samples(self._next_nonfinal_window_size()),
                    is_final=False,
                )
            return
        while self._has_ready_nonfinal_window(
            max_remaining=self.backend.max_final_window_samples
        ):
            self._process_window(
                self._take_samples(self._next_nonfinal_window_size()),
                is_final=False,
            )
        if self._pending_samples or self.processed_windows > 0:
            self._process_window(self._take_all_samples(), is_final=True)

    def _has_ready_nonfinal_window(self, *, max_remaining: int | None = None) -> bool:
        needed = self._next_nonfinal_window_size()
        if len(self._pending_samples) < needed:
            return False
        if max_remaining is not None:
            return len(self._pending_samples) > max_remaining
        return True

    def _next_nonfinal_window_size(self) -> int:
        if self.processed_windows == 0:
            return self.backend.initial_window_samples
        return self.backend.increment_samples

    def _take_samples(self, count: int) -> list[float]:
        taken = self._pending_samples[:count]
        del self._pending_samples[:count]
        return taken

    def _take_all_samples(self) -> list[float]:
        return self._take_samples(len(self._pending_samples))

    def _process_window(self, samples: list[float], *, is_final: bool) -> None:
        self._current_hyps, self._state, self.transcript = (
            self.backend.transcribe_window(
                self._buffer,
                samples=samples,
                is_final=is_final,
                state=self._state,
                current_hyps=self._current_hyps,
            )
        )
        self.processed_windows += 1


def _configure_parakeet_live_decoding(model, *, open_dict, decoding_mode: str) -> None:
    if decoding_mode != "greedy":
        raise LiveTranscriptionError(
            "Parakeet live beta currently supports greedy decoding only."
        )
    decoding_cfg = getattr(getattr(model, "cfg", None), "decoding", None)
    if decoding_cfg is None:
        raise LiveTranscriptionError(
            "Parakeet live beta could not access the model decoding config."
        )
    try:
        with open_dict(decoding_cfg):
            decoding_cfg.strategy = "greedy_batch"
            greedy_cfg = getattr(decoding_cfg, "greedy", None)
            if greedy_cfg is not None and hasattr(greedy_cfg, "loop_labels"):
                greedy_cfg.loop_labels = True
            if hasattr(decoding_cfg, "tdt_include_token_duration"):
                decoding_cfg.tdt_include_token_duration = False
            if hasattr(decoding_cfg, "preserve_alignments"):
                decoding_cfg.preserve_alignments = False
            if hasattr(decoding_cfg, "fused_batch_size"):
                decoding_cfg.fused_batch_size = -1
            beam_cfg = getattr(decoding_cfg, "beam", None)
            if beam_cfg is not None and hasattr(beam_cfg, "return_best_hypothesis"):
                beam_cfg.return_best_hypothesis = True
        model.change_decoding_strategy(decoding_cfg)
    except Exception as exc:
        raise LiveTranscriptionError(
            f"Failed to configure Parakeet live decoding: {exc}"
        ) from exc


def _parakeet_sample_rate(model) -> int:
    preprocessor = getattr(getattr(model, "_cfg", None), "preprocessor", None)
    sample_rate = getattr(preprocessor, "sample_rate", None)
    if isinstance(sample_rate, int) and sample_rate > 0:
        return sample_rate
    preprocessor = getattr(getattr(model, "cfg", None), "preprocessor", None)
    sample_rate = getattr(preprocessor, "sample_rate", None)
    if isinstance(sample_rate, int) and sample_rate > 0:
        return sample_rate
    return 16_000


def _parakeet_encoder_frame_span(model, *, sample_rate: int) -> int:
    preprocessor = getattr(getattr(model, "_cfg", None), "preprocessor", None)
    if preprocessor is None:
        preprocessor = getattr(getattr(model, "cfg", None), "preprocessor", None)
    window_stride = getattr(preprocessor, "window_stride", None)
    if not isinstance(window_stride, (int, float)) or window_stride <= 0:
        window_stride = 0.01
    encoder = getattr(model, "encoder", None)
    subsampling_factor = getattr(encoder, "subsampling_factor", None)
    if not isinstance(subsampling_factor, int) or subsampling_factor < 1:
        subsampling_factor = 8
    feature_frame_samples = _make_divisible_by(
        int(sample_rate * float(window_stride)),
        factor=subsampling_factor,
    )
    return feature_frame_samples * subsampling_factor


def _parakeet_context_samples(
    *,
    runtime: "ParakeetNemoCudaLiveRuntime",
    model,
    config: ParakeetLiveConfig,
    sample_rate: int,
    encoder_frame2audio_samples: int,
):
    preprocessor = getattr(getattr(model, "_cfg", None), "preprocessor", None)
    if preprocessor is None:
        preprocessor = getattr(getattr(model, "cfg", None), "preprocessor", None)
    window_stride = getattr(preprocessor, "window_stride", None)
    if not isinstance(window_stride, (int, float)) or window_stride <= 0:
        window_stride = 0.01
    encoder = getattr(model, "encoder", None)
    subsampling_factor = getattr(encoder, "subsampling_factor", None)
    if not isinstance(subsampling_factor, int) or subsampling_factor < 1:
        subsampling_factor = 8
    features_per_sec = 1.0 / float(window_stride)
    context_encoder_frames = runtime.ContextSize(
        left=int(config.left_context_secs * features_per_sec / subsampling_factor),
        chunk=int(config.chunk_secs * features_per_sec / subsampling_factor),
        right=int(config.right_context_secs * features_per_sec / subsampling_factor),
    )
    frame_sample_span = encoder_frame2audio_samples // subsampling_factor
    return runtime.ContextSize(
        left=context_encoder_frames.left * subsampling_factor * frame_sample_span,
        chunk=context_encoder_frames.chunk * subsampling_factor * frame_sample_span,
        right=context_encoder_frames.right * subsampling_factor * frame_sample_span,
    )


def _decode_browser_audio_chunk(
    chunk_bytes: bytes,
    *,
    content_type: str | None,
    sample_rate: int,
) -> list[float]:
    if not chunk_bytes:
        return []
    ffmpeg_path = shutil.which("ffmpeg")
    if ffmpeg_path is None:
        raise LiveTranscriptionError("ffmpeg is required to decode live audio chunks.")
    suffix = _content_type_suffix(content_type)
    with tempfile.TemporaryDirectory(prefix="mlx-ui-live-") as tmp_dir:
        input_path = Path(tmp_dir) / f"chunk{suffix}"
        input_path.write_bytes(chunk_bytes)
        result = subprocess.run(
            [
                ffmpeg_path,
                "-nostdin",
                "-hide_banner",
                "-loglevel",
                "error",
                "-i",
                str(input_path),
                "-ac",
                "1",
                "-ar",
                str(sample_rate),
                "-f",
                "s16le",
                "-",
            ],
            capture_output=True,
            check=False,
        )
    if result.returncode != 0:
        detail = (result.stderr or b"").decode("utf-8", errors="replace").strip()
        raise LiveTranscriptionError(
            "Failed to decode the browser audio chunk. "
            f"{detail or 'ffmpeg returned an unknown error.'}"
        )
    pcm_bytes = result.stdout
    if len(pcm_bytes) % 2 == 1:
        pcm_bytes = pcm_bytes[:-1]
    pcm_samples = array("h")
    pcm_samples.frombytes(pcm_bytes)
    if pcm_samples.itemsize != 2:
        raise LiveTranscriptionError(
            "Decoded live audio chunk used an unexpected sample format."
        )
    return [sample / 32768.0 for sample in pcm_samples]


def _content_type_suffix(content_type: str | None) -> str:
    normalized = (content_type or "").split(";", 1)[0].strip().lower()
    return {
        "audio/webm": ".webm",
        "video/webm": ".webm",
        "audio/ogg": ".ogg",
        "application/ogg": ".ogg",
        "audio/wav": ".wav",
        "audio/x-wav": ".wav",
        "audio/mp4": ".mp4",
        "audio/mpeg": ".mp3",
    }.get(normalized, ".bin")


def _make_divisible_by(num: int, factor: int) -> int:
    if factor <= 0:
        return num
    return max((num // factor) * factor, factor)


def _coalesce_device(model, runtime: "ParakeetNemoCudaLiveRuntime"):
    device = getattr(model, "device", None)
    if device is not None:
        return device
    cuda = getattr(runtime.torch, "cuda", None)
    if cuda is not None and callable(getattr(cuda, "is_available", None)):
        if cuda.is_available():
            return "cuda"
    return "cpu"


@contextmanager
def _optional_torch_mode(torch_module, name: str):
    factory = getattr(torch_module, name, None)
    if factory is None:
        yield
        return
    with factory():
        yield
