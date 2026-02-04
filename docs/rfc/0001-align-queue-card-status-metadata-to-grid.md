RFC 0001: Align Queue Card Status Metadata to Grid

Problem statement

Queue list cards in the Queue tab do not align status metadata to the visual grid. The status label (RUNNING/QUEUED) drifts off the right edge and is not aligned under other right-column elements. The timer text and the trash icon are not aligned with the bottom informational line ("1 item ahead"), causing inconsistent vertical rhythm and a misaligned right edge across cards.

Motivation

This is a high-visibility part of the UI and users scan it frequently. Misalignment reduces legibility and makes the queue look unstable. Aligning the right column to the grid improves clarity and perceived quality without changing functionality.

Goals

- Align the status label to the top-right of each queue card, anchored to the right edge.
- Align the elapsed timer (running) and trash icon (queued) to the bottom-right of the card on the same visual row as the queue line (e.g., "1 item ahead").
- Ensure all right-column elements stack vertically in a single right-aligned column.
- Maintain current responsive behavior and text content.

Non-goals

- Changing queue ordering, statuses, or business logic.
- Altering status labels, icons, or copy.
- Redesigning the overall card layout beyond alignment.

Proposed design

Implement a dedicated right-column layout for queue cards and align it to the grid of the left column.

- Convert `.job-row` to a grid layout with explicit columns for icon (optional), body, and actions.
  - Example: `grid-template-columns: auto 1fr minmax(88px, max-content)` with a consistent column gap.
  - Preserve existing padding and border styles.
- Rework `.job-actions` to a two-slot vertical layout that aligns with the top and bottom of the card.
  - Use `display: grid` or `display: flex` with `justify-content: space-between` and `align-items: flex-end`.
  - Place `.job-status` in the top slot; place `.job-elapsed` or `.job-bin` in the bottom slot.
  - Ensure `justify-self: end` / `text-align: right` for right-edge alignment.
- Remove `align-self: center` from `.job-status` so it aligns to the top of the column.
- Align the bottom slot to the same baseline as the queue line:
  - Keep line-height consistent across `.job-queue`, `.job-elapsed`, and the icon button label height.
  - If needed, add a shared utility (e.g., `.job-actions-bottom`) to enforce baseline alignment.
- Keep the DOM structure consistent between server-rendered HTML and the JS template builder.
  - Update both the Jinja template and the client-side `buildQueueActions` / `buildQueueRow` output to match the new right-column structure.

External behavior / user-facing impact

- Status text is visibly aligned to the top-right of each queue card.
- Timer and trash actions align to the bottom-right, on the same horizontal level as the "items ahead" line.
- Right column no longer appears to drift or overflow.

APIs and interfaces

No changes to backend APIs or data models. Changes are limited to HTML structure and CSS.

Data model changes

None.

Operational considerations

None. This is a purely presentational change.

Security and privacy considerations

None.

Implementation plan

1. Update `.job-row` layout to a grid-based layout with an explicit right column for actions in `mlx_ui/templates/index.html`.
2. Rework `.job-actions` styling to align top and bottom slots, and remove centering behavior for `.job-status`.
3. Introduce any small utility classes needed to align baselines (e.g., shared line-height for bottom-row elements).
4. Update server-rendered markup in the queue list to wrap right-column elements in the new structure.
5. Update the client-side template builders (`buildQueueActions`, `buildQueueRow`) to emit the same structure.
6. Manually verify alignment in the Queue tab for both running and queued jobs (including with and without "items ahead").

Testing strategy

- Manual UI verification on the Queue tab:
  - Running card: status top-right, elapsed timer bottom-right aligned with the last left-column line.
  - Queued card: status top-right, trash icon bottom-right aligned with the "items ahead" line.
  - Multiple cards: right edge alignment is consistent across the list.
- No automated tests required (presentation-only change).

Acceptance criteria

- Status labels are right-aligned and pinned to the top-right corner of each queue card.
- The elapsed timer and the trash icon are right-aligned and share the same horizontal row as the queue line.
- Right-column elements stack vertically without overlap or overflow.
- Server-rendered and client-rendered queue rows appear identical.

Risks

- CSS grid changes could slightly affect spacing on very narrow viewports.
- Baseline alignment might require small line-height adjustments to avoid visual jitter.

Open questions

- Confirm that the elapsed timer should align to the bottom-right (same row as the queue line) for running cards.
- Confirm whether the bottom alignment should match the queue line or the last meta line when a running card has no queue line.
