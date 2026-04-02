from __future__ import annotations

from fastapi import APIRouter, File, HTTPException, UploadFile

from mlx_ui.app_context import get_base_dir, get_live_service
from mlx_ui.live_transcription import (
    LiveSessionNotFound,
    LiveTranscriptionError,
    ParakeetLiveConfig,
)
from mlx_ui.settings import (
    build_live_transcription_snapshot,
    PARAKEET_LIVE_CHUNK_SECS,
    PARAKEET_LIVE_LEFT_CONTEXT_SECS,
    PARAKEET_LIVE_RIGHT_CONTEXT_SECS,
    PARAKEET_LIVE_TIMESLICE_MS,
)

router = APIRouter()


def _build_parakeet_live_config(live_snapshot: dict[str, object]) -> ParakeetLiveConfig:
    return ParakeetLiveConfig(
        repo_id=str(live_snapshot.get("configured_model") or ""),
        decoding_mode="greedy",
        left_context_secs=float(
            live_snapshot.get("left_context_secs") or PARAKEET_LIVE_LEFT_CONTEXT_SECS
        ),
        chunk_secs=float(live_snapshot.get("chunk_secs") or PARAKEET_LIVE_CHUNK_SECS),
        right_context_secs=float(
            live_snapshot.get("right_context_secs") or PARAKEET_LIVE_RIGHT_CONTEXT_SECS
        ),
        timeslice_ms=int(
            live_snapshot.get("timeslice_ms") or PARAKEET_LIVE_TIMESLICE_MS
        ),
    )


@router.post("/api/live/session")
def api_live_start_session() -> dict[str, object]:
    live_snapshot = build_live_transcription_snapshot(base_dir=get_base_dir())
    if not live_snapshot.get("active"):
        raise HTTPException(
            status_code=409,
            detail=str(
                live_snapshot.get("reason")
                or "Parakeet live beta is not available in the current environment."
            ),
        )
    config = _build_parakeet_live_config(live_snapshot)
    try:
        update = get_live_service().open_session(config)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {
        "session": update.to_dict(),
        "live": live_snapshot,
    }


@router.post("/api/live/session/{session_id}/chunk")
async def api_live_append_chunk(
    session_id: str,
    file: UploadFile = File(...),
) -> dict[str, object]:
    try:
        payload = await file.read()
    finally:
        await file.close()
    try:
        update = get_live_service().append_chunk(
            session_id,
            payload,
            content_type=file.content_type,
        )
    except LiveSessionNotFound as exc:
        raise HTTPException(status_code=404, detail="Live session not found.") from exc
    except LiveTranscriptionError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {"session": update.to_dict()}


@router.post("/api/live/session/{session_id}/stop")
def api_live_stop_session(session_id: str) -> dict[str, object]:
    try:
        update = get_live_service().stop_session(session_id)
    except LiveSessionNotFound as exc:
        raise HTTPException(status_code=404, detail="Live session not found.") from exc
    except LiveTranscriptionError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {"session": update.to_dict()}
