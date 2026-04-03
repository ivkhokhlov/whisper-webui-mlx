#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil

import tomllib


REPO_DIR = Path(__file__).resolve().parents[1]
CONTRACT_PATH = REPO_DIR / "docs" / "release" / "macos_targets.toml"


def _load_contract(path: Path) -> dict[str, object]:
    return tomllib.loads(path.read_text(encoding="utf-8"))


def _read_version(pyproject_path: Path) -> str:
    data = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))
    version = data.get("tool", {}).get("poetry", {}).get("version")
    if not isinstance(version, str) or not version.strip():
        raise ValueError("pyproject.toml is missing tool.poetry.version")
    return version.strip()


def _bundle_id_for_target(contract: dict[str, object], target: str) -> str:
    macos = contract.get("macos")
    if not isinstance(macos, dict):
        raise ValueError("Contract missing [macos] table.")
    base = macos.get("bundle_identifier_base")
    targets = macos.get("targets")
    if not isinstance(base, str) or not base.strip():
        raise ValueError("Contract missing macos.bundle_identifier_base.")
    if not isinstance(targets, dict):
        raise ValueError("Contract missing [macos.targets] table.")
    target_payload = targets.get(target)
    if not isinstance(target_payload, dict):
        raise ValueError(f"Contract missing macos.targets.{target}.")
    suffix = target_payload.get("bundle_identifier_suffix", "")
    if suffix is None:
        suffix = ""
    if not isinstance(suffix, str):
        raise ValueError("Contract has invalid bundle_identifier_suffix value.")
    return f"{base}{suffix}"


def _ignore_patterns() -> shutil.IgnorePattern:
    return shutil.ignore_patterns(
        "__pycache__",
        "*.pyc",
        "*.pyo",
        "*.pyd",
        ".DS_Store",
        ".pytest_cache",
        ".ruff_cache",
    )


def _copy_file(src: Path, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dest)


def _copy_dir(src: Path, dest: Path) -> None:
    shutil.copytree(src, dest, ignore=_ignore_patterns(), dirs_exist_ok=True)


def _write_manifest(
    stage_dir: Path,
    *,
    payload_dir: Path,
    target: str,
    version: str,
    bundle_id: str,
) -> None:
    files: list[str] = []
    for path in payload_dir.rglob("*"):
        if path.is_file():
            files.append(str(path.relative_to(payload_dir)))
    files.sort()
    manifest = {
        "target": target,
        "version": version,
        "bundle_id": bundle_id,
        "payload_dir": "payload",
        "files": files,
    }
    (stage_dir / "stage_manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def build_stage(
    stage_dir: Path,
    *,
    target: str,
    clean: bool,
) -> Path:
    contract = _load_contract(CONTRACT_PATH)
    version = _read_version(REPO_DIR / "pyproject.toml")
    bundle_id = _bundle_id_for_target(contract, target)

    if stage_dir.exists():
        if not clean:
            raise FileExistsError(
                f"Stage directory already exists: {stage_dir} (pass --clean to recreate)"
            )
        shutil.rmtree(stage_dir)

    payload_dir = stage_dir / "payload"
    payload_dir.mkdir(parents=True, exist_ok=True)

    _copy_dir(REPO_DIR / "mlx_ui", payload_dir / "mlx_ui")
    _copy_dir(REPO_DIR / "docs" / "release", payload_dir / "docs" / "release")

    for filename in (
        "pyproject.toml",
        "requirements.txt",
        "requirements-whisper-mlx.txt",
        "requirements-whisper-cpu.txt",
        "requirements-parakeet-mlx.txt",
        "requirements-cohere.txt",
        "mel_filters.npz",
    ):
        src = REPO_DIR / filename
        if src.exists():
            _copy_file(src, payload_dir / filename)

    _write_manifest(
        stage_dir,
        payload_dir=payload_dir,
        target=target,
        version=version,
        bundle_id=bundle_id,
    )
    return payload_dir


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Create a disposable staging directory containing the packaged app payload "
            "(code + templates + static assets + metadata), without embedding a Python environment."
        )
    )
    parser.add_argument(
        "--target",
        default="macos-arm64",
        help="Release target name from docs/release/macos_targets.toml (default: macos-arm64).",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=REPO_DIR / "dist" / "stage" / "macos-arm64",
        help="Stage output directory (default: dist/stage/<target>).",
    )
    parser.add_argument(
        "--clean",
        action="store_true",
        help="Remove the output directory before staging.",
    )
    args = parser.parse_args()

    out_dir = Path(args.out)
    if str(out_dir).endswith("macos-arm64") and args.target != "macos-arm64":
        out_dir = out_dir.parent / args.target

    payload_dir = build_stage(out_dir, target=args.target, clean=args.clean)
    print(f"Staged payload: {payload_dir}")
    print(f"Manifest: {out_dir / 'stage_manifest.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
