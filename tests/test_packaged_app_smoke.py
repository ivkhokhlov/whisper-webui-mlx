from __future__ import annotations

import json
import os
from pathlib import Path
import plistlib
import socket
import subprocess
import sys
import time

import pytest


ROOT_DIR = Path(__file__).resolve().parents[1]
VALIDATOR = ROOT_DIR / "scripts" / "validate_macos_app_bundle.py"


def _write_plist(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(plistlib.dumps(payload, fmt=plistlib.FMT_XML))


def _make_executable(path: Path) -> None:
    path.chmod(path.stat().st_mode | 0o111)


def _make_minimal_app_bundle(tmp_path: Path) -> Path:
    app_path = tmp_path / "Test.app"
    contents = app_path / "Contents"
    info = contents / "Info.plist"
    launcher = contents / "MacOS" / "launcher"
    payload_dir = contents / "Resources" / "payload"

    _write_plist(
        info,
        {
            "CFBundleName": "Test",
            "CFBundleDisplayName": "Test",
            "CFBundleIdentifier": "com.example.test",
            "CFBundleVersion": "0.0.0",
            "CFBundleShortVersionString": "0.0.0",
            "CFBundlePackageType": "APPL",
            "CFBundleExecutable": "launcher",
            "LSMinimumSystemVersion": "12.0",
        },
    )

    launcher.parent.mkdir(parents=True, exist_ok=True)
    launcher.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
    _make_executable(launcher)

    (payload_dir / "mlx_ui" / "static").mkdir(parents=True, exist_ok=True)
    (payload_dir / "mlx_ui" / "templates").mkdir(parents=True, exist_ok=True)
    (payload_dir / "mlx_ui" / "app.py").write_text("# stub\n", encoding="utf-8")
    (payload_dir / "mlx_ui" / "static" / "favicon.ico").write_bytes(b"\0")
    (payload_dir / "mlx_ui" / "templates" / "index.html").write_text(
        "<html></html>", encoding="utf-8"
    )
    (payload_dir / "mlx_ui" / "templates" / "live.html").write_text(
        "<html></html>", encoding="utf-8"
    )

    runtime_dir = payload_dir / "runtime"
    (runtime_dir / "python").mkdir(parents=True, exist_ok=True)
    (runtime_dir / "venv").mkdir(parents=True, exist_ok=True)
    (runtime_dir / "embedded_runtime.json").write_text(
        json.dumps({"target": "macos-arm64"}) + "\n",
        encoding="utf-8",
    )

    build_dir = contents / "Resources" / "build"
    build_dir.mkdir(parents=True, exist_ok=True)
    (build_dir / "stage_manifest.json").write_text("{}", encoding="utf-8")

    return app_path


def test_validate_macos_app_bundle_accepts_minimal_structure(tmp_path: Path) -> None:
    app_path = _make_minimal_app_bundle(tmp_path)
    result = subprocess.run(
        [sys.executable, str(VALIDATOR), "--app", str(app_path)],
        capture_output=True,
        text=True,
        check=True,
    )
    assert "bundle_id" in result.stdout


def test_validate_macos_app_bundle_rejects_missing_launcher(tmp_path: Path) -> None:
    app_path = _make_minimal_app_bundle(tmp_path)
    (app_path / "Contents" / "MacOS" / "launcher").unlink()
    result = subprocess.run(
        [sys.executable, str(VALIDATOR), "--app", str(app_path)],
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "Missing launcher" in (result.stderr or result.stdout)


@pytest.mark.skipif(sys.platform != "darwin", reason="macOS-only launch smoke test.")
def test_packaged_app_launcher_opt_in_smoke(tmp_path: Path, monkeypatch) -> None:
    app_path_env = os.getenv("MLX_UI_SMOKE_APP_PATH", "").strip()
    if not app_path_env:
        pytest.skip(
            "Set MLX_UI_SMOKE_APP_PATH=/path/to/App.app to run this smoke test."
        )

    app_path = Path(app_path_env)
    if not app_path.is_dir():
        pytest.skip(f"App bundle not found: {app_path}")

    # Avoid breaking local developer machines: skip if port is busy.
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        if sock.connect_ex(("127.0.0.1", 8000)) == 0:
            pytest.skip("Port 8000 is already in use.")

    subprocess.run(
        [sys.executable, str(VALIDATOR), "--app", str(app_path)],
        capture_output=True,
        text=True,
        check=True,
    )

    fakebin = tmp_path / "fakebin"
    fakebin.mkdir(parents=True, exist_ok=True)
    (fakebin / "open").write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
    _make_executable(fakebin / "open")
    (fakebin / "osascript").write_text(
        "#!/usr/bin/env bash\nexit 0\n", encoding="utf-8"
    )
    _make_executable(fakebin / "osascript")

    home_dir = tmp_path / "home"
    home_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("HOME", str(home_dir))
    monkeypatch.setenv("DISABLE_UPDATE_CHECK", "1")
    monkeypatch.setenv("PATH", f"{fakebin}:{os.environ.get('PATH', '')}")

    launcher = app_path / "Contents" / "MacOS" / "launcher"
    proc = subprocess.Popen(
        [str(launcher)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        env=dict(os.environ),
    )
    try:
        deadline = time.time() + 10.0
        while time.time() < deadline:
            try:
                import urllib.request

                with urllib.request.urlopen(
                    "http://127.0.0.1:8000/api/state", timeout=0.5
                ) as resp:
                    if resp.status == 200:
                        break
            except Exception:
                time.sleep(0.2)
        else:
            pytest.fail("Server did not become ready within 10 seconds.")
    finally:
        proc.terminate()
        proc.wait(timeout=5)
