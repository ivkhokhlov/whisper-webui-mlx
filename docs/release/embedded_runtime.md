# Embedded runtime (macOS release stages)

Packaged macOS artifacts should ship with a self-contained Python runtime so the
end-user does **not** need Homebrew or a system Python.

This repo’s packaging flow is split into two deterministic build steps:

1. Stage a clean payload (code + templates + static + metadata) with
   `scripts/stage_release_payload.py`.
2. Embed a target-aware Python environment (Python prefix + venv + deps) with
   `scripts/build_embedded_runtime.py`.

## Build host assumptions

- You are building **on macOS**.
- You have a **redistributable** Python 3.12.3+ for the target architecture:
  - `macos-arm64`: arm64 Python
  - `macos-intel`: x86_64 Python
- The build host has network access for pip installs.
- Optional: Xcode CLT may be required if pip needs to build any native wheels.

The embedded runtime step copies `sys.base_prefix` into the stage payload, so
the provided Python must be suitable for redistribution and relocation. (A
portable/standalone Python distribution is recommended.)

## Commands

Stage the payload:

```bash
python3 scripts/stage_release_payload.py --target macos-arm64 --clean
```

Build the embedded runtime (default: uses the current interpreter):

```bash
python3 scripts/build_embedded_runtime.py \
  --stage dist/stage/macos-arm64 \
  --target macos-arm64 \
  --clean
```

Include the optional Cohere engine:

```bash
python3 scripts/build_embedded_runtime.py \
  --stage dist/stage/macos-arm64 \
  --target macos-arm64 \
  --with-cohere \
  --clean
```

Dry-run planning (no filesystem changes):

```bash
python3 scripts/build_embedded_runtime.py --stage dist/stage/macos-arm64 --target macos-arm64 --dry-run
```

## Target-aware dependency profiles

- `macos-arm64` embeds:
  - base app deps (`requirements.txt`)
  - Whisper MLX profile (`requirements-whisper-mlx.txt`)
  - optional Cohere (`requirements-cohere.txt`) when `--with-cohere`
- `macos-intel` embeds:
  - base app deps (`requirements.txt`)
  - Whisper CPU profile (`requirements-whisper-cpu.txt`)
  - optional Cohere (`requirements-cohere.txt`) when `--with-cohere`

## Payload layout after embedding

```text
dist/stage/<target>/
  payload/
    runtime/
      python/                 # embedded sys.base_prefix
      venv/                   # embedded venv with installed deps
      embedded_runtime.json   # target/profile metadata
      requirements_frozen.txt # pip freeze for diagnostics
```

