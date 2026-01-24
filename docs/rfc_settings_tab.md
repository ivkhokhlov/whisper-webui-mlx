# RFC — Settings Tab

Status: Draft
Owner: TBD
Created: 2026-01-24

## Summary
Introduce a Settings tab in the main UI, pinned to the right of the tab bar, to surface and manage runtime configuration in a local-only, safe way. The tab should be distinct from the Queue/History flow and remain accessible on both the main and Live pages.

## Motivation
Users need a single place to understand and adjust runtime behavior (update checks, transcription defaults, notification status) without hunting through environment variables or docs. A Settings tab improves discoverability, reduces setup friction, and makes configuration explicit while keeping secrets safe.

## Goals
- Add a Settings tab pinned to the right of the main tab list (Queue/History on the left, Settings on the right).
- Provide a read/write UI for non-secret settings.
- Show effective values and their sources (defaults vs environment vs settings file).
- Persist configurable values locally and apply them to new jobs without restarting when safe.
- Keep the UI local-only and offline-first.

## Non-goals
- No cloud sync or remote profiles.
- No in-browser editing of secrets (tokens must remain in env vars).
- No multi-user authentication or role management.
- No dynamic changes that reconfigure an in-flight transcription job.

## UX / Information Architecture
The Settings tab is its own panel, visually separated from Queue/History. Proposed sections:

1) General
- Update check toggle (maps to `DISABLE_UPDATE_CHECK`).
- Log level selector (`LOG_LEVEL`) with a short hint.
- Open data folder shortcut.

2) Transcription
- `WTM_QUICK` toggle with a performance/quality hint.
- Default output formats (txt, srt, vtt, json) as checkboxes.
- Language mode: keep `any_lang` as the only option for now (read-only).

3) Notifications
- Telegram status (Configured / Missing) derived from env vars.
- Test send button (no secrets shown; masked token).

4) Storage
- Data paths summary (`data/uploads`, `data/results`, `data/jobs.db`, `data/logs`).
- Clear uploads/results actions with confirmation.

5) About
- App version, build date, and `wtm` binary path.

## Data Model
Persist settings in a new local file:
- Path: `data/settings.json`
- Schema (example):
  - `update_check_enabled`: boolean
  - `log_level`: string
  - `wtm_quick`: boolean
  - `output_formats`: array of strings

Environment variables override persisted settings. The UI should show the effective value and the source (Env / File / Default).

## API / Backend
- `GET /api/settings` returns effective settings + source metadata.
- `POST /api/settings` updates allowed fields and writes to `data/settings.json`.
- Server should validate values and ignore unknown keys.

## Security & Privacy
- Never display secrets; mask tokens and only show presence/absence.
- Localhost-only; no external network calls unless explicitly triggered (e.g., Telegram test).
- Actions that delete data must include confirmation steps.

## Rollout Plan
1) Ship the Settings tab UI with a stub panel and RFC-driven placeholder.
2) Add `data/settings.json` persistence and `GET /api/settings` read-only.
3) Enable editing for safe fields and `POST /api/settings`.
4) Add data management actions and Telegram test.

## Open Questions
- Should settings changes apply immediately to the worker, or only for new jobs?
- Which output formats are guaranteed by `wtm` across models?
- Should update checks be opt-in or opt-out by default?
