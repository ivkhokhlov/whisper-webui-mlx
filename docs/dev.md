# Developer guide

## Requirements (target)
- macOS Apple Silicon (M1+)
- Python 3.11+
- Homebrew (for system deps like ffmpeg)

## Quick start (eventual)
```bash
./scripts/setup_and_run.sh
```
Notes:
- Requires Homebrew (for ffmpeg), Python 3.11+, and Poetry (the script installs missing deps via Homebrew).
- First run needs network access to install `whisper-turbo-mlx` and download the default model.
- Set `SKIP_MODEL_DOWNLOAD=1` to skip prefetching weights (not recommended).

## Manual dev loop
```bash
poetry install --with dev

make test
make run
```

## Telegram delivery (optional)
Set environment variables before starting the app:
- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`

Failures are logged and do not break the job pipeline. Tokens are masked in logs.

## Notes
- The app must bind only to `127.0.0.1`.
- Keep network usage optional and best-effort (Telegram, update check).
- Update check runs at startup; set `DISABLE_UPDATE_CHECK=1` to skip or `UPDATE_CHECK_URL` to override the releases endpoint.
- Prefer tests that do not require the real ML model; mock `wtm` execution.
