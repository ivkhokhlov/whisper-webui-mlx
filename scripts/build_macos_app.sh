#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CONTRACT_PATH="${ROOT_DIR}/docs/release/macos_targets.toml"

APP_NAME_OVERRIDE=""
TARGET="macos-arm64"
OUT_DIR="${ROOT_DIR}/dist"
STAGE_DIR=""
PYTHON_FOR_EMBED=""
WITH_COHERE=0
FORCE=0

usage() {
  cat <<'EOF'
Build a self-contained macOS .app bundle (no repo-root dependency).

This is a packaging script (NOT the dev bootstrap flow).
- Dev bootstrap: ./run.sh or ./scripts/setup_and_run.sh
- Packaged build: scripts/build_macos_app.sh

Usage:
  ./scripts/build_macos_app.sh --target macos-arm64 [--with-cohere] [--python /path/to/python] [--out DIR] [--force]
  ./scripts/build_macos_app.sh --target macos-intel [--with-cohere] [--python /path/to/python] [--out DIR] [--force]

Options:
  --target TARGET      Release target from docs/release/macos_targets.toml (macos-arm64 | macos-intel)
  --with-cohere        Embed the optional Cohere engine dependencies
  --python PATH        Target-arch Python executable to embed + use for installs (recommended: portable/standalone Python)
  --stage DIR          Stage directory (default: dist/stage/<target>)
  --out DIR            Output directory for the .app (default: dist/<target>/)
  --name NAME          Override app display name (bundle filename stays contract-driven)
  --force              Overwrite existing output .app
  -h, --help           Show this help

Notes:
- This script creates a clean stage, builds an embedded runtime into it, then assembles a .app.
- No DMG/signing/notarization is performed here.
- The resulting app stays local-only on 127.0.0.1.
EOF
}

fail() {
  printf '%s\n' "ERROR: $*" >&2
  exit 1
}

python_field() {
  local target="$1"
  local key="$2"
  python3 - "$CONTRACT_PATH" "$target" "$key" <<'PY'
import sys
from pathlib import Path
import tomllib

contract_path = Path(sys.argv[1])
target = sys.argv[2]
key = sys.argv[3]

data = tomllib.loads(contract_path.read_text(encoding="utf-8"))
macos = data.get("macos", {})
targets = macos.get("targets", {})
if target not in targets:
    raise SystemExit(f"unknown target: {target}")

if key == "product_name":
    print(macos.get("product_name", "").strip())
elif key == "bundle_name":
    print(macos.get("bundle_name", "").strip())
elif key == "bundle_identifier":
    base = str(macos.get("bundle_identifier_base", "")).strip()
    suffix = str(targets[target].get("bundle_identifier_suffix", "") or "")
    print(f"{base}{suffix}")
elif key == "minimum_macos":
    print(str(targets[target].get("minimum_macos", "")).strip())
elif key == "arch":
    print(str(targets[target].get("arch", "")).strip())
else:
    raise SystemExit(f"unknown key: {key}")
PY
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --target)
      TARGET="${2:-}"
      shift 2
      ;;
    --with-cohere)
      WITH_COHERE=1
      shift
      ;;
    --python)
      PYTHON_FOR_EMBED="${2:-}"
      shift 2
      ;;
    --stage)
      STAGE_DIR="${2:-}"
      shift 2
      ;;
    --out)
      OUT_DIR="${2:-}"
      shift 2
      ;;
    --name)
      APP_NAME_OVERRIDE="${2:-}"
      shift 2
      ;;
    --force)
      FORCE=1
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

if [[ "$(uname -s)" != "Darwin" ]]; then
  fail "This script supports macOS only."
fi

if [[ ! -f "$CONTRACT_PATH" ]]; then
  fail "Missing contract file: $CONTRACT_PATH"
fi

ARCH="$(python_field "$TARGET" "arch")"
if [[ -z "$ARCH" ]]; then
  fail "Contract missing arch for target '$TARGET'."
fi

