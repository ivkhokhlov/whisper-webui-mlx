from pathlib import Path
import subprocess
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
    assert "Parakeet is not installed here" in output


def test_install_help_describes_architecture_aware_bootstrap() -> None:
    output = _run_help("scripts/install.sh")

    assert "macOS arm64: installs Whisper MLX" in output
    assert "macOS Intel: installs Whisper CPU" in output
    assert "--with-cohere" in output
    assert "Parakeet is not installed by the macOS bootstrap path" in output


def test_build_macos_app_help_mentions_apple_silicon_bundle() -> None:
    output = _run_help("scripts/build_macos_app.sh")

    assert "Apple Silicon macOS app bundle" in output
    assert "MLX-first local path" in output


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
    cohere = (ROOT_DIR / "requirements-cohere.txt").read_text(encoding="utf-8")

    assert "requirements-whisper-mlx.txt" in base
    assert "requirements-whisper-cpu.txt" in base
    assert "requirements-cohere.txt" in base
    assert "whisper-turbo-mlx" not in base
    assert "openai-whisper" not in base
    assert "cohere>=" not in base
    assert "whisper-turbo-mlx" in whisper_mlx
    assert "openai-whisper" in whisper_cpu
    assert "cohere" in cohere
