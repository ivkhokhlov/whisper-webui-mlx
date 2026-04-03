from contextlib import contextmanager
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
from types import SimpleNamespace
import wave

import pytest

from mlx_ui.db import JobRecord
import mlx_ui.transcriber as transcriber_module
from mlx_ui.transcriber import (
    CohereTranscriber,
    ParakeetMlxTranscriber,
    ParakeetNemoCudaTranscriber,
    WhisperTranscriber,
    WtmTranscriber,
)


def _make_job(tmp_path: Path) -> JobRecord:
    uploads_dir = tmp_path / "uploads" / "job1"
    uploads_dir.mkdir(parents=True, exist_ok=True)
    upload_path = uploads_dir / "sample.wav"
    _write_silent_wav(upload_path)
    return JobRecord(
        id="job1",
        filename="sample.wav",
        status="queued",
        created_at=datetime(2024, 1, 1, tzinfo=timezone.utc).isoformat(
            timespec="seconds"
        ),
        upload_path=str(upload_path),
        language="fr",
    )


def _make_job_with_id(tmp_path: Path, job_id: str) -> JobRecord:
    uploads_dir = tmp_path / "uploads" / job_id
    uploads_dir.mkdir(parents=True, exist_ok=True)
    upload_path = uploads_dir / "sample.wav"
    _write_silent_wav(upload_path)
    return JobRecord(
        id=job_id,
        filename="sample.wav",
        status="queued",
        created_at=datetime(2024, 1, 1, tzinfo=timezone.utc).isoformat(
            timespec="seconds"
        ),
        upload_path=str(upload_path),
        language="en",
    )


def _write_silent_wav(
    path: Path, *, duration_seconds: float = 0.1, sample_rate: int = 16_000
) -> None:
    frame_count = max(1, int(duration_seconds * sample_rate))
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(b"\x00\x00" * frame_count)


class FakeParakeetModel:
    def __init__(self, outputs: list[object]) -> None:
        self.outputs = outputs
        self.cfg = SimpleNamespace(
            decoding=SimpleNamespace(
                strategy="greedy_batch",
                compute_timestamps=False,
                preserve_alignments=False,
                rnnt_timestamp_type=None,
                word_seperator=None,
                segment_seperators=None,
            ),
            preprocessor=SimpleNamespace(window_stride=0.01),
        )
        self.calls: list[dict[str, object]] = []
        self.decoding_strategy = None

    def change_decoding_strategy(self, decoding_cfg) -> None:  # type: ignore[no-untyped-def]
        self.decoding_strategy = decoding_cfg

    def transcribe(self, **kwargs):  # type: ignore[no-untyped-def]
        self.calls.append(dict(kwargs))
        return list(self.outputs)


class FakeParakeetFactory:
    def __init__(self, model: FakeParakeetModel) -> None:
        self.model = model
        self.calls: list[str] = []

    def from_pretrained(self, repo_id: str):  # type: ignore[no-untyped-def]
        self.calls.append(repo_id)
        return self.model


class FakeParakeetMlxModel:
    def __init__(self, output: object) -> None:
        self.output = output
        self.calls: list[dict[str, object]] = []

    def transcribe(
        self,
        source_path: str,
        *,
        chunk_duration: float | None = None,
        overlap_duration: float | None = None,
        decoding_mode: str | None = None,
        batch_size: int | None = None,
    ) -> object:
        self.calls.append(
            {
                "source_path": source_path,
                "chunk_duration": chunk_duration,
                "overlap_duration": overlap_duration,
                "decoding_mode": decoding_mode,
                "batch_size": batch_size,
            }
        )
        return self.output


class FakeParakeetMlxRuntime:
    def __init__(self, model: FakeParakeetMlxModel) -> None:
        self.model = model
        self.calls: list[str] = []

    def from_pretrained(self, model_id: str) -> FakeParakeetMlxModel:
        self.calls.append(model_id)
        return self.model


@contextmanager
def _fake_open_dict(cfg):  # type: ignore[no-untyped-def]
    yield cfg


class FakeCohereApiError(Exception):
    def __init__(self, *, status_code=None, body=None, headers=None) -> None:
        self.status_code = status_code
        self.body = body
        self.headers = headers
        super().__init__(f"status={status_code}, body={body}")


