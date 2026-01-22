# Project tree (curated)

This file is a human-maintained map of the repo. Update when structure changes.

## Current
- `data/` — runtime uploads/results/logs/jobs.db (created on demand)
- `docs/` — spec + dev notes + this tree map
- `mlx_ui/` — FastAPI app package (`app.py`, `db.py`, `worker.py`, `transcriber.py`, `telegram.py`, `update_check.py`)
- `mlx_ui/logging_config.py` — logging setup (file + console)
- `mlx_ui/templates/` — Jinja2 templates (`index.html`, `live.html`)
- `scripts/` — setup/run script (`setup_and_run.sh`)
- `run.sh` — one-command launcher (calls `scripts/setup_and_run.sh`)
- `tests/` — pytest suite (`test_app.py`, `test_db_migration.py`, `test_transcriber.py`, `test_worker.py`, `test_telegram.py`, `test_update_check.py`)
- `Makefile` — dev commands
- `pyproject.toml` — dependencies and tooling
- `requirements.txt` — pip dependencies (runtime)
- `requirements-dev.txt` — pip dependencies (dev/test)
- `README.md` — repo overview
