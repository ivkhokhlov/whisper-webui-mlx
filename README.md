# whisper-webui-mlx (agent harness bootstrap)

This repo currently contains the **3-phase Codex harness** (Planner → Worker → Judge) to build a local macOS (M1+) WebUI around `whisper-turbo-mlx` / `wtm`.

## Quick start (app)
Run the minimal FastAPI app on localhost:
```bash
make run
```

## Tests and lint
```bash
make test
make lint
make fmt
```

## Quick start (agent loop)
```bash
bash scripts/codex_loop_3phase.sh 50
```

Watch progress:
```bash
bash scripts/status.sh
```

Stop the loop:
```bash
touch .agent/STOP
```

## Specs
See:
- `docs/spec.md`
- `.agent/PROJECT.md`
- `.agent/queue.md`
