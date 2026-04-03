#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from typing import Any

import tomllib


REPO_DIR = Path(__file__).resolve().parents[1]
CONTRACT_PATH = REPO_DIR / "docs" / "release" / "macos_targets.toml"

RUNTIME_DIR_NAME = "runtime"
EMBEDDED_PYTHON_DIRNAME = "python"
EMBEDDED_VENV_DIRNAME = "venv"

CLOUD_ENGINE_IDS = {"cohere"}
REQUIREMENTS_PROFILE_ENGINE_IDS = {
    "requirements-whisper-mlx.txt": "whisper_mlx",
    "requirements-whisper-cpu.txt": "whisper_cpu",
    "requirements-parakeet-mlx.txt": "parakeet_tdt_v3",
    "requirements-cohere.txt": "cohere",
}


def _load_contract(path: Path) -> dict[str, object]:
    return tomllib.loads(path.read_text(encoding="utf-8"))


def _contract_targets(contract: dict[str, object]) -> dict[str, object]:
    macos = contract.get("macos")
    if not isinstance(macos, dict):
        raise ValueError("Contract missing [macos] table.")
    targets = macos.get("targets")
    if not isinstance(targets, dict):
        raise ValueError("Contract missing [macos.targets] table.")
    return targets


def _target_engine_profile(target: str) -> str:
    if target == "macos-arm64":
        return "whisper_mlx"
    if target == "macos-intel":
        return "whisper_cpu"
    raise ValueError(f"Unsupported release target: {target}")


def _requirements_for_target(target: str, *, with_cohere: bool) -> list[str]:
    base = ["requirements.txt"]
    profile = _target_engine_profile(target)
    if profile == "whisper_mlx":
        base.append("requirements-whisper-mlx.txt")
        base.append("requirements-parakeet-mlx.txt")
    elif profile == "whisper_cpu":
        base.append("requirements-whisper-cpu.txt")
    if with_cohere:
        base.append("requirements-cohere.txt")
    return base


def _engine_ids_for_requirements(requirement_files: list[str]) -> list[str]:
    engine_ids: list[str] = []
    for rel_path in requirement_files:
        engine_id = REQUIREMENTS_PROFILE_ENGINE_IDS.get(rel_path)
        if engine_id and engine_id not in engine_ids:
            engine_ids.append(engine_id)
    return engine_ids


def _run_json(
    argv: list[str],
    *,
    env: dict[str, str] | None = None,
    cwd: Path | None = None,
) -> dict[str, Any]:
    result = subprocess.run(
        argv,
        capture_output=True,
        text=True,
        check=True,
        env=env,
        cwd=str(cwd) if cwd is not None else None,
    )
    payload = result.stdout.strip()
    if not payload:
        raise RuntimeError(f"Command produced no output: {' '.join(argv)}")
    return json.loads(payload)


def _python_runtime_info(python_exec: Path) -> dict[str, str]:
    data = _run_json(
        [
            str(python_exec),
            "-c",
            (
                "import json, sys\n"
                "print(json.dumps({"
                "'version': sys.version.split()[0], "
                "'base_prefix': sys.base_prefix, "
                "'executable': sys.executable"
                "}))\n"
            ),
        ]
    )
    version = str(data.get("version") or "").strip()
    base_prefix = str(data.get("base_prefix") or "").strip()
    executable = str(data.get("executable") or "").strip()
    if not version or not base_prefix or not executable:
        raise RuntimeError("Failed to resolve python runtime metadata.")
    return {"version": version, "base_prefix": base_prefix, "executable": executable}


def _copy_python_prefix(base_prefix: Path, dest: Path, *, clean: bool) -> None:
    if dest.exists():
        if not clean:
            raise FileExistsError(
                f"Embedded python prefix already exists: {dest} (pass --clean to recreate)"
            )
        shutil.rmtree(dest)
    shutil.copytree(base_prefix, dest, symlinks=True)


def _create_venv(
    python_exec: Path,
    venv_dir: Path,
    *,
    clean: bool,
) -> None:
    if venv_dir.exists():
        if not clean:
            raise FileExistsError(
                f"Embedded venv already exists: {venv_dir} (pass --clean to recreate)"
            )
        shutil.rmtree(venv_dir)
    subprocess.run(
        [str(python_exec), "-m", "venv", "--copies", str(venv_dir)],
        check=True,
    )


