# Developer guide

## Requirements (target)
- macOS Apple Silicon (M1+)
- `ffmpeg` on PATH (required for audio decode)
- Internet access on first run (to download the embedded Python runtime, install deps, and download the model)

## Quick start (eventual)
```bash
./scripts/setup_and_run.sh
```
Notes:
- By default, the script downloads a portable Python runtime into `./.runtime/python` and uses it to create/manage `./.venv`.
- The script manages a local `.venv` and installs deps with pip (no global site-packages).
- Use `--reinstall-python` (or `MLX_UI_REINSTALL_PYTHON=1`) to re-download the embedded Python runtime.
- Use `--bootstrap` (or `MLX_UI_ALLOW_SYSTEM_INSTALL=1`) to allow installing missing system prerequisites via Homebrew and prompt for Xcode Command Line Tools.
- Use `--python /path/to/python3.12` if you want to force a specific Python interpreter (must be Python 3.12.3+ and <3.13).
- First run needs network access to install `whisper-turbo-mlx` and download the default model.
- Set `SKIP_MODEL_DOWNLOAD=1` to skip prefetching weights (not recommended).
- Set `WTM_QUICK=1` to enable `wtm --quick=True` (default: `false`).

## Manual dev loop
```bash
make dev-deps
make test
make run
```

## Docker (CPU backend)
Docker uses the `openai-whisper` CPU backend (not MLX). Run:
```bash
./docker-run.sh
```

Notes:
- The container binds to `127.0.0.1:8000` on the host by default.
- Data and model cache persist under `./data`.

## Troubleshooting `wtm` (transcription)
If you see `Could not consume arg: --any_lang` or a help screen listing string
methods (capitalize, lower, etc.), a different `wtm` binary is being used instead
of `whisper-turbo-mlx`.

Fixes:
- Install `whisper-turbo-mlx` into the local venv:
  `./.venv/bin/pip install --upgrade "whisper-turbo-mlx @ https://github.com/JosefAlbers/whisper-turbo-mlx/archive/8a389f03ea786e8094a7d02e6dcc38f5178965dc.zip"`
- Run the app via `make run` (or `./.venv/bin/python -m uvicorn ...`) so the venv `wtm` is used.
- Or set `WTM_PATH` to the correct binary:
  `export WTM_PATH="$(pwd)/.venv/bin/wtm"`

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