class FakeCohereClientV2:
    response = None
    error = None
    created: list["FakeCohereClientV2"] = []

    def __init__(self, api_key: str) -> None:
        self.api_key = api_key
        self.calls: list[dict[str, object]] = []
        self.audio = SimpleNamespace(
            transcriptions=SimpleNamespace(create=self._create_transcription)
        )
        self.__class__.created.append(self)

    def _create_transcription(self, *, model, language, file):  # type: ignore[no-untyped-def]
        payload = {
            "model": model,
            "language": language,
            "filename": Path(file.name).name,
            "content": file.read(),
        }
        self.calls.append(payload)
        if self.__class__.error is not None:
            raise self.__class__.error
        return self.__class__.response

    @classmethod
    def reset(cls) -> None:
        cls.response = None
        cls.error = None
        cls.created = []


def _fake_cohere_runtime():  # type: ignore[no-untyped-def]
    return (
        SimpleNamespace(ClientV2=FakeCohereClientV2),
        FakeCohereApiError,
    )


def test_wtm_transcriber_runs_and_returns_txt(tmp_path: Path, monkeypatch) -> None:
    job = _make_job(tmp_path)
    results_dir = tmp_path / "results"
    captured: dict[str, list[str]] = {}

    class FakePopen:
        def __init__(self, cmd, stdout, stderr, text):  # type: ignore[no-untyped-def]
            captured["cmd"] = list(cmd)
            self.returncode = 0

        def communicate(self):  # type: ignore[no-untyped-def]
            return ("hello", "")

    monkeypatch.setattr(subprocess, "Popen", FakePopen)
    monkeypatch.delenv("WTM_QUICK", raising=False)

    transcriber = WtmTranscriber(wtm_path="wtm")
    result_path = transcriber.transcribe(job, results_dir)

    assert result_path.is_file()
    assert result_path.read_text(encoding="utf-8") == "hello\n"
    assert captured["cmd"][0] == "wtm"
    assert "--path_audio" in captured["cmd"]
    assert "--any_lang=True" in captured["cmd"]
    assert "--quick=False" in captured["cmd"]
    assert str(Path(job.upload_path)) in captured["cmd"]
    assert (results_dir / job.id / "sample.txt").is_file()


def test_wtm_transcriber_respects_quick_env(tmp_path: Path, monkeypatch) -> None:
    job = _make_job(tmp_path)
    results_dir = tmp_path / "results"
    captured: dict[str, list[str]] = {}

    class FakePopen:
        def __init__(self, cmd, stdout, stderr, text):  # type: ignore[no-untyped-def]
            captured["cmd"] = list(cmd)
            self.returncode = 0

        def communicate(self):  # type: ignore[no-untyped-def]
            return ("hello", "")

    monkeypatch.setattr(subprocess, "Popen", FakePopen)
    monkeypatch.setenv("WTM_QUICK", "true")

    transcriber = WtmTranscriber(wtm_path="wtm")
    transcriber.transcribe(job, results_dir)

    assert "--quick=True" in captured["cmd"]


def test_wtm_transcriber_honors_output_formats_without_faking_timestamps(
    tmp_path: Path, monkeypatch
) -> None:
    job = _make_job(tmp_path)
    results_dir = tmp_path / "results"

    class FakePopen:
        def __init__(self, cmd, stdout, stderr, text):  # type: ignore[no-untyped-def]
            self.returncode = 0

        def communicate(self):  # type: ignore[no-untyped-def]
            return ("hello", "")

    monkeypatch.setattr(subprocess, "Popen", FakePopen)

    transcriber = WtmTranscriber(
        wtm_path="wtm",
        output_formats=("txt", "json", "srt", "vtt"),
    )
    result_path = transcriber.transcribe(job, results_dir)

    assert result_path == results_dir / job.id / "sample.txt"
    assert result_path.read_text(encoding="utf-8") == "hello\n"
    payload = json.loads((results_dir / job.id / "sample.json").read_text("utf-8"))
    assert payload["text"] == "hello"
    assert payload["engine_id"] == "whisper_mlx"
    assert payload["segments"] == []
    assert payload["words"] == []
    assert not (results_dir / job.id / "sample.srt").exists()
    assert not (results_dir / job.id / "sample.vtt").exists()


