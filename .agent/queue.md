# Queue

## Now

## Next

## Later

## Done
- [x] WUI-090 — Live mode skeleton (acceptance: UI has “Live” page stub + technical plan in docs; no implementation yet)
- [x] WUI-050 — Update check at startup (acceptance: if online, checks for updates with timeout; if offline, no errors and app works)
- [x] WUI-040 — Telegram delivery (acceptance: when env vars are set, send TXT + message; failures do not break pipeline; secrets masked)
- [x] WUI-030 — One-command setup & run on M1+ macOS (acceptance: `./scripts/setup_and_run.sh` installs deps, downloads models, starts server, and opens browser)
- [x] WUI-021 — Results browsing + download (acceptance: history page shows per-job links to view/download TXT and other generated formats)
- [x] WUI-020 — Integrate `wtm` CLI transcription (acceptance: for a job, system runs `wtm` with chosen language and produces at least `.txt` in `data/results/<job_id>/`)
- [x] WUI-012 — Sequential worker + fake transcriber (acceptance: single worker processes jobs strictly one-at-a-time; tests do not require ML model)
- [x] WUI-011 — Persistent job store (SQLite) (acceptance: jobs survive server restart; history page lists prior jobs)
- [x] WUI-010 — Upload endpoint + local storage (acceptance: user can upload multiple files; files saved under `data/uploads/` and jobs are created)
- [x] WUI-002 — Minimal WebUI shell (acceptance: localhost page renders with tabs: Queue + History, using server-side templates)
- [x] WUI-001A — Fix pytest availability for `make test` (acceptance: `make test` succeeds in a clean env by ensuring pytest is installed or Makefile uses Poetry/venv)
- [x] WUI-001 — Bootstrap repo skeleton (acceptance: `make test` passes with a minimal FastAPI app + 1–3 tests, and docs/agent harness files exist)
