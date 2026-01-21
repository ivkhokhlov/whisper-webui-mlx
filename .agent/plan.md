# Plan

Task: WUI-012 — Sequential worker + fake transcriber
Acceptance: single worker processes jobs strictly one-at-a-time; tests do not require ML model

Assumptions:
- A background loop can run in-process (thread or asyncio task) on app startup to poll queued jobs.
- Fake transcriber can write a stub TXT result under `data/results/<job_id>/result.txt` without calling `wtm`.

Implementation steps:
- Add DB helpers to fetch the next queued job and update job status (queued/running/done/failed) atomically.
- Implement a single worker loop that polls for queued jobs, marks one running, runs the fake transcriber, then marks done or failed.
- Guard the worker with a single global lock or singleton to prevent concurrent execution.
- Create a small fake transcriber module that writes a deterministic TXT result for each job.
- Wire the worker startup into FastAPI startup so it begins processing uploads automatically.
- Add tests that enqueue multiple jobs and assert they complete sequentially without parallel execution or real ML model calls.
- Update `docs/tree.md` if new modules or data directories are added.
- Record test/lint results in `.agent/worker_report.md`.

Files likely to touch:
- `mlx_ui/app.py`
- `mlx_ui/db.py`
- `mlx_ui/worker.py` (new)
- `tests/test_worker.py` (new) or `tests/test_app.py`
- `docs/tree.md`
- `.agent/worker_report.md`

Verification:
- `make test`
- `make lint`
