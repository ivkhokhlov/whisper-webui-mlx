# Release staging layout

Before creating a macOS `.app` bundle, the build should assemble a clean,
disposable staging directory that contains only the runtime payload (source
code + templates + static assets + metadata), without embedding a Python
environment.

This staging step is the boundary that ensures the final `.app` bundle does
**not** depend on the repo root.

## Script

Use `scripts/stage_release_payload.py`:

```bash
python3 scripts/stage_release_payload.py --target macos-arm64 --clean
```

## Output layout

Default output location:

```text
dist/stage/<target>/
  stage_manifest.json
  payload/
    mlx_ui/
    docs/release/
    pyproject.toml
    requirements*.txt
    mel_filters.npz
```

Notes:
- The payload is an allowlisted copy (no `tests/`, no `data/`, no `dist/`, no
  local venv).
- `stage_manifest.json` is deterministic (sorted file list; no timestamps).
- Mutable runtime state is **not** staged (settings, DB, uploads, results, logs
  live in the user-writable runtime paths at execution time).
- The next build step can embed a self-contained Python runtime under
  `payload/runtime/` (see `docs/release/embedded_runtime.md`).
