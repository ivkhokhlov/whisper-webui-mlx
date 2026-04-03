from datetime import datetime, timezone
import re
from pathlib import Path

from fastapi.testclient import TestClient

from mlx_ui.app import app
from mlx_ui.db import JobRecord, init_db, insert_job


def _configure_app(tmp_path: Path) -> None:
    app.state.base_dir = tmp_path
    app.state.uploads_dir = tmp_path / "uploads"
    app.state.results_dir = tmp_path / "results"
    app.state.db_path = tmp_path / "jobs.db"
    app.state.worker_enabled = False
    app.state.update_check_enabled = False
    app.state.live_service = None


def _extract_history_row(html: str, job_id: str) -> str:
    match = re.search(
        rf'<div\s+class="history-row"[^>]*data-job-id="{re.escape(job_id)}".*?</details>\s*</div>',
        html,
        re.DOTALL,
    )
    assert match is not None
    return match.group(0)


def test_root_history_rows_use_lighter_summary_and_single_primary_action(tmp_path: Path) -> None:
    _configure_app(tmp_path)
    db_path = Path(app.state.db_path)
    init_db(db_path)

    done_id = "job-done-row"
    done_dir = Path(app.state.uploads_dir) / done_id
    done_dir.mkdir(parents=True, exist_ok=True)
    done_path = done_dir / "meeting.wav"
    done_path.write_text("data", encoding="utf-8")
    completed_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    insert_job(
        db_path,
        JobRecord(
            id=done_id,
            filename="meeting.wav",
            status="done",
            created_at=completed_at,
            completed_at=completed_at,
            upload_path=str(done_path),
            language="fr",
            requested_engine="cohere",
        ),
    )
    done_results_dir = Path(app.state.results_dir) / done_id
    done_results_dir.mkdir(parents=True, exist_ok=True)
    (done_results_dir / "meeting.txt").write_text("transcript", encoding="utf-8")
    (done_results_dir / "meeting.srt").write_text("subtitles", encoding="utf-8")

    failed_id = "job-failed-row"
    failed_dir = Path(app.state.uploads_dir) / failed_id
    failed_dir.mkdir(parents=True, exist_ok=True)
    failed_path = failed_dir / "broken.wav"
    failed_path.write_text("data", encoding="utf-8")
    insert_job(
        db_path,
        JobRecord(
            id=failed_id,
            filename="broken.wav",
            status="failed",
            created_at=completed_at,
            completed_at=completed_at,
            upload_path=str(failed_path),
            language="auto",
            error_message="Decoder crashed on frame 1\nfull stack trace",
        ),
    )

    with TestClient(app) as client:
        response = client.get("/?tab=history")

    assert response.status_code == 200
    done_row = _extract_history_row(response.text, done_id)
    failed_row = _extract_history_row(response.text, failed_id)

    assert 'class="status-badge is-done">Done<' in done_row
    assert 'class="status-badge is-failed">Failed<' in failed_row
    assert 'data-time-meta' in done_row
    assert 'data-time-meta' in failed_row
    assert 'class="job-primary"' in done_row
    assert len(re.findall(r'class="job-primary', done_row)) == 1
    assert len(re.findall(r'class="job-primary', failed_row)) == 1
    assert 'data-action="preview"' in done_row
    assert 'class="job-primary is-secondary js-only"' not in done_row
    assert 'output-chip' not in done_row
    assert 'output-chip' not in failed_row
    assert 'meta-chip' not in done_row
    assert 'meta-chip' not in failed_row
    assert "Decoder crashed on frame 1" in failed_row
