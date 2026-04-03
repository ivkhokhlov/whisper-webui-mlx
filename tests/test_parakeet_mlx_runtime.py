import types

from mlx_ui.engines import parakeet_mlx_runtime


def test_probe_reports_unsupported_platform(monkeypatch) -> None:
    monkeypatch.setattr(parakeet_mlx_runtime, "_platform", lambda: "linux")

    assert (
        parakeet_mlx_runtime.parakeet_mlx_runtime_unavailability_reason()
        == "Parakeet MLX runtime is supported on macOS only."
    )


def test_probe_reports_unsupported_architecture(monkeypatch) -> None:
    monkeypatch.setattr(parakeet_mlx_runtime, "_platform", lambda: "darwin")
    monkeypatch.setattr(parakeet_mlx_runtime, "_machine", lambda: "x86_64")

    assert (
        parakeet_mlx_runtime.parakeet_mlx_runtime_unavailability_reason()
        == "Parakeet MLX runtime is supported on Apple Silicon (arm64) only."
    )


def test_probe_reports_missing_optional_dependency(monkeypatch) -> None:
    monkeypatch.setattr(parakeet_mlx_runtime, "_platform", lambda: "darwin")
    monkeypatch.setattr(parakeet_mlx_runtime, "_machine", lambda: "arm64")
    monkeypatch.setattr(
        parakeet_mlx_runtime.importlib.util,
        "find_spec",
        lambda _: None,
    )

    assert (
        parakeet_mlx_runtime.parakeet_mlx_runtime_unavailability_reason()
        == "The optional 'parakeet-mlx' dependency is not installed (Python module 'parakeet_mlx')."
    )


def test_probe_reports_usable_when_importable(monkeypatch) -> None:
    monkeypatch.setattr(parakeet_mlx_runtime, "_platform", lambda: "darwin")
    monkeypatch.setattr(parakeet_mlx_runtime, "_machine", lambda: "arm64")
    monkeypatch.setattr(
        parakeet_mlx_runtime.importlib.util,
        "find_spec",
        lambda _: object(),
    )

    assert parakeet_mlx_runtime.parakeet_mlx_runtime_unavailability_reason() is None
    assert parakeet_mlx_runtime.is_parakeet_mlx_runtime_usable() is True


def test_feature_detection_is_best_effort(monkeypatch) -> None:
    monkeypatch.setattr(
        parakeet_mlx_runtime,
        "is_parakeet_mlx_runtime_usable",
        lambda: True,
    )

    stub = types.SimpleNamespace(
        DecodingConfig=object(),
        Beam=object(),
        Greedy=object(),
    )
    monkeypatch.setattr(parakeet_mlx_runtime, "_import_parakeet_mlx", lambda: stub)

    assert (
        parakeet_mlx_runtime.parakeet_mlx_exposes_advanced_decoding_config_types()
        is True
    )


def test_beam_support_requires_constructable_config(monkeypatch) -> None:
    monkeypatch.setattr(
        parakeet_mlx_runtime,
        "is_parakeet_mlx_runtime_usable",
        lambda: True,
    )

    class Beam:
        def __init__(self, beam_size: int = 4) -> None:
            self.beam_size = beam_size

    class Greedy:
        pass

    class DecodingConfig:
        def __init__(self, strategy) -> None:  # type: ignore[no-untyped-def]
            self.strategy = strategy

    stub = types.SimpleNamespace(
        DecodingConfig=DecodingConfig,
        Beam=Beam,
        Greedy=Greedy,
    )
    monkeypatch.setattr(parakeet_mlx_runtime, "_import_parakeet_mlx", lambda: stub)

    config = parakeet_mlx_runtime.build_parakeet_mlx_decoding_config("beam")
    assert config is not None
    assert isinstance(config.strategy, Beam)
    assert config.strategy.beam_size == 4
    assert parakeet_mlx_runtime.parakeet_mlx_supports_beam_decoding() is True
