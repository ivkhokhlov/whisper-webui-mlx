import types

from mlx_ui.engines import parakeet_mlx_live_runtime


def test_probe_reports_unsupported_platform(monkeypatch) -> None:
    monkeypatch.setattr(parakeet_mlx_live_runtime, "_platform", lambda: "linux")

    assert (
        parakeet_mlx_live_runtime.parakeet_mlx_live_runtime_unavailability_reason()
        == "Parakeet MLX live beta is supported on macOS only."
    )


def test_probe_reports_unsupported_architecture(monkeypatch) -> None:
    monkeypatch.setattr(parakeet_mlx_live_runtime, "_platform", lambda: "darwin")
    monkeypatch.setattr(parakeet_mlx_live_runtime, "_machine", lambda: "x86_64")

    assert (
        parakeet_mlx_live_runtime.parakeet_mlx_live_runtime_unavailability_reason()
        == "Parakeet MLX live beta is supported on Apple Silicon (arm64) only."
    )


def test_probe_reports_missing_optional_dependency(monkeypatch) -> None:
    monkeypatch.setattr(parakeet_mlx_live_runtime, "_platform", lambda: "darwin")
    monkeypatch.setattr(parakeet_mlx_live_runtime, "_machine", lambda: "arm64")
    monkeypatch.setattr(
        parakeet_mlx_live_runtime.importlib.util,
        "find_spec",
        lambda _: None,
    )

    assert (
        parakeet_mlx_live_runtime.parakeet_mlx_live_runtime_unavailability_reason()
        == "The optional 'parakeet-mlx' dependency is not installed (Python module 'parakeet_mlx')."
    )


def test_probe_reports_missing_streaming_api(monkeypatch) -> None:
    monkeypatch.setattr(parakeet_mlx_live_runtime, "_platform", lambda: "darwin")
    monkeypatch.setattr(parakeet_mlx_live_runtime, "_machine", lambda: "arm64")
    monkeypatch.setattr(
        parakeet_mlx_live_runtime.importlib.util,
        "find_spec",
        lambda _: object(),
    )

    stub = types.SimpleNamespace(from_pretrained=lambda _: object())
    monkeypatch.setattr(parakeet_mlx_live_runtime, "_import_parakeet_mlx", lambda: stub)

    assert (
        parakeet_mlx_live_runtime.parakeet_mlx_live_runtime_unavailability_reason()
        == "The installed Parakeet MLX runtime does not expose a streaming API (missing StreamingParakeet)."
    )


def test_probe_reports_missing_from_pretrained(monkeypatch) -> None:
    monkeypatch.setattr(parakeet_mlx_live_runtime, "_platform", lambda: "darwin")
    monkeypatch.setattr(parakeet_mlx_live_runtime, "_machine", lambda: "arm64")
    monkeypatch.setattr(
        parakeet_mlx_live_runtime.importlib.util,
        "find_spec",
        lambda _: object(),
    )

    class StreamingParakeet:
        def add_audio(self, audio):  # type: ignore[no-untyped-def]
            return None

        @property
        def result(self):  # type: ignore[no-untyped-def]
            return None

    stub = types.SimpleNamespace(StreamingParakeet=StreamingParakeet)
    monkeypatch.setattr(parakeet_mlx_live_runtime, "_import_parakeet_mlx", lambda: stub)

    assert (
        parakeet_mlx_live_runtime.parakeet_mlx_live_runtime_unavailability_reason()
        == "The installed Parakeet MLX runtime is missing the expected from_pretrained() loader."
    )


def test_probe_reports_usable_when_streaming_present(monkeypatch) -> None:
    monkeypatch.setattr(parakeet_mlx_live_runtime, "_platform", lambda: "darwin")
    monkeypatch.setattr(parakeet_mlx_live_runtime, "_machine", lambda: "arm64")
    monkeypatch.setattr(
        parakeet_mlx_live_runtime.importlib.util,
        "find_spec",
        lambda _: object(),
    )

    class StreamingParakeet:
        def add_audio(self, audio):  # type: ignore[no-untyped-def]
            return None

        @property
        def result(self):  # type: ignore[no-untyped-def]
            return None

    stub = types.SimpleNamespace(
        StreamingParakeet=StreamingParakeet,
        from_pretrained=lambda _: object(),
    )
    monkeypatch.setattr(parakeet_mlx_live_runtime, "_import_parakeet_mlx", lambda: stub)

    assert (
        parakeet_mlx_live_runtime.parakeet_mlx_live_runtime_unavailability_reason()
        is None
    )
    assert parakeet_mlx_live_runtime.is_parakeet_mlx_live_runtime_usable() is True
