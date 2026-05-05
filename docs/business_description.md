# Business Description

## Product overview
mlx-ui is a local-first transcription web application with a localhost UI,
sequential job processing, and a growing engine matrix. Users upload audio or
video files in batches, choose a job language, queue work, and retrieve results
from a queue/history flow backed by SQLite and on-disk artifacts. The product
still runs on `127.0.0.1` and keeps uploads, results, settings, and logs on the
local machine, but it now supports both local engines and an optional cloud
engine. On macOS, the engine story is explicit:

- Apple Silicon (arm64): local Whisper MLX and local Parakeet MLX
- Intel (x86_64): local Whisper CPU
- Cohere: optional cloud transcription (uploads audio)
- Legacy Parakeet NeMo/CUDA: experimental/internal only (Linux + CUDA), disabled by default
- DGX Spark Parakeet CUDA profile: repo-only Docker path for Linux/NVIDIA hosts

In developer/repo mode, mutable runtime state lives under `data/` inside
the repo. In packaged macOS app mode, the same mutable state lives under
`~/Library/Application Support/<bundle_id>/data/` so the `.app` bundle and its
embedded payload remain read-only. Recent work added a real provider registry,
per-job engine persistence, per-job engine resolution in the worker, normalized
transcript outputs, local model readiness metadata, and UI badges that show
which engine and language each job used. The `/live` route remains an honest
beta preview rather than a production capture workflow. Ongoing refactors keep
the app maintainable while preserving the same UI/API contract, including an
app-factory bootstrap path, focused routers, provider modules per engine, and
template partials. Repo/dev mode also treats transient workspace automation
artifacts as untracked local state, keeping operational traces out of the
shared project history while preserving the same user-facing data flow.
Repo bootstrap is also designed to avoid accidental "Python drift" between
machines: `./run.sh` downloads a portable CPython 3.12 runtime into
`./.runtime/python` (gitignored) and uses it to create/manage `./.venv`, so the
default developer setup does not depend on a system/Homebrew Python install.

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
- Best-supported Apple Silicon local path (Whisper MLX + Parakeet MLX), plus a
  practical Whisper CPU path for Intel/Docker, plus an optional Cohere cloud
  engine.
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
- A DGX Spark-oriented Docker profile for experimental Parakeet NeMo/CUDA
  deployments on Linux/NVIDIA hosts, with separate `data-spark` state, seeded
  Parakeet settings, Hugging Face cache reuse, and localhost-only binding.

## Target users
- Individuals or small teams with sensitive audio (legal, research, product,
  internal meetings).
- macOS Apple Silicon users who want the fastest local path.
- macOS Intel users who still want a practical local UI with CPU transcription.
- Users who prefer a local UI but sometimes need an optional cloud transcription
  backend.
- Anyone who prefers a simple UI over managing ML CLI workflows.

## Key features
- Batch uploads via browser (files or folders) with preflight summary and
  filtering; queued, one-at-a-time processing.
- Optional “hot folder” ingestion: watch an input folder, move detected
  audio/video files into the queue for processing, and export `.txt`
  transcripts into a configured output folder (mirrors subfolders; restores the
  input file on failed jobs). In repo/dev mode, hot folder defaults to
  `./input` → `./output` and is enabled automatically.
- Batch-level language selector plus a persisted default language setting.
- Requested/effective engine tracking per job, exposed in the queue/history
  lists and preview metadata.
- Compact utility header with a short operational sentence plus a worker status
  pill that stays a fixed height and only reflects the global worker state
  (Idle/Running/Stopping), while per-job details and controls live in the Queue
  list.
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
- Queue upload uses one large drag-and-drop target that also opens the file
  picker on click, reducing redundant buttons while preserving folder batches
  via drag-and-drop.
- Upload selection summary now keeps the file count primary, hides skipped
  items when none were filtered out, and removes size/batch estimates from the
  default surface.
- Queue rows now collapse to a filename/status line plus one short contextual
  summary, replacing duplicate queue numbers and chip-heavy engine/language
  metadata with calmer scan-first labels.
- Task status colors now follow semantic design-system tokens, so running work
  reads as active/success, failed work stays clearly error-coded, and idle or
  queued states remain visually neutral.
- Active and queued work now has direct control affordances: the active queue
  row exposes a stop icon button for the running task, queued rows use subtle
  icon-only remove buttons, and both flows route through confirmation modals so
  mistakes are recoverable before local files are deleted.
- Cancelling a running job now uses a real backend API path with worker-owned
  cleanup semantics, including a transient `Stopping` state, removal of partial
  outputs, and a cancelled history entry instead of leaving hidden orphaned
  records in SQLite.
- Running work now shows a small indeterminate activity spinner alongside the
  elapsed timer in the active queue row, reusing the shared loader primitive
  and disabling the animation automatically when the system requests reduced
  motion.
- Main navigation is now typography-led instead of container-led: Queue,
  History, and Settings sit directly on the page background with lighter
  spacing, a thin active underline, and stronger active weight instead of a
  boxed segmented strip.
- Queue form polish now treats the file-count summary as muted inline text,
  moves cloud-upload guidance into a small info tooltip beside the Language
  field, and keeps disabled queue actions readable without looking active.
- The Queue intake area now scales with workload: it stays prominent when idle
  and collapses into a tighter banner once jobs are queued or running, giving
  the worker and queue list more vertical priority without removing drag/drop.
- Compact History view with filename, one clear status marker, one primary row
  action, and quieter toolbar controls, while output formats and metadata move
  behind overflow actions or details.
- History result links now URL-encode job IDs and filenames, so result files
  with spaces or other path-sensitive characters download through the same
  queue/history UI instead of requiring manual filesystem access.
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
  integrations stay understandable at a glance without exposing setup detail
  until the user asks for it.
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
- Clear onboarding: the repo documentation stays text-first, so setup steps,
  engine tradeoffs, and release paths are readable without relying on embedded
  demo media.
- Reliability: sequential processing avoids model re-init churn and resource
  spikes, while compact history keeps large job lists responsive.

## Differentiators
- Apple Silicon MLX acceleration (faster than CPU-only alternatives).
- Real multi-engine registry with explicit compatibility and readiness metadata.
- Built-in queue/history flow optimized for scanning and triage, not just demos.
- Local-first product that still handles cloud transcription honestly when the
  user explicitly selects it.
- Optional CPU Docker backend and Intel macOS path for broader compatibility.
- Experimental DGX Spark Parakeet CUDA deployment profile for users with local
  NVIDIA infrastructure who want a browser queue around NeMo Parakeet.

## Constraints and scope
- Native MLX backends require macOS Apple Silicon.
- Parakeet MLX requires macOS Apple Silicon and the optional `parakeet-mlx`
  dependency (the packaged `macos-arm64` artifact embeds it; repo bootstrap is
  opt-in via `--with-parakeet-mlx`).
- Legacy Parakeet NeMo/CUDA is retained for internal/experimental Linux CUDA
  flows only; it is disabled by default and not part of the macOS bootstrap or
  packaged release targets. The Spark Docker profile keeps this path separate
  from the supported macOS release flow and normalizes non-ready media through
  `ffmpeg` into 16 kHz mono WAV before Parakeet inference.
- Cohere requires network access, an API key, and an explicit supported
  language; it is not an offline backend.
- Designed for local, single-machine use; not a multi-user cloud service.
- Out of scope for v1: diarization, advanced timestamping, queue pause/resume.
