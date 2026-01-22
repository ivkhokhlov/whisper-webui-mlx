#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"
VENV_DIR="$ROOT_DIR/.venv"
VENV_PYTHON="$VENV_DIR/bin/python"
VENV_PIP="$VENV_DIR/bin/pip"
STEP_COUNT=0

log() {
  printf '%s\n' "==> $*"
}

warn() {
  printf '%s\n' "WARN: $*" >&2
}

fail() {
  printf '%s\n' "ERROR: $*" >&2
  exit 1
}

step() {
  STEP_COUNT=$((STEP_COUNT + 1))
  log "Step ${STEP_COUNT}: $*"
}

require_macos_arm64() {
  if [[ "$(uname -s)" != "Darwin" ]]; then
    fail "This script supports macOS only."
  fi
  if [[ "$(uname -m)" != "arm64" ]]; then
    fail "Apple Silicon (arm64) is required."
  fi
}

ensure_xcode_cli_tools() {
  if ! xcode-select -p >/dev/null 2>&1; then
    fail "Xcode Command Line Tools are required. Run: xcode-select --install"
  fi
}

ensure_brew() {
  if ! command -v brew >/dev/null 2>&1; then
    fail "Homebrew is required. Install it from https://brew.sh/ and re-run."
  fi
}

python_is_compatible() {
  "$1" - <<'PY'
import sys
raise SystemExit(0 if sys.version_info >= (3, 12, 3) else 1)
PY
}

select_python() {
  if command -v python3.12 >/dev/null 2>&1; then
    if python_is_compatible python3.12; then
      echo "python3.12"
      return 0
    fi
  fi
  if command -v python3 >/dev/null 2>&1; then
    if python_is_compatible python3; then
      echo "python3"
      return 0
    fi
  fi
  return 1
}

ensure_python() {
  local python_bin
  python_bin="$(select_python || true)"
  if [[ -n "$python_bin" ]]; then
    printf '%s\n' "==> Using Python: $python_bin ($("$python_bin" --version 2>&1))" >&2
    echo "$python_bin"
    return 0
  fi

  printf '%s\n' "==> Python 3.12.3+ not found. Installing python@3.12 via Homebrew..." >&2
  brew install python@3.12
  hash -r
  if command -v python3.12 >/dev/null 2>&1; then
    echo "python3.12"
    return 0
  fi
  fail "python3.12 not found after install. Ensure Homebrew is on PATH."
}

ensure_ffmpeg() {
  if command -v ffmpeg >/dev/null 2>&1; then
    return 0
  fi
  log "ffmpeg not found. Installing via Homebrew..."
  brew install ffmpeg
}

ensure_git() {
  if command -v git >/dev/null 2>&1; then
    return 0
  fi
  fail "git is required to install whisper-turbo-mlx. Install Xcode Command Line Tools."
}

ensure_python_deps() {
  local python_bin="$1"
  if [[ ! -f "$ROOT_DIR/requirements.txt" ]]; then
    fail "requirements.txt not found in repo root."
  fi
  if [[ ! -d "$VENV_DIR" ]]; then
    log "Creating virtual environment at $VENV_DIR..."
    "$python_bin" -m venv "$VENV_DIR"
  fi
  if [[ ! -x "$VENV_PYTHON" ]]; then
    fail "Virtual environment missing python at $VENV_PYTHON"
  fi
  export PATH="$VENV_DIR/bin:$PATH"
  log "Installing Python dependencies..."
  "$VENV_PIP" install --upgrade pip
  "$VENV_PIP" install -r "$ROOT_DIR/requirements.txt"
}

ensure_wtm() {
  if "$VENV_PYTHON" - <<'PY'
import importlib.util
raise SystemExit(0 if importlib.util.find_spec("whisper_turbo") else 1)
PY
  then
    return 0
  fi

  log "Installing whisper-turbo-mlx (wtm)..."
  "$VENV_PIP" install --upgrade \
    "whisper-turbo-mlx @ git+https://github.com/JosefAlbers/whisper-turbo-mlx.git"
}

download_model() {
  if [[ "${SKIP_MODEL_DOWNLOAD:-}" == "1" ]]; then
    warn "Skipping model download because SKIP_MODEL_DOWNLOAD=1."
    return 0
  fi
  check_disk_space
  log "Downloading model weights (openai/whisper-large-v3-turbo)..."
  if ! "$VENV_PYTHON" - <<'PY'
from huggingface_hub import hf_hub_download, snapshot_download

snapshot_download(
    repo_id="openai/whisper-large-v3-turbo",
    allow_patterns=["config.json", "model.safetensors"],
)
hf_hub_download(
    repo_id="JosefAlbers/whisper",
    filename="multilingual.tiktoken",
)
PY
  then
    fail "Model download failed. Check your network and rerun."
  fi
}

check_disk_space() {
  local required_kb=8000000
  local available_kb
  available_kb=$(df -Pk "$ROOT_DIR" | awk 'NR==2 {print $4}')
  if [[ -n "$available_kb" && "$available_kb" -lt "$required_kb" ]]; then
    warn "Low disk space: less than 8GB available. Model download may fail."
  fi
}

prepare_data_dirs() {
  mkdir -p data/uploads data/results data/logs
}

wait_for_server() {
  local url="http://127.0.0.1:8000"
  local attempts=40
  local delay=0.5

  for _ in $(seq 1 "$attempts"); do
    if curl --silent --fail --max-time 1 "$url" >/dev/null 2>&1; then
      return 0
    fi
    sleep "$delay"
  done
  return 1
}

open_browser() {
  local url="http://127.0.0.1:8000"
  if command -v open >/dev/null 2>&1; then
    open "$url" >/dev/null 2>&1 || warn "Failed to open browser."
  else
    warn "open command not available; navigate to $url manually."
  fi
}

start_server() {
  log "Starting server (http://127.0.0.1:8000)..."
  make run &
  server_pid=$!

  if wait_for_server; then
    open_browser
  else
    warn "Server did not respond yet; open http://127.0.0.1:8000 manually."
  fi

  log "Ready! URL: http://127.0.0.1:8000"
  log "Results: $ROOT_DIR/data/results"
  log "Logs: $ROOT_DIR/data/logs"
  log "Stop the server with Ctrl+C."

  wait "$server_pid"
}

step "Checking platform compatibility"
require_macos_arm64
ensure_xcode_cli_tools
ensure_git
step "Checking Homebrew"
ensure_brew
step "Selecting Python"
PYTHON_BIN="$(ensure_python)"
step "Installing dependencies"
ensure_ffmpeg
ensure_python_deps "$PYTHON_BIN"
step "Installing whisper-turbo-mlx"
ensure_wtm
step "Downloading model weights (if needed)"
download_model
step "Preparing local data directories"
prepare_data_dirs

server_pid=""
trap 'if [[ -n "${server_pid}" ]]; then kill "${server_pid}" 2>/dev/null || true; fi' EXIT

step "Launching Web UI"
start_server
