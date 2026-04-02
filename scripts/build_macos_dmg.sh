#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CONTRACT_PATH="${ROOT_DIR}/docs/release/macos_targets.toml"

TARGET="macos-arm64"
APP_PATH=""
OUT_DIR="${ROOT_DIR}/dist/release"
STAGE_DIR=""
FORCE=0
VOLUME_NAME_OVERRIDE=""

usage() {
  cat <<'EOF'
Build a deterministic, drag-to-Applications DMG from a finished .app bundle.

Usage:
  ./scripts/build_macos_dmg.sh --target macos-arm64 [--app PATH] [--out DIR] [--force]
  ./scripts/build_macos_dmg.sh --target macos-intel [--app PATH] [--out DIR] [--force]

Options:
  --target TARGET      Release target from docs/release/macos_targets.toml (macos-arm64 | macos-intel)
  --app PATH           Path to the finished .app (default: dist/<target>/<bundle_name>)
  --out DIR            Output directory (default: dist/release/)
  --stage DIR          Deterministic staging directory (default: dist/dmg-stage/<target>)
  --volume-name NAME   Override the DMG volume name (default: product name from the contract)
  --force              Overwrite existing DMG output
  -h, --help           Show this help

Notes:
- Uses built-in macOS tooling (hdiutil + ditto). No signing/notarization.
- The DMG contains the .app bundle + an /Applications symlink.
EOF
}

fail() {
  printf '%s\n' "ERROR: $*" >&2
  exit 1
}

python_field() {
  local target="$1"
  local key="$2"
  local version="$3"
  python3 - "$CONTRACT_PATH" "$target" "$key" "$version" <<'PY'
import sys
from pathlib import Path
import tomllib

contract_path = Path(sys.argv[1])
target = sys.argv[2]
key = sys.argv[3]
version = sys.argv[4]

data = tomllib.loads(contract_path.read_text(encoding="utf-8"))
macos = data.get("macos", {})
targets = macos.get("targets", {})
if target not in targets:
    raise SystemExit(f"unknown target: {target}")

if key == "product_name":
    print((macos.get("product_name") or "").strip())
elif key == "bundle_name":
    print((macos.get("bundle_name") or "").strip())
elif key == "dmg_artifact_name":
    tmpl = (targets[target].get("dmg_artifact_name") or "").strip()
    print(tmpl.replace("{version}", version))
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
    --app)
      APP_PATH="${2:-}"
      shift 2
      ;;
    --out)
      OUT_DIR="${2:-}"
      shift 2
      ;;
    --stage)
      STAGE_DIR="${2:-}"
      shift 2
      ;;
    --volume-name)
      VOLUME_NAME_OVERRIDE="${2:-}"
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

if ! command -v hdiutil >/dev/null 2>&1; then
  fail "Missing required tool: hdiutil"
fi
if ! command -v ditto >/dev/null 2>&1; then
  fail "Missing required tool: ditto"
fi

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

BUNDLE_NAME="$(python_field "$TARGET" "bundle_name" "$VERSION")"
if [[ -z "$BUNDLE_NAME" ]]; then
  fail "Contract missing macos.bundle_name."
fi

if [[ -z "$APP_PATH" ]]; then
  APP_PATH="${ROOT_DIR}/dist/${TARGET}/${BUNDLE_NAME}"
fi
if [[ ! -d "$APP_PATH" ]]; then
  fail "App bundle not found: $APP_PATH"
fi
if [[ "${APP_PATH}" != *.app ]]; then
  fail "Expected a .app bundle directory, got: $APP_PATH"
fi

VALIDATOR="${ROOT_DIR}/scripts/validate_macos_app_bundle.py"
if [[ ! -f "$VALIDATOR" ]]; then
  fail "Missing app-bundle validator: $VALIDATOR"
fi
python3 "$VALIDATOR" --app "$APP_PATH" >/dev/null

DMG_NAME="$(python_field "$TARGET" "dmg_artifact_name" "$VERSION")"
if [[ -z "$DMG_NAME" ]]; then
  fail "Contract missing dmg_artifact_name for target '$TARGET'."
fi

OUT_DIR="${OUT_DIR%/}"
mkdir -p "$OUT_DIR"
DMG_PATH="${OUT_DIR}/${DMG_NAME}"

if [[ -e "$DMG_PATH" && "$FORCE" != "1" ]]; then
  fail "${DMG_PATH} already exists. Re-run with --force to overwrite."
fi

if [[ -z "$STAGE_DIR" ]]; then
  STAGE_DIR="${ROOT_DIR}/dist/dmg-stage/${TARGET}"
fi

APP_BASENAME="$(basename "$APP_PATH")"

rm -rf "$STAGE_DIR"
mkdir -p "$STAGE_DIR"

printf '%s\n' "==> Staging DMG contents..."
ditto "$APP_PATH" "${STAGE_DIR}/${APP_BASENAME}"
ln -s /Applications "${STAGE_DIR}/Applications"

VOLUME_NAME="$(python_field "$TARGET" "product_name" "$VERSION")"
if [[ -n "$VOLUME_NAME_OVERRIDE" ]]; then
  VOLUME_NAME="$VOLUME_NAME_OVERRIDE"
fi
if [[ -z "$VOLUME_NAME" ]]; then
  VOLUME_NAME="Whisper WebUI"
fi

TMP_DMG="${DMG_PATH%.dmg}.tmp.dmg"
rm -f "$TMP_DMG" "$DMG_PATH"

printf '%s\n' "==> Building DMG..."
hdiutil create \
  -volname "$VOLUME_NAME" \
  -srcfolder "$STAGE_DIR" \
  -ov \
  -fs HFS+ \
  -format UDZO \
  -imagekey zlib-level=9 \
  "$TMP_DMG" >/dev/null

printf '%s\n' "==> Verifying DMG..."
hdiutil verify "$TMP_DMG" >/dev/null

mv "$TMP_DMG" "$DMG_PATH"

printf '%s\n' "Created DMG: ${DMG_PATH}"
printf '%s\n' "Target: ${TARGET}"
printf '%s\n' "App: ${APP_PATH}"
printf '%s\n' "Volume name: ${VOLUME_NAME}"
