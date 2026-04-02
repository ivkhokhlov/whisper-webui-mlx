#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CONTRACT_PATH="${ROOT_DIR}/docs/release/macos_targets.toml"
VALIDATOR="${ROOT_DIR}/scripts/validate_macos_app_bundle.py"

TARGET=""
TYPE="dmg" # dmg | zip | app
ARTIFACT_DIR="${ROOT_DIR}/dist/release"
ARTIFACT_PATH=""
LOG_DIR=""
FORCE=0
DRY_RUN=0
KEEP_WORKDIR=0

usage() {
  cat <<'EOF'
Verify a packaged macOS release artifact before shipping (offline).

Checks:
- Bundle integrity via scripts/validate_macos_app_bundle.py
- Code signatures via codesign --verify --deep --strict
- Notarization ticket via xcrun stapler validate
- Gatekeeper readiness:
  - Modern: syspolicy_check distribution (if available)
  - Fallback: spctl --assess (--type execute/open)

Usage (explicit path):
  ./scripts/verify_macos_artifact.sh --artifact dist/release/whisper-webui-mlx-v0.1.4-macos-arm64.dmg
  ./scripts/verify_macos_artifact.sh --artifact dist/macos-arm64/"Whisper WebUI (MLX).app"

Usage (resolve from contract):
  ./scripts/verify_macos_artifact.sh --target macos-arm64 --type dmg

Options:
  --artifact PATH         Path to a .dmg, .zip, or .app (overrides --target/--type)
  --target TARGET         Release target (macos-arm64 | macos-intel) used to resolve artifact path
  --type TYPE             Artifact type: dmg | zip | app (default: dmg)
  --artifact-dir DIR      Directory containing artifacts when using --target (default: dist/release/)
  --log-dir DIR           Directory to write verification logs (default: dist/release/verify/<artifact_stem>/)
  --keep-workdir          Keep extracted workdir (zip) for debugging
  --force                 Overwrite existing log dir
  --dry-run               Print the plan without running verification
  -h, --help              Show this help

Notes:
- For DMG: verifies the disk image, validates stapling, checks Gatekeeper on the DMG,
  mounts read-only, and verifies the contained .app.
- For ZIP: extracts, expects a single top-level .app, and verifies that app (including stapling).
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
if key == "bundle_name":
    tmpl = str(macos.get("bundle_name") or "").strip()
elif key == "artifact_name":
    tmpl = str(targets[target].get("artifact_name") or "").strip()
elif key == "dmg_artifact_name":
    tmpl = str(targets[target].get("dmg_artifact_name") or "").strip()
else:
    raise SystemExit(f"unknown key: {key}")

print(tmpl.replace("{version}", version))
PY
}

run_logged() {
  local name="$1"
  shift
  local out="${LOG_DIR}/${name}.txt"
  printf '%s\n' "==> ${name}"
  if ! "$@" >"$out" 2>&1; then
    printf '%s\n' "FAILED: ${name}"
    printf '%s\n' "Command: $*"
    printf '%s\n' "---- output (${out}) ----" >&2
    tail -n 200 "$out" >&2 || true
    printf '%s\n' "---- end ----" >&2
    return 1
  fi
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
      TYPE="${2:-}"
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
    --keep-workdir)
      KEEP_WORKDIR=1
      shift
      ;;
    --force)
      FORCE=1
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

if [[ "$TYPE" != "dmg" && "$TYPE" != "zip" && "$TYPE" != "app" ]]; then
  fail "Unsupported --type: ${TYPE} (expected: dmg | zip | app)"
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

  ARTIFACT_DIR="${ARTIFACT_DIR%/}"
  if [[ "$TYPE" == "dmg" ]]; then
    name="$(python_field "$TARGET" "dmg_artifact_name" "$VERSION")"
    ARTIFACT_PATH="${ARTIFACT_DIR}/${name}"
  elif [[ "$TYPE" == "zip" ]]; then
    name="$(python_field "$TARGET" "artifact_name" "$VERSION")"
    ARTIFACT_PATH="${ARTIFACT_DIR}/${name}"
  else
    bundle_name="$(python_field "$TARGET" "bundle_name" "$VERSION")"
    ARTIFACT_PATH="${ROOT_DIR}/dist/${TARGET}/${bundle_name}"
  fi
fi

