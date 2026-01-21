import logging
import urllib.error
import urllib.request

from mlx_ui import update_check


def test_resolve_update_url_prefers_override() -> None:
    env = {update_check.UPDATE_CHECK_URL_ENV: "https://example.com/override"}
    url = update_check.resolve_update_url(
        env=env,
        remote_url="https://github.com/example/repo.git",
    )

    assert url == "https://example.com/override"


def test_resolve_update_url_from_github_remote() -> None:
    env: dict[str, str] = {}
    url = update_check.resolve_update_url(
        env=env,
        remote_url="git@github.com:octo/repo.git",
    )

    assert url == "https://api.github.com/repos/octo/repo/releases/latest"


def test_check_for_updates_handles_urlerror(monkeypatch) -> None:
    monkeypatch.setattr(update_check, "read_local_version", lambda: "0.1.0")
    monkeypatch.setattr(
        update_check,
        "resolve_update_url",
        lambda *args, **kwargs: "https://example.com",
    )

    def fake_urlopen(request, timeout=0):  # type: ignore[no-untyped-def]
        raise urllib.error.URLError("offline")

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

    update_check.check_for_updates(timeout=0.01)


def test_check_for_updates_logs_available(monkeypatch, caplog) -> None:
    monkeypatch.setattr(update_check, "read_local_version", lambda: "0.1.0")
    monkeypatch.setattr(
        update_check,
        "resolve_update_url",
        lambda *args, **kwargs: "https://example.com",
    )
    monkeypatch.setattr(
        update_check,
        "_fetch_latest_version",
        lambda *args, **kwargs: "0.2.0",
    )

    caplog.set_level(logging.INFO, logger="mlx_ui.update_check")

    update_check.check_for_updates(timeout=0.01)

    assert "Update available" in caplog.text
    assert "0.1.0" in caplog.text
    assert "0.2.0" in caplog.text
