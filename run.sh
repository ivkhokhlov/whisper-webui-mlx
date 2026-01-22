#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

printf '%s\n' "Whisper WebUI (MLX) — one-command launcher"
printf '%s\n' "Running setup + server. Press Ctrl+C to stop."

exec "$ROOT_DIR/scripts/setup_and_run.sh"
