from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from mlx_ui.app_context import get_base_dir, get_results_dir, get_uploads_dir
from mlx_ui.settings import (
    build_cohere_snapshot,
    build_settings_snapshot,
    build_telegram_snapshot,
    update_settings_file,
    validate_settings_payload,
)
from mlx_ui.storage import clear_directory

router = APIRouter()


@router.get("/api/settings")
def api_settings() -> dict[str, object]:
    base_dir = get_base_dir()
    snapshot = build_settings_snapshot(base_dir=base_dir)
    snapshot["cohere_snapshot"] = build_cohere_snapshot(base_dir=base_dir)
    snapshot["telegram_snapshot"] = build_telegram_snapshot(base_dir=base_dir)
    return snapshot


@router.post("/api/settings")
async def api_update_settings(request: Request) -> dict[str, object]:
    payload = await request.json()
    updates, errors = validate_settings_payload(payload)
    if errors:
        raise HTTPException(status_code=422, detail=errors)
    if updates:
        update_settings_file(get_base_dir(), updates)
    base_dir = get_base_dir()
    snapshot = build_settings_snapshot(base_dir=base_dir)
    snapshot["cohere_snapshot"] = build_cohere_snapshot(base_dir=base_dir)
    snapshot["telegram_snapshot"] = build_telegram_snapshot(base_dir=base_dir)
    return snapshot


@router.post("/api/settings/clear-uploads")
def api_clear_uploads() -> dict[str, str]:
    clear_directory(get_uploads_dir())
    return {"status": "ok"}


@router.post("/api/settings/clear-results")
def api_clear_results() -> dict[str, str]:
    clear_directory(get_results_dir())
    return {"status": "ok"}
