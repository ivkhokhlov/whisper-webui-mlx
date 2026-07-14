from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
import os
import signal
import subprocess
import sys
from typing import Any

CUDA_WATCHDOG_ENV = "PARAKEET_CUDA_WATCHDOG"
CUDA_PROBE_INTERVAL_ENV = "PARAKEET_CUDA_PROBE_INTERVAL"
CUDA_PROBE_TIMEOUT_ENV = "PARAKEET_CUDA_PROBE_TIMEOUT"
CUDA_PROBE_FAILURES_ENV = "PARAKEET_CUDA_PROBE_FAILURES"
CUDA_WATCHDOG_EXIT_CODE = 70


@dataclass(frozen=True)
class CudaWatchdogConfig:
    interval_seconds: float = 15.0
    timeout_seconds: float = 5.0
    failure_threshold: int = 2


def load_watchdog_config(
    env: Mapping[str, str] | None = None,
) -> CudaWatchdogConfig:
    if env is None:
        env = os.environ
    return CudaWatchdogConfig(
        interval_seconds=_positive_float(
            env.get(CUDA_PROBE_INTERVAL_ENV, "15"), CUDA_PROBE_INTERVAL_ENV
        ),
        timeout_seconds=_positive_float(
            env.get(CUDA_PROBE_TIMEOUT_ENV, "5"), CUDA_PROBE_TIMEOUT_ENV
        ),
        failure_threshold=_positive_int(
            env.get(CUDA_PROBE_FAILURES_ENV, "2"), CUDA_PROBE_FAILURES_ENV
        ),
    )


def watchdog_enabled(env: Mapping[str, str] | None = None) -> bool:
    if env is None:
        env = os.environ
    value = env.get(CUDA_WATCHDOG_ENV, "1").strip().lower()
    return value not in {"0", "false", "no", "off"}


def probe_cuda(
    timeout_seconds: float,
    *,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> tuple[bool, str]:
    try:
        result = runner(
            ["nvidia-smi", "-L"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )
    except FileNotFoundError:
        return False, "nvidia-smi is not available inside the container"
    except subprocess.TimeoutExpired:
        return False, f"nvidia-smi timed out after {timeout_seconds:g}s"
    except OSError as exc:
        return False, f"nvidia-smi could not start: {exc}"
    if result.returncode == 0:
        return True, ""
    detail = _compact_detail(result.stderr) or f"exit code {result.returncode}"
    return False, detail


def run_supervisor(
    command: Sequence[str],
    *,
    config: CudaWatchdogConfig,
    probe: Callable[[float], tuple[bool, str]] = probe_cuda,
    popen_factory: Callable[[Sequence[str]], Any] = subprocess.Popen,
    emit: Callable[[str], None] | None = None,
    install_signal_handlers: bool = True,
) -> int:
    emit = emit or _emit
    healthy, detail = probe(config.timeout_seconds)
    if not healthy:
        emit(
            "CUDA preflight failed; exiting so the container runtime can restore "
            f"GPU access: {detail}"
        )
        return CUDA_WATCHDOG_EXIT_CODE

    process = popen_factory(list(command))
    failures = 0
    with _forward_signals(process, enabled=install_signal_handlers):
        while True:
            try:
                status = process.wait(timeout=config.interval_seconds)
            except subprocess.TimeoutExpired:
                pass
            else:
                return _normalize_exit_status(status)

            healthy, detail = probe(config.timeout_seconds)
            if healthy:
                if failures:
                    emit("CUDA probe recovered before the failure threshold.")
                failures = 0
                continue

            failures += 1
            emit(f"CUDA probe failed ({failures}/{config.failure_threshold}): {detail}")
            if failures < config.failure_threshold:
                continue

            emit(
                "CUDA access is unavailable; stopping the app so the container "
                "restart policy can restore the NVIDIA device bindings."
            )
            _terminate_process(process)
            return CUDA_WATCHDOG_EXIT_CODE


def main() -> int:
    env = os.environ
    command = (
        sys.executable,
        "-m",
        "uvicorn",
        "mlx_ui.app:app",
        "--host",
        env.get("BIND_ADDRESS", "0.0.0.0"),
        "--port",
        env.get("PORT", "8000"),
    )
    if not watchdog_enabled(env):
        os.execv(sys.executable, command)
    try:
        config = load_watchdog_config(env)
    except ValueError as exc:
        _emit(str(exc))
        return 64
    return run_supervisor(command, config=config)


def _positive_float(raw: str, name: str) -> float:
    try:
        value = float(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be a positive number") from exc
    if value <= 0:
        raise ValueError(f"{name} must be a positive number")
    return value


def _positive_int(raw: str, name: str) -> int:
    try:
        value = int(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be a positive integer") from exc
    if value <= 0:
        raise ValueError(f"{name} must be a positive integer")
    return value


def _compact_detail(value: str | None) -> str:
    if not value:
        return ""
    return " ".join(value.split())[:300]


def _normalize_exit_status(status: int) -> int:
    if status >= 0:
        return status
    return 128 + abs(status)


def _terminate_process(process: Any) -> None:
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=20)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()


@contextmanager
def _forward_signals(process: Any, *, enabled: bool):
    if not enabled:
        yield
        return

    previous_handlers: dict[int, Any] = {}

    def forward(signum: int, _frame: object) -> None:
        if process.poll() is None:
            process.send_signal(signum)

    try:
        for signum in (signal.SIGTERM, signal.SIGINT):
            previous_handlers[signum] = signal.getsignal(signum)
            signal.signal(signum, forward)
        yield
    finally:
        for signum, handler in previous_handlers.items():
            signal.signal(signum, handler)


def _emit(message: str) -> None:
    print(f"spark-cuda-watchdog | {message}", file=sys.stderr, flush=True)


if __name__ == "__main__":
    raise SystemExit(main())
