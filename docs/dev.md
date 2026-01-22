# Developer guide

## Requirements (target)
- macOS Apple Silicon (M1+)
- Python 3.12.3+
- Homebrew (for system deps like ffmpeg)

## Quick start (eventual)
```bash
./scripts/setup_and_run.sh
```
Notes:
- Requires Homebrew (for ffmpeg), Python 3.12.3+, and Poetry (the script installs missing deps via Homebrew).
- First run needs network access to install `whisper-turbo-mlx` and download the default model.
- Set `SKIP_MODEL_DOWNLOAD=1` to skip prefetching weights (not recommended).

## Manual dev loop
```bash
poetry install --with dev

make test
make run
```

## Troubleshooting `wtm` (transcription)
If you see `Could not consume arg: --language`, a different `wtm` binary is being used
instead of `whisper-turbo-mlx`.

Fixes:
- Install `whisper-turbo-mlx` into the Poetry env:
  `poetry run pip install --upgrade "whisper-turbo-mlx @ git+https://github.com/JosefAlbers/whisper-turbo-mlx.git"`
- Run the app via `make run` (or `poetry run uvicorn ...`) so the venv `wtm` is used.
- Or set `WTM_PATH` to the correct binary:
  `export WTM_PATH="$(poetry run which wtm)"`

## Telegram delivery (optional)
Set environment variables before starting the app:
- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`

Failures are logged and do not break the job pipeline. Tokens are masked in logs.

## Live mode plan (stub)
- Capture microphone + browser tab audio in the browser (getUserMedia + getDisplayMedia).
- Mix streams client-side, encode, chunk into ~10s segments.
- POST chunks to a server session endpoint with selected language.
- Server writes chunks to disk, enqueues sequential transcription jobs via the worker.
- UI streams partial transcript updates and saves final text to results.

## Notes
- The app must bind only to `127.0.0.1`.
- Keep network usage optional and best-effort (Telegram, update check).
- Update check runs at startup; set `DISABLE_UPDATE_CHECK=1` to skip or `UPDATE_CHECK_URL` to override the releases endpoint.
- Prefer tests that do not require the real ML model; mock `wtm` execution.
