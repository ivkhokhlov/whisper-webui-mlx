#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CONTRACT_PATH="${ROOT_DIR}/docs/release/macos_targets.toml"

TARGET=""
ARTIFACT_TYPE="dmg" # dmg | zip
ARTIFACT_DIR="${ROOT_DIR}/dist/release"
ARTIFACT_PATH=""
LOG_DIR=""
TIMEOUT="60m"
FORCE=0
DRY_RUN=0
KEEP_WORKDIR=0

# Auth (prefer keychain profile)
KEYCHAIN_PROFILE="${MACOS_NOTARY_KEYCHAIN_PROFILE:-${NOTARYTOOL_KEYCHAIN_PROFILE:-}}"
KEYCHAIN_PATH="${MACOS_NOTARY_KEYCHAIN:-}"

# Apple ID auth
APPLE_ID="${MACOS_NOTARY_APPLE_ID:-${APPLE_ID:-}}"
TEAM_ID="${MACOS_NOTARY_TEAM_ID:-${TEAM_ID:-}}"
PASSWORD="${MACOS_NOTARY_PASSWORD:-${APPLE_APP_SPECIFIC_PASSWORD:-${NOTARYTOOL_PASSWORD:-}}}"

# API key auth (App Store Connect)
ASC_KEY_PATH="${MACOS_NOTARY_KEY:-}"
ASC_KEY_ID="${MACOS_NOTARY_KEY_ID:-}"
ASC_ISSUER="${MACOS_NOTARY_ISSUER:-}"

usage() {
  cat <<'EOF'
Notarize a signed macOS release artifact (DMG or ZIP) and staple the ticket.

This script performs notarization only (no build/sign). It uses:
- xcrun notarytool submit --wait
- xcrun notarytool log
- xcrun stapler staple + validate

Usage (explicit artifact path):
  ./scripts/notarize_macos_artifact.sh --artifact dist/release/whisper-webui-mlx-v0.1.4-macos-arm64.dmg --keychain-profile "profile"

Usage (resolve artifact path from contract):
  ./scripts/notarize_macos_artifact.sh --target macos-arm64 --type dmg --keychain-profile "profile"

Options:
  --artifact PATH         Path to the signed .dmg or .zip to notarize (overrides --target/--type)
  --target TARGET         macOS release target (macos-arm64 | macos-intel) used to resolve artifact path
  --type TYPE             Artifact type: dmg | zip (default: dmg)
  --artifact-dir DIR      Directory containing artifacts when using --target (default: dist/release/)
  --log-dir DIR           Directory to write notarization logs (default: dist/release/notary/<artifact_stem>/)
  --timeout DURATION      notarytool --wait timeout (default: 60m)
  --keep-workdir          Keep extracted workdir (zip stapling) for debugging
  --force                 Overwrite existing log dir

Auth (choose one method; do not hard-code secrets):
  --keychain-profile NAME Use a notarytool keychain profile (recommended)
  --keychain PATH         Keychain file path for reading the profile
  --apple-id ID           Apple ID email
  --team-id ID            Apple Developer Team ID
  --password PASS         App-specific password (optional; notarytool may prompt if omitted)
  --key PATH              App Store Connect API key (.p8)
  --key-id ID             App Store Connect API Key ID
  --issuer UUID           App Store Connect API Issuer ID

Dry-run:
  --dry-run               Print the plan without running notarytool/stapler (no credentials required)
  -h, --help              Show this help

Notes:
- For ZIP artifacts, this script expects the zip to contain a single top-level .app bundle.
- Notarization is intentionally separate from signing and notarization credentials are never stored in repo files.
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

tmpl = ""
if key == "artifact_name":
    tmpl = str(targets[target].get("artifact_name") or "").strip()
elif key == "dmg_artifact_name":
    tmpl = str(targets[target].get("dmg_artifact_name") or "").strip()
else:
    raise SystemExit(f"unknown key: {key}")

print(tmpl.replace("{version}", version))
PY
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --artifact)
      ARTIFACT_PATH="${2:-}"
      shift 2
      ;;
    --target)
      TARGET="${2:-}"
      shift 2
      ;;
    --type)
      ARTIFACT_TYPE="${2:-}"
      shift 2
      ;;
    --artifact-dir)
      ARTIFACT_DIR="${2:-}"
      shift 2
      ;;
    --log-dir)
      LOG_DIR="${2:-}"
      shift 2
      ;;
    --timeout)
      TIMEOUT="${2:-}"
      shift 2
      ;;
    --keep-workdir)
      KEEP_WORKDIR=1
      shift
      ;;
    --force)
      FORCE=1
      shift
      ;;
    --keychain-profile)
      KEYCHAIN_PROFILE="${2:-}"
      shift 2
      ;;
    --keychain)
      KEYCHAIN_PATH="${2:-}"
      shift 2
      ;;
    --apple-id)
      APPLE_ID="${2:-}"
      shift 2
      ;;
    --team-id)
      TEAM_ID="${2:-}"
      shift 2
      ;;
    --password)
      PASSWORD="${2:-}"
      shift 2
      ;;
    --key)
      ASC_KEY_PATH="${2:-}"
      shift 2
      ;;
    --key-id)
      ASC_KEY_ID="${2:-}"
      shift 2
      ;;
    --issuer)
      ASC_ISSUER="${2:-}"
      shift 2
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

