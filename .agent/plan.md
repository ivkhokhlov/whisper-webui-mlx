# Plan

Task: WUI-030 — One-command setup & run on M1+ macOS

Acceptance: `./scripts/setup_and_run.sh` installs deps, downloads models, starts server, and opens browser

Assumptions:
- Homebrew is available for system deps (ffmpeg), or the script will fail fast with a clear message.
- Network is available on first run to install deps and download the ML model; subsequent runs should work offline.
- `whisper-turbo-mlx` / `wtm` install path is via pip (poetry) unless upstream docs indicate otherwise.

Implementation steps:
- Review upstream `whisper-turbo-mlx` / `wtm` installation and model download instructions to select a default model and the CLI flags for pre-download.
- Add `scripts/setup_and_run.sh` that checks macOS + Apple Silicon, ensures `python3.11` + `poetry` are available (install/exit with guidance if missing), installs Python deps, installs `wtm`, and pre-downloads the default model.
- Ensure the script creates needed data directories, exports any required env vars (e.g., `WTM_PATH`), and starts the server via `make run` bound to `127.0.0.1`.
- Open the browser to `http://127.0.0.1:8000` once the server is up (best-effort, no failure if `open` fails).
- Update docs to mention the one-command script and update `docs/tree.md` to include the new script.

Files likely to touch:
- `scripts/setup_and_run.sh`
- `docs/dev.md`
- `README.md`
- `docs/tree.md`

Verification steps:
- `make test`
- `make lint`
