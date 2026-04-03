#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"
VENV_DIR="$ROOT_DIR/.venv"
VENV_PYTHON="$VENV_DIR/bin/python"
VENV_PIP="$VENV_DIR/bin/pip"
STEP_COUNT=0
WITH_COHERE="${WHISPER_WEBUI_WITH_COHERE:-0}"
WITH_WHISPER_CPU="${WHISPER_WEBUI_WITH_WHISPER_CPU:-0}"
WITH_PARAKEET_MLX="${WHISPER_WEBUI_WITH_PARAKEET_MLX:-0}"
MACOS_ARCH=""
INSTALL_MLX_DEFAULT=0
DATA_ROOT_DIR="$ROOT_DIR"

if [[ "${MLX_UI_RUNTIME_MODE:-}" == "packaged" ]]; then
  bundle_id="${MLX_UI_BUNDLE_ID:-com.whisperwebui.mlx}"
  if [[ -n "${HOME:-}" ]]; then
    DATA_ROOT_DIR="${HOME}/Library/Application Support/${bundle_id}"
  fi
fi

# macOS release targets contract (single source of truth):
#   docs/release/macos_targets.toml
#
# Keep the bootstrap expectations and supported optional profiles aligned with
# that contract. This script remains the canonical developer bootstrap entry.

usage() {
  cat <<'EOF'
Usage: ./scripts/setup_and_run.sh [--with-cohere] [--with-whisper-cpu] [--with-parakeet-mlx]

Release targets (packaging contract):
  macos-arm64  -> default local engine: Whisper MLX
  macos-intel  -> default local engine: Whisper CPU
  Source of truth: docs/release/macos_targets.toml

Default engine bootstrap:
  macOS arm64   -> Whisper MLX (default) + optional local Parakeet MLX (--with-parakeet-mlx)
  macOS x86_64  -> Whisper CPU

Optional profiles:
  --with-cohere       Install the Cohere SDK for the cloud backend
  --with-whisper-cpu  On Apple Silicon, also install the Whisper CPU fallback
  --with-parakeet-mlx On Apple Silicon, install the optional Parakeet MLX dependency profile

Environment variables:
  WHISPER_WEBUI_WITH_COHERE=1
  WHISPER_WEBUI_WITH_WHISPER_CPU=1
  WHISPER_WEBUI_WITH_PARAKEET_MLX=1

Notes:
  - This bootstrap script supports macOS only.
  - Parakeet MLX is a local Apple Silicon engine, but it is dependency-optional in the repo bootstrap flow.
  - Legacy Parakeet NeMo/CUDA backends are experimental/internal only and not supported on macOS.
EOF
}

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

normalize_bool() {
  local value="${1:-}"
  # macOS ships bash 3.2 which doesn't support ${var,,}
  local value_lc
  value_lc="$(printf '%s' "$value" | tr '[:upper:]' '[:lower:]')"
  case "$value_lc" in
    1|true|yes|on) printf '1\n' ;;
    0|false|no|off|'') printf '0\n' ;;
    *)
      fail "Expected a boolean value, got '$value'."
      ;;
  esac
}

parse_args() {
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --with-cohere)
        WITH_COHERE=1
        shift
        ;;
      --with-whisper-cpu)
        WITH_WHISPER_CPU=1
        shift
        ;;
      --with-parakeet-mlx)
        WITH_PARAKEET_MLX=1
        shift
        ;;
      -h|--help)
        usage
        exit 0
        ;;
      *)
        fail "Unknown argument: $1"
        ;;
    esac
  done
}

require_macos() {
  if [[ "$(uname -s)" != "Darwin" ]]; then
    fail "This script supports macOS only."
  fi
}

detect_macos_arch() {
  local arch
  arch="$(uname -m)"
  case "$arch" in
    arm64|x86_64)
      printf '%s\n' "$arch"
      ;;
    *)
      fail "Unsupported macOS architecture '$arch'."
      ;;
  esac
}

