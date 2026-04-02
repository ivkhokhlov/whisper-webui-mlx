# Business Description

## Product overview
mlx-ui is a local-only web application for fast, private transcription of audio and
video files on macOS Apple Silicon. It wraps the whisper-turbo-mlx engine in an
easy, localhost UI that lets users upload files in batches, process them
sequentially, and download text results from a queue/history view. Uploads
support files or folders with a preflight summary (count, size, estimate) and
basic filtering before queueing. After initial setup and model download, it runs
fully offline. Recent UI work focuses on a compact Queue/History/Settings shell
with a mobile-friendly tab rail, a calmer Queue first screen for batch uploads,
a stable Worker status card that only shows current-file metadata while work is
active, a denser History list for high-volume datasets, and a clearer Settings
panel for default model selection, WTM quick mode, Telegram delivery, storage
management, and local diagnostics. The `/live` route remains an honest beta
preview rather than a production capture workflow.

## Problem it solves
- Cloud transcription is slow to upload, expensive at scale, and risky for
  sensitive audio.
- CLI-based ML transcription is powerful but too technical for many users and
  teams.
- Batch transcription needs job tracking, queues, and reliable result storage.
- Offline or air-gapped environments cannot depend on hosted services.

## Solution
- A local web UI on 127.0.0.1 that makes transcription accessible to
  non-technical users.
- Apple-Silicon-optimized MLX backend (wtm) for fast on-device processing.
- Sequential job queue to keep the model warm and avoid parallel overhead.
- Local storage of uploads, results, logs, and job metadata with SQLite.
- Optional Telegram delivery of text results and best-effort update checks,
  configurable from the Settings tab.

## Target users
- Individuals or small teams with sensitive audio (legal, research, product,
  internal meetings).
- macOS Apple Silicon users who want fast, offline transcription.
- Anyone who prefers a simple UI over managing ML CLI workflows.

## Key features
- Batch uploads via browser (files or folders) with preflight summary and
  filtering; queued, one-at-a-time processing.
- Worker status card that surfaces queue depth, mode, and current job metadata
  only when the worker is actively processing.
- Compact top-level navigation for Queue, History, and Settings that stays
  usable on mobile while `/live` remains a direct beta-preview route.
- Queue-first onboarding that keeps one dominant “Select files…” action above
  the fold while preserving folder batch upload and drag-and-drop as secondary
  affordances.
- Compact History view with status, filename, time, output labels, and one-click
  primary actions, plus overflow actions that stay inside the viewport near
  screen edges.
- Details-on-demand panel for full timestamps, outputs list, and error logs.
- Lazy-loaded transcript preview snippets to avoid loading full results for
  every job.
- History action menus (⋯) dismiss on outside click for faster triage.
- Per-item history deletion and bulk “delete all results” controls with
  confirmations, removing stored outputs from disk.
- Local data storage under data/ for easy retention and cleanup.
- Settings panel for default model selection (defaults to large-v3-turbo) and
  WTM quick mode, persisted in data/settings.json.
- Settings -> About reflects the app version from `pyproject.toml`, so the UI
  stays in sync with the current local build/version bump.
- Settings and the transcriber resolver now keep the selected engine
  (`Whisper (MLX / Metal)` vs `Whisper (CPU)`), effective backend, log level,
  and update-check preference aligned between saved settings, environment
  overrides, and the About/runtime snapshot.
- Local settings API endpoints for automation (read, update, and clear storage).
- Optional Telegram delivery of results without blocking the queue, configured
  via saved tokens or environment variables.
- Telegram delivery sends a single message with the transcript file attached
  and the original filename as the caption.
- Beta preview route for Live mode that communicates the intended future flow
  without implying microphone/browser capture is already implemented.
- Branded favicon in the browser tab for quick visual recognition of the local UI.

## Value proposition
- Privacy by design: all processing stays on the user's machine.
- Speed and cost control: no per-minute API fees, no upload bottlenecks.
- Operational simplicity: one-command setup and offline operation.
- Reliability: sequential processing avoids model re-init churn and resource
  spikes, while compact history keeps large job lists responsive.

## Differentiators
- Apple Silicon MLX acceleration (faster than CPU-only alternatives).
- Local-only design with no external dependencies after setup.
- Built-in queue/history flow optimized for scanning and triage, not just demos.
- Optional CPU-only Docker backend for broader compatibility.

## Constraints and scope
- Native MLX backend requires macOS Apple Silicon.
- Designed for local, single-machine use; not a multi-user cloud service.
- Out of scope for v1: diarization, advanced timestamping, pause/cancel queue.
