# mlx-ui

Local-first transcription web UI with a sequential queue, per-job engine
selection, and a truthful multi-engine runtime model. The app runs on
`127.0.0.1`, stores its queue/history locally, and can process jobs with local
or cloud engines depending on what you install and select.

## Origin / inspiration
This repo’s core idea and MLX backend flow are based on JosefAlbers’s
`whisper-turbo-mlx` project:
```text
https://github.com/JosefAlbers/whisper-turbo-mlx
```

## Features
- Localhost-only FastAPI + Jinja2 UI for queue, history, settings, and preview
- Sequential worker with per-job `requested_engine` and `effective_engine`
- Shared transcript writers for `.txt`, `.json`, `.srt`, and `.vtt` when the
  backend provides real timing data
- `/live` route is a beta preview (may be unavailable depending on runtime)
- Batch uploads with an explicit job language (`auto` or a concrete language)
- Multipart `/api/jobs` intake for local automation clients that need to attach
  stable `client` and `client_job_id` ownership metadata to queued jobs
- SQLite job tracking in `data/jobs.db`
- Local readiness metadata for Whisper and Parakeet model caches
- Optional Telegram delivery of `.txt` results (best-effort)
- Startup update check (best-effort, can be disabled)

## Architecture matrix

### Engines

| Engine | Type | Typical environment | Notes |
| --- | --- | --- | --- |
| `whisper_mlx` | Local | macOS Apple Silicon | Best-supported local path via `whisper-turbo-mlx` / Metal |
| `whisper_cpu` | Local | macOS Intel, Docker, fallback on Apple Silicon | CPU-only `openai-whisper` path |
| `parakeet_tdt_v3` | Local | macOS Apple Silicon (MLX) | Parakeet TDT v3 via the optional `parakeet-mlx` dependency (bundled in the `macos-arm64` packaged artifact; dev bootstrap: `--with-parakeet-mlx`) |
| `cohere` | Cloud | Any machine with the optional SDK and API key | Sends audio to Cohere; not local/offline |

Implementation notes:
- Apple Silicon Parakeet uses the MLX implementation (`parakeet_mlx`).
- A legacy NeMo/CUDA implementation (`parakeet_nemo_cuda`) is retained for internal/experimental Linux CUDA flows only; it is disabled by default and not part of macOS releases.

### macOS release targets

The macOS packaging contract (release targets, artifact naming, bundle ids, and
minimum OS versions) lives in `docs/release/macos_targets.toml`. It formalizes:

- `macos-arm64` (Apple Silicon): default local engine `whisper_mlx`, optional `parakeet_tdt_v3` + `cohere`
- `macos-intel` (x86_64): default local engine `whisper_cpu`, optional `cohere`

| Target | Arch | Min macOS | Default local | Optional | Bundle id | DMG artifact |
| --- | --- | --- | --- | --- | --- | --- |
| `macos-arm64` | arm64 | 12.0 | `whisper_mlx` | `parakeet_tdt_v3`, `cohere` | `com.whisperwebui.mlx` | `whisper-webui-mlx-v{version}-macos-arm64.dmg` |
| `macos-intel` | x86_64 | 12.0 | `whisper_cpu` | `cohere` | `com.whisperwebui.mlx.cpu` | `whisper-webui-mlx-v{version}-macos-intel.dmg` |

The standard `macos-arm64` packaged artifact includes Parakeet MLX dependencies; Intel artifacts do not.

## Local vs cloud engine truthfulness

The UI stays local-first, but it is no longer honest to describe the product as
always local-only. If you select `cohere`, the job runs through Cohere's cloud
API and uploads audio for transcription. That path requires network access plus
an explicit supported language.

## Developer bootstrap (repo)

### Requirements
- No system Python required (the launcher downloads a portable Python 3.12 runtime into `./.runtime/python`)
- `ffmpeg` on `PATH` (system dependency)
- Internet access on first run for dependencies and first-run model downloads
- macOS Apple Silicon for local Whisper MLX and Parakeet MLX
- macOS Intel or Docker for the local Whisper CPU path
- Optional Cohere account + API key for the cloud engine

### Quick start
```bash
./run.sh
```
Then open http://127.0.0.1:8000.

If you want the script to install missing prerequisites via Homebrew (and prompt
for Xcode Command Line Tools), run:
```bash
./run.sh --bootstrap
```

If you want to re-download the embedded Python runtime (or recover from a
corrupted download), run:
```bash
./run.sh --reinstall-python
```

If you want to use a specific local Python interpreter instead of the embedded
runtime (must be Python 3.12.3+ and <3.13), run:
```bash
./run.sh --python python3.12
```

Bootstrap defaults on macOS:
- Apple Silicon: installs Whisper MLX
- Intel: installs Whisper CPU

Optional profiles:
```bash
./run.sh --with-cohere
./run.sh --with-whisper-cpu
./run.sh --with-parakeet-mlx
```

Notes:
- `--with-parakeet-mlx` is supported on macOS Apple Silicon only. On Intel macOS it fails with a clear message.
- `--with-parakeet-mlx` installs the optional `requirements-parakeet-mlx.txt` profile (dependency-only; it does not change the default engine).

You can also call the bootstrap script directly:
```bash
./scripts/setup_and_run.sh --with-cohere
```

The launcher downloads a portable Python runtime into `./.runtime/python`,
creates/updates `.venv`, installs the appropriate dependency profile for the
current machine, and starts the app on `127.0.0.1:8000`. System-wide installs
are opt-in via `--bootstrap`. First-run model downloads can still take a while
for local engines that are not already cached.

### Automation job intake

Local automation can enqueue one file at a time through the same sequential
worker without using the browser form:

