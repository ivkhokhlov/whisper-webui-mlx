# Repository Guidelines

## Project Structure & Module Organization
- `mlx_ui/` houses the FastAPI app (`app.py`, `db.py`, `worker.py`, `transcriber.py`, `telegram.py`, `update_check.py`, `uploads.py`).
- `mlx_ui/templates/` contains Jinja2 templates (`index.html`, `live.html`).
- `tests/` is the pytest suite (`test_*.py`).
- `scripts/` includes the bootstrap script `setup_and_run.sh`; `run.sh` is the one-command launcher.
- `data/` is runtime state (uploads, results, logs, SQLite DB); it is created on demand.
- `docs/` holds the spec, dev notes, and the curated tree map.

## Build, Test, and Development Commands
- `./run.sh` — bootstrap and run the app (installs deps, downloads model if needed).
- `./scripts/setup_and_run.sh` — same bootstrap flow, useful for direct invocation.
- `make dev-deps` — create `.venv` and install runtime + dev dependencies.
- `make run` — start Uvicorn at `127.0.0.1:8000` using the local venv.
- `make test` — run the pytest suite.
- `make lint` — Ruff lint checks.
- `make fmt` — Ruff auto-formatting.

## Coding Style & Naming Conventions
- Python is formatted and linted with Ruff; use `make fmt` before committing.
- Keep modules and files in `snake_case` (matching existing `mlx_ui/*.py`).
- Test files follow `tests/test_*.py`, and test functions should use `test_` prefixes.

## Testing Guidelines
- Tests are written with pytest; run them via `make test`.
- Prefer tests that do not require the real ML model; mock `wtm` execution where possible.

## Commit & Pull Request Guidelines
- Commit history uses short, imperative summaries with gitflow-style prefixes (e.g., `feat:`, `fix:`, `chore:`, `docs:`). Keep the first line concise.
- PRs should include a brief summary, testing notes, and screenshots for UI changes. Link related issues and call out any data or config changes.

## Configuration & Runtime Data
- Environment variables: `WTM_PATH`, `WTM_QUICK`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `LOG_LEVEL`, `LOG_DIR`, `DISABLE_UPDATE_CHECK`, `UPDATE_CHECK_URL`, `SKIP_MODEL_DOWNLOAD`.
- Runtime paths: `data/uploads/`, `data/results/`, `data/jobs.db`, `data/logs/`.
- The app is local-only and should bind to `127.0.0.1`.
