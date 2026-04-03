#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
from pathlib import Path, PurePosixPath
import stat
import subprocess
import sys
import time
import zipfile


SCRIPT_REPO_DIR = Path(__file__).resolve().parents[1]


def _git_stdout(repo_dir: Path, *args: str) -> str:
    try:
        result = subprocess.run(
            ["git", "-C", str(repo_dir), *args],
            capture_output=True,
            text=True,
            check=True,
        )
    except FileNotFoundError as exc:
        raise RuntimeError("git is required to build the archive.") from exc
    except subprocess.CalledProcessError as exc:
        message = exc.stderr.strip() or exc.stdout.strip() or str(exc)
        raise RuntimeError(message) from exc
    return result.stdout.strip()


def _resolve_repo_root(repo_dir: Path) -> Path:
    resolved = _git_stdout(repo_dir, "rev-parse", "--show-toplevel")
    return Path(resolved).resolve()


def _list_repo_files(repo_root: Path) -> list[Path]:
    try:
        result = subprocess.run(
            [
                "git",
                "-C",
                str(repo_root),
                "ls-files",
                "--cached",
                "--others",
                "--exclude-standard",
                "-z",
            ],
            capture_output=True,
            check=True,
        )
    except FileNotFoundError as exc:
        raise RuntimeError("git is required to build the archive.") from exc
    except subprocess.CalledProcessError as exc:
        message = exc.stderr.decode("utf-8", errors="replace").strip() or str(exc)
        raise RuntimeError(message) from exc

    paths = {
        Path(os.fsdecode(raw_path))
        for raw_path in result.stdout.split(b"\0")
        if raw_path
    }
    return sorted(paths, key=lambda path: path.as_posix())


def _archive_member_path(repo_root: Path, relative_path: Path) -> str:
    return str(PurePosixPath(repo_root.name, *relative_path.parts))


def _write_symlink(
    archive: zipfile.ZipFile,
    source_path: Path,
    *,
    archive_path: str,
) -> None:
    link_target = os.readlink(source_path)
    stat_result = source_path.lstat()
    zip_info = zipfile.ZipInfo(archive_path)
    zip_info.date_time = time.localtime(stat_result.st_mtime)[:6]
    zip_info.create_system = 3
    zip_info.compress_type = zipfile.ZIP_DEFLATED
    zip_info.external_attr = (stat.S_IFLNK | stat.S_IMODE(stat_result.st_mode)) << 16
    archive.writestr(zip_info, link_target.encode("utf-8"))


def build_repo_archive(
    repo_root: Path,
    output_path: Path,
) -> tuple[Path, int]:
    repo_root = repo_root.resolve()
    output_path = output_path.resolve()

    repo_files = _list_repo_files(repo_root)

    output_relative: Path | None = None
    try:
        output_relative = output_path.relative_to(repo_root)
    except ValueError:
        output_relative = None

    files_to_archive: list[Path] = []
    for relative_path in repo_files:
        if output_relative is not None and relative_path == output_relative:
            continue
        files_to_archive.append(relative_path)

    output_path.parent.mkdir(parents=True, exist_ok=True)

    archived_files = 0
    with zipfile.ZipFile(
        output_path,
        mode="w",
        compression=zipfile.ZIP_DEFLATED,
        compresslevel=9,
        strict_timestamps=False,
    ) as archive:
        for relative_path in files_to_archive:
            source_path = repo_root / relative_path
            if source_path.is_symlink():
                _write_symlink(
                    archive,
                    source_path,
                    archive_path=_archive_member_path(repo_root, relative_path),
                )
                archived_files += 1
                continue
            if source_path.is_file():
                archive.write(
                    source_path,
                    arcname=_archive_member_path(repo_root, relative_path),
                )
                archived_files += 1
                continue
            if source_path.exists():
                print(
                    f"Skipping non-file path listed by git: {relative_path}",
                    file=sys.stderr,
                )
                continue
            print(
                f"Skipping missing path listed by git: {relative_path}",
                file=sys.stderr,
            )

    return output_path, archived_files


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Create a .zip snapshot of the repository using git's exclude rules, "
            "including tracked files and untracked non-ignored files."
        )
    )
    parser.add_argument(
        "--repo",
        type=Path,
        default=SCRIPT_REPO_DIR,
        help=(
            "Path to the git repository to archive. Defaults to the repository "
            "that contains this script."
        ),
    )
    parser.add_argument(
        "--output",
        type=Path,
        help=(
            "Archive path. Defaults to <repo>/dist/<repo-name>.zip, which is safe "
            "to rerun because dist/ is gitignored in this repository."
        ),
    )
    args = parser.parse_args()

    try:
        repo_root = _resolve_repo_root(Path(args.repo))
        output_path = args.output
        if output_path is None:
            output_path = repo_root / "dist" / f"{repo_root.name}.zip"
        archive_path, archived_files = build_repo_archive(repo_root, Path(output_path))
    except RuntimeError as exc:
        parser.exit(1, f"Error: {exc}\n")

    print(f"Created {archive_path} with {archived_files} files.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
