from datetime import datetime, timezone
from pathlib import Path
import subprocess

from mlx_ui.db import JobRecord
from mlx_ui.transcriber import WtmTranscriber


def _make_job(tmp_path: Path) -> JobRecord:
    uploads_dir = tmp_path / "uploads" / "job1"
    uploads_dir.mkdir(parents=True, exist_ok=True)
    upload_path = uploads_dir / "sample.wav"
    upload_path.write_text("data", encoding="utf-8")
    return JobRecord(
        id="job1",
        filename="sample.wav",
        status="queued",
        created_at=datetime(2024, 1, 1, tzinfo=timezone.utc).isoformat(timespec="seconds"),
        upload_path=str(upload_path),
        language="fr",
    )


def test_wtm_transcriber_runs_and_returns_txt(tmp_path: Path, monkeypatch) -> None:
    job = _make_job(tmp_path)
    results_dir = tmp_path / "results"
    captured: dict[str, list[str]] = {}

    def fake_run(cmd, capture_output, text, check):  # type: ignore[no-untyped-def]
        captured["cmd"] = list(cmd)
        return subprocess.CompletedProcess(cmd, 0, stdout="hello", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.delenv("WTM_QUICK", raising=False)

    transcriber = WtmTranscriber(wtm_path="wtm")
    result_path = transcriber.transcribe(job, results_dir)

    assert result_path.is_file()
    assert result_path.read_text(encoding="utf-8") == "hello\n"
    assert captured["cmd"][0] == "wtm"
    assert "--path_audio" in captured["cmd"]
    assert "--any_lang=True" in captured["cmd"]
    assert "--quick=False" in captured["cmd"]
    assert str(Path(job.upload_path)) in captured["cmd"]
    assert (results_dir / job.id / "result.txt").is_file()


def test_wtm_transcriber_respects_quick_env(tmp_path: Path, monkeypatch) -> None:
    job = _make_job(tmp_path)
    results_dir = tmp_path / "results"
    captured: dict[str, list[str]] = {}

    def fake_run(cmd, capture_output, text, check):  # type: ignore[no-untyped-def]
        captured["cmd"] = list(cmd)
        return subprocess.CompletedProcess(cmd, 0, stdout="hello", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.setenv("WTM_QUICK", "true")

    transcriber = WtmTranscriber(wtm_path="wtm")
    transcriber.transcribe(job, results_dir)

    assert "--quick=True" in captured["cmd"]
