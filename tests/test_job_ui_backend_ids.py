from datetime import datetime, timezone

from mlx_ui.db import JobRecord
from mlx_ui.job_ui import build_job_ui


def test_job_ui_resolves_backend_ids_to_provider_metadata() -> None:
    created_at = datetime(2024, 1, 1, tzinfo=timezone.utc).isoformat(timespec="seconds")
    job = JobRecord(
        id="job-1",
        filename="alpha.wav",
        status="done",
        created_at=created_at,
        upload_path="/tmp/alpha.wav",
        language="en",
        requested_engine="whisper_mlx",
        effective_engine="wtm",
    )

    ui = build_job_ui(job)

    assert ui["requested_engine"]["id"] == "whisper_mlx"
    assert ui["effective_engine"]["id"] == "whisper_mlx"
    assert ui["effective_engine"]["label"] == "Whisper (MLX / Metal)"
    assert ui["effective_implementation"]["id"] == "wtm"
    assert "Backend: wtm" in ui["preview_meta"]


def test_job_ui_resolves_parakeet_mlx_backend_id_to_parakeet_family() -> None:
    created_at = datetime(2024, 1, 1, tzinfo=timezone.utc).isoformat(timespec="seconds")
    job = JobRecord(
        id="job-2",
        filename="beta.wav",
        status="done",
        created_at=created_at,
        upload_path="/tmp/beta.wav",
        language="en",
        requested_engine="parakeet_tdt_v3",
        effective_engine="parakeet_tdt_v3",
        effective_implementation_id="parakeet_mlx",
    )

    ui = build_job_ui(job)

    assert ui["requested_engine"]["id"] == "parakeet_tdt_v3"
    assert ui["effective_engine"]["id"] == "parakeet_tdt_v3"
    assert ui["effective_engine"]["label"] == "Parakeet TDT v3"
    assert ui["effective_implementation"]["id"] == "parakeet_mlx"
    assert "Backend: parakeet_mlx" in ui["preview_meta"]