def _patch_pyvenv_cfg(venv_dir: Path, *, home_value: str) -> None:
    cfg_path = venv_dir / "pyvenv.cfg"
    if not cfg_path.is_file():
        raise FileNotFoundError(f"Missing venv config: {cfg_path}")
    lines = cfg_path.read_text(encoding="utf-8").splitlines()
    out: list[str] = []
    replaced = False
    for line in lines:
        if line.startswith("home = "):
            out.append(f"home = {home_value}")
            replaced = True
        else:
            out.append(line)
    if not replaced:
        out.insert(0, f"home = {home_value}")
    cfg_path.write_text("\n".join(out) + "\n", encoding="utf-8")


def _venv_python(venv_dir: Path) -> Path:
    python_exec = venv_dir / "bin" / "python3"
    if python_exec.exists():
        return python_exec
    return venv_dir / "bin" / "python"


def _pip_install(
    venv_dir: Path,
    payload_dir: Path,
    requirement_files: list[str],
) -> None:
    python_exec = _venv_python(venv_dir)
    env = dict(os.environ)
    env.setdefault("PIP_DISABLE_PIP_VERSION_CHECK", "1")
    env.setdefault("PIP_NO_PYTHON_VERSION_WARNING", "1")

    subprocess.run(
        [str(python_exec), "-m", "ensurepip", "--upgrade"], check=True, env=env
    )
    for rel_path in requirement_files:
        req_path = payload_dir / rel_path
        if not req_path.is_file():
            raise FileNotFoundError(f"Missing requirements file in payload: {req_path}")
        subprocess.run(
            [
                str(python_exec),
                "-m",
                "pip",
                "install",
                "--no-cache-dir",
                "--upgrade",
                "-r",
                str(req_path),
            ],
            check=True,
            env=env,
        )


