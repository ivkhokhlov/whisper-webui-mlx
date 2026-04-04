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
ALLOW_SYSTEM_INSTALL="${MLX_UI_ALLOW_SYSTEM_INSTALL:-0}"
PYTHON_BIN_OVERRIDE="${MLX_UI_PYTHON:-}"
REINSTALL_PYTHON="${MLX_UI_REINSTALL_PYTHON:-0}"
RUNTIME_DIR="${ROOT_DIR}/.runtime"
EMBEDDED_PYTHON_DIR="${RUNTIME_DIR}/python"
EMBEDDED_PYTHON_BIN="${EMBEDDED_PYTHON_DIR}/bin/python3.12"
EMBEDDED_TMP_DIR="${RUNTIME_DIR}/.tmp"
PYTHON_STANDALONE_RELEASE_TAG="20260325"
PYTHON_STANDALONE_VERSION="3.12.13"
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
                               [--python /path/to/python] [--bootstrap] [--reinstall-python]

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

Embedded Python (default):
  This script uses a portable CPython runtime (python-build-standalone) stored
  under ./.runtime/python and creates/uses a local ./.venv. It does not require
  or modify a system Python installation.

System bootstrap (opt-in):
  --bootstrap  Allow installing missing system prerequisites (Homebrew + ffmpeg, Xcode CLI tools prompt)

Python selection:
  --python PATH  Use a specific Python interpreter (must be 3.12.3+ and <3.13)

Embedded Python controls:
  --reinstall-python  Delete ./.runtime/python and re-download the portable Python runtime

Environment variables:
  WHISPER_WEBUI_WITH_COHERE=1
  WHISPER_WEBUI_WITH_WHISPER_CPU=1
  WHISPER_WEBUI_WITH_PARAKEET_MLX=1
  MLX_UI_ALLOW_SYSTEM_INSTALL=1
  MLX_UI_PYTHON=/path/to/python
  MLX_UI_REINSTALL_PYTHON=1

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
      --bootstrap)
        ALLOW_SYSTEM_INSTALL=1
        shift
        ;;
      --python)
        PYTHON_BIN_OVERRIDE="${2:-}"
        if [[ -z "$PYTHON_BIN_OVERRIDE" ]]; then
          fail "--python requires a value."
        fi
        shift 2
        ;;
      --reinstall-python)
        REINSTALL_PYTHON=1
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
    if [[ "$ALLOW_SYSTEM_INSTALL" == "1" ]]; then
      log "Xcode Command Line Tools not found. Launching installer..."
      xcode-select --install >/dev/null 2>&1 || true
      fail "Xcode Command Line Tools are required. Finish the installer, then re-run."
    fi
    fail "Xcode Command Line Tools are required. Install them with: xcode-select --install"
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

  if [[ "$ALLOW_SYSTEM_INSTALL" != "1" ]]; then
    fail "Homebrew not found. Install it from https://brew.sh or rerun with --bootstrap."
  fi

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
raise SystemExit(0 if (sys.version_info >= (3, 12, 3) and sys.version_info < (3, 13, 0)) else 1)
PY
}

resolve_python_override() {
  local candidate="${1:-}"
  if [[ -z "$candidate" ]]; then
    return 1
  fi
  if [[ -x "$candidate" ]]; then
    printf '%s\n' "$candidate"
    return 0
  fi
  if command -v "$candidate" >/dev/null 2>&1; then
    printf '%s\n' "$candidate"
    return 0
  fi
  return 1
}

sha256_file() {
  local path="$1"
  if command -v shasum >/dev/null 2>&1; then
    shasum -a 256 "$path" | awk '{print $1}'
    return 0
  fi
  if command -v openssl >/dev/null 2>&1; then
    openssl dgst -sha256 "$path" | awk '{print $2}'
    return 0
  fi
  return 1
}

