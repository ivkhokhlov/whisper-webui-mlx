# RFC — History Delete Controls

Status: Draft
Owner: TBD
Created: 2026-01-25

## Summary
Add per-item delete actions and a "Delete all results" control in the History tab so users can remove completed jobs (and their artifacts) from local storage.

## Motivation
History grows quickly and can contain sensitive transcripts. Users need a fast way to remove a single item or wipe history entirely without leaving results files behind.

## Goals
- Add a per-item delete action in the History row menu.
- Add a "Delete all results" (delete all) control in the History header.
- Deleting a history item removes stored outputs first; the DB row is removed only after file deletion succeeds.
- Any leftover upload path is cleaned up if present.
- Actions are confirmed and show success/failure feedback.
- Queue and running jobs remain unaffected.

## Non-goals
- Deleting queued or running jobs (still handled by the queue removal flow).
- Undo/restore, recycle bin, or backups.
- Bulk multi-select (beyond clear-all).
- Remote sync or multi-user permissions.

## UX / Information Architecture
- **History header:** Add a right-aligned "Delete all results" button near the title/description.
  - Disabled/hidden when there are no history entries.
  - Confirmation copy calls out that outputs will be deleted (and what is *not* removed).
- **Row menu:** Add a "Delete" action in the existing ellipsis menu.
  - Confirmation dialog: "Delete this history item and its outputs?"
- **Feedback:** Use the existing toast/notify system for success and failure.
- **Empty state:** After deletion, show the existing placeholder when the list is empty.

## Data Model
No schema changes.
- Job records live in `data/jobs.db` (table `jobs`).
- Results live in `data/results/<job_id>/`.
- Uploads may already be cleaned, but any leftover `data/uploads/<job_id>/` should be removed on delete.

## API / Backend
Proposed endpoints:
- `DELETE /api/history/{job_id}`
  - Validates `job_id` as a safe path component.
  - Only allows status in `{done, failed}` (future-proof for `{cancelled}` if added to History).
  - Removes `data/results/<job_id>/` first; if file deletion fails, the DB row stays.
  - On success, removes the DB row and any leftover upload path.
  - Returns `{ ok: true }` plus optional warnings.
- `POST /api/history/clear`
  - Deletes all history jobs (status `{done, failed}`) and their results directories.
  - Rows stay if file deletion fails for a job.
  - Returns `{ ok: true, deleted_jobs: N, deleted_results: N, failed_results: M }`.

Implementation notes:
- Add DB helpers:
  - `list_history_jobs(db_path) -> list[JobRecord]`
  - `delete_history_job(db_path, job_id) -> bool`
  - `delete_history_jobs(db_path, job_ids) -> int`
- Results removal uses safe path checks similar to download handlers.
- Do not remove DB rows if file deletion fails; surface an error so the UI stays honest.

## Security & Privacy
- Localhost-only, no secrets involved.
- Destructive actions require confirmation.
- Safe path validation prevents directory traversal when deleting files.

## Rollout Plan
1) Add backend endpoints + DB delete helpers with tests.
2) Add History UI controls and wire the actions to API calls.
3) Add copy/confirmation text and finalize styling.

## Open Questions
- Should we offer a "remove from history but keep files" option?
- Should "Delete all results" share the same endpoint as Settings "Clear results," or remain distinct for clarity?
- Should history include `cancelled` jobs, and if so, should delete apply to them too?