if [[ "$ARTIFACT_TYPE" != "dmg" && "$ARTIFACT_TYPE" != "zip" ]]; then
  fail "Unsupported --type: ${ARTIFACT_TYPE} (expected: dmg | zip)"
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

if [[ -z "$ARTIFACT_PATH" ]]; then
  if [[ -z "$TARGET" ]]; then
    fail "Provide --artifact PATH or --target TARGET."
  fi
  if [[ ! -f "$CONTRACT_PATH" ]]; then
    fail "Missing contract file: $CONTRACT_PATH"
  fi
  name_key="dmg_artifact_name"
  if [[ "$ARTIFACT_TYPE" == "zip" ]]; then
    name_key="artifact_name"
  fi
  ARTIFACT_NAME="$(python_field "$TARGET" "$name_key" "$VERSION")"
  if [[ -z "$ARTIFACT_NAME" ]]; then
    fail "Contract missing artifact name for target '${TARGET}'."
  fi
  ARTIFACT_DIR="${ARTIFACT_DIR%/}"
  ARTIFACT_PATH="${ARTIFACT_DIR}/${ARTIFACT_NAME}"
fi

if [[ -z "$LOG_DIR" ]]; then
  artifact_base="$(basename "$ARTIFACT_PATH")"
  artifact_stem="${artifact_base%.*}"
  LOG_DIR="${ROOT_DIR}/dist/release/notary/${artifact_stem}"
fi

if [[ "$DRY_RUN" == "1" ]]; then
  printf '%s\n' "==> Dry-run plan"
  printf '%s\n' "Artifact: ${ARTIFACT_PATH}"
  printf '%s\n' "Type: ${ARTIFACT_TYPE}"
  printf '%s\n' "Logs: ${LOG_DIR}"
  printf '%s\n' "Timeout: ${TIMEOUT}"
  printf '%s\n' "Actions:"
  printf '%s\n' "  - xcrun notarytool submit --wait (auth via keychain profile / Apple ID / API key)"
  printf '%s\n' "  - xcrun notarytool log <submission-id> -> ${LOG_DIR}/notary_log.json"
  if [[ "$ARTIFACT_TYPE" == "dmg" ]]; then
    printf '%s\n' "  - xcrun stapler staple + validate ${ARTIFACT_PATH}"
  else
    printf '%s\n' "  - extract zip, staple the .app, re-zip in-place"
  fi
  exit 0
fi

if [[ "$(uname -s)" != "Darwin" ]]; then
  fail "This script supports macOS only."
fi