HOST_ARCH="$(uname -m)"
if [[ "$HOST_ARCH" != "$ARCH" ]]; then
  fail "Host arch '$HOST_ARCH' does not match target '$TARGET' arch '$ARCH'. Build on matching hardware."
fi

BUNDLE_NAME="$(python_field "$TARGET" "bundle_name")"
if [[ -z "$BUNDLE_NAME" ]]; then
  fail "Contract missing macos.bundle_name."
fi

PRODUCT_NAME="$(python_field "$TARGET" "product_name")"
if [[ -z "$PRODUCT_NAME" ]]; then
  fail "Contract missing macos.product_name."
fi

APP_NAME="$PRODUCT_NAME"
if [[ -n "$APP_NAME_OVERRIDE" ]]; then
  APP_NAME="$APP_NAME_OVERRIDE"
fi

BUNDLE_ID="$(python_field "$TARGET" "bundle_identifier")"
MIN_MACOS="$(python_field "$TARGET" "minimum_macos")"

VERSION="$(python3 - "$ROOT_DIR/pyproject.toml" <<'PY'
import sys
from pathlib import Path
import tomllib

pyproject = Path(sys.argv[1])
data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
version = data.get("tool", {}).get("poetry", {}).get("version")
print((version or "").strip() or "0.1.0")
PY
)"

if [[ -z "$STAGE_DIR" ]]; then
  STAGE_DIR="${ROOT_DIR}/dist/stage/${TARGET}"
fi

if [[ -z "$PYTHON_FOR_EMBED" ]]; then
  PYTHON_FOR_EMBED="$(command -v python3 || true)"
fi
if [[ -z "$PYTHON_FOR_EMBED" ]]; then
  fail "python3 not found. Provide a target Python via --python."
fi

OUT_DIR="${OUT_DIR%/}/${TARGET}"
APP_PATH="${OUT_DIR}/${BUNDLE_NAME}"
CONTENTS_DIR="${APP_PATH}/Contents"
MACOS_DIR="${CONTENTS_DIR}/MacOS"
RESOURCES_DIR="${CONTENTS_DIR}/Resources"

if [[ -e "$APP_PATH" && "$FORCE" != "1" ]]; then
  fail "${APP_PATH} already exists. Re-run with --force to overwrite."
fi

rm -rf "$APP_PATH"
mkdir -p "$MACOS_DIR" "$RESOURCES_DIR" "$RESOURCES_DIR/build"

printf '%s\n' "==> Staging clean payload (${TARGET})..."
python3 "${ROOT_DIR}/scripts/stage_release_payload.py" \
  --target "$TARGET" \
  --out "$STAGE_DIR" \
  --clean

printf '%s\n' "==> Building embedded runtime (${TARGET})..."
embed_args=(
  "${ROOT_DIR}/scripts/build_embedded_runtime.py"
  --stage "$STAGE_DIR"
  --target "$TARGET"
  --python "$PYTHON_FOR_EMBED"
  --clean
)
if [[ "$WITH_COHERE" == "1" ]]; then
  embed_args+=(--with-cohere)
fi
python3 "${embed_args[@]}"

if [[ ! -x "${STAGE_DIR}/payload/runtime/venv/bin/python3" && ! -x "${STAGE_DIR}/payload/runtime/venv/bin/python" ]]; then
  fail "Embedded runtime missing venv python under ${STAGE_DIR}/payload/runtime/venv/bin."
fi

cat > "${CONTENTS_DIR}/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleName</key>
  <string>${APP_NAME}</string>
  <key>CFBundleDisplayName</key>
  <string>${APP_NAME}</string>
  <key>CFBundleIdentifier</key>
  <string>${BUNDLE_ID}</string>
  <key>CFBundleVersion</key>
  <string>${VERSION}</string>
  <key>CFBundleShortVersionString</key>
  <string>${VERSION}</string>
  <key>CFBundlePackageType</key>
  <string>APPL</string>
  <key>CFBundleExecutable</key>
  <string>launcher</string>
  <key>NSHighResolutionCapable</key>
  <true/>
  <key>LSMinimumSystemVersion</key>
  <string>${MIN_MACOS}</string>