```bash
curl -F "file=@/path/to/audio.wav" \
  -F "language=auto" \
  -F "client=local-agent" \
  -F "client_job_id=source-job-123" \
  http://127.0.0.1:8000/api/jobs
```

The endpoint stores the upload locally, creates a queued job, and returns the
generated `job_id` plus the submitted ownership fields. `client` and
`client_job_id` are required, trimmed, limited to 128 characters, and accept
letters, numbers, `_`, `-`, `.`, and `:`.

### Install via curl

You can install the app and a convenient launcher script with a single command:

```bash
curl -fsSL https://raw.githubusercontent.com/ivkhokhlov/whisper-webui-mlx/master/scripts/install.sh | bash
```

This will:

- Clone/update the repo under `~/.local/share/whisper-webui-mlx` (by default)
- Create a `whisper-webui-mlx` launcher in `~/.local/bin`

Make sure `~/.local/bin` is on your `PATH`, then you can start the app with:

```bash
whisper-webui-mlx
```

The launcher forwards bootstrap flags too:
```bash
whisper-webui-mlx --bootstrap
whisper-webui-mlx --reinstall-python
whisper-webui-mlx --with-cohere
whisper-webui-mlx --with-whisper-cpu
whisper-webui-mlx --with-parakeet-mlx
```

### Docker quick start (CPU backend)
Docker runs the CPU Whisper backend (`whisper_cpu`) only. This is slower than
MLX but works as an isolated local fallback. For best performance on Apple
Silicon, use the native `./run.sh` flow. Whisper/Parakeet MLX require macOS +
Metal and are not available in Docker.

```bash
./docker-run.sh
```

Then open http://127.0.0.1:8000.

Notes:
- Data, logs, and the Whisper model cache are persisted under `./data`.
- The script cleans up stopped containers for the same image to avoid junk build-up.
- Override settings with env vars (examples below).
- Use `DOCKER_PLATFORM=linux/amd64` on Intel hosts if you need to force a platform.

Example overrides:
```bash
WHISPER_MODEL=base PORT=9000 ./docker-run.sh
```
Note: `TRANSCRIBER_BACKEND=wtm` is not supported in Docker; use `whisper` or
run natively with `./run.sh` for MLX.

### Manual dev loop
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

### Configuration
- `WTM_PATH` - path to the `wtm` binary if a different one is on PATH
- `WTM_QUICK` - set to `1`/`true` to enable quick mode (default: `false`)
- `TRANSCRIBER_BACKEND` - backend/env override (`wtm`, `whisper`, `cohere`,
  `parakeet_tdt_v3`, `parakeet_mlx`, `fake`, plus legacy aliases; `parakeet_nemo_cuda` is experimental/internal and gated)
- `WHISPER_MODEL` - Whisper model name (default: `large-v3-turbo`)
- `WHISPER_DEVICE` - `cpu` (default) or `cuda` if you extend the image
- `WHISPER_FP16` - set to `1`/`true` to enable fp16 (GPU-only)
- `WHISPER_CACHE_DIR` - override Whisper model cache directory
- `COHERE_API_KEY` - optional Cohere API key
- `COHERE_MODEL` - Cohere transcription model id
- `TELEGRAM_BOT_TOKEN` - optional, for Telegram delivery
- `TELEGRAM_CHAT_ID` - optional, for Telegram delivery
- `LOG_LEVEL` - logging verbosity (default: `INFO`)
- `LOG_DIR` - log directory (default: `data/logs`)
- `DISABLE_UPDATE_CHECK=1` - skip startup update check
- `UPDATE_CHECK_URL` - override update check URL
- `SKIP_MODEL_DOWNLOAD=1` - skip model download in `scripts/setup_and_run.sh`

### Data locations
- `data/uploads/` - uploaded files
- `data/results/` - transcription outputs by job ID
- `data/jobs.db` - SQLite job metadata
- `data/logs/` - log files for debugging
- `data/.cache/whisper/` - optional local Whisper cache (Docker/backend-dependent)
- `~/.cache/huggingface/` - typical Parakeet cache location when used locally

### Notes
- The server binds to `127.0.0.1` only.
- Jobs persist the selected language plus the requested and effective engine.
- Local engines can work offline after setup and model download.
- The `cohere` engine is intentionally not offline and will upload audio to
  Cohere for transcription.
- Telegram delivery and update checks are best-effort and never block the queue.

## Packaged macOS release flow (maintainers)

This is the end-user distribution path. It is intentionally separate from the
developer bootstrap (`./run.sh`).

High-level sequence:

1. Build self-contained `.app` (embeds a Python runtime + deps)
2. Sign the `.app` (nested code first)
3. Wrap into a DMG (drag-to-Applications)
4. Notarize the DMG and staple the ticket
5. Verify the final artifact offline (Gatekeeper readiness)

Ergonomic entry points live in `Makefile`:

```bash
make macos-app-arm64 MACOS_APP_ARGS="--python /path/to/python --with-cohere --force"
make macos-sign-arm64 MACOS_SIGN_ARGS="--identity 'Developer ID Application: ...' --hardened-runtime"
make macos-dmg-arm64
make macos-notarize-arm64 MACOS_NOTARY_ARGS="--keychain-profile whisper-webui-notary"
make macos-verify-arm64
```

Notes:
- Build on matching hardware: `macos-arm64` requires an arm64 Mac; `macos-intel`
  requires an x86_64 Mac.
- Packaged apps store mutable state under `~/Library/Application Support/<bundle_id>/data/`
  (settings, DB, uploads, results, logs) and still bind to `127.0.0.1`.
- The release contract lives in `docs/release/macos_targets.toml`. The manual
  maintainer playbook is in `docs/release/playbook.md`.
