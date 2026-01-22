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
        output_dir = Path(cmd[cmd.index("--output_dir") + 1])
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / "sample.txt").write_text("hello", encoding="utf-8")
        return subprocess.CompletedProcess(cmd, 0, stdout="ok", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)

    transcriber = WtmTranscriber(wtm_path="wtm", language="fr")
    result_path = transcriber.transcribe(job, results_dir)

    assert result_path.is_file()
    assert result_path.read_text(encoding="utf-8") == "hello"
    assert captured["cmd"][0] == "wtm"
    assert str(Path(job.upload_path)) in captured["cmd"]
    assert "--language" in captured["cmd"]
    assert "fr" in captured["cmd"]
    assert "--output_dir" in captured["cmd"]
    assert str(results_dir / job.id) in captured["cmd"]
