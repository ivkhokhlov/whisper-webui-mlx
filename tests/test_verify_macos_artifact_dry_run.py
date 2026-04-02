from __future__ import annotations

from pathlib import Path
import subprocess


ROOT_DIR = Path(__file__).resolve().parents[1]


def test_verify_macos_artifact_dry_run_accepts_explicit_path(tmp_path: Path) -> None:
    artifact = tmp_path / "artifact.dmg"
    artifact.write_bytes(b"stub")

    script = ROOT_DIR / "scripts" / "verify_macos_artifact.sh"
    result = subprocess.run(
        ["bash", str(script), "--artifact", str(artifact), "--dry-run"],
        capture_output=True,
        text=True,
        check=True,
    )

    assert "Dry-run plan" in result.stdout
    assert f"Artifact: {artifact}" in result.stdout
    assert "syspolicy_check distribution" in result.stdout


def test_verify_macos_artifact_dry_run_resolves_contract_paths() -> None:
    script = ROOT_DIR / "scripts" / "verify_macos_artifact.sh"
    result = subprocess.run(
        ["bash", str(script), "--target", "macos-arm64", "--type", "dmg", "--dry-run"],
        capture_output=True,
        text=True,
        check=True,
    )

    artifact_line = ""
    for line in result.stdout.splitlines():
        if line.startswith("Artifact: "):
            artifact_line = line
            break

    assert artifact_line
    assert "macos-arm64" in artifact_line
    assert artifact_line.endswith(".dmg")