</dict>
</plist>
PLIST

printf '%s\n' "==> Copying staged payload into app bundle..."
if command -v ditto >/dev/null 2>&1; then
  ditto "${STAGE_DIR}/payload" "${RESOURCES_DIR}/payload"
else
  cp -R "${STAGE_DIR}/payload" "${RESOURCES_DIR}/payload"
fi
cp "${STAGE_DIR}/stage_manifest.json" "${RESOURCES_DIR}/build/stage_manifest.json"

cat > "${MACOS_DIR}/launcher" <<BASH
#!/usr/bin/env bash
set -euo pipefail

CONTENTS_DIR="\$(cd "\$(dirname "\${BASH_SOURCE[0]}")/.." && pwd)"
RESOURCES_DIR="\${CONTENTS_DIR}/Resources"
PAYLOAD_DIR="\${RESOURCES_DIR}/payload"
VENV_DIR="\${PAYLOAD_DIR}/runtime/venv"
SERVER_URL="http://127.0.0.1:8000"

PYTHON="\${VENV_DIR}/bin/python3"
if [[ ! -x "\${PYTHON}" ]]; then
  PYTHON="\${VENV_DIR}/bin/python"
fi

export MLX_UI_RUNTIME_MODE="packaged"
export MLX_UI_BUNDLE_ID="${BUNDLE_ID}"

if [[ -z "\${HOME:-}" ]]; then
  if command -v osascript >/dev/null 2>&1; then
    osascript -e 'display dialog "Unable to start Whisper WebUI: HOME is not set." buttons {"OK"} with icon stop'
  fi
  exit 1
fi

APP_SUPPORT_DIR="\${HOME}/Library/Application Support/\${MLX_UI_BUNDLE_ID}"
LOG_DIR="\${APP_SUPPORT_DIR}/data/logs"
export LOG_DIR
if ! mkdir -p "\${LOG_DIR}" >/dev/null 2>&1; then
  if command -v osascript >/dev/null 2>&1; then
    osascript -e "display dialog \"Unable to start Whisper WebUI: cannot create logs directory:\n\${LOG_DIR}\" buttons {\"OK\"} with icon stop"
  fi
  exit 1
fi

export PYTHONPYCACHEPREFIX="\${APP_SUPPORT_DIR}/pycache"
if ! mkdir -p "\${PYTHONPYCACHEPREFIX}" >/dev/null 2>&1; then
  if command -v osascript >/dev/null 2>&1; then
    osascript -e "display dialog \"Unable to start Whisper WebUI: cannot create cache directory:\n\${PYTHONPYCACHEPREFIX}\" buttons {\"OK\"} with icon stop"
  fi
  exit 1
fi

export PYTHONPATH="\${PAYLOAD_DIR}"
export PATH="\${VENV_DIR}/bin:\${PATH}"
export PYTHONUNBUFFERED=1

LOG_FILE="\${LOG_DIR}/app_launcher.log"
PID_FILE="\${APP_SUPPORT_DIR}/server.pid"

log() {
  printf '%s\n' "\$*" >>"\${LOG_FILE}"
}

fatal_dialog() {
  local message="\$1"
  log "FATAL: \${message}"
  log "Logs: \${LOG_FILE}"
  if command -v osascript >/dev/null 2>&1; then
    osascript -e "display dialog \"\${message}\n\nLogs:\n\${LOG_FILE}\" buttons {\"OK\"} with icon stop"
  fi
}

if [[ ! -x "\${PYTHON}" ]]; then
  fatal_dialog "Embedded Python runtime is missing or not executable."
  exit 1
fi

if [[ ! -d "\${PAYLOAD_DIR}/mlx_ui" ]]; then
  fatal_dialog "Packaged app payload is missing (mlx_ui). Rebuild the app."
  exit 1
fi