def test_whisper_transcriber_honors_output_formats_with_real_timing(
    tmp_path: Path, monkeypatch
) -> None:
    job = _make_job(tmp_path)
    results_dir = tmp_path / "results"
    captured: dict[str, object] = {}

    class FakeWhisperModel:
        def transcribe(self, source_path: str, **kwargs):  # type: ignore[no-untyped-def]
            captured["source_path"] = source_path
            captured["kwargs"] = dict(kwargs)
            return {
                "text": "hello world",
                "language": "en",
                "segments": [
                    {"id": 0, "text": "hello", "start": 0.0, "end": 0.5},
                    {"id": 1, "text": "world", "start": 0.5, "end": 1.0},
                ],
                "words": [
                    {"word": "hello", "start": 0.0, "end": 0.5},
                    {"word": "world", "start": 0.5, "end": 1.0},
                ],
            }

    transcriber = WhisperTranscriber(
        model_name="tiny",
        output_formats=("txt", "json", "srt", "vtt"),
    )
    monkeypatch.setattr(transcriber, "_ensure_model", lambda: FakeWhisperModel())

    result_path = transcriber.transcribe(job, results_dir)

    assert result_path == results_dir / job.id / "sample.txt"
    assert result_path.read_text(encoding="utf-8") == "hello world\n"
    assert (results_dir / job.id / "sample.json").is_file()
    assert (results_dir / job.id / "sample.srt").is_file()
    assert (results_dir / job.id / "sample.vtt").is_file()
    assert captured["source_path"] == str(Path(job.upload_path))
    assert captured["kwargs"] == {"fp16": False, "word_timestamps": True}


def test_whisper_transcriber_skips_timed_outputs_when_backend_has_no_timing(
    tmp_path: Path, monkeypatch
) -> None:
    job = _make_job(tmp_path)
    results_dir = tmp_path / "results"

    class FakeWhisperModel:
        def transcribe(self, source_path: str, **kwargs):  # type: ignore[no-untyped-def]
            return {
                "text": "hello world",
                "language": "en",
                "segments": [],
                "words": [],
            }

    transcriber = WhisperTranscriber(
        model_name="tiny",
        output_formats=("txt", "json", "srt", "vtt"),
    )
    monkeypatch.setattr(transcriber, "_ensure_model", lambda: FakeWhisperModel())

    result_path = transcriber.transcribe(job, results_dir)

    assert result_path == results_dir / job.id / "sample.txt"
    assert (results_dir / job.id / "sample.json").is_file()
    assert not (results_dir / job.id / "sample.srt").exists()
    assert not (results_dir / job.id / "sample.vtt").exists()


def test_parakeet_nemo_cuda_transcriber_uses_python_api_and_writes_outputs(
    tmp_path: Path, monkeypatch
) -> None:
    job = _make_job(tmp_path)
    results_dir = tmp_path / "results"
    model = FakeParakeetModel(
        outputs=[
            {
                "text": "hello world",
                "language": "en",
                "timestamp": {
                    "segment": [
                        {
                            "segment": "hello world",
                            "start_offset": 0,
                            "end_offset": 12,
                        }
                    ],
                    "word": [
                        {"word": "hello", "start_offset": 0, "end_offset": 5},
                        {"word": "world", "start_offset": 6, "end_offset": 12},
                    ],
                },
            }
        ]
    )
    factory = FakeParakeetFactory(model)
    fake_nemo_asr = SimpleNamespace(models=SimpleNamespace(ASRModel=factory))
    monkeypatch.setattr(
        transcriber_module,
        "_load_parakeet_runtime",
        lambda: (fake_nemo_asr, _fake_open_dict),
    )

    transcriber = ParakeetNemoCudaTranscriber(
        output_formats=("txt", "srt", "vtt", "json"),
        batch_size=4,
    )
    result_path = transcriber.transcribe(job, results_dir)

    assert factory.calls == ["nvidia/parakeet-tdt-0.6b-v3"]
    assert result_path == results_dir / job.id / "sample.txt"
    assert result_path.read_text(encoding="utf-8") == "hello world\n"
    assert (results_dir / job.id / "sample.srt").is_file()
    assert (results_dir / job.id / "sample.vtt").is_file()
    payload = json.loads((results_dir / job.id / "sample.json").read_text("utf-8"))
    assert payload["engine_id"] == "parakeet_tdt_v3"
    assert payload["model_id"] == "nvidia/parakeet-tdt-0.6b-v3"
    assert payload["language"] == "en"
    assert model.calls[0]["audio"] == [str(Path(job.upload_path))]
    assert model.calls[0]["batch_size"] == 1
    assert model.calls[0]["return_hypotheses"] is True
    assert model.calls[0]["timestamps"] is True
    assert model.decoding_strategy is not None
    assert model.decoding_strategy.strategy == "greedy_batch"


