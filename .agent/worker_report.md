# Worker Report

- Task: WUI-030 — One-command setup & run on M1+ macOS
- What changed:
  - Added `scripts/setup_and_run.sh` to install deps, install `wtm`, prefetch model weights, and run the server + open browser.
  - Documented the one-command setup in `README.md` and `docs/dev.md`.
  - Updated `docs/tree.md` to include the new script.
- Files changed:
  - scripts/setup_and_run.sh
  - README.md
  - docs/dev.md
  - docs/tree.md
- Commands run:
  - `make test` (pass) -> .agent/logs/test_10.log
  - `make lint` (pass) -> .agent/logs/lint_10.log
- Failures: none
