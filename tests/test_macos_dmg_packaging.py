from __future__ import annotations

import os
from pathlib import Path
import plistlib
import shutil
import subprocess
import sys
import tomllib

import pytest


ROOT_DIR = Path(__file__).resolve().parents[1]


def _make_stub_app_bundle(tmp_path: Path) -> Path:
    app_path = tmp_path / "Test.app"
    contents_dir = app_path / "Contents"
    macos_dir = contents_dir / "MacOS"
    macos_dir.mkdir(parents=True, exist_ok=True)

    (macos_dir / "launcher").write_text(
        "#!/usr/bin/env bash\nexit 0\n", encoding="utf-8"
    )
    (macos_dir / "launcher").chmod(0o755)

    resources_dir = contents_dir / "Resources"
    payload_dir = resources_dir / "payload"
    build_dir = resources_dir / "build"

    (payload_dir / "mlx_ui" / "templates").mkdir(parents=True, exist_ok=True)
    (payload_dir / "mlx_ui" / "static").mkdir(parents=True, exist_ok=True)
    (payload_dir / "mlx_ui" / "app.py").write_text("# stub\n", encoding="utf-8")
    (payload_dir / "mlx_ui" / "templates" / "index.html").write_text(
        "<html></html>", encoding="utf-8"
    )
    (payload_dir / "mlx_ui" / "templates" / "live.html").write_text(
        "<html></html>", encoding="utf-8"
    )
    (payload_dir / "mlx_ui" / "static" / "favicon.ico").write_bytes(b"\0")

    runtime_dir = payload_dir / "runtime"
    (runtime_dir / "python").mkdir(parents=True, exist_ok=True)
    (runtime_dir / "venv").mkdir(parents=True, exist_ok=True)
    (runtime_dir / "embedded_runtime.json").write_text(
        '{"target":"macos-arm64"}\n', encoding="utf-8"
    )

    build_dir.mkdir(parents=True, exist_ok=True)
    (build_dir / "stage_manifest.json").write_text("{}", encoding="utf-8")

    info_plist = {
        "CFBundleName": "Test",
        "CFBundleDisplayName": "Test",
        "CFBundleIdentifier": "com.example.test",
        "CFBundleVersion": "0.0.0",
        "CFBundleShortVersionString": "0.0.0",
        "CFBundlePackageType": "APPL",
        "CFBundleExecutable": "launcher",
        "LSMinimumSystemVersion": "12.0",
    }
    (contents_dir / "Info.plist").write_bytes(
        plistlib.dumps(info_plist, fmt=plistlib.FMT_XML)
    )
    return app_path


def _attach_dmg(dmg_path: Path) -> tuple[str, str]:
    result = subprocess.run(
        ["hdiutil", "attach", "-nobrowse", "-readonly", "-plist", str(dmg_path)],
        capture_output=True,
        check=True,
    )
    payload = plistlib.loads(result.stdout)
    for entity in payload.get("system-entities", []):
        mount_point = entity.get("mount-point")
        dev_entry = entity.get("dev-entry")
        if mount_point and dev_entry:
            return mount_point, dev_entry
    raise RuntimeError("Unable to find mount-point in hdiutil attach output.")


@pytest.mark.skipif(sys.platform != "darwin", reason="macOS-only DMG packaging test.")
def test_build_macos_dmg_creates_drag_install_layout(tmp_path: Path) -> None:
    if not os.getenv("MLX_UI_SMOKE_DMG", "").strip():
        pytest.skip("Set MLX_UI_SMOKE_DMG=1 to run the DMG packaging smoke test.")

    if shutil.which("hdiutil") is None:
        pytest.skip("hdiutil not available.")

    app_path = _make_stub_app_bundle(tmp_path)
    out_dir = tmp_path / "out"
    out_dir.mkdir(parents=True, exist_ok=True)
    stage_dir = tmp_path / "stage"

    script = ROOT_DIR / "scripts" / "build_macos_dmg.sh"
    subprocess.run(
        [
            "bash",
            str(script),
            "--target",
            "macos-arm64",
            "--app",
            str(app_path),
            "--out",
            str(out_dir),
            "--stage",
            str(stage_dir),
            "--force",
        ],
        capture_output=True,
        text=True,
        check=True,
    )

    contract_path = ROOT_DIR / "docs" / "release" / "macos_targets.toml"
    contract = tomllib.loads(contract_path.read_text(encoding="utf-8"))
    dmg_tmpl = contract["macos"]["targets"]["macos-arm64"]["dmg_artifact_name"]

    pyproject = tomllib.loads((ROOT_DIR / "pyproject.toml").read_text("utf-8"))
    version = pyproject["tool"]["poetry"]["version"]

    dmg_path = out_dir / dmg_tmpl.replace("{version}", version)
    assert dmg_path.is_file()

    mount_point = ""
    dev_entry = ""
    try:
        mount_point, dev_entry = _attach_dmg(dmg_path)
        mount_dir = Path(mount_point)
        assert (mount_dir / app_path.name).is_dir()

        applications_link = mount_dir / "Applications"
        assert applications_link.is_symlink()
        assert os.readlink(applications_link) == "/Applications"
    finally:
        if dev_entry:
            subprocess.run(
                ["hdiutil", "detach", dev_entry, "-force"],
                capture_output=True,
                text=True,
            )