def test_parakeet_nemo_cuda_transcriber_lazy_loads_and_reuses_model(
    tmp_path: Path, monkeypatch
) -> None:
    job1 = _make_job_with_id(tmp_path, "job1")
    job2 = _make_job_with_id(tmp_path, "job2")
    results_dir = tmp_path / "results"
    model = FakeParakeetModel(outputs=[{"text": "hello"}])
    factory = FakeParakeetFactory(model)
    fake_nemo_asr = SimpleNamespace(models=SimpleNamespace(ASRModel=factory))
    monkeypatch.setattr(
        transcriber_module,
        "_load_parakeet_runtime",
        lambda: (fake_nemo_asr, _fake_open_dict),
    )

    transcriber = ParakeetNemoCudaTranscriber()
    transcriber.transcribe(job1, results_dir)
    transcriber.transcribe(job2, results_dir)

    assert factory.calls == ["nvidia/parakeet-tdt-0.6b-v3"]
    assert len(model.calls) == 2


def test_parakeet_nemo_cuda_transcriber_raises_clear_error_when_runtime_missing(
    tmp_path: Path, monkeypatch
) -> None:
    job = _make_job(tmp_path)

    def fail_runtime():  # type: ignore[no-untyped-def]
        raise RuntimeError(
            "Parakeet backend cannot run: NVIDIA NeMo ASR is not installed."
        )

    monkeypatch.setattr(transcriber_module, "_load_parakeet_runtime", fail_runtime)

    transcriber = ParakeetNemoCudaTranscriber()

    with pytest.raises(
        RuntimeError,
        match="Parakeet backend cannot run: NVIDIA NeMo ASR is not installed.",
    ):
        transcriber.transcribe(job, tmp_path / "results")


def test_parakeet_mlx_transcriber_uses_python_api_and_writes_outputs(
    tmp_path: Path, monkeypatch
) -> None:
    job = _make_job(tmp_path)
    results_dir = tmp_path / "results"
    model_output = {
        "text": "hello world",
        "language": "en",
        "segments": [{"id": 0, "text": "hello world", "start": 0.0, "end": 1.0}],
        "words": [
            {"word": "hello", "start": 0.0, "end": 0.5},
            {"word": "world", "start": 0.5, "end": 1.0},
        ],
    }
    model = FakeParakeetMlxModel(model_output)
    runtime = FakeParakeetMlxRuntime(model)
    monkeypatch.setattr(
        transcriber_module,
        "_load_parakeet_mlx_runtime",
        lambda: runtime.from_pretrained,
    )

    transcriber = ParakeetMlxTranscriber(
        output_formats=("txt", "srt", "vtt", "json"),
    )
    result_path = transcriber.transcribe(job, results_dir)

    assert runtime.calls == ["mlx-community/parakeet-tdt-0.6b-v3"]
    assert result_path == results_dir / job.id / "sample.txt"
    assert result_path.read_text(encoding="utf-8") == "hello world\n"
    assert (results_dir / job.id / "sample.srt").is_file()
    assert (results_dir / job.id / "sample.vtt").is_file()
    payload = json.loads((results_dir / job.id / "sample.json").read_text("utf-8"))
    assert payload["engine_id"] == "parakeet_tdt_v3"
    assert payload["model_id"] == "mlx-community/parakeet-tdt-0.6b-v3"
    assert payload["language"] == "en"
    assert model.calls[0]["source_path"] == str(Path(job.upload_path))
    assert model.calls[0]["chunk_duration"] == 30.0
    assert model.calls[0]["overlap_duration"] == 5.0
    assert model.calls[0]["decoding_mode"] == "greedy"
    assert model.calls[0]["batch_size"] == 1


def test_parakeet_mlx_transcriber_lazy_loads_and_reuses_model(
    tmp_path: Path, monkeypatch
) -> None:
    job1 = _make_job_with_id(tmp_path, "job1")
    job2 = _make_job_with_id(tmp_path, "job2")
    results_dir = tmp_path / "results"
    model = FakeParakeetMlxModel({"text": "hello"})
    runtime = FakeParakeetMlxRuntime(model)
    monkeypatch.setattr(
        transcriber_module,
        "_load_parakeet_mlx_runtime",
        lambda: runtime.from_pretrained,
    )

    transcriber = ParakeetMlxTranscriber()
    transcriber.transcribe(job1, results_dir)
    transcriber.transcribe(job2, results_dir)

    assert runtime.calls == ["mlx-community/parakeet-tdt-0.6b-v3"]
    assert len(model.calls) == 2


