# UI Noise Audit

## Scope

Baseline audit of the current FastAPI + Jinja2 + vanilla JS product surfaces
before any UI refactor. This pass is based on live browser inspection at
`127.0.0.1`, template review, and screenshots captured at desktop and mobile
widths.

Capture notes:

- Desktop width: 1440px
- Mobile width: 390px
- Queue was captured with seeded queued items in a disposable runtime so the
  queue-state density is visible without mutating repo product code or the real
  runtime data.
- History and Settings were captured against real existing history volume.
- `/live` was captured in its current disabled beta state.
- The user-provided History screenshot with a running worker confirms the same
  pattern: once the worker is active, the worker card adds even more chips and
  metadata above already dense content.

## Screenshot Files

| Surface | Desktop | Mobile |
| --- | --- | --- |
| Queue | `docs/ui_noise_audit_screenshots/queue-desktop.png` | `docs/ui_noise_audit_screenshots/queue-mobile.png` |
| History | `docs/ui_noise_audit_screenshots/history-desktop.png` | `docs/ui_noise_audit_screenshots/history-mobile.png` |
| Settings | `docs/ui_noise_audit_screenshots/settings-desktop.png` | `docs/ui_noise_audit_screenshots/settings-mobile.png` |
| Live | `docs/ui_noise_audit_screenshots/live-desktop.png` | `docs/ui_noise_audit_screenshots/live-mobile.png` |

## Cross-Surface Patterns

- Redundant numbers and metrics: queue depth appears in the worker card, panel
  header, and queue rows; History rows combine relative time plus duration; Live
  repeats availability, latency, engine, and beta-state metrics in multiple
  places.
- Chip and pill overload: status, engine, language, queue position, source, and
  output pills compete with the primary task almost everywhere.
- Repeated explanatory copy: the same local/cloud, beta, restart-required, and
  “saved locally” concepts are restated in hero copy, panel intros, field
  hints, and footer copy.
- Loud treatment everywhere: nearly every section uses a rounded card, border,
  tint, and shadow, so hierarchy flattens and everything asks for equal
  attention.
- System metadata is louder than the task: worker state, source badges,
  diagnostic paths, model cache info, and runtime labels often outrank the main
  user goal of queueing, finding, or configuring work.
- Mobile amplifies the problem: stacked cards and persistent helper copy push
  primary controls below the fold faster than necessary.

## Queue

### What should stay

- The core upload flow: select files, select folder, drag-and-drop.
- A visible language selector before queueing.
- Clear separation between upload controls and queued items.
- A plain local/cloud trust signal somewhere near the submit action.

### What should be simplified

- The worker card, queue count badge, and per-row queue math repeat the same
  story too many times.
- The empty/selection summary chips (`0 files`, `0 B`, `Small batch`,
  `Skipped 0`) are noisy before the user has picked anything.
- The upload card uses too many helper lines for one task: select, drop, folder
  behavior, formats, batch note, language note, and processing note.
- Per-row chips stack status, queue order, items ahead, engine, and language
  into a visually busy strip.

### What should move behind progressive disclosure

- “Skipped” explanation and supported-format detail.
- Queue order math beyond the next actionable signal.
- Detailed engine/source labels for queued rows.
- Secondary folder-upload guidance after the user already chose a method.

### Top 3 highest-leverage fixes

1. Collapse pre-selection metrics and helper text into one short line until
   files are actually chosen.
2. Reduce queue rows to filename, status, and one compact metadata line instead
   of a chip cluster.
3. Demote the worker card so Queue owns the page, with queue depth shown once.

## History

### What should stay

- Search, status, and sort controls.
- Preview and Download as the default primary actions.
- Inline failed-state visibility.
- Details-on-demand for logs and outputs.

### What should be simplified

- Every row repeats status chip, output chip, time string, engine chip,
  language chip, details affordance, overflow affordance, and actions.
- Relative time plus duration in the same line is useful but visually dense
  across a long list.
- The toolbar labels, inputs, and delete action all share similar emphasis.
- Worker metadata at the top competes with the task of scanning history.

### What should move behind progressive disclosure

- Output format pills when there is only one obvious default output.
- Engine/backend metadata for successful jobs.
- Full timeline and output list until a row is expanded.
- Overflow actions beyond preview/download.

### Top 3 highest-leverage fixes

1. Turn each row into a tighter two-line scan pattern with one primary action
   group and one secondary metadata line.
2. Reserve chips for exceptions: failed, cloud, or unusual language/runtime,
   instead of using chips for every normal row.
3. Make the toolbar and destructive action quieter than the results list.

## Settings

### What should stay

- High-level grouping by Engine, Transcription, Cohere, Notifications, Storage,
  and About.
- Clear separation of destructive actions.
- A visible save bar.
- The About section as the home for runtime diagnostics.

### What should be simplified

- Source pills on nearly every field (`FILE`, `DEFAULT`, `MISSING`) create a
  badge wall that is harder to parse than the settings themselves.
- Hint copy is too long and too frequent; most cards read like documentation,
  not settings.
- Storage paths and destructive counts are visually louder than routine
  configuration.
- Current masked token/chat values add another metadata layer on an already
  crowded form.
- Some settings are not understandable at a glance because the useful decision
  is mixed with implementation detail:
  - Engine selection is mixed with compatibility notes, active-now notes,
    model-cache notes, and WTM command diagnostics.
  - Cohere mixes setup status, SDK availability, source, API key, and model ID
    with equal weight.
  - Telegram mixes enablement, provenance, masked current values, and clear
    toggles before explaining the outcome.

### What should move behind progressive disclosure

- Source provenance details.
- WTM command, model cache, SDK availability, and masked current values.
- Full storage paths.
- Advanced destructive actions.
- Log-level and update-check explanations beyond a short one-line summary.

### Top 3 highest-leverage fixes

1. Replace per-field source pills with one section-level “managed by file/env”
   summary.
2. Rewrite helper copy into short decision-oriented text, then move diagnostics
   into collapsible “advanced details.”
3. Split the page into “everyday defaults” and “advanced/runtime” so the first
   screen answers only the common decisions.

## /live

### What should stay

- The honest beta framing.
- A single primary capture area with Start/Stop.
- A direct path back to Queue.
- Clear separation between current capability and future intent.

### What should be simplified

- The disabled state repeats “experimental,” “preview,” and “not active”
  messaging in the hero, status card, main note, transcript placeholder, and
  lower explainer cards.
- Engine/local/auto/latency chips remain loud even when capture is unavailable.
- The page uses several explanatory sections to say one thing: this feature is
  off and Queue is the stable path.

### What should move behind progressive disclosure

- Flag/environment instructions.
- Beta scope and “what works now” lists.
- Model and latency metadata when the feature is disabled.

### Top 3 highest-leverage fixes

1. Compress the disabled state into one banner plus one disabled control block.
2. Keep only one explanation of why Live is unavailable, with an expandable
   “beta details” section below.
3. Remove non-actionable chips and metrics when the feature is off.

## Highest-Leverage Product-Wide Fixes

1. Establish one clear hierarchy rule: primary task first, diagnostics second,
   provenance third.
2. Reduce chip usage by at least half and reserve pills for exceptions,
   warnings, or true state changes.
3. Convert repeated helper paragraphs into short summary lines with optional
   progressive disclosure for advanced detail.