server_responding() {
  if command -v curl >/dev/null 2>&1; then
    curl --silent --fail --max-time 1 "\${SERVER_URL}/api/state" >/dev/null 2>&1
    return \$?
  fi
  "\${PYTHON}" - "\${SERVER_URL}" <<'PY' >/dev/null 2>&1
import sys
import urllib.request

url = sys.argv[1].rstrip("/") + "/api/state"
req = urllib.request.Request(url, headers={"Accept": "application/json"})
with urllib.request.urlopen(req, timeout=1.0) as resp:
    if resp.status != 200:
        raise SystemExit(1)
raise SystemExit(0)
PY
}

open_browser() {
  if command -v open >/dev/null 2>&1; then
    open "\${SERVER_URL}" >/dev/null 2>&1 || true
  fi
}

wait_for_server() {
  local attempts=80
  local delay=0.25
  for _ in \$(seq 1 "\${attempts}"); do
    if server_responding; then
      return 0
    fi
    sleep "\${delay}"
  done
  return 1
}

is_pid_running() {
  local pid="\$1"
  if [[ -z "\${pid}" ]]; then
    return 1
  fi
  if [[ ! "\${pid}" =~ ^[0-9]+$ ]]; then
    return 1
  fi
  kill -0 "\${pid}" >/dev/null 2>&1
}

log "----"
log "Launcher started."
log "Bundle: \${MLX_UI_BUNDLE_ID}"
log "Payload: \${PAYLOAD_DIR}"
log "Python: \${PYTHON}"
log "App support: \${APP_SUPPORT_DIR}"

if server_responding; then
  log "Server is already running; opening browser."
  open_browser
  exit 0
fi

if [[ -f "\${PID_FILE}" ]]; then
  existing_pid="\$(cat "\${PID_FILE}" 2>/dev/null || true)"
  if is_pid_running "\${existing_pid}"; then
    log "Detected existing server process (pid=\${existing_pid}); waiting for readiness."
    if wait_for_server; then
      open_browser
      exit 0
    fi
    fatal_dialog "Whisper WebUI is taking too long to start."
    exit 1
  fi
  rm -f "\${PID_FILE}" || true
fi

if command -v lsof >/dev/null 2>&1; then
  if lsof -iTCP:8000 -sTCP:LISTEN -n -P >/dev/null 2>&1; then
    fatal_dialog "Port 8000 is already in use by another application. Quit it and try again."
    exit 1
  fi
fi

server_pid=""
cd "\${APP_SUPPORT_DIR}" || {
  fatal_dialog "Unable to start Whisper WebUI: cannot access app data directory."
  exit 1
}

"\${PYTHON}" -m uvicorn mlx_ui.app:app --host 127.0.0.1 --port 8000 >>"\${LOG_FILE}" 2>&1 &
server_pid="\$!"
printf '%s\n' "\${server_pid}" >"\${PID_FILE}" 2>/dev/null || true

cleanup() {
  rm -f "\${PID_FILE}" >/dev/null 2>&1 || true
  if [[ -n "\${server_pid}" ]]; then
    kill "\${server_pid}" >/dev/null 2>&1 || true
  fi
}
trap cleanup EXIT

if wait_for_server; then
  log "Server ready; opening browser."
  open_browser
else
  fatal_dialog "Whisper WebUI failed to start."
  exit 1
fi

wait "\${server_pid}"
BASH

chmod +x "${MACOS_DIR}/launcher"

printf '%s\n' "==> Validating app bundle structure..."
python3 "${ROOT_DIR}/scripts/validate_macos_app_bundle.py" --app "${APP_PATH}" >/dev/null

printf '%s\n' "Created app: ${APP_PATH}"
printf '%s\n' "Target: ${TARGET} (${ARCH})"
printf '%s\n' "Bundle id: ${BUNDLE_ID}"
printf '%s\n' "Launcher logs: ~/Library/Application Support/${BUNDLE_ID}/data/logs/app_launcher.log"
printf '%s\n' "Payload embedded at: ${APP_PATH}/Contents/Resources/payload"
printf '%s\n' "Build metadata: ${APP_PATH}/Contents/Resources/build/stage_manifest.json"
printf '%s\n' "Note: Dev bootstrap remains ./run.sh (repo-based)."