if [[ -z "$LOG_DIR" ]]; then
  base="$(basename "$ARTIFACT_PATH")"
  stem="${base%.*}"
  LOG_DIR="${ROOT_DIR}/dist/release/verify/${stem}"
fi

if [[ "$DRY_RUN" == "1" ]]; then
  printf '%s\n' "==> Dry-run plan"
  printf '%s\n' "Artifact: ${ARTIFACT_PATH}"
  printf '%s\n' "Type: ${TYPE}"
  printf '%s\n' "Logs: ${LOG_DIR}"
  printf '%s\n' "Checks:"
  if [[ "$TYPE" == "dmg" ]]; then
    printf '%s\n' "  - hdiutil verify"
    printf '%s\n' "  - stapler validate (DMG)"
    printf '%s\n' "  - spctl assess (DMG open)"
    printf '%s\n' "  - mount + verify contained .app"
  elif [[ "$TYPE" == "zip" ]]; then
    printf '%s\n' "  - extract + verify contained .app"
  else
    printf '%s\n' "  - verify .app"
  fi
  printf '%s\n' "  - validate_macos_app_bundle.py"
  printf '%s\n' "  - codesign verify"
  printf '%s\n' "  - stapler validate (app)"
  printf '%s\n' "  - syspolicy_check distribution (if available), else spctl execute"
  exit 0
fi

if [[ "$(uname -s)" != "Darwin" ]]; then
  fail "This script supports macOS only."
fi

if [[ -d "$LOG_DIR" ]]; then
  if [[ "$FORCE" != "1" ]]; then
    fail "Log dir already exists: $LOG_DIR (use --force to overwrite)"
  fi
  rm -rf "$LOG_DIR"
fi
mkdir -p "$LOG_DIR"

if [[ ! -f "$VALIDATOR" ]]; then
  fail "Missing app-bundle validator: $VALIDATOR"
fi

if ! command -v codesign >/dev/null 2>&1; then
  fail "Missing required tool: codesign"
fi
if ! command -v spctl >/dev/null 2>&1; then
  fail "Missing required tool: spctl"
fi
if ! command -v xcrun >/dev/null 2>&1; then
  fail "Missing required tool: xcrun"
fi
if ! xcrun stapler validate -h >/dev/null 2>&1; then
  fail "xcrun stapler is not available (install Xcode Command Line Tools)."
fi

work_dir="${LOG_DIR}/workdir"
rm -rf "$work_dir"
mkdir -p "$work_dir"

dmg_dev_entry=""
dmg_mount_point=""
cleanup_dmg_mount() {
  if [[ -n "$dmg_dev_entry" ]]; then
    hdiutil detach "$dmg_dev_entry" -force >/dev/null 2>&1 || true
  fi
}
trap cleanup_dmg_mount EXIT

verify_app() {
  local app_path="$1"

  if [[ ! -d "$app_path" ]]; then
    fail "App bundle not found: $app_path"
  fi
  if [[ "${app_path}" != *.app ]]; then
    fail "Expected a .app bundle directory, got: $app_path"
  fi

  run_logged "bundle_validate" python3 "$VALIDATOR" --app "$app_path"
  run_logged "codesign_verify" codesign -vv --deep --strict "$app_path"
  run_logged "codesign_details" codesign -d --verbose=4 "$app_path"
  run_logged "stapler_validate_app" xcrun stapler validate -v "$app_path"

  if command -v syspolicy_check >/dev/null 2>&1; then
    printf '%s\n' "==> syspolicy_check distribution (modern Gatekeeper preflight)"
    local json_out="${LOG_DIR}/syspolicy_check.json"
    local err_out="${LOG_DIR}/syspolicy_check.stderr.txt"
    if ! syspolicy_check distribution "$app_path" -vvv --json >"$json_out" 2>"$err_out"; then
      printf '%s\n' "FAILED: syspolicy_check distribution"
      printf '%s\n' "See:"
      printf '%s\n' "  ${json_out}"
      printf '%s\n' "  ${err_out}"
      tail -n 200 "$err_out" >&2 || true
      return 1
    fi
  else
    printf '%s\n' "==> syspolicy_check not available; using spctl fallback."
  fi

  run_logged "spctl_assess_execute" spctl --assess --type execute -vv "$app_path"
}

if [[ "$TYPE" == "app" ]]; then
  verify_app "$ARTIFACT_PATH"
