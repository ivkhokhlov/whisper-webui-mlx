from __future__ import annotations

import json
from pathlib import Path
import plistlib
import shutil
import subprocess
import sys

import pytest


ROOT_DIR = Path(__file__).resolve().parents[1]


def _write_plist(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(plistlib.dumps(payload, fmt=plistlib.FMT_XML))


def _make_executable(path: Path) -> None:
    path.chmod(path.stat().st_mode | 0o111)


def _make_minimal_packaged_app_bundle(tmp_path: Path) -> Path:
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


@pytest.mark.skipif(sys.platform != "darwin", reason="macOS-only signing script test.")
def test_sign_macos_app_dry_run_lists_expected_targets(tmp_path: Path) -> None:
    if shutil.which("codesign") is None:
        pytest.skip("codesign not available.")

    app_path = _make_minimal_packaged_app_bundle(tmp_path)

    macho_src = Path("/usr/bin/true")
    if not macho_src.is_file():
        pytest.skip("Missing /usr/bin/true on this system.")

    (
        app_path / "Contents" / "Resources" / "payload" / "runtime" / "python" / "bin"
    ).mkdir(parents=True, exist_ok=True)
    python3_path = (
        app_path
        / "Contents"
        / "Resources"
        / "payload"
        / "runtime"
        / "python"
        / "bin"
        / "python3"
    )
    python3_path.write_bytes(macho_src.read_bytes())
    _make_executable(python3_path)

    (
        app_path / "Contents" / "Resources" / "payload" / "runtime" / "venv" / "bin"
    ).mkdir(parents=True, exist_ok=True)
    venv_python3 = (
        app_path
        / "Contents"
        / "Resources"
        / "payload"
        / "runtime"
        / "venv"
        / "bin"
        / "python3"
    )
    venv_python3.write_bytes(macho_src.read_bytes())
    _make_executable(venv_python3)

    so_path = (
        app_path
        / "Contents"
        / "Resources"
        / "payload"
        / "runtime"
        / "venv"
        / "lib"
        / "python3.12"
        / "site-packages"
        / "_stub.so"
    )
    so_path.parent.mkdir(parents=True, exist_ok=True)
    so_path.write_bytes(macho_src.read_bytes())

    script = ROOT_DIR / "scripts" / "sign_macos_app.sh"
    result = subprocess.run(
        ["bash", str(script), "--app", str(app_path), "--dry-run"],
        capture_output=True,
        text=True,
        check=True,
    )

    assert str(app_path / "Contents" / "MacOS" / "launcher") in result.stdout
    assert str(python3_path) in result.stdout
    assert str(venv_python3) in result.stdout
    assert str(so_path) in result.stdout


@pytest.mark.skipif(sys.platform != "darwin", reason="macOS-only signing script test.")
def test_sign_macos_app_requires_identity_without_dry_run(tmp_path: Path) -> None:
    if shutil.which("codesign") is None:
        pytest.skip("codesign not available.")

    app_path = _make_minimal_packaged_app_bundle(tmp_path)
    script = ROOT_DIR / "scripts" / "sign_macos_app.sh"
    result = subprocess.run(
        ["bash", str(script), "--app", str(app_path)],
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "Missing signing identity" in (result.stderr or result.stdout)
