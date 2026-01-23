#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP_NAME="Whisper WebUI (MLX)"
OUT_DIR="${ROOT_DIR}/dist"
FORCE=0

usage() {
  printf '%s\n' "Usage: $0 [--name=APP_NAME] [--out=OUTPUT_DIR] [--force]"
}

for arg in "$@"; do
  case "$arg" in
    --name=*)
      APP_NAME="${arg#*=}"
      ;;
    --out=*)
      OUT_DIR="${arg#*=}"
      ;;
    --force)
      FORCE=1
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      printf '%s\n' "Unknown argument: $arg" >&2
      usage >&2
      exit 1
      ;;
  esac
done

if [[ "$(uname -s)" != "Darwin" ]]; then
  printf '%s\n' "ERROR: This script supports macOS only." >&2
  exit 1
fi

if [[ "$(uname -m)" != "arm64" ]]; then
  printf '%s\n' "ERROR: Apple Silicon (arm64) is required for Whisper WebUI (MLX)." >&2
  exit 1
fi

VERSION="$(sed -n 's/^version = "\(.*\)"/\1/p' "$ROOT_DIR/pyproject.toml" | head -n 1)"
if [[ -z "$VERSION" ]]; then
  VERSION="0.1.0"
fi

APP_PATH="${OUT_DIR}/${APP_NAME}.app"
CONTENTS_DIR="${APP_PATH}/Contents"
MACOS_DIR="${CONTENTS_DIR}/MacOS"
RESOURCES_DIR="${CONTENTS_DIR}/Resources"

if [[ -e "$APP_PATH" && "$FORCE" != "1" ]]; then
  printf '%s\n' "ERROR: ${APP_PATH} already exists. Re-run with --force to overwrite." >&2
  exit 1
fi

if [[ -e "$APP_PATH" && "$FORCE" == "1" ]]; then
  rm -rf "$APP_PATH"
fi

mkdir -p "$MACOS_DIR" "$RESOURCES_DIR"

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
  <string>com.whisperwebui.mlx</string>
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
  <string>12.0</string>
</dict>
</plist>
PLIST

cat > "${MACOS_DIR}/launcher" <<BASH
#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="${ROOT_DIR}"
LOG_DIR="\${ROOT_DIR}/data/logs"
LOG_FILE="\${LOG_DIR}/app_launcher.log"

if [[ ! -x "\${ROOT_DIR}/run.sh" ]]; then
  if command -v osascript >/dev/null 2>&1; then
    osascript -e 'display dialog "Could not find run.sh. Rebuild the app from the repo root." buttons {"OK"} with icon stop'
  fi
  exit 1
fi

mkdir -p "\${LOG_DIR}"

if command -v lsof >/dev/null 2>&1; then
  if lsof -iTCP:8000 -sTCP:LISTEN -n -P >/dev/null 2>&1; then
    if command -v open >/dev/null 2>&1; then
      open "http://127.0.0.1:8000" >/dev/null 2>&1 || true
    fi
    exit 0
  fi
fi

exec "\${ROOT_DIR}/run.sh" >>"\${LOG_FILE}" 2>&1
BASH

chmod +x "${MACOS_DIR}/launcher"

printf '%s\n' "Created app: ${APP_PATH}"
printf '%s\n' "Logs: ${ROOT_DIR}/data/logs/app_launcher.log"
