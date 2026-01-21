# AGENTS.md

This repo is developed using an autonomous loop (Planner → Worker → Judge) driven by `codex exec`.
Because each run starts with limited context, **durable state MUST be stored in `.agent/`**.

## Source of truth
- `.agent/PROJECT.md` — high-level constraints and commands
- `docs/spec.md` — product requirements
- `.agent/queue.md` — backlog (Judge marks tasks done)

## How to run
- Tests: `make test`
- Lint: `make lint`
- Format: `make fmt`
- Run server: `make run`

If Makefile does not exist yet, create it during bootstrap.

## Safety / security rules
- Never touch anything outside the repo root.
- Never read or print secrets. If Telegram token exists in `.env`, always mask it in logs/UI.
- Bind server to `127.0.0.1` only (localhost only).
- After initial setup and model download, the app must work fully offline.
- Telegram and update check must be best-effort; failures must not break the pipeline.

## Engineering rules
- Keep tasks incremental and test-driven where practical.
- Do not introduce parallel transcription. One sequential worker only.
- Prefer clear, maintainable code over cleverness.
- Tests must not require the real ML model by default; mock `wtm` execution unless running explicit integration tests.
- Always update `docs/tree.md` when repo structure changes.
