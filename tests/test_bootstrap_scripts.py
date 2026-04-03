import json
from pathlib import Path
import subprocess
import sys
import tomllib


ROOT_DIR = Path(__file__).resolve().parents[1]


def _run_help(relative_path: str) -> str:
    result = subprocess.run(
        ["bash", str(ROOT_DIR / relative_path), "--help"],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout


def test_setup_and_run_help_describes_engine_matrix() -> None:
    output = _run_help("scripts/setup_and_run.sh")

    assert "macOS arm64   -> Whisper MLX" in output
    assert "macOS x86_64  -> Whisper CPU" in output
    assert "--with-cohere" in output
    assert "--with-whisper-cpu" in output
    assert "--with-parakeet-mlx" in output
    assert "WHISPER_WEBUI_WITH_PARAKEET_MLX=1" in output
    assert "Parakeet MLX is a local Apple Silicon engine" in output
    assert "Legacy Parakeet NeMo/CUDA" in output


def test_install_help_describes_architecture_aware_bootstrap() -> None:
    output = _run_help("scripts/install.sh")

    assert "macOS arm64: installs Whisper MLX" in output
    assert "macOS Intel: installs Whisper CPU" in output
    assert "--with-cohere" in output
    assert "--with-parakeet-mlx" in output
    assert "Apple Silicon-only Parakeet MLX dependency profile" in output
    assert "Legacy Parakeet NeMo/CUDA" in output


def test_build_macos_app_help_mentions_apple_silicon_bundle() -> None:
    output = _run_help("scripts/build_macos_app.sh")

    assert "self-contained macOS .app bundle" in output
    assert "Dev bootstrap" in output
    assert "macos-arm64" in output
    assert "macos-intel" in output
    assert "--with-cohere" in output


def test_build_macos_dmg_help_mentions_drag_install() -> None:
    output = _run_help("scripts/build_macos_dmg.sh")

    assert "drag-to-Applications DMG" in output
    assert "macos-arm64" in output
    assert "macos-intel" in output
    assert "--app" in output


def test_sign_macos_app_help_mentions_identity_and_dry_run() -> None:
    output = _run_help("scripts/sign_macos_app.sh")

    assert "Sign a packaged macOS .app bundle" in output
    assert "--identity" in output
    assert "MACOS_SIGNING_IDENTITY" in output
    assert "--dry-run" in output


def test_notarize_macos_artifact_help_mentions_notarytool_and_stapler() -> None:
    output = _run_help("scripts/notarize_macos_artifact.sh")

    assert "notarytool submit" in output
    assert "stapler staple" in output
    assert "--keychain-profile" in output
    assert "--dry-run" in output


def test_verify_macos_artifact_help_mentions_gatekeeper_checks() -> None:
    output = _run_help("scripts/verify_macos_artifact.sh")

    assert "Gatekeeper readiness" in output
    assert "syspolicy_check distribution" in output
    assert "spctl --assess" in output
    assert "stapler validate" in output


def test_build_macos_app_builder_uses_staging_and_embedded_runtime() -> None:
    source = (ROOT_DIR / "scripts" / "build_macos_app.sh").read_text(encoding="utf-8")

    assert "stage_release_payload.py" in source
    assert "build_embedded_runtime.py" in source
    assert "uvicorn mlx_ui.app:app" in source


def test_packaged_launcher_is_one_click_and_idempotent() -> None:
    source = (ROOT_DIR / "scripts" / "build_macos_app.sh").read_text(encoding="utf-8")

    assert "/api/state" in source
    assert "server.pid" in source
    assert "server_responding" in source
    assert "wait_for_server" in source
    assert "open_browser" in source
    assert "fatal_dialog" in source


def test_run_sh_forwards_optional_bootstrap_flags(tmp_path: Path) -> None:
    run_copy = tmp_path / "run.sh"
    run_copy.write_text((ROOT_DIR / "run.sh").read_text(encoding="utf-8"), "utf-8")
    run_copy.chmod(0o755)

    forwarded_args = tmp_path / "forwarded_args.txt"
    setup_script = tmp_path / "scripts" / "setup_and_run.sh"
    setup_script.parent.mkdir(parents=True, exist_ok=True)
    setup_script.write_text(
        (
            "#!/usr/bin/env bash\n"
            "set -euo pipefail\n"
            f"printf '%s\\n' \"$@\" > {str(forwarded_args)!r}\n"
        ),
        encoding="utf-8",
    )
    setup_script.chmod(0o755)

    subprocess.run(
        ["bash", str(run_copy), "--with-cohere", "--with-whisper-cpu"],
        capture_output=True,
        text=True,
        check=True,
    )

    assert forwarded_args.read_text(encoding="utf-8").splitlines() == [
        "--with-cohere",
        "--with-whisper-cpu",
    ]


def test_pyproject_declares_optional_engine_dependency_groups() -> None:
    pyproject = tomllib.loads((ROOT_DIR / "pyproject.toml").read_text("utf-8"))
    groups = pyproject["tool"]["poetry"]["group"]

    assert "whisper_mlx" in groups
    assert "whisper_cpu" in groups
    assert "cohere" in groups
    assert "whisper-turbo-mlx" in groups["whisper_mlx"]["dependencies"]
    assert "openai-whisper" in groups["whisper_cpu"]["dependencies"]
    assert "cohere" in groups["cohere"]["dependencies"]


def test_requirements_profiles_keep_optional_engines_explicit() -> None:
    base = (ROOT_DIR / "requirements.txt").read_text(encoding="utf-8")
    whisper_mlx = (ROOT_DIR / "requirements-whisper-mlx.txt").read_text(
        encoding="utf-8"
    )
    whisper_cpu = (ROOT_DIR / "requirements-whisper-cpu.txt").read_text(
        encoding="utf-8"
    )
    parakeet_mlx = (ROOT_DIR / "requirements-parakeet-mlx.txt").read_text(
        encoding="utf-8"
    )
    cohere = (ROOT_DIR / "requirements-cohere.txt").read_text(encoding="utf-8")

    assert "requirements-whisper-mlx.txt" in base
    assert "requirements-whisper-cpu.txt" in base
    assert "requirements-parakeet-mlx.txt" in base
    assert "requirements-cohere.txt" in base
    assert "whisper-turbo-mlx" not in base
    assert "openai-whisper" not in base
    assert "safetensors" not in base
    assert "huggingface-hub" not in base
    assert "cohere>=" not in base
    assert "whisper-turbo-mlx" in whisper_mlx
    assert "openai-whisper" in whisper_cpu
    assert "parakeet-mlx" in parakeet_mlx
    assert "huggingface-hub" in parakeet_mlx
    assert "mlx" in parakeet_mlx
    assert "safetensors" in parakeet_mlx
    assert "cohere" in cohere


def test_macos_release_targets_contract_is_explicit() -> None:
    contract_path = ROOT_DIR / "docs" / "release" / "macos_targets.toml"
    payload = tomllib.loads(contract_path.read_text(encoding="utf-8"))

    macos = payload["macos"]
    assert macos["bundle_identifier_base"] == "com.whisperwebui.mlx"
    assert macos["artifact_prefix"] == "whisper-webui-mlx"

    targets = macos["targets"]
    assert set(targets.keys()) == {"macos-arm64", "macos-intel"}

    arm64 = targets["macos-arm64"]
    assert arm64["arch"] == "arm64"
    assert arm64["minimum_macos"] == "12.0"
    assert arm64["default_local_engine"] == "whisper_mlx"
    assert arm64["optional_engines"] == ["parakeet_tdt_v3", "cohere"]
    assert arm64["bundle_identifier_suffix"] == ""
    assert arm64["artifact_name"].endswith("-macos-arm64.zip")
    assert arm64["dmg_artifact_name"].endswith("-macos-arm64.dmg")

    intel = targets["macos-intel"]
    assert intel["arch"] == "x86_64"
    assert intel["minimum_macos"] == "12.0"
    assert intel["default_local_engine"] == "whisper_cpu"
    assert intel["optional_engines"] == ["cohere"]
    assert intel["bundle_identifier_suffix"] == ".cpu"
    assert intel["artifact_name"].endswith("-macos-intel.zip")
    assert intel["dmg_artifact_name"].endswith("-macos-intel.dmg")


def test_stage_release_payload_creates_clean_allowlisted_tree(tmp_path: Path) -> None:
    stage_dir = tmp_path / "stage"
    script = ROOT_DIR / "scripts" / "stage_release_payload.py"

    subprocess.run(
        [
            sys.executable,
            str(script),
            "--target",
            "macos-arm64",
            "--out",
            str(stage_dir),
            "--clean",
        ],
        capture_output=True,
        text=True,
        check=True,
    )

    payload = stage_dir / "payload"
    assert (stage_dir / "stage_manifest.json").is_file()
    assert (payload / "mlx_ui" / "app.py").is_file()
    assert (payload / "mlx_ui" / "templates" / "index.html").is_file()
    assert (payload / "mlx_ui" / "static").is_dir()
    assert (payload / "pyproject.toml").is_file()
    assert (payload / "requirements-parakeet-mlx.txt").is_file()
    assert (payload / "docs" / "release" / "macos_targets.toml").is_file()

    assert not (payload / "tests").exists()
    assert not (payload / "data").exists()
    assert not (payload / "dist").exists()
    assert list(payload.rglob("__pycache__")) == []


def _run_json(script: Path, args: list[str]) -> dict[str, object]:
    result = subprocess.run(
        [sys.executable, str(script), *args],
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(result.stdout)


def test_build_embedded_runtime_dry_run_is_target_aware(tmp_path: Path) -> None:
    script = ROOT_DIR / "scripts" / "build_embedded_runtime.py"
    stage_dir = tmp_path / "stage"

    arm64 = _run_json(
        script,
        ["--stage", str(stage_dir), "--target", "macos-arm64", "--dry-run"],
    )
    assert arm64["engine_profile"] == "whisper_mlx"
    assert arm64["requirements"] == [
        "requirements.txt",
        "requirements-whisper-mlx.txt",
        "requirements-parakeet-mlx.txt",
    ]

    arm64_with_cohere = _run_json(
        script,
        [
            "--stage",
            str(stage_dir),
            "--target",
            "macos-arm64",
            "--with-cohere",
            "--dry-run",
        ],
    )
    assert arm64_with_cohere["requirements"] == [
        "requirements.txt",
        "requirements-whisper-mlx.txt",
        "requirements-parakeet-mlx.txt",
        "requirements-cohere.txt",
    ]

    intel = _run_json(
        script,
        ["--stage", str(stage_dir), "--target", "macos-intel", "--dry-run"],
    )
    assert intel["engine_profile"] == "whisper_cpu"
    assert intel["requirements"] == [
        "requirements.txt",
        "requirements-whisper-cpu.txt",
    ]

    intel_with_cohere = _run_json(
        script,
        [
            "--stage",
            str(stage_dir),
            "--target",
            "macos-intel",
            "--with-cohere",
            "--dry-run",
        ],
    )
    assert intel_with_cohere["requirements"] == [
        "requirements.txt",
        "requirements-whisper-cpu.txt",
        "requirements-cohere.txt",
    ]