embedded_python_asset_name() {
  local arch="$1"
  case "$arch" in
    arm64)
      printf '%s\n' "cpython-${PYTHON_STANDALONE_VERSION}+${PYTHON_STANDALONE_RELEASE_TAG}-aarch64-apple-darwin-install_only_stripped.tar.gz"
      ;;
    x86_64)
      printf '%s\n' "cpython-${PYTHON_STANDALONE_VERSION}+${PYTHON_STANDALONE_RELEASE_TAG}-x86_64-apple-darwin-install_only_stripped.tar.gz"
      ;;
    *)
      fail "Unsupported macOS architecture '$arch'."
      ;;
  esac
}

embedded_python_expected_sha256() {
  local arch="$1"
  case "$arch" in
    arm64) printf '%s\n' "c33a34853ae48d54fbac15cbb84ad67ccd8a639ce2cef866ecf474ebd02f1286" ;;
    x86_64) printf '%s\n' "2d0259f7939b6592a6d019e6b2fa1ac10765e215965cd96cf8cc995274df4257" ;;
    *)
      fail "Unsupported macOS architecture '$arch'."
      ;;
  esac
}

ensure_embedded_python() {
  local arch="$1"
  local python_bin="${EMBEDDED_PYTHON_BIN}"

  if [[ "$REINSTALL_PYTHON" == "1" ]]; then
    printf '%s\n' "==> Forcing embedded Python reinstall." >&2
    rm -rf "$EMBEDDED_PYTHON_DIR"
    rm -rf "$VENV_DIR"
  fi

  if [[ -x "$python_bin" ]]; then
    if python_is_compatible "$python_bin"; then
      printf '%s\n' "==> Using embedded Python: $python_bin ($("$python_bin" --version 2>&1))" >&2
      echo "$python_bin"
      return 0
    fi
    warn "Embedded Python at $python_bin is incompatible; reinstalling..."
    rm -rf "$EMBEDDED_PYTHON_DIR"
    rm -rf "$VENV_DIR"
  fi

  if ! command -v curl >/dev/null 2>&1; then
    fail "curl is required to download the embedded Python runtime."
  fi
  if ! command -v tar >/dev/null 2>&1; then
    fail "tar is required to extract the embedded Python runtime."
  fi

  mkdir -p "$RUNTIME_DIR" "$EMBEDDED_TMP_DIR"

  local asset
  asset="$(embedded_python_asset_name "$arch")"
  local expected_sha
  expected_sha="$(embedded_python_expected_sha256 "$arch")"

  local encoded_asset
  # GitHub release URLs use %2B for '+'.
  encoded_asset="${asset//+/%2B}"
  local url
  url="https://github.com/astral-sh/python-build-standalone/releases/download/${PYTHON_STANDALONE_RELEASE_TAG}/${encoded_asset}"

  local archive_path
  archive_path="${EMBEDDED_TMP_DIR}/${asset}"
  local download_path
  download_path="${archive_path}.download"

  if [[ -f "$archive_path" ]]; then
    printf '%s\n' "==> Found cached embedded Python archive: $archive_path" >&2
  else
    printf '%s\n' "==> Downloading embedded Python ${PYTHON_STANDALONE_VERSION} (${arch})..." >&2
    curl -L --fail --silent --show-error -o "$download_path" "$url" || \
      fail "Failed to download embedded Python archive from: $url"
    mv -f "$download_path" "$archive_path"
  fi

  local actual_sha
  actual_sha="$(sha256_file "$archive_path" || true)"
  if [[ -z "$actual_sha" ]]; then
    fail "Unable to compute SHA256 for $archive_path (need shasum or openssl)."
  fi
  if [[ "$actual_sha" != "$expected_sha" ]]; then
    rm -f "$archive_path"
    fail "SHA256 mismatch for embedded Python archive. Expected $expected_sha, got $actual_sha. Deleted $archive_path; re-run to retry."
  fi

  local extract_dir
  extract_dir="$(mktemp -d "${EMBEDDED_TMP_DIR}/extract.XXXXXX")"
  tar -xzf "$archive_path" -C "$extract_dir" || fail "Failed to extract embedded Python archive."
  if [[ ! -x "$extract_dir/python/bin/python3.12" ]]; then
    rm -rf "$extract_dir"
    fail "Embedded Python archive did not contain python/bin/python3.12 as expected."
  fi

  rm -rf "$EMBEDDED_PYTHON_DIR"
  mv "$extract_dir/python" "$EMBEDDED_PYTHON_DIR"
  rm -rf "$extract_dir"

  python_bin="${EMBEDDED_PYTHON_BIN}"
  if [[ ! -x "$python_bin" ]]; then
    fail "Embedded Python install failed: missing $python_bin"
  fi
  if ! python_is_compatible "$python_bin"; then
    fail "Embedded Python at $python_bin is incompatible. Require Python 3.12.3+ and <3.13."
  fi

  printf '%s\n' "==> Using embedded Python: $python_bin ($("$python_bin" --version 2>&1))" >&2
  echo "$python_bin"
}