if ! command -v xcrun >/dev/null 2>&1; then
  fail "Missing required tool: xcrun"
fi
if ! xcrun notarytool --help >/dev/null 2>&1; then
  fail "xcrun notarytool is not available (install Xcode Command Line Tools)."
fi
if ! command -v file >/dev/null 2>&1; then
  fail "Missing required tool: file"
fi
if [[ "$ARTIFACT_TYPE" == "zip" ]]; then
  if ! command -v ditto >/dev/null 2>&1; then
    fail "Missing required tool for zip stapling: ditto"
  fi
fi

if [[ ! -f "$ARTIFACT_PATH" ]]; then
  fail "Artifact not found: $ARTIFACT_PATH"
fi
if [[ "$ARTIFACT_TYPE" == "dmg" && "${ARTIFACT_PATH}" != *.dmg ]]; then
  fail "Expected a .dmg artifact path, got: $ARTIFACT_PATH"
fi
if [[ "$ARTIFACT_TYPE" == "zip" && "${ARTIFACT_PATH}" != *.zip ]]; then
  fail "Expected a .zip artifact path, got: $ARTIFACT_PATH"
fi

auth_args=()
if [[ -n "$KEYCHAIN_PROFILE" ]]; then
  auth_args+=(--keychain-profile "$KEYCHAIN_PROFILE")
  if [[ -n "$KEYCHAIN_PATH" ]]; then
    auth_args+=(--keychain "$KEYCHAIN_PATH")
  fi
elif [[ -n "$ASC_KEY_PATH" || -n "$ASC_KEY_ID" || -n "$ASC_ISSUER" ]]; then
  if [[ -z "$ASC_KEY_PATH" || -z "$ASC_KEY_ID" ]]; then
    fail "API key auth requires --key and --key-id (and optionally --issuer)."
  fi
  auth_args+=(--key "$ASC_KEY_PATH" --key-id "$ASC_KEY_ID")
  if [[ -n "$ASC_ISSUER" ]]; then
    auth_args+=(--issuer "$ASC_ISSUER")
  fi
elif [[ -n "$APPLE_ID" || -n "$TEAM_ID" || -n "$PASSWORD" ]]; then
  if [[ -z "$APPLE_ID" || -z "$TEAM_ID" ]]; then
    fail "Apple ID auth requires --apple-id and --team-id (and optionally --password)."
  fi
  auth_args+=(--apple-id "$APPLE_ID" --team-id "$TEAM_ID")
  if [[ -n "$PASSWORD" ]]; then
    auth_args+=(--password "$PASSWORD")
  fi
else
  fail "Missing notarization credentials. Use --keychain-profile or Apple ID / API key arguments."
fi

if [[ -d "$LOG_DIR" ]]; then
  if [[ "$FORCE" != "1" ]]; then
    fail "Log dir already exists: $LOG_DIR (use --force to overwrite)"
  fi
  rm -rf "$LOG_DIR"
fi
mkdir -p "$LOG_DIR"

SUBMIT_JSON="${LOG_DIR}/notary_submit.json"
SUBMIT_STDERR="${LOG_DIR}/notary_submit.stderr.txt"
LOG_JSON="${LOG_DIR}/notary_log.json"

printf '%s\n' "==> Submitting for notarization..."
if ! xcrun notarytool submit "${auth_args[@]}" \
  --wait --timeout "$TIMEOUT" --output-format json \
  "$ARTIFACT_PATH" >"$SUBMIT_JSON" 2>"$SUBMIT_STDERR"; then
  printf '%s\n' "Notary submission failed. See:" >&2
  printf '%s\n' "  ${SUBMIT_STDERR}" >&2
  exit 1
fi

submission_id="$(python3 - "$SUBMIT_JSON" <<'PY'
import json
import sys
from pathlib import Path

data = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
print((data.get("id") or "").strip())
PY
)"
status="$(python3 - "$SUBMIT_JSON" <<'PY'
import json
import sys
from pathlib import Path

data = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
print((data.get("status") or "").strip())
PY
)"

if [[ -z "$submission_id" ]]; then
  fail "Unable to parse notary submission id from ${SUBMIT_JSON}"
fi

printf '%s\n' "Submission id: ${submission_id}"
printf '%s\n' "Status: ${status:-unknown}"

printf '%s\n' "==> Fetching notarization log..."
if ! xcrun notarytool log "${auth_args[@]}" "$submission_id" "$LOG_JSON" >/dev/null 2>&1; then
  printf '%s\n' "WARNING: Failed to fetch notary log (submission id: ${submission_id})." >&2
else
  printf '%s\n' "Notary log: ${LOG_JSON}"
fi

if [[ "$status" != "Accepted" ]]; then
  printf '%s\n' "ERROR: Notarization did not succeed (status: ${status})." >&2
  printf '%s\n' "See logs in: ${LOG_DIR}" >&2
  exit 2
fi

printf '%s\n' "==> Notarization accepted; stapling ticket..."

if [[ "$ARTIFACT_TYPE" == "dmg" ]]; then
  STAPLE_OUT="${LOG_DIR}/stapler_staple.txt"
  VALIDATE_OUT="${LOG_DIR}/stapler_validate.txt"
  xcrun stapler staple -v "$ARTIFACT_PATH" >"$STAPLE_OUT" 2>&1
  xcrun stapler validate -v "$ARTIFACT_PATH" >"$VALIDATE_OUT" 2>&1
  printf '%s\n' "Stapled DMG: ${ARTIFACT_PATH}"
  printf '%s\n' "Stapler output: ${STAPLE_OUT}"
  printf '%s\n' "Stapler validate: ${VALIDATE_OUT}"
else
  WORK_DIR="${LOG_DIR}/zip_workdir"
  EXTRACT_DIR="${WORK_DIR}/extract"
  rm -rf "$WORK_DIR"
  mkdir -p "$EXTRACT_DIR"

  printf '%s\n' "==> Extracting zip for stapling..."
  ditto -x -k "$ARTIFACT_PATH" "$EXTRACT_DIR"

  apps=()
  while IFS= read -r line; do
    apps+=("$line")
  done < <(find "$EXTRACT_DIR" -maxdepth 1 -type d -name '*.app' | sort)

  apps_count="${#apps[@]}"
  if [[ "$apps_count" != "1" ]]; then
    printf '%s\n' "ERROR: Expected a single top-level .app in the zip; found ${apps_count}." >&2
    printf '%s\n' "Extracted at: ${EXTRACT_DIR}" >&2
    exit 3
  fi
  APP_TO_STAPLE="${apps[0]}"

  STAPLE_OUT="${LOG_DIR}/stapler_staple.txt"
  VALIDATE_OUT="${LOG_DIR}/stapler_validate.txt"
  xcrun stapler staple -v "$APP_TO_STAPLE" >"$STAPLE_OUT" 2>&1
  xcrun stapler validate -v "$APP_TO_STAPLE" >"$VALIDATE_OUT" 2>&1

  printf '%s\n' "==> Repacking zip (in-place)..."
  TMP_ZIP="${ARTIFACT_PATH%.zip}.tmp.zip"
  rm -f "$TMP_ZIP"
  ditto -c -k --sequesterRsrc --keepParent "$APP_TO_STAPLE" "$TMP_ZIP"
  mv "$TMP_ZIP" "$ARTIFACT_PATH"

  if [[ "$KEEP_WORKDIR" != "1" ]]; then
    rm -rf "$WORK_DIR"
  fi

  printf '%s\n' "Stapled app inside zip: ${ARTIFACT_PATH}"
  printf '%s\n' "Stapler output: ${STAPLE_OUT}"
  printf '%s\n' "Stapler validate: ${VALIDATE_OUT}"
fi

printf '%s\n' "Notarization complete."
printf '%s\n' "Logs: ${LOG_DIR}"