def test_parakeet_mlx_transcriber_passes_beam_decoding_config_when_supported(
    tmp_path: Path,
    monkeypatch,
) -> None:
    job = _make_job(tmp_path)
    results_dir = tmp_path / "results"
    decoding_configs: list[object] = []

    class BeamModel:
        def transcribe(
            self,
            source_path: str,
            *,
            decoding_config=None,
            **_kwargs,  # type: ignore[no-untyped-def]
        ) -> object:
            decoding_configs.append(decoding_config)
            return {"text": "hello"}

    model = BeamModel()
    runtime = FakeParakeetMlxRuntime(model)  # type: ignore[arg-type]
    monkeypatch.setattr(
        transcriber_module,
        "_load_parakeet_mlx_runtime",
        lambda: runtime.from_pretrained,
    )

    import mlx_ui.engines.parakeet_mlx as parakeet_mlx_engine

    sentinel = object()
    monkeypatch.setattr(
        parakeet_mlx_engine, "parakeet_mlx_supports_beam_decoding", lambda: True
    )
    monkeypatch.setattr(
        parakeet_mlx_engine,
        "build_parakeet_mlx_decoding_config",
        lambda _mode: sentinel,
    )

    transcriber = ParakeetMlxTranscriber(decoding_mode="beam")
    transcriber.transcribe(job, results_dir)

    assert decoding_configs == [sentinel]


def test_parakeet_mlx_transcriber_rejects_beam_when_runtime_does_not_support_it(
    tmp_path: Path,
    monkeypatch,
) -> None:
    job = _make_job(tmp_path)
    results_dir = tmp_path / "results"
    model = FakeParakeetMlxModel({"text": "hello"})
    runtime = FakeParakeetMlxRuntime(model)
    monkeypatch.setattr(
        transcriber_module,
        "_load_parakeet_mlx_runtime",
        lambda: runtime.from_pretrained,
    )
    import mlx_ui.engines.parakeet_mlx as parakeet_mlx_engine

    monkeypatch.setattr(
        parakeet_mlx_engine, "parakeet_mlx_supports_beam_decoding", lambda: False
    )

    transcriber = ParakeetMlxTranscriber(decoding_mode="beam")

    with pytest.raises(
        RuntimeError,
        match="Beam decoding requested",
    ):
        transcriber.transcribe(job, results_dir)


def test_parakeet_mlx_transcriber_raises_clear_error_when_runtime_missing(
    tmp_path: Path, monkeypatch
) -> None:
    job = _make_job(tmp_path)

    def fail_runtime():  # type: ignore[no-untyped-def]
        raise RuntimeError(
            "Parakeet MLX backend cannot run: The optional 'parakeet-mlx' dependency is not installed."
        )

    monkeypatch.setattr(transcriber_module, "_load_parakeet_mlx_runtime", fail_runtime)

    transcriber = ParakeetMlxTranscriber()

    with pytest.raises(
        RuntimeError,
        match="Parakeet MLX backend cannot run: The optional 'parakeet-mlx' dependency is not installed.",
    ):
        transcriber.transcribe(job, tmp_path / "results")


def test_cohere_transcriber_uses_sdk_and_shared_output_writers(
    tmp_path: Path, monkeypatch
) -> None:
    job = _make_job(tmp_path)
    results_dir = tmp_path / "results"
    FakeCohereClientV2.reset()
    FakeCohereClientV2.response = SimpleNamespace(text="bonjour le monde")
    monkeypatch.setattr(
        transcriber_module,
        "_load_cohere_runtime",
        _fake_cohere_runtime,
    )

    transcriber = CohereTranscriber(
        api_key="cohere-secret-key",
        model_name="cohere-transcribe-03-2026",
        output_formats=("txt", "json", "srt", "vtt"),
    )
    result_path = transcriber.transcribe(job, results_dir)

    assert len(FakeCohereClientV2.created) == 1
    client = FakeCohereClientV2.created[0]
    assert client.api_key == "cohere-secret-key"
    assert client.calls == [
        {
            "model": "cohere-transcribe-03-2026",
            "language": "fr",
            "filename": "sample.wav",
            "content": Path(job.upload_path).read_bytes(),
        }
    ]
    assert result_path == results_dir / job.id / "sample.txt"
    assert result_path.read_text(encoding="utf-8") == "bonjour le monde\n"
    payload = json.loads((results_dir / job.id / "sample.json").read_text("utf-8"))
    assert payload["text"] == "bonjour le monde"
    assert payload["engine_id"] == "cohere"
    assert payload["model_id"] == "cohere-transcribe-03-2026"
    assert payload["language"] == "fr"
    assert payload["segments"] == []
    assert payload["words"] == []
    assert not (results_dir / job.id / "sample.srt").exists()
    assert not (results_dir / job.id / "sample.vtt").exists()


