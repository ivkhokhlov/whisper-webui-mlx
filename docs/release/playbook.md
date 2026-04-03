# Manual macOS release playbook (maintainers)

This repo supports a **packaged** macOS distribution path that is intentionally
separate from the developer bootstrap (`./run.sh`).

The intended maintainer flow is:

**build `.app` → sign `.app` → build DMG → notarize + staple → verify**

## Prerequisites

- Build on **matching hardware** for each target:
  - `macos-arm64`: build on an Apple Silicon Mac
  - `macos-intel`: build on an Intel (x86_64) Mac
- Xcode Command Line Tools installed (`xcrun`, `codesign`, `notarytool`,
  `stapler`, `syspolicy_check`).
- A **redistributable** Python 3.12.3+ for the target architecture (recommended:
  a portable/standalone Python distribution). The build embeds `sys.base_prefix`
  and creates an embedded venv inside the app payload.
- A `Developer ID Application` signing identity (for distribution).
- Notarization credentials configured (recommended: a notarytool keychain profile).

Notes:
- The packaged app is still a localhost web UI bound to `127.0.0.1`.
- Mutable runtime state is stored in user-writable locations (Application
  Support), not inside the `.app` bundle.
- End-user machines still need `ffmpeg` available on `PATH` for transcription.

## Before you cut a release

1. Bump the version in `pyproject.toml`.
2. Ensure `Settings -> About` matches the version (it should reflect
   `pyproject.toml`).
3. Update `docs/business_description.md` if behavior/UX changed.
4. Run the test suite:

```bash
make test
```

## Build the `.app`

Apple Silicon (`macos-arm64`):

```bash
make macos-app-arm64 MACOS_APP_ARGS="--python /path/to/arm64/python --force"
```

Notes:
- `macos-arm64` embeds both Whisper MLX and Parakeet MLX dependencies by default (see `docs/release/macos_targets.toml`).
- Add `--with-cohere` only if you want the optional cloud engine SDK embedded in the packaged runtime.

Intel (`macos-intel`):

```bash
make macos-app-intel MACOS_APP_ARGS="--python /path/to/x86_64/python --force"
```

Outputs:
- `dist/<target>/Whisper WebUI (MLX).app`

## Sign the `.app`

Set the identity once (recommended):

```bash
export MACOS_SIGNING_IDENTITY="Developer ID Application: Your Name (TEAMID)"
```

Then sign:

```bash
make macos-sign-arm64 MACOS_SIGN_ARGS="--hardened-runtime"
```

(Or pass `--identity ...` directly via `MACOS_SIGN_ARGS`.)

## Build the DMG

```bash
make macos-dmg-arm64
```

Output:
- `dist/release/<dmg_artifact_name>` (from `docs/release/macos_targets.toml`)

## Notarize + staple

Recommended: use a notarytool keychain profile (see
`docs/release/notarization.md`).

```bash
make macos-notarize-arm64 MACOS_NOTARY_ARGS="--keychain-profile whisper-webui-notary"
```

Outputs:
- `dist/release/notary/<artifact_stem>/...` (submission JSON, log JSON, stapler output)

## Verify final artifact (offline)

```bash
make macos-verify-arm64
```

Outputs:
- `dist/release/verify/<artifact_stem>/...` (per-check logs)

## Manual sanity check

1. Mount the DMG and drag the app to `/Applications`.
2. Launch the app, confirm it opens the browser automatically and the UI loads.
3. Confirm the server stays local-only on `127.0.0.1`.
4. Run a small transcription job and confirm results are written under the
   expected Application Support directory for the bundle id.
   - `macos-arm64`: verify Whisper MLX; optionally verify Parakeet MLX (first run may download the model).
   - `macos-intel`: verify Whisper CPU.

## Publishing

- Upload the notarized + stapled DMG(s) as release artifacts.
- Include the engine matrix and platform notes (Apple Silicon MLX vs Intel CPU;
  Cohere cloud is optional; Parakeet MLX is included on Apple Silicon only).

## Convenience

For a full sequence (still uses separate scripts under the hood):

```bash
make macos-release-arm64
```
