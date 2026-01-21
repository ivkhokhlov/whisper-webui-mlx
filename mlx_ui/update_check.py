from __future__ import annotations

import importlib.metadata
import json
import logging
import os
from pathlib import Path
import re
import subprocess
import urllib.parse
import urllib.request
from typing import Mapping

import tomllib

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 2.0
UPDATE_CHECK_URL_ENV = "UPDATE_CHECK_URL"
DISABLE_UPDATE_CHECK_ENV = "DISABLE_UPDATE_CHECK"

_BASE_DIR = Path(__file__).resolve().parent.parent


def is_update_check_disabled(env: Mapping[str, str] | None = None) -> bool:
    if env is None:
        env = os.environ
    value = env.get(DISABLE_UPDATE_CHECK_ENV, "").strip().lower()
    return value in {"1", "true", "yes", "on"}


def resolve_update_url(
    env: Mapping[str, str] | None = None,
    remote_url: str | None = None,
) -> str | None:
    if env is None:
        env = os.environ
    override = env.get(UPDATE_CHECK_URL_ENV, "").strip()
    if override:
        return override
    if remote_url is None:
        remote_url = get_git_remote_url()
    if not remote_url:
        return None
    return _github_releases_url(remote_url)


def get_git_remote_url() -> str | None:
    try:
        result = subprocess.run(
            ["git", "config", "--get", "remote.origin.url"],
            capture_output=True,
            text=True,
            check=True,
            cwd=_BASE_DIR,
        )
    except (FileNotFoundError, subprocess.CalledProcessError):
        return None
    remote = result.stdout.strip()
    return remote or None


def read_local_version() -> str | None:
    try:
        return importlib.metadata.version("mlx-ui")
    except importlib.metadata.PackageNotFoundError:
        return _read_version_from_pyproject()


def check_for_updates(timeout: float = DEFAULT_TIMEOUT) -> None:
    local_version = read_local_version()
    if not local_version:
        logger.debug("Update check skipped: local version unavailable.")
        return

    update_url = resolve_update_url()
    if not update_url:
        logger.debug("Update check skipped: no update URL available.")
        return

    try:
        latest_version = _fetch_latest_version(update_url, timeout)
    except Exception as exc:
        logger.debug("Update check failed: %s", exc.__class__.__name__)
        return

    if not latest_version:
        logger.debug("Update check failed: no version returned.")
        return

    comparison = _compare_versions(local_version, latest_version)
    if comparison is None:
        if _normalize_version(local_version) == _normalize_version(latest_version):
            logger.info(
                "Update check: current version %s is up to date.",
                local_version,
            )
        else:
            logger.info("Update available: %s -> %s", local_version, latest_version)
        return

    if comparison < 0:
        logger.info("Update available: %s -> %s", local_version, latest_version)
    elif comparison == 0:
        logger.info(
            "Update check: current version %s is up to date.",
            local_version,
        )
    else:
        logger.info(
            "Update check: local version %s is newer than latest %s.",
            local_version,
            latest_version,
        )


def _github_releases_url(remote_url: str) -> str | None:
    repo = _extract_github_repo(remote_url)
    if not repo:
        return None
    owner, name = repo
    return f"https://api.github.com/repos/{owner}/{name}/releases/latest"


def _extract_github_repo(remote_url: str) -> tuple[str, str] | None:
    remote_url = remote_url.strip()
    if not remote_url:
        return None

    if remote_url.startswith("git@github.com:"):
        path = remote_url.split(":", 1)[1]
    else:
        parsed = urllib.parse.urlparse(remote_url)
        if parsed.netloc != "github.com":
            return None
        path = parsed.path.lstrip("/")

    parts = [part for part in path.split("/") if part]
    if len(parts) < 2:
        return None
    owner = parts[0]
    repo = parts[1]
    if repo.endswith(".git"):
        repo = repo[: -len(".git")]
    if not owner or not repo:
        return None
    return owner, repo


def _read_version_from_pyproject() -> str | None:
    pyproject_path = _BASE_DIR / "pyproject.toml"
    if not pyproject_path.is_file():
        return None
    try:
        data = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))
    except Exception:
        return None
    version = data.get("tool", {}).get("poetry", {}).get("version")
    if not isinstance(version, str):
        return None
    version = version.strip()
    return version or None


def _fetch_latest_version(update_url: str, timeout: float) -> str | None:
    request = urllib.request.Request(
        update_url,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "mlx-ui-update-check",
        },
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        payload = response.read()
    try:
        data = json.loads(payload)
    except json.JSONDecodeError:
        return None
    tag = data.get("tag_name") or data.get("name")
    if not tag:
        return None
    return str(tag).strip()


def _compare_versions(local: str, latest: str) -> int | None:
    local_parts = _parse_version(local)
    latest_parts = _parse_version(latest)
    if local_parts is None or latest_parts is None:
        return None
    max_len = max(len(local_parts), len(latest_parts))
    local_parts += (0,) * (max_len - len(local_parts))
    latest_parts += (0,) * (max_len - len(latest_parts))
    if local_parts < latest_parts:
        return -1
    if local_parts > latest_parts:
        return 1
    return 0


def _parse_version(value: str) -> tuple[int, ...] | None:
    match = re.match(r"(\d+(?:\.\d+)*)", _normalize_version(value))
    if not match:
        return None
    try:
        return tuple(int(part) for part in match.group(1).split("."))
    except ValueError:
        return None


def _normalize_version(value: str) -> str:
    return value.strip().lstrip("v")
