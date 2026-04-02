#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VALIDATOR="${ROOT_DIR}/scripts/validate_macos_app_bundle.py"

APP_PATH=""
IDENTITY="${MACOS_SIGNING_IDENTITY:-${CODESIGN_IDENTITY:-}}"
ENTITLEMENTS=""
DRY_RUN=0
HARDENED_RUNTIME=0
TIMESTAMP_FLAG="--timestamp=none"
export LC_ALL=C

usage() {
  cat <<'EOF'
Sign a packaged macOS .app bundle (nested code first, then the top-level app).

This script performs code signing only (no notarization).

Usage:
  ./scripts/sign_macos_app.sh --app dist/macos-arm64/"Whisper WebUI (MLX).app" --identity "Developer ID Application: ..."

Options:
  --app PATH           Path to the finished .app bundle to sign
  --identity ID        Code-sign identity (or set MACOS_SIGNING_IDENTITY / CODESIGN_IDENTITY)
  --adhoc              Use ad-hoc signing identity ("-") for local testing
  --entitlements PATH  Optional entitlements plist (applied to the top-level .app)
  --hardened-runtime   Add --options runtime when signing
  --timestamp          Enable RFC3161 timestamping (network); default disables timestamps for determinism
  --dry-run            Print the signing plan without modifying the app
  -h, --help           Show this help

Notes:
- The app bundle is validated using scripts/validate_macos_app_bundle.py first.
- Only Mach-O files are signed as nested code (plus the launcher entrypoint).
- Verification is run after signing (codesign --verify --deep --strict).
EOF
}

fail() {
  printf '%s\n' "ERROR: $*" >&2
  exit 1
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --app)
      APP_PATH="${2:-}"
      shift 2
      ;;
    --identity)
      IDENTITY="${2:-}"
      shift 2
      ;;
    --adhoc)
      IDENTITY="-"
      shift
      ;;
    --entitlements)
      ENTITLEMENTS="${2:-}"
      shift 2
      ;;
    --hardened-runtime)
      HARDENED_RUNTIME=1
      shift
      ;;
    --timestamp)
      TIMESTAMP_FLAG="--timestamp"
      shift
      ;;
    --dry-run)
      DRY_RUN=1
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

if [[ -z "$APP_PATH" ]]; then
  fail "Missing --app PATH"
fi

if [[ "$(uname -s)" != "Darwin" ]]; then
  fail "This script supports macOS only."
fi

if ! command -v codesign >/dev/null 2>&1; then
  fail "Missing required tool: codesign"
fi
if ! command -v file >/dev/null 2>&1; then
  fail "Missing required tool: file"
fi
if [[ ! -f "$VALIDATOR" ]]; then
  fail "Missing app-bundle validator: $VALIDATOR"
fi

if [[ ! -d "$APP_PATH" ]]; then
  fail "App bundle not found: $APP_PATH"
fi
if [[ "${APP_PATH}" != *.app ]]; then
  fail "Expected a .app bundle directory, got: $APP_PATH"
fi

python3 "$VALIDATOR" --app "$APP_PATH" >/dev/null

if [[ -n "$ENTITLEMENTS" && ! -f "$ENTITLEMENTS" ]]; then
  fail "Entitlements plist not found: $ENTITLEMENTS"
fi

if [[ "$DRY_RUN" != "1" && -z "$IDENTITY" ]]; then
  fail "Missing signing identity. Pass --identity or set MACOS_SIGNING_IDENTITY/CODESIGN_IDENTITY."
fi

if [[ ! -x "${APP_PATH}/Contents/MacOS/launcher" ]]; then
  fail "Missing launcher executable: ${APP_PATH}/Contents/MacOS/launcher"
fi

printf '%s\n' "==> Collecting nested sign targets..."

sign_targets_tmp="$(mktemp)"
cleanup_tmp() { rm -f "$sign_targets_tmp" >/dev/null 2>&1 || true; }
trap cleanup_tmp EXIT

printf '%s\n' "${APP_PATH}/Contents/MacOS/launcher" >"$sign_targets_tmp"

while IFS= read -r -d '' candidate; do
  if file -b "$candidate" | grep -q "Mach-O"; then
    printf '%s\n' "$candidate" >>"$sign_targets_tmp"
  fi
done < <(
  find "${APP_PATH}/Contents" -type f \
    \( -perm -111 -o -name '*.dylib' -o -name '*.so' -o -name '*.bundle' \) \
    -print0
)

SIGN_TARGETS=()
while IFS= read -r path; do
  SIGN_TARGETS+=("$path")
done < <(
  sort -u "$sign_targets_tmp" | awk -F/ '{print (NF-1) "\t" $0}' | sort -nr -k1,1 -k2,2 | cut -f2-
)

printf '%s\n' "==> Signing plan (nested first):"
for path in "${SIGN_TARGETS[@]}"; do
  printf '  %s\n' "$path"
done
printf '  %s\n' "${APP_PATH}"

codesign_common_args=(
  --force
  --sign "$IDENTITY"
  "$TIMESTAMP_FLAG"
)
if [[ "$HARDENED_RUNTIME" == "1" ]]; then
  codesign_common_args+=(--options runtime)
fi

if [[ "$DRY_RUN" == "1" ]]; then
  printf '%s\n' "==> Dry-run: no signing performed."
  exit 0
fi

printf '%s\n' "==> Signing nested code..."
for path in "${SIGN_TARGETS[@]}"; do
  printf '%s\n' "Signing: ${path}"
  codesign "${codesign_common_args[@]}" "$path"
done

printf '%s\n' "==> Signing top-level app..."
top_level_args=("${codesign_common_args[@]}")
if [[ -n "$ENTITLEMENTS" ]]; then
  top_level_args+=(--entitlements "$ENTITLEMENTS")
fi
codesign "${top_level_args[@]}" "$APP_PATH"

printf '%s\n' "==> Verification (codesign --verify --deep --strict)..."
codesign -vv --deep --strict "$APP_PATH"

printf '%s\n' "==> Signed app details:"
codesign -d --verbose=4 "$APP_PATH" 2>&1

printf '%s\n' "Signed app: ${APP_PATH}"
