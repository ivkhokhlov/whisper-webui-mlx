from mlx_ui.live_transcription import (
    LiveSessionNotFound,
    LiveTranscriptionUpdate,
    LiveTranscriptionService,
    ParakeetLiveConfig,
)


class FakeSession:
    def __init__(self, session_id: str, *, model_id: str) -> None:
        self.session_id = session_id
        self.model_id = model_id
        self.status = "ready"
        self.transcript = ""
        self.received_chunks = 0
        self.processed_windows = 0
        self.error = None

    def snapshot(self):  # type: ignore[no-untyped-def]
        return _update_from_session(self)

    def push_chunk(self, chunk_bytes: bytes, *, content_type: str | None):  # type: ignore[no-untyped-def]
        self.status = "running"
        self.received_chunks += 1
        self.processed_windows += 1
        self.transcript = f"{content_type}:{chunk_bytes.decode('utf-8')}"
        return _update_from_session(self)

    def finish(self):  # type: ignore[no-untyped-def]
        self.status = "stopped"
        return _update_from_session(self)

    def mark_error(self, message: str) -> None:
        self.status = "error"
        self.error = message


def _update_from_session(session: FakeSession):  # type: ignore[no-untyped-def]
    return LiveTranscriptionUpdate(
        session_id=session.session_id,
        status=session.status,
        transcript=session.transcript,
        received_chunks=session.received_chunks,
        processed_windows=session.processed_windows,
        engine_id="parakeet_tdt_v3",
        engine_label="Parakeet TDT v3",
        model_id=session.model_id,
        note="Experimental local-only Parakeet streaming.",
        error=session.error,
    )


def test_live_transcription_service_reuses_backend_for_same_config() -> None:
    created_models: list[str] = []

    class FakeBackend:
        def __init__(self, config: ParakeetLiveConfig) -> None:
            created_models.append(config.repo_id)
            self.config = config

        def create_session(self, session_id: str):  # type: ignore[no-untyped-def]
            return FakeSession(session_id, model_id=self.config.repo_id)

    service = LiveTranscriptionService(backend_factory=FakeBackend)
    config = ParakeetLiveConfig(repo_id="nvidia/parakeet-tdt-0.6b-v3")

    first = service.open_session(config)
    second = service.open_session(config)
    service.append_chunk(first.session_id, b"one", content_type="audio/webm")
    stopped = service.stop_session(second.session_id)

    assert created_models == ["nvidia/parakeet-tdt-0.6b-v3"]
    assert first.status == "ready"
    assert stopped.status == "stopped"


def test_live_transcription_service_rejects_unknown_session() -> None:
    class FakeBackend:
        def __init__(self, config: ParakeetLiveConfig) -> None:
            self.config = config

        def create_session(self, session_id: str):  # type: ignore[no-untyped-def]
            return FakeSession(session_id, model_id=self.config.repo_id)

    service = LiveTranscriptionService(backend_factory=FakeBackend)

    try:
        service.stop_session("missing")
    except LiveSessionNotFound as exc:
        assert str(exc) == "'missing'"
    else:  # pragma: no cover - defensive
        raise AssertionError("Expected LiveSessionNotFound")
