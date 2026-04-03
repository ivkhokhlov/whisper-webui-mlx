import mlx_ui.engine_registry as engine_registry
from mlx_ui.live_backend_runtime import resolve_parakeet_live_backend
from mlx_ui.runtime_metadata_engine_options import build_registry_engine_options


def _unexpected_nemo_probe(_env):  # type: ignore[no-untyped-def]
    raise AssertionError("Unexpected NeMo probe call")


def test_live_backend_resolution_on_macos_never_uses_nemo_backend(monkeypatch) -> None:
    monkeypatch.setattr("mlx_ui.live_backend_runtime.sys.platform", "darwin")
    monkeypatch.setattr(
        "mlx_ui.live_backend_runtime.parakeet_mlx_live_runtime_unavailability_reason",
        lambda: "The optional 'parakeet-mlx' dependency is not installed.",
    )
    monkeypatch.setattr(
        "mlx_ui.live_backend_runtime._parakeet_nemo_cuda_live_unavailability_reason",
        _unexpected_nemo_probe,
    )

    resolution = resolve_parakeet_live_backend(
        env={engine_registry.PARAKEET_NEMO_CUDA_EXPERIMENTAL_ENV: "1"}
    )

    assert resolution.state == "unavailable"
    assert resolution.implementation_id == engine_registry.PARAKEET_MLX_BACKEND
    assert "parakeet-mlx" in str(resolution.reason)


def test_live_backend_resolution_on_linux_without_experimental_flag_does_not_probe_nemo(
    monkeypatch,
) -> None:
    monkeypatch.setattr("mlx_ui.live_backend_runtime.sys.platform", "linux")
    monkeypatch.delenv(engine_registry.PARAKEET_NEMO_CUDA_EXPERIMENTAL_ENV, raising=False)
    monkeypatch.setattr(
        "mlx_ui.live_backend_runtime._parakeet_nemo_cuda_live_unavailability_reason",
        _unexpected_nemo_probe,
    )

    resolution = resolve_parakeet_live_backend(env={})

    assert resolution.state == "unavailable"
    assert resolution.implementation_id is None
    assert engine_registry.PARAKEET_NEMO_CUDA_EXPERIMENTAL_ENV in str(resolution.reason)


def test_live_backend_resolution_probes_nemo_only_when_experimental_enabled(
    monkeypatch,
) -> None:
    monkeypatch.setattr("mlx_ui.live_backend_runtime.sys.platform", "linux")

    called = {"value": False}

    def _probe(env):  # type: ignore[no-untyped-def]
        called["value"] = True
        assert env.get(engine_registry.PARAKEET_NEMO_CUDA_EXPERIMENTAL_ENV) == "1"
        return "CUDA runtime is not available."

    monkeypatch.setattr(
        "mlx_ui.live_backend_runtime._parakeet_nemo_cuda_live_unavailability_reason",
        _probe,
    )

    env = {engine_registry.PARAKEET_NEMO_CUDA_EXPERIMENTAL_ENV: "1"}
    resolution = resolve_parakeet_live_backend(env=env)

    assert called["value"] is True
    assert resolution.state == "unavailable"
    assert resolution.implementation_id == engine_registry.PARAKEET_NEMO_CUDA_BACKEND
    assert resolution.reason == "CUDA runtime is not available."


def test_parakeet_engine_options_keep_mlx_primary_on_apple_silicon(monkeypatch) -> None:
    monkeypatch.setattr(engine_registry.sys, "platform", "darwin")
    monkeypatch.setattr(engine_registry.platform, "machine", lambda: "arm64")
    monkeypatch.setenv(engine_registry.PARAKEET_NEMO_CUDA_EXPERIMENTAL_ENV, "1")
    monkeypatch.setattr(engine_registry, "is_parakeet_mlx_runtime_usable", lambda: False)

    options = build_registry_engine_options()
    parakeet = next(option for option in options if option["id"] == "parakeet_tdt_v3")

    assert parakeet["implementation_id"] == engine_registry.PARAKEET_MLX_BACKEND
