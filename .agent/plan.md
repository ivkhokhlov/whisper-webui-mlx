# Plan

Task: WUI-090 - Live mode skeleton
Acceptance: UI has “Live” page stub + technical plan in docs; no implementation yet

Assumptions:
- Live mode is a UI stub only; no recording, chunking, or worker changes in this task.
- Adding a "Live" tab alongside Queue/History is acceptable.

Implementation steps:
1) Add a /live route in the FastAPI app that renders a new template with stub copy and a clear "coming soon" status.
2) Create a Jinja template for the Live page and add a navigation link/tab to it in the shared layout.
3) Document a short technical plan for Live mode (browser capture → chunking → server ingestion → sequential transcription) in docs.
4) Add a minimal test that asserts the /live page renders (and optionally that nav includes Live).
5) Update docs/tree.md if any new files are added.

Files likely to touch:
- mlx_ui/app.py
- mlx_ui/templates/base.html
- mlx_ui/templates/live.html
- tests/test_app.py
- docs/spec.md or docs/dev.md or docs/live.md
- docs/tree.md

Verification steps:
- make test
- make lint
