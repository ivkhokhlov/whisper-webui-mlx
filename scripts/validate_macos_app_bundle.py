#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import plistlib
import stat
import sys


def _fail(message: str) -> None:
    raise ValueError(message)


def _is_executable(path: Path) -> bool:
    try:
        mode = path.stat().st_mode
    except OSError:
        return False
    if mode & stat.S_IXUSR:
        return True
    return os.access(path, os.X_OK)


def validate_app_bundle(app_path: Path) -> dict[str, object]:
    app_path = Path(app_path)
    if not app_path.exists():
        _fail(f"App bundle not found: {app_path}")
    if not app_path.is_dir():
        _fail(f"App bundle path is not a directory: {app_path}")
    if app_path.suffix != ".app":
        _fail(f"Expected a .app bundle directory, got: {app_path.name}")

    contents_dir = app_path / "Contents"
    info_plist_path = contents_dir / "Info.plist"
    if not info_plist_path.is_file():
        _fail(f"Missing Info.plist: {info_plist_path}")

    try:
        info = plistlib.loads(info_plist_path.read_bytes())
    except Exception as exc:  # pragma: no cover
        _fail(f"Info.plist is not valid plist XML: {exc.__class__.__name__}")
        raise

    required_keys = (
        "CFBundleIdentifier",
        "CFBundleExecutable",
        "CFBundleName",
        "CFBundleVersion",
        "CFBundleShortVersionString",
        "LSMinimumSystemVersion",
    )
    for key in required_keys:
        value = info.get(key)
        if not isinstance(value, str) or not value.strip():
            _fail(f"Info.plist missing required string key: {key}")

    executable = str(info["CFBundleExecutable"]).strip()
    macos_dir = contents_dir / "MacOS"
    launcher_path = macos_dir / executable
    if not launcher_path.is_file():
        _fail(f"Missing launcher: {launcher_path}")
    if not _is_executable(launcher_path):
        _fail(f"Launcher is not executable: {launcher_path}")

    resources_dir = contents_dir / "Resources"
    payload_dir = resources_dir / "payload"
    if not payload_dir.is_dir():
        _fail(f"Missing staged payload: {payload_dir}")

    mlx_ui_dir = payload_dir / "mlx_ui"
    if not mlx_ui_dir.is_dir():
        _fail(f"Missing Python app package: {mlx_ui_dir}")
    if not (mlx_ui_dir / "app.py").is_file():
        _fail("Missing mlx_ui/app.py inside payload.")

    templates_dir = mlx_ui_dir / "templates"
    static_dir = mlx_ui_dir / "static"
    if not (templates_dir / "index.html").is_file():
        _fail("Missing templates/index.html inside payload.")
    if not (templates_dir / "live.html").is_file():
        _fail("Missing templates/live.html inside payload.")
    if not static_dir.is_dir():
        _fail("Missing static/ directory inside payload.")
    if not (static_dir / "favicon.ico").is_file():
        _fail("Missing static/favicon.ico inside payload.")

    runtime_dir = payload_dir / "runtime"
    python_dir = runtime_dir / "python"
    venv_dir = runtime_dir / "venv"
    if not python_dir.is_dir():
        _fail("Missing embedded python prefix at payload/runtime/python.")
    if not venv_dir.is_dir():
        _fail("Missing embedded venv at payload/runtime/venv.")

    embedded_runtime = runtime_dir / "embedded_runtime.json"
    if not embedded_runtime.is_file():
        _fail("Missing payload/runtime/embedded_runtime.json.")
    try:
        embedded_payload = json.loads(embedded_runtime.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        _fail("payload/runtime/embedded_runtime.json is not valid JSON.")
    if not isinstance(embedded_payload, dict) or "target" not in embedded_payload:
        _fail("payload/runtime/embedded_runtime.json is missing the expected keys.")

    build_dir = resources_dir / "build"
    stage_manifest = build_dir / "stage_manifest.json"
    if not stage_manifest.is_file():
        _fail(f"Missing build metadata: {stage_manifest}")

    return {
        "app_path": str(app_path),
        "bundle_id": str(info["CFBundleIdentifier"]),
        "executable": executable,
        "payload_dir": str(payload_dir),
        "launcher_path": str(launcher_path),
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate a packaged macOS .app bundle structure (fast, offline)."
    )
    parser.add_argument(
        "--app",
        type=Path,
        required=True,
        help="Path to the .app bundle to validate.",
    )
    args = parser.parse_args()

    try:
        result = validate_app_bundle(Path(args.app))
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
