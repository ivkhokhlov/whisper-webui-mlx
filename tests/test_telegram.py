import logging
from pathlib import Path
import urllib.error
import urllib.request

from mlx_ui.db import JobRecord
from mlx_ui.telegram import maybe_send_telegram, mask_secret


class DummyResponse:
    def __init__(self, status: int = 200, body: bytes | None = None) -> None:
        self._status = status
        self._body = body or b"ok"

    def read(self) -> bytes:
        return self._body

    def getcode(self) -> int:
        return self._status

    def __enter__(self) -> "DummyResponse":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:  # type: ignore[no-untyped-def]
        return False


def _make_job(tmp_path: Path) -> tuple[JobRecord, Path]:
    uploads_dir = tmp_path / "uploads" / "job1"
    uploads_dir.mkdir(parents=True, exist_ok=True)
    upload_path = uploads_dir / "sample.wav"
    upload_path.write_text("data", encoding="utf-8")
    job = JobRecord(
        id="job1",
        filename="sample.wav",
        status="done",
        created_at="2024-01-01T00:00:00Z",
        upload_path=str(upload_path),
        language="en",
    )
    result_path = tmp_path / "results" / job.id
    result_path.mkdir(parents=True, exist_ok=True)
    txt_path = result_path / "sample.txt"
    txt_path.write_text("hello", encoding="utf-8")
    return job, txt_path


def test_maybe_send_telegram_success(monkeypatch, tmp_path: Path) -> None:
    job, result_path = _make_job(tmp_path)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "token-12345")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "123")

    requests: list[tuple[urllib.request.Request, float]] = []

    def fake_urlopen(request, timeout=0):  # type: ignore[no-untyped-def]
        requests.append((request, float(timeout)))
        return DummyResponse()

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

    maybe_send_telegram(job, result_path, timeout=2.5)

    assert len(requests) == 2
    assert requests[0][1] == 2.5
    assert requests[1][1] == 2.5
    assert requests[0][0].full_url.endswith("/sendMessage")
    assert requests[1][0].full_url.endswith("/sendDocument")
    assert b"chat_id=123" in requests[0][0].data
    assert b"Transcription+complete%3A" in requests[0][0].data
    assert b"chat_id" in requests[1][0].data
    assert result_path.name.encode("utf-8") in requests[1][0].data


def test_maybe_send_telegram_skips_without_config(monkeypatch, tmp_path: Path) -> None:
    job, result_path = _make_job(tmp_path)
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)

    called = False

    def fake_urlopen(request, timeout=0):  # type: ignore[no-untyped-def]
        nonlocal called
        called = True
        return DummyResponse()

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

    maybe_send_telegram(job, result_path)

    assert called is False


def test_maybe_send_telegram_failure_logs_masked_token(
    monkeypatch, tmp_path: Path, caplog
) -> None:
    job, result_path = _make_job(tmp_path)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "super-secret-token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "123")

    def fake_urlopen(request, timeout=0):  # type: ignore[no-untyped-def]
        raise urllib.error.URLError("connection refused")

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

    caplog.set_level(logging.WARNING, logger="mlx_ui.telegram")

    maybe_send_telegram(job, result_path)

    assert "super-secret-token" not in caplog.text
    assert mask_secret("super-secret-token") in caplog.text
