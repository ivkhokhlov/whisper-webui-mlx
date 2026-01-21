# Spec — whisper-webui-mlx

## Goal
Create a **local-only** tool for **macOS Apple Silicon (M1+)** that provides a **Web UI on localhost** to manage **local transcription** of audio/video files using the engine from `whisper-turbo-mlx` via its CLI `wtm` (MLX).

The tool must be easy to deploy to another M1+ Mac (one command), and after the initial setup + model download it must work **fully offline**.

## MVP: Batch file transcription via Web UI
### UX
- User opens Web UI (localhost).
- User uploads **one or multiple files** (audio or video).
- User selects the **language manually** (no auto-detect).
- Files are placed into a **queue** and processed **strictly sequentially** (no parallel jobs).
- UI has:
  - Queue view: current job + pending jobs
  - History view: completed jobs + access to results

### Processing rules
- One worker processes one job at a time (sequential).
- Keep the ML model “warm” behavior in mind: avoid parallelism and avoid reinitialization churn.
- For each job, create results in all formats supported by upstream tool (at minimum, guarantee `.txt`).
- Store results in a repo-local folder (safe local storage), e.g. `data/results/<job_id>/`.

### Storage
- Persist job metadata (queued/running/done/failed, timestamps, filenames, language, errors) in SQLite.
- Persist uploads under `data/uploads/`.
- Persist logs under `data/logs/` (or `logs/`), keep them readable.

## After MVP: Telegram delivery
Configuration via `.env`:
- `TELEGRAM_BOT_TOKEN` (secret)
- `TELEGRAM_CHAT_ID`

Behavior:
- After successful transcription of each file, send:
  - a message with the source filename
  - the resulting `.txt` file (NOT the original media)
- Telegram failures:
  - log the error
  - do NOT break the pipeline; simply skip sending

Security:
- Never display secrets in UI or logs; always mask tokens.

## Final phase: Live recording + chunked transcription
- Web UI exposes “Live” mode:
  - record microphone + selected browser tab audio (Chrome/Firefox)
  - mix into one stream (diarization/layers later)
- Save recordings locally under repo storage.
- Transcribe in chunks (target ~10s+) and incrementally update UI with plain text.
- If browser audio capture is unreliable, any working approach is acceptable; priority is “it works”.

## Non-functional requirements
- Platform: macOS Apple Silicon only (M1+).
- Access: localhost only (bind to 127.0.0.1).
- Offline: after initial setup/models, app works offline; network-only features (Telegram/update check) must degrade gracefully.
- Observability: logs for debugging.
- Update check: on startup, if network is available, check for updates (best-effort; must never break offline operation).

## One-command deployment
A new user on an M1+ Mac should be able to:
1) clone repo
2) run one script, which:
   - installs dependencies (brew/venv/pip)
   - installs/sets up `whisper-turbo-mlx` and `wtm`
   - downloads required models/weights
   - starts local Web UI
   - opens browser automatically

Note: Docker may be optional, but the MLX transcription engine is macOS-specific; prioritize native setup.

## Out of scope for v1
- Pause/cancel jobs in queue
- diarization, multi-track, timestamps, enhanced punctuation, VAD, custom dictionaries
- packaging as .app / DMG