print_engine_expectations() {
  local arch="$1"
  if [[ "$arch" == "arm64" ]]; then
    log "Detected Apple Silicon macOS."
    log "Expected local engine after bootstrap: Whisper MLX."
    log "Optional local engines on this machine: Parakeet MLX (--with-parakeet-mlx), Whisper CPU (--with-whisper-cpu)."
    log "Optional cloud engine on this machine: Cohere (--with-cohere)."
  else
    log "Detected Intel macOS."
    log "Expected local engine after bootstrap: Whisper CPU."
    log "Optional cloud engine on this machine: Cohere (--with-cohere)."
    log "Whisper MLX is not installed on Intel."
    log "Parakeet MLX is not supported on Intel macOS."
  fi
  log "Legacy Parakeet NeMo/CUDA backends are experimental/internal only and not part of the macOS bootstrap story."
}

ensure_xcode_cli_tools() {
  if ! xcode-select -p >/dev/null 2>&1; then
    log "Xcode Command Line Tools not found. Launching installer..."
    xcode-select --install >/dev/null 2>&1 || true
    fail "Xcode Command Line Tools are required. Finish the installer, then re-run."
  fi
}

load_brew_shellenv() {
  if [[ -x "/opt/homebrew/bin/brew" ]]; then
    eval "$(/opt/homebrew/bin/brew shellenv)"
    return 0
  fi
  if [[ -x "/usr/local/bin/brew" ]]; then
    eval "$(/usr/local/bin/brew shellenv)"
    return 0
  fi
  return 1
}

ensure_brew() {
  if command -v brew >/dev/null 2>&1; then
    return 0
  fi
  load_brew_shellenv && return 0

  log "Homebrew not found. Installing..."
  if ! command -v curl >/dev/null 2>&1; then
    fail "curl is required to install Homebrew. Install curl and re-run."
  fi
  NONINTERACTIVE=1 /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)" || \
    fail "Homebrew install failed."
  load_brew_shellenv || true
  if ! command -v brew >/dev/null 2>&1; then
    fail "Homebrew not found after install. Ensure brew is on PATH."
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

  # Prefer Homebrew's python@3.12 even if it isn't linked into PATH.
  if command -v brew >/dev/null 2>&1; then
    local brew_prefix
    brew_prefix="$(brew --prefix python@3.12 2>/dev/null || true)"
    if [[ -n "$brew_prefix" && -x "$brew_prefix/bin/python3.12" ]]; then
      python_bin="$brew_prefix/bin/python3.12"
      if python_is_compatible "$python_bin"; then
        printf '%s\n' "==> Using Homebrew Python: $python_bin ($("$python_bin" --version 2>&1))" >&2
        echo "$python_bin"
        return 0
      fi
    fi
  fi

  printf '%s\n' "==> Python 3.12.3+ not found. Installing python@3.12 via Homebrew..." >&2
  brew install python@3.12
  hash -r

  if command -v brew >/dev/null 2>&1; then
    local brew_prefix
    brew_prefix="$(brew --prefix python@3.12 2>/dev/null || true)"
    if [[ -n "$brew_prefix" && -x "$brew_prefix/bin/python3.12" ]]; then
      python_bin="$brew_prefix/bin/python3.12"
      printf '%s\n' "==> Using Homebrew Python: $python_bin ($("$python_bin" --version 2>&1))" >&2
      echo "$python_bin"
      return 0
    fi
  fi

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

ensure_base_python_deps() {
  local python_bin="$1"
  if [[ ! -f "$ROOT_DIR/requirements.txt" ]]; then
    fail "requirements.txt not found in repo root."
  fi
  if [[ -d "$VENV_DIR" ]]; then
    # Check that existing venv Python is compatible; recreate if too old.
    if ! python_is_compatible "$VENV_PYTHON"; then
      warn "Existing virtualenv Python is too old; recreating venv..."
      rm -rf "$VENV_DIR"
    fi
  fi
  if [[ ! -d "$VENV_DIR" ]]; then
    log "Creating virtual environment at $VENV_DIR..."
    "$python_bin" -m venv "$VENV_DIR"
  fi
  if [[ ! -x "$VENV_PYTHON" ]]; then
    fail "Virtual environment missing python at $VENV_PYTHON"
  fi
  export PATH="$VENV_DIR/bin:$PATH"
  log "Installing base Python dependencies..."
  "$VENV_PIP" install --upgrade pip
  "$VENV_PIP" install -r "$ROOT_DIR/requirements.txt"
}

