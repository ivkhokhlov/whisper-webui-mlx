# Business Description

## Product overview
mlx-ui is a local-first transcription web application with a localhost UI,
sequential job processing, and a growing engine matrix. Users upload audio or
video files in batches, choose a job language, queue work, and retrieve results
from a queue/history flow backed by SQLite and on-disk artifacts. The product
still runs on `127.0.0.1` and keeps uploads, results, settings, and logs on the
local machine, but it now supports both local engines and an optional cloud
engine. In developer/repo mode, mutable runtime state lives under `data/` inside
the repo. In packaged macOS app mode, the same mutable state lives under
`~/Library/Application Support/<bundle_id>/data/` so the `.app` bundle and its
embedded payload remain read-only. Recent work added a real provider registry,
per-job engine persistence, per-job engine resolution in the worker, normalized
transcript outputs, local model readiness metadata, and UI badges that show
which engine and language each job used. The `/live` route remains an honest
beta preview rather than a production capture workflow. Ongoing refactors keep
the app maintainable while preserving the same UI/API contract, including an
app-factory bootstrap path, focused routers, provider modules per engine, and
template partials.

## Problem it solves
- Cloud transcription is slow to upload, expensive at scale, and risky for
  sensitive audio.
- CLI-based ML transcription is powerful but too technical for many users and
  teams.
- Batch transcription needs job tracking, queues, and reliable result storage.
- Some users need offline/local processing, while others need a practical cloud
  fallback when local acceleration is unavailable.

## Solution
- A local web UI on 127.0.0.1 that makes transcription accessible to
  non-technical users.
- Engine registry and settings model that expose real engine availability,
  configuration, and compatibility notes instead of hard-coded backend logic.
- Best-supported Apple Silicon MLX path for fast local processing, plus a real
  CPU Whisper path for Intel/Docker, a local Parakeet path for Linux + CUDA, and
  an optional Cohere cloud path.
- Sequential job queue with per-job `requested_engine`, `effective_engine`, and
  explicit language values so queued work remains truthful even when settings
  change later.
- Explicit job lifecycle transitions (reserve -> resolve -> running -> done/failed)
  so `started_at` and `effective_engine` are written intentionally once per job.
- Local storage of uploads, results, logs, settings, and job metadata with
  SQLite, plus best-effort Telegram delivery and update checks.
- A packaged macOS distribution path (self-contained `.app` + DMG) so a
  non-technical user can install, double-click, and use the same localhost UX
  without cloning the repo or installing Python.
- Shared output writers so engines can produce `.txt` by default and `.json`,
  `.srt`, or `.vtt` when real metadata exists.

## Target users
- Individuals or small teams with sensitive audio (legal, research, product,
  internal meetings).
- macOS Apple Silicon users who want the fastest local path.
- macOS Intel users who still want a practical local UI with CPU transcription.
- Linux + CUDA users who want Parakeet locally.
- Users who prefer a local UI but sometimes need an optional cloud transcription
  backend.
- Anyone who prefers a simple UI over managing ML CLI workflows.

## Key features
- Batch uploads via browser (files or folders) with preflight summary and
  filtering; queued, one-at-a-time processing.
- Batch-level language selector plus a persisted default language setting.
- Requested/effective engine tracking per job, exposed in the worker shell,
  queue, history, and preview metadata.
- Compact utility header with a short operational sentence plus a worker status
  area that stays quiet when idle and only shows queue depth, elapsed time,
  filename, and minimal engine/language context when that information helps.
- Compact top-level navigation for Queue, History, and Settings that stays
  usable on mobile while `/live` remains a direct beta-preview route.
- Distinct task surfaces: Queue is for adding work, History is for retrieving
  results, Settings is for configuration, and `/live` stays intentionally
  separate from the stable saved workflow.
- Shared visual chrome is intentionally calmer and flatter, so actions and
  transcript content read before decorative cards, shadows, and borders.
- The top shell avoids permanent “pill soup”: zero-value queue counts stay
  hidden, always-on mode labels are removed, and the worker area never shows
  more than two secondary metadata tokens at once.
- Queue-first onboarding that keeps one dominant “Select files…” action above
  the fold while preserving folder batch upload and drag-and-drop as secondary
  affordances.
- Upload selection summary now keeps the file count primary, hides skipped
  items when none were filtered out, and removes size/batch estimates from the
  default surface.