ensure_python() {
  local python_bin

  if [[ -n "${PYTHON_BIN_OVERRIDE}" ]]; then
    python_bin="$(resolve_python_override "$PYTHON_BIN_OVERRIDE" || true)"
    if [[ -z "$python_bin" ]]; then
      fail "Requested Python '${PYTHON_BIN_OVERRIDE}' not found. Provide an absolute path or a command on PATH."
    fi
    if ! python_is_compatible "$python_bin"; then
      fail "Requested Python '${python_bin}' is not compatible. Require Python 3.12.3+ and <3.13."
    fi
    printf '%s\n' "==> Using Python: $python_bin ($("$python_bin" --version 2>&1))" >&2
    echo "$python_bin"
    return 0
  fi
  ensure_embedded_python "$MACOS_ARCH"
}

ensure_ffmpeg() {
  if command -v ffmpeg >/dev/null 2>&1; then
    return 0
  fi
  if [[ "$ALLOW_SYSTEM_INSTALL" != "1" ]]; then
    fail "ffmpeg is required but not found. Install it (e.g. 'brew install ffmpeg') or rerun with --bootstrap."
  fi
  log "ffmpeg not found. Installing via Homebrew..."
  brew install ffmpeg
}

ensure_git() {
  if command -v git >/dev/null 2>&1; then
    return 0
  fi
  fail "git is required for the --bootstrap flow. Install Xcode Command Line Tools."
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
ALLOW_SYSTEM_INSTALL="$(normalize_bool "$ALLOW_SYSTEM_INSTALL")"
REINSTALL_PYTHON="$(normalize_bool "$REINSTALL_PYTHON")"

step "Checking platform compatibility"
require_macos
MACOS_ARCH="$(detect_macos_arch)"
if [[ "$WITH_PARAKEET_MLX" == "1" && "$MACOS_ARCH" != "arm64" ]]; then
  fail "Parakeet MLX dependencies are supported on macOS arm64 (Apple Silicon) only. Intel macOS cannot run local Parakeet MLX; use Whisper CPU or Cohere instead."
fi
print_engine_expectations "$MACOS_ARCH"
if [[ "$ALLOW_SYSTEM_INSTALL" == "1" ]]; then
  ensure_xcode_cli_tools
  ensure_git
fi
step "Checking Homebrew"
if [[ "$ALLOW_SYSTEM_INSTALL" == "1" ]]; then
  ensure_brew
else
  load_brew_shellenv || true
  if command -v brew >/dev/null 2>&1; then
    log "Homebrew found."
  else
    log "Homebrew not found (system bootstrap disabled)."
  fi
fi
step "Selecting Python"
PYTHON_BIN="$(ensure_python)"
step "Installing dependencies"
if [[ "$ALLOW_SYSTEM_INSTALL" == "1" ]]; then
  ensure_brew
fi
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