install_requirements_profile() {
  local file="$1"
  local label="$2"
  local path="$ROOT_DIR/$file"
  if [[ ! -f "$path" ]]; then
    fail "$file not found in repo root."
  fi
  log "Installing ${label} dependencies..."
  "$VENV_PIP" install -r "$path"
}

python_modules_installed() {
  "$VENV_PYTHON" - "$@" <<'PY'
import importlib.util
import sys

modules = sys.argv[1:]
for name in modules:
    if importlib.util.find_spec(name) is None:
        raise SystemExit(1)
raise SystemExit(0)
PY
}

install_engine_profiles() {
  local arch="$1"

  INSTALL_MLX_DEFAULT=0
  if [[ "$arch" == "arm64" ]]; then
    if python_modules_installed "whisper_turbo" "huggingface_hub"; then
      log "Whisper MLX dependencies already installed."
    else
      install_requirements_profile "requirements-whisper-mlx.txt" "Whisper MLX"
    fi
    INSTALL_MLX_DEFAULT=1
    if [[ "$WITH_PARAKEET_MLX" == "1" ]]; then
      if python_modules_installed "parakeet_mlx"; then
        log "Parakeet MLX dependencies already installed."
      else
        install_requirements_profile "requirements-parakeet-mlx.txt" "Parakeet MLX"
      fi
    fi
    if [[ "$WITH_WHISPER_CPU" == "1" ]]; then
      if python_modules_installed "whisper"; then
        log "Whisper CPU fallback dependencies already installed."
      else
        install_requirements_profile "requirements-whisper-cpu.txt" "Whisper CPU fallback"
      fi
    fi
  else
    if python_modules_installed "whisper"; then
      log "Whisper CPU dependencies already installed."
    else
      install_requirements_profile "requirements-whisper-cpu.txt" "Whisper CPU"
    fi
  fi

  if [[ "$WITH_COHERE" == "1" ]]; then
    if python_modules_installed "cohere"; then
      log "Cohere SDK already installed."
    else
      install_requirements_profile "requirements-cohere.txt" "Cohere"
    fi
  fi
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
  mkdir -p "${DATA_ROOT_DIR}/data/uploads" "${DATA_ROOT_DIR}/data/results" "${DATA_ROOT_DIR}/data/logs"
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
  log "Results: ${DATA_ROOT_DIR}/data/results"
  log "Logs: ${LOG_DIR:-${DATA_ROOT_DIR}/data/logs}"
  log "Stop the server with Ctrl+C."

  wait "$server_pid"
}

parse_args "$@"
WITH_COHERE="$(normalize_bool "$WITH_COHERE")"
WITH_WHISPER_CPU="$(normalize_bool "$WITH_WHISPER_CPU")"
WITH_PARAKEET_MLX="$(normalize_bool "$WITH_PARAKEET_MLX")"

step "Checking platform compatibility"
require_macos
MACOS_ARCH="$(detect_macos_arch)"
if [[ "$WITH_PARAKEET_MLX" == "1" && "$MACOS_ARCH" != "arm64" ]]; then
  fail "Parakeet MLX dependencies are supported on macOS arm64 (Apple Silicon) only. Intel macOS cannot run local Parakeet MLX; use Whisper CPU or Cohere instead."
fi
print_engine_expectations "$MACOS_ARCH"
ensure_xcode_cli_tools
ensure_git
step "Checking Homebrew"
ensure_brew
step "Selecting Python"
PYTHON_BIN="$(ensure_python)"
step "Installing dependencies"
ensure_ffmpeg
ensure_base_python_deps "$PYTHON_BIN"
step "Installing engine profiles"
install_engine_profiles "$MACOS_ARCH"
if [[ "$INSTALL_MLX_DEFAULT" == "1" ]]; then
  step "Downloading Whisper MLX model weights (if needed)"
  download_model
else
  step "Skipping Whisper MLX model predownload"
  log "Whisper CPU will download its configured model on first use if it is not already cached."
fi
step "Preparing local data directories"
prepare_data_dirs

server_pid=""
trap 'if [[ -n "${server_pid}" ]]; then kill "${server_pid}" 2>/dev/null || true; fi' EXIT

step "Launching Web UI"
start_server
