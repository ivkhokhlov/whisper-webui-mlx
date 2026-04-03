import types

from mlx_ui.engines.parakeet_mlx_live_runtime import ParakeetMlxLiveRuntime
from mlx_ui.live_transcription import ParakeetLiveConfig, ParakeetMlxLiveBackend


def test_parakeet_mlx_live_session_streams_text(monkeypatch) -> None:
    class FakeMx:
        float32 = "float32"

        def array(self, values, dtype=None):  # type: ignore[no-untyped-def]
            return {"values": list(values), "dtype": dtype}

    class StreamingParakeet:
        def __init__(self, model) -> None:
            self._chunks = 0

        def add_audio(self, audio) -> None:  # type: ignore[no-untyped-def]
            self._chunks += 1

        @property
        def result(self):  # type: ignore[no-untyped-def]
            return types.SimpleNamespace(text=f"chunks={self._chunks}")

        def finalize(self) -> None:
            return None

    runtime = ParakeetMlxLiveRuntime(
        from_pretrained=lambda _: object(),
        StreamingParakeet=StreamingParakeet,
        mx=FakeMx(),
    )

    backend = ParakeetMlxLiveBackend(
        ParakeetLiveConfig(repo_id="mlx-community/parakeet-tdt-0.6b-v3"),
        runtime_loader=lambda: runtime,
    )
    monkeypatch.setattr(
        backend,
        "decode_chunk",
        lambda *_args, **_kwargs: [0.1, -0.2, 0.3],
    )

    session = backend.create_session("live-1")
    first = session.push_chunk(b"ignored", content_type="audio/webm")
    second = session.push_chunk(b"ignored", content_type="audio/webm")
    stopped = session.finish()

    assert first.status == "running"
    assert first.transcript == "chunks=1"
    assert first.received_chunks == 1
    assert first.processed_windows == 1

    assert second.transcript == "chunks=2"
    assert second.received_chunks == 2
    assert second.processed_windows == 2

    assert stopped.status == "stopped"


def test_parakeet_mlx_live_session_skips_empty_audio(monkeypatch) -> None:
    class FakeMx:
        def array(self, values, dtype=None):  # type: ignore[no-untyped-def]
            return list(values)

    class StreamingParakeet:
        def __init__(self, model) -> None:
            self._chunks = 0

        def add_audio(self, audio) -> None:  # type: ignore[no-untyped-def]
            self._chunks += 1

        @property
        def result(self):  # type: ignore[no-untyped-def]
            return types.SimpleNamespace(text=f"chunks={self._chunks}")

    runtime = ParakeetMlxLiveRuntime(
        from_pretrained=lambda _: object(),
        StreamingParakeet=StreamingParakeet,
        mx=FakeMx(),
    )

    backend = ParakeetMlxLiveBackend(
        ParakeetLiveConfig(repo_id="mlx-community/parakeet-tdt-0.6b-v3"),
        runtime_loader=lambda: runtime,
    )
    monkeypatch.setattr(
        backend,
        "decode_chunk",
        lambda *_args, **_kwargs: [],
    )

    session = backend.create_session("live-1")
    update = session.push_chunk(b"ignored", content_type="audio/webm")

    assert update.received_chunks == 1
    assert update.processed_windows == 0
    assert update.transcript == ""
