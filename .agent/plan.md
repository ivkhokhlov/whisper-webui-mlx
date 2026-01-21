# Plan

Task: WUI-040 — Telegram delivery
Acceptance: when env vars are set, send TXT + message; failures do not break pipeline; secrets masked

Assumptions:
- Telegram config is provided via environment variables and can be accessed from the worker process.
- Each completed job has a deterministic `.txt` result path to attach.

Implementation steps:
1) Inspect the worker completion flow to find where result paths are available and where to hook delivery.
2) Add a small config helper to read `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID`, plus a masking helper for logs.
3) Implement Telegram send helper with a short timeout; send a message plus the `.txt` file; catch and log failures without raising.
4) Call the helper after successful transcription; skip if config missing or `.txt` is absent; ensure pipeline continues.
5) Add tests with mocked HTTP calls to cover success, missing config (no call), and failure (no exception, masked logs).
6) Update docs to note the env vars if not already documented.

Files likely to touch:
- `mlx_ui/worker.py`
- `mlx_ui/transcriber.py` or `mlx_ui/app.py`
- `tests/test_worker.py`
- `README.md` or `docs/dev.md`

Verification steps:
- `make test`
- `make lint`