- Queue rows now collapse to a filename/status line plus one short contextual
  summary, replacing duplicate queue numbers and chip-heavy engine/language
  metadata with calmer scan-first labels.
- Compact History view with filename, one clear status marker, one primary row
  action, and quieter toolbar controls, while output formats and metadata move
  behind overflow actions or details.
- Details-on-demand panel is the canonical home for secondary history context:
  preview snippets, full timestamps, engine/language/backend metadata, output
  lists, and failure logs.
- Lazy-loaded transcript preview snippets to avoid loading full results for
  every job.
- History action menus (⋯) dismiss on outside click for faster triage.
- Per-item history deletion and bulk “delete all results” controls with
  confirmations, removing stored outputs from disk.
- Local data storage:
  - developer/repo mode: `data/` in the repo
  - packaged macOS app mode: `~/Library/Application Support/<bundle_id>/data/`
- Settings panel for engine selection, Whisper/Parakeet/Cohere configuration,
  default language, output formats, WTM quick mode, Telegram delivery, and local
  diagnostics, persisted in `data/settings.json` (dev) or
  `~/Library/Application Support/<bundle_id>/data/settings.json` (packaged).
- Settings now follow a clearer priority order: transcription defaults first,
  optional integrations second, local storage third, and diagnostics/update
  controls behind a calmer About / Advanced disclosure.
- Field-level source metadata is now demoted: editable controls lead with plain
  labels, env-locked values explain that they are managed by environment, and
  repeated restart warnings are collapsed into section-level notes.
- Cohere and Telegram now use status-first setup disclosures, so optional
  integrations read as compact summaries until the user explicitly opens masked
  setup details or clear actions.
- Final responsive QA tightened History row tap targets and reduced the empty
  Live transcript footprint so mobile and keyboard navigation stay calm,
  readable, and easier to operate.
- Storage now leads with cleanup actions while raw local paths live behind a
  disclosure; destructive buttons use plain labels and counts stay in muted
  helper text.
- Live preview now uses one clear status area, one action area, and one
  transcript area, with latency and chunk/window metrics removed from the
  default surface while the unsaved-session limitation stays explicit.
- UI copy across Queue, History, Settings, and Live is now shorter and more
  operational, reducing repeated local/beta/history explanations while keeping
  cloud behavior, environment locks, and destructive actions explicit.
- Settings -> About reflects the app version from `pyproject.toml`, so the UI
  stays in sync with the current local build/version bump.
- Runtime metadata reports which local Whisper and Parakeet models appear to be
  cached already, so the app can explain likely first-run downloads before jobs
  stall.
- Settings and the resolver keep the selected engine, compatibility notes, log
  level, output formats, update-check preference, and environment overrides
  aligned between saved settings and runtime snapshots.
- Local settings API endpoints for automation (read, update, and clear storage).
- Optional Telegram delivery of results without blocking the queue, configured
  via saved tokens or environment variables.
- Telegram delivery sends a single message with the transcript file attached
  and the original filename as the caption.
- Beta preview route for Live mode that communicates the intended future flow
  without implying microphone/browser capture is already implemented.
- Branded favicon in the browser tab for quick visual recognition of the local UI.

## Value proposition
- Local-first privacy: the default experience keeps the UI, storage, and local
  engines on the user's machine.
- Honest engine behavior: the app distinguishes local/offline engines from cloud
  processing instead of pretending every backend is equivalent.
- Speed and cost control: Apple Silicon MLX remains the premium local path, with
  CPU and cloud options when that path is unavailable.
- Operational simplicity: one-command setup on macOS, coherent settings, and a
  queue/history UX instead of raw CLIs.
- Reliability: sequential processing avoids model re-init churn and resource
  spikes, while compact history keeps large job lists responsive.

## Differentiators
- Apple Silicon MLX acceleration (faster than CPU-only alternatives).
- Real multi-engine registry with explicit compatibility and readiness metadata.
- Built-in queue/history flow optimized for scanning and triage, not just demos.
- Local-first product that still handles cloud transcription honestly when the
  user explicitly selects it.
- Optional CPU Docker backend and Intel macOS path for broader compatibility.

## Constraints and scope
- Native MLX backend requires macOS Apple Silicon.
- Parakeet currently requires Linux + CUDA + PyTorch + NeMo.
- Cohere requires network access, an API key, and an explicit supported
  language; it is not an offline backend.
- Designed for local, single-machine use; not a multi-user cloud service.
- Out of scope for v1: diarization, advanced timestamping, pause/cancel queue.