elif [[ "$TYPE" == "zip" ]]; then
  if ! command -v ditto >/dev/null 2>&1; then
    fail "Missing required tool for zip extraction: ditto"
  fi
  if [[ ! -f "$ARTIFACT_PATH" ]]; then
    fail "Artifact not found: $ARTIFACT_PATH"
  fi
  if [[ "${ARTIFACT_PATH}" != *.zip ]]; then
    fail "Expected a .zip artifact path, got: $ARTIFACT_PATH"
  fi

  extract_dir="${work_dir}/extract"
  mkdir -p "$extract_dir"
  run_logged "zip_extract" ditto -x -k "$ARTIFACT_PATH" "$extract_dir"

  apps=()
  while IFS= read -r line; do
    apps+=("$line")
  done < <(find "$extract_dir" -maxdepth 1 -type d -name '*.app' | sort)

  if [[ "${#apps[@]}" != "1" ]]; then
    printf '%s\n' "ERROR: Expected a single top-level .app in the zip; found ${#apps[@]}." >&2
    printf '%s\n' "Extracted at: ${extract_dir}" >&2
    exit 3
  fi
  verify_app "${apps[0]}"

  if [[ "$KEEP_WORKDIR" != "1" ]]; then
    rm -rf "$work_dir"
  fi
else
  if [[ ! -f "$ARTIFACT_PATH" ]]; then
    fail "Artifact not found: $ARTIFACT_PATH"
  fi
  if [[ "${ARTIFACT_PATH}" != *.dmg ]]; then
    fail "Expected a .dmg artifact path, got: $ARTIFACT_PATH"
  fi

  if ! command -v hdiutil >/dev/null 2>&1; then
    fail "Missing required tool: hdiutil"
  fi

  run_logged "dmg_verify" hdiutil verify "$ARTIFACT_PATH"
  run_logged "stapler_validate_dmg" xcrun stapler validate -v "$ARTIFACT_PATH"
  run_logged "spctl_assess_open" spctl --assess --type open -vv "$ARTIFACT_PATH"

  attach_plist="${work_dir}/dmg_attach.plist"
  if ! hdiutil attach -nobrowse -readonly -plist "$ARTIFACT_PATH" >"$attach_plist" 2>"${LOG_DIR}/dmg_attach.stderr.txt"; then
    printf '%s\n' "ERROR: Failed to attach DMG. See ${LOG_DIR}/dmg_attach.stderr.txt" >&2
    exit 4
  fi

  IFS=$'\n' read -r dmg_mount_point dmg_dev_entry < <(python3 - "$attach_plist" <<'PY'
import plistlib
import sys
from pathlib import Path

payload = plistlib.loads(Path(sys.argv[1]).read_bytes())
mount = ""
dev = ""
for entity in payload.get("system-entities", []):
    mp = entity.get("mount-point")
    de = entity.get("dev-entry")
    if mp and de:
        mount = mp
        dev = de
        break
print(mount)
print(dev)
PY
)

  if [[ -z "$dmg_mount_point" || -z "$dmg_dev_entry" ]]; then
    fail "Unable to parse DMG mount point from ${attach_plist}"
  fi

  run_logged "dmg_ls_root" ls -la "$dmg_mount_point"

  applications_link="${dmg_mount_point}/Applications"
  if [[ ! -L "$applications_link" ]]; then
    fail "DMG is missing /Applications symlink at: ${applications_link}"
  fi
  if [[ "$(readlink "$applications_link" || true)" != "/Applications" ]]; then
    fail "DMG Applications symlink does not point to /Applications."
  fi

  apps=()
  while IFS= read -r line; do
    apps+=("$line")
  done < <(find "$dmg_mount_point" -maxdepth 1 -type d -name '*.app' | sort)

  if [[ "${#apps[@]}" != "1" ]]; then
    printf '%s\n' "ERROR: Expected a single top-level .app in the DMG; found ${#apps[@]}." >&2
    printf '%s\n' "Mounted at: ${dmg_mount_point}" >&2
    exit 5
  fi

  verify_app "${apps[0]}"

  cleanup_dmg_mount
  dmg_dev_entry=""
  dmg_mount_point=""

  if [[ "$KEEP_WORKDIR" != "1" ]]; then
    rm -rf "$work_dir"
  fi
fi

printf '%s\n' "Verification succeeded."
printf '%s\n' "Logs: ${LOG_DIR}"
