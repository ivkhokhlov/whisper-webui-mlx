# Business Description

## Product overview
mlx-ui is a local-only web application for fast, private transcription of audio and
video files on macOS Apple Silicon. It wraps the whisper-turbo-mlx engine in an
easy, localhost UI that lets users upload files in batches, process them
sequentially, and download text results from a queue/history view. Uploads
support files or folders with a preflight summary (count, size, estimate) and
basic filtering before queueing. After initial setup and model download, it runs
fully offline. Recent UI work focuses on a compact, scannable History view with
details-on-demand and transcript previews.

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
- Optional Telegram delivery of text results and best-effort update checks.

## Target users
- Individuals or small teams with sensitive audio (legal, research, product,
  internal meetings).
- macOS Apple Silicon users who want fast, offline transcription.
- Anyone who prefers a simple UI over managing ML CLI workflows.

## Key features
- Batch uploads via browser (files or folders) with preflight summary and
  filtering; queued, one-at-a-time processing.
- Compact History view with status, filename, time, output labels, and one-click
  primary actions (download or view log).
- Details-on-demand panel for full timestamps, outputs list, and error logs.
- Lazy-loaded transcript preview snippets to avoid loading full results for
  every job.
- Local data storage under data/ for easy retention and cleanup.
- Optional Telegram delivery of results without blocking the queue.
- (Planned/available) Live mode for recording and chunked transcription in the
  browser.

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
