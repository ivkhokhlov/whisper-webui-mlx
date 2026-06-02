import sys
from types import SimpleNamespace

from mlx_ui.engines import parakeet_nemo_cuda_live_runtime_experimental as runtime


def test_probe_reports_streaming_spec_inspection_errors(monkeypatch) -> None:
    monkeypatch.setattr(runtime.sys, "platform", "linux")
    monkeypatch.setitem(
        sys.modules,
        "torch",
        SimpleNamespace(cuda=SimpleNamespace(is_available=lambda: True)),
    )

    def fake_find_spec(name):  # type: ignore[no-untyped-def]
        if name == "nemo.collections.asr.parts.utils.rnnt_utils":
            raise AttributeError("partially initialized rnnt_utils")
        return object()

    monkeypatch.setattr(runtime.importlib.util, "find_spec", fake_find_spec)

    reason = runtime.parakeet_nemo_cuda_live_runtime_unavailability_reason()

    assert reason == (
        "NVIDIA NeMo streaming utilities could not be inspected: "
        "AttributeError: partially initialized rnnt_utils"
    )
