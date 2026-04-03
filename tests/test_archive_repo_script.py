from __future__ import annotations

from pathlib import Path
import subprocess
import sys
import zipfile


ROOT_DIR = Path(__file__).resolve().parents[1]


def _git(repo_dir: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(repo_dir), *args],
        capture_output=True,
        text=True,
        check=True,
    )


def test_archive_repo_respects_gitignore_and_keeps_nonignored_untracked_files(
    tmp_path: Path,
) -> None:
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    script = ROOT_DIR / "scripts" / "archive_repo.py"

    _git(repo_dir, "init")

    (repo_dir / ".gitignore").write_text("ignored/\n*.log\ndist/\n", encoding="utf-8")
    (repo_dir / "tracked.txt").write_text("tracked\n", encoding="utf-8")
    (repo_dir / "nested").mkdir()
    (repo_dir / "nested" / "tracked.py").write_text("print('ok')\n", encoding="utf-8")
    (repo_dir / "draft.md").write_text("keep me\n", encoding="utf-8")
    (repo_dir / "ignored").mkdir()
    (repo_dir / "ignored" / "skip.txt").write_text("skip\n", encoding="utf-8")
    (repo_dir / "debug.log").write_text("skip\n", encoding="utf-8")

    _git(repo_dir, "add", ".gitignore", "tracked.txt", "nested/tracked.py")

    archive_path = repo_dir / "repo-export.zip"
    for _ in range(2):
        subprocess.run(
            [
                sys.executable,
                str(script),
                "--repo",
                str(repo_dir),
                "--output",
                str(archive_path),
            ],
            capture_output=True,
            text=True,
            check=True,
        )

    with zipfile.ZipFile(archive_path) as archive:
        names = sorted(archive.namelist())
        root_prefix = f"{repo_dir.name}/"

        assert f"{root_prefix}.gitignore" in names
        assert f"{root_prefix}tracked.txt" in names
        assert f"{root_prefix}nested/tracked.py" in names
        assert f"{root_prefix}draft.md" in names
        assert f"{root_prefix}ignored/skip.txt" not in names
        assert f"{root_prefix}debug.log" not in names
        assert f"{root_prefix}repo-export.zip" not in names


def test_archive_repo_help_mentions_gitignore_behavior() -> None:
    script = ROOT_DIR / "scripts" / "archive_repo.py"
    result = subprocess.run(
        [sys.executable, str(script), "--help"],
        capture_output=True,
        text=True,
        check=True,
    )

    assert "git's exclude rules" in result.stdout
    assert "tracked files and untracked non-ignored files" in result.stdout
    assert "--output" in result.stdout