def _write_runtime_metadata(
    payload_dir: Path,
    *,
    target: str,
    with_cohere: bool,
    python_info: dict[str, str],
    requirement_files: list[str],
) -> None:
    runtime_dir = payload_dir / RUNTIME_DIR_NAME
    runtime_dir.mkdir(parents=True, exist_ok=True)
    included_engines = _engine_ids_for_requirements(requirement_files)
    metadata = {
        "target": target,
        "with_cohere": with_cohere,
        "engine_profile": _target_engine_profile(target),
        "included_engines": included_engines,
        "included_local_engines": [
            engine for engine in included_engines if engine not in CLOUD_ENGINE_IDS
        ],
        "python": python_info,
        "requirements": list(requirement_files),
        "venv_dir": f"{RUNTIME_DIR_NAME}/{EMBEDDED_VENV_DIRNAME}",
        "python_dir": f"{RUNTIME_DIR_NAME}/{EMBEDDED_PYTHON_DIRNAME}",
    }
    (runtime_dir / "embedded_runtime.json").write_text(
        json.dumps(metadata, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _write_requirements_freeze(payload_dir: Path, venv_dir: Path) -> None:
    python_exec = _venv_python(venv_dir)
    runtime_dir = payload_dir / RUNTIME_DIR_NAME
    runtime_dir.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        [str(python_exec), "-m", "pip", "freeze"],
        capture_output=True,
        text=True,
        check=True,
    )
    (runtime_dir / "requirements_frozen.txt").write_text(
        result.stdout.strip() + "\n",
        encoding="utf-8",
    )


def build_embedded_runtime(
    stage_dir: Path,
    *,
    target: str,
    python_exec: Path,
    with_cohere: bool,
    clean: bool,
) -> dict[str, object]:
    payload_dir = stage_dir / "payload"
    if not payload_dir.is_dir():
        raise FileNotFoundError(f"Missing stage payload directory: {payload_dir}")

    contract = _load_contract(CONTRACT_PATH)
    targets = _contract_targets(contract)
    if target not in targets:
        raise ValueError(
            f"Unknown target {target!r}; expected one of {sorted(targets)}"
        )

    requirement_files = _requirements_for_target(target, with_cohere=with_cohere)

    python_info = _python_runtime_info(python_exec)
    base_prefix = Path(python_info["base_prefix"]).resolve()
    python_exec_resolved = Path(python_info["executable"]).resolve()
    if not python_exec_resolved.is_relative_to(base_prefix):
        raise ValueError(
            "Python executable must live inside its sys.base_prefix so the prefix can be embedded."
        )

    embedded_python_dir = payload_dir / RUNTIME_DIR_NAME / EMBEDDED_PYTHON_DIRNAME
    embedded_venv_dir = payload_dir / RUNTIME_DIR_NAME / EMBEDDED_VENV_DIRNAME
    embedded_python_exec = embedded_python_dir / python_exec_resolved.relative_to(
        base_prefix
    )

    _copy_python_prefix(base_prefix, embedded_python_dir, clean=clean)
    _create_venv(embedded_python_exec, embedded_venv_dir, clean=clean)
    _patch_pyvenv_cfg(embedded_venv_dir, home_value=f"../{EMBEDDED_PYTHON_DIRNAME}/bin")
    _pip_install(embedded_venv_dir, payload_dir, requirement_files)
    _write_requirements_freeze(payload_dir, embedded_venv_dir)
    _write_runtime_metadata(
        payload_dir,
        target=target,
        with_cohere=with_cohere,
        python_info=python_info,
        requirement_files=requirement_files,
    )

    return {
        "target": target,
        "with_cohere": with_cohere,
        "payload_dir": str(payload_dir),
        "embedded_python_dir": str(embedded_python_dir),
        "embedded_venv_dir": str(embedded_venv_dir),
        "requirements": requirement_files,
        "python": python_info,
    }


def _build_plan(
    stage_dir: Path,
    *,
    target: str,
    with_cohere: bool,
) -> dict[str, object]:
    requirement_files = _requirements_for_target(target, with_cohere=with_cohere)
    payload_dir = stage_dir / "payload"
    embedded_python_dir = payload_dir / RUNTIME_DIR_NAME / EMBEDDED_PYTHON_DIRNAME
    embedded_venv_dir = payload_dir / RUNTIME_DIR_NAME / EMBEDDED_VENV_DIRNAME
    return {
        "target": target,
        "with_cohere": with_cohere,
        "engine_profile": _target_engine_profile(target),
        "stage_dir": str(stage_dir),
        "payload_dir": str(payload_dir),
        "embedded_python_dir": str(embedded_python_dir),
        "embedded_venv_dir": str(embedded_venv_dir),
        "requirements": requirement_files,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Build an embedded, target-aware Python environment inside an existing release stage.\n\n"
            "This step is intended for packaged macOS artifacts: it installs the correct dependency\n"
            "profile per release target (arm64 MLX vs intel CPU) and keeps optional engines (Cohere)\n"
            "explicit and script-driven."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--stage",
        type=Path,
        required=True,
        help="Stage directory created by scripts/stage_release_payload.py (contains payload/).",
    )
    parser.add_argument(
        "--target",
        default="macos-arm64",
        help="Release target name from docs/release/macos_targets.toml (default: macos-arm64).",
    )
    parser.add_argument(
        "--python",
        dest="python_exec",
        type=Path,
        default=Path(sys.executable),
        help=(
            "Python executable to embed + use for installs. Must be a redistributable, target-arch Python 3.12.3+ "
            "(recommended: a portable/standalone Python distribution). Defaults to the running interpreter."
        ),
    )
    parser.add_argument(
        "--with-cohere",
        action="store_true",
        help="Include the optional Cohere engine profile in the embedded environment.",
    )
    parser.add_argument(
        "--clean",
        action="store_true",
        help="Recreate payload/runtime/python and payload/runtime/venv if they already exist.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the build plan as JSON without creating the embedded environment.",
    )
    args = parser.parse_args()

    stage_dir = Path(args.stage)
    target = str(args.target)
    with_cohere = bool(args.with_cohere)

    if args.dry_run:
        print(
            json.dumps(
                _build_plan(stage_dir, target=target, with_cohere=with_cohere), indent=2
            )
        )
        return 0

    result = build_embedded_runtime(
        stage_dir,
        target=target,
        python_exec=Path(args.python_exec),
        with_cohere=with_cohere,
        clean=bool(args.clean),
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
