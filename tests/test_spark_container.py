from pathlib import Path
import subprocess

import pytest

from mlx_ui.spark_container import (
    CUDA_WATCHDOG_EXIT_CODE,
    CudaWatchdogConfig,
    load_watchdog_config,
    probe_cuda,
    run_supervisor,
)


ROOT_DIR = Path(__file__).resolve().parents[1]


class FakeProcess:
    def __init__(self) -> None:
        self.terminated = False
        self.killed = False

    def wait(self, timeout=None):  # type: ignore[no-untyped-def]
        if self.terminated or self.killed:
            return 0
        raise subprocess.TimeoutExpired(["fake-app"], timeout)

    def poll(self):  # type: ignore[no-untyped-def]
        return 0 if self.terminated or self.killed else None

    def terminate(self) -> None:
        self.terminated = True

    def kill(self) -> None:
        self.killed = True


def test_probe_cuda_reports_nvml_failure() -> None:
    def runner(*_args, **_kwargs):  # type: ignore[no-untyped-def]
        return subprocess.CompletedProcess(
            ["nvidia-smi", "-L"],
            1,
            "",
            "Failed to initialize NVML: Unknown Error\n",
        )

    healthy, detail = probe_cuda(5, runner=runner)

    assert healthy is False
    assert detail == "Failed to initialize NVML: Unknown Error"


def test_supervisor_exits_before_starting_app_when_cuda_is_missing() -> None:
    started: list[list[str]] = []

    def popen(command):  # type: ignore[no-untyped-def]
        started.append(list(command))
        return FakeProcess()

    messages: list[str] = []
    status = run_supervisor(
        ["fake-app"],
        config=CudaWatchdogConfig(),
        probe=lambda _timeout: (False, "NVML unknown error"),
        popen_factory=popen,
        emit=messages.append,
        install_signal_handlers=False,
    )

    assert status == CUDA_WATCHDOG_EXIT_CODE
    assert started == []
    assert "CUDA preflight failed" in messages[0]


def test_supervisor_stops_app_after_consecutive_cuda_failures() -> None:
    process = FakeProcess()
    probe_results = iter(
        [
            (True, ""),
            (False, "first failure"),
            (True, ""),
            (False, "second failure"),
            (False, "third failure"),
        ]
    )
    messages: list[str] = []

    status = run_supervisor(
        ["fake-app"],
        config=CudaWatchdogConfig(
            interval_seconds=0.01,
            timeout_seconds=0.01,
            failure_threshold=2,
        ),
        probe=lambda _timeout: next(probe_results),
        popen_factory=lambda _command: process,
        emit=messages.append,
        install_signal_handlers=False,
    )

    assert status == CUDA_WATCHDOG_EXIT_CODE
    assert process.terminated is True
    assert "recovered" in messages[1]
    assert "restart policy" in messages[-1]


def test_watchdog_config_rejects_non_positive_values() -> None:
    with pytest.raises(ValueError, match="positive number"):
        load_watchdog_config({"PARAKEET_CUDA_PROBE_INTERVAL": "0"})


def test_spark_image_uses_cuda_supervisor_and_gpu_healthcheck() -> None:
    dockerfile = (ROOT_DIR / "Dockerfile.spark").read_text(encoding="utf-8")
    cpu_dockerfile = (ROOT_DIR / "Dockerfile").read_text(encoding="utf-8")
    launcher = (ROOT_DIR / "docker-run-spark.sh").read_text(encoding="utf-8")

    assert "COPY pyproject.toml ./" in dockerfile
    assert "COPY pyproject.toml ./" in cpu_dockerfile
    assert 'CMD ["python3", "-m", "mlx_ui.spark_container"]' in dockerfile
    assert "HEALTHCHECK" in dockerfile
    assert "nvidia-smi -L" in dockerfile
    assert "PARAKEET_CUDA_OOM_CPU_FALLBACK=1" in dockerfile
    assert "gpu_device_args" in launcher
    assert "nvidia-smi -L" in launcher
