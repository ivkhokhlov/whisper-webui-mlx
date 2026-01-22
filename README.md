# mlx-ui

Local-only Web UI for running whisper-turbo-mlx on macOS Apple Silicon. Upload
audio or video files, process them sequentially with `wtm`, and download the
results from a queue + history view.

## Features
- Localhost-only FastAPI UI for batch uploads
- Sequential worker (one job at a time)
- Results saved under `data/results/<job_id>/` (at least `.txt`)
- SQLite job tracking in `data/jobs.db`
- Optional Telegram delivery of `.txt` results (best-effort)
- Startup update check (best-effort, can be disabled)

## Requirements
- macOS Apple Silicon (arm64)
- Python 3.12.3+
- Homebrew (for `ffmpeg`)
- `whisper-turbo-mlx` CLI (`wtm`)

## Quick start
```bash
./run.sh
```
Then open http://127.0.0.1:8000.

## Manual dev loop
```bash
make dev-deps
make run
```

Other useful commands:
```bash
make test
make lint
make fmt
```

## Configuration
- `WTM_PATH` - path to the `wtm` binary if a different one is on PATH
- `WTM_QUICK` - set to `1`/`true` to enable quick mode (default: `false`)
- `TELEGRAM_BOT_TOKEN` - optional, for Telegram delivery
- `TELEGRAM_CHAT_ID` - optional, for Telegram delivery
- `LOG_LEVEL` - logging verbosity (default: `INFO`)
- `LOG_DIR` - log directory (default: `data/logs`)
- `DISABLE_UPDATE_CHECK=1` - skip startup update check
- `UPDATE_CHECK_URL` - override update check URL
- `SKIP_MODEL_DOWNLOAD=1` - skip model download in `scripts/setup_and_run.sh`

## Data locations
- `data/uploads/` - uploaded files
- `data/results/` - transcription outputs by job ID
- `data/jobs.db` - SQLite job metadata
- `data/logs/` - log files for debugging

## Notes
- The server binds to `127.0.0.1` only.
- After initial setup and model download, the app works offline.
- Telegram delivery and update checks are best-effort and never block the queue.
