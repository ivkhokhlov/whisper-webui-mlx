RFC 0003: Worker Status Card: Deduplicate Status and Truncate Filenames

Problem statement

The Worker Status Card (top-right panel on the main page) currently shows redundant and layout-breaking information when the worker is running:

- Redundant status text: the status is rendered as a large heading ("Running") and then repeated again in the detail line directly before the filename (effectively "Running <filename>").
- Layout shift with long filenames: long filenames wrap onto a second line instead of staying on one line, which disrupts vertical rhythm and can misalign the elapsed timer (e.g., `00:03`).

Motivation

This panel is always visible and is used as a quick glance indicator. Redundant text adds visual noise, and layout shifts make the UI feel unstable. Fixing both issues improves readability and perceived UI quality without changing any backend behavior.

Goals

- When the worker is running, show the status exactly once (in the status heading), without repeating it in the detail line.
- Keep the running detail line to a single visual line regardless of filename length.
- Truncate long filenames with an ellipsis while keeping the full filename accessible (e.g., via `title` and screen-reader label).
- Preserve the current idle-state message and overall card layout.

Non-goals

- Changing worker state semantics, status names, or backend APIs (`/api/state`).
- Redesigning the Worker Status Card beyond the detail-line rendering and its text overflow behavior.
- Introducing new UI elements (icons, tooltips beyond existing `title`, or additional metadata such as queue length).

Proposed design

Update the Worker Status Card’s detail-line rendering (server and client) and apply single-line truncation styling for filenames.

External behavior / user-facing impact

- Running state:
  - Status heading remains `Running`.
  - Detail line shows `<filename> · <elapsed>` (when elapsed is available), without a leading `Running` prefix.
  - Long filenames are truncated with `…` and do not wrap to a second line.
- Idle state:
  - Detail line remains the existing idle message ("Sequential queue, one job at a time.").

HTML/JS rendering changes

- Server-rendered HTML (`mlx_ui/templates/index.html`):
  - Remove the `worker-detail-prefix` span from the running branch so only the filename is rendered.
- Client-side updates (`setWorkerDetailRunning` in `mlx_ui/templates/index.html`):
  - Stop generating/appending the `worker-detail-prefix` element.
  - Keep setting `title` and `aria-label` to the full filename.
  - Keep the elapsed element (e.g., `· 00:03`) unchanged.

CSS changes (single-line truncation)

- Replace the current multi-line clamping behavior for `.worker-filename` with a single-line ellipsis strategy:
  - `white-space: nowrap`
  - `overflow: hidden`
  - `text-overflow: ellipsis`
  - Ensure flexbox shrink works (keep/verify `min-width: 0` on the filename element).
- Prevent the detail row from wrapping into multiple flex lines so the elapsed timer remains aligned on the same row.

Compatibility considerations

- This is a purely presentational change and is backwards compatible.
- Ellipsis behavior should work in modern browsers; ensure flex-item shrink is enabled (`min-width: 0`) so ellipsis triggers reliably.

Security and privacy considerations

None. This only changes how already-present data (status and filename) is displayed.

Implementation plan

1. Update server-rendered markup in `mlx_ui/templates/index.html` to remove the `worker-detail-prefix` span from the running branch.
2. Update `setWorkerDetailRunning(filename, elapsed)` in `mlx_ui/templates/index.html` to render only the filename and elapsed (no status prefix).
3. Update CSS in `mlx_ui/templates/index.html`:
   - Change `.worker-filename` to a single-line ellipsis configuration.
   - Update `.worker-detail` to prevent wrapping across flex lines while preserving baseline alignment.
4. Manually verify:
   - Running state shows `Running` only once (heading), and the detail row reads as `<filename> · <elapsed>`.
   - Very long filenames remain on one line with ellipsis and do not shift the card height.
   - Elapsed timer remains visible and aligned on the same row.
   - Hovering the filename shows the full value via `title`; screen readers can access the full name via `aria-label`.

Testing strategy

- Manual UI verification on the main page:
  - Use a long filename (including spaces) and confirm it truncates with ellipsis on a single line.
  - Confirm no duplicate "Running" appears in the detail row.
  - Confirm the elapsed timer does not wrap to a new line.
- No automated tests are required (presentation-only change).

Acceptance criteria

- When worker status is `Running`, the Worker Status Card shows `Running` only in the status heading and not in the detail line.
- When running with a long filename, the detail line remains one line and the filename is truncated with an ellipsis.
- The elapsed timer remains on the same line as the filename and does not shift vertically due to filename length.
- The full filename remains accessible via `title` and is announced via `aria-label`.
- Idle state display remains unchanged.

Risks

- Truncation hides parts of filenames that may be important for disambiguation. Mitigation: preserve `title`/`aria-label` with the full filename.
- Ellipsis may fail in some flex layouts if shrink is not enabled. Mitigation: keep/verify `min-width: 0` on the filename element and prevent flex-line wrapping in the detail row.

Open questions

- Should the detail line be allowed to wrap on extremely narrow viewports, or must it remain single-line even if that reduces the visible filename to only `…`?