def test_cohere_transcriber_rejects_auto_language(tmp_path: Path) -> None:
    job = _make_job(tmp_path)
    job.language = "auto"
    transcriber = CohereTranscriber(api_key="cohere-secret-key")

    with pytest.raises(
        RuntimeError,
        match="automatic language detection is not supported",
    ):
        transcriber.transcribe(job, tmp_path / "results")


def test_cohere_transcriber_rejects_unsupported_language(tmp_path: Path) -> None:
    job = _make_job(tmp_path)
    job.language = "ru"
    transcriber = CohereTranscriber(api_key="cohere-secret-key")

    with pytest.raises(RuntimeError, match="Cohere does not support language 'ru'"):
        transcriber.transcribe(job, tmp_path / "results")


def test_cohere_transcriber_requires_api_key(tmp_path: Path) -> None:
    job = _make_job(tmp_path)
    transcriber = CohereTranscriber(api_key="")

    with pytest.raises(RuntimeError, match="no API key is configured"):
        transcriber.transcribe(job, tmp_path / "results")


def test_cohere_transcriber_classifies_auth_failure(
    tmp_path: Path, monkeypatch
) -> None:
    job = _make_job(tmp_path)
    FakeCohereClientV2.reset()
    FakeCohereClientV2.error = FakeCohereApiError(
        status_code=401,
        body={"message": "invalid api key"},
    )
    monkeypatch.setattr(
        transcriber_module,
        "_load_cohere_runtime",
        _fake_cohere_runtime,
    )
    transcriber = CohereTranscriber(api_key="cohere-secret-key")

    with pytest.raises(RuntimeError, match="Cohere authentication failed"):
        transcriber.transcribe(job, tmp_path / "results")


def test_cohere_transcriber_classifies_rate_limit(tmp_path: Path, monkeypatch) -> None:
    job = _make_job(tmp_path)
    FakeCohereClientV2.reset()
    FakeCohereClientV2.error = FakeCohereApiError(
        status_code=429,
        body={"message": "too many requests"},
    )
    monkeypatch.setattr(
        transcriber_module,
        "_load_cohere_runtime",
        _fake_cohere_runtime,
    )
    transcriber = CohereTranscriber(api_key="cohere-secret-key")

    with pytest.raises(RuntimeError, match="Cohere rate limit exceeded"):
        transcriber.transcribe(job, tmp_path / "results")


def test_cohere_transcriber_classifies_validation_error(
    tmp_path: Path, monkeypatch
) -> None:
    job = _make_job(tmp_path)
    FakeCohereClientV2.reset()
    FakeCohereClientV2.error = FakeCohereApiError(
        status_code=422,
        body={"message": "invalid request"},
    )
    monkeypatch.setattr(
        transcriber_module,
        "_load_cohere_runtime",
        _fake_cohere_runtime,
    )
    transcriber = CohereTranscriber(api_key="cohere-secret-key")

    with pytest.raises(RuntimeError, match="Cohere request validation failed"):
        transcriber.transcribe(job, tmp_path / "results")


def test_cohere_transcriber_classifies_service_error(
    tmp_path: Path, monkeypatch
) -> None:
    job = _make_job(tmp_path)
    FakeCohereClientV2.reset()
    FakeCohereClientV2.error = FakeCohereApiError(
        status_code=503,
        body={"message": "service unavailable"},
    )
    monkeypatch.setattr(
        transcriber_module,
        "_load_cohere_runtime",
        _fake_cohere_runtime,
    )
    transcriber = CohereTranscriber(api_key="cohere-secret-key")

    with pytest.raises(RuntimeError, match="Cohere service error"):
        transcriber.transcribe(job, tmp_path / "results")
