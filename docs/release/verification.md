# Verification (final local preflight)

Before shipping a macOS release, run a final local verification step that
checks:

- App bundle integrity (expected payload layout)
- Code signatures (nested + top-level)
- Notarization ticket presence (stapled)
- Gatekeeper readiness (modern system policy checks when available)

This verification step is intentionally separate from build/sign/notarize.

## Script

Use `scripts/verify_macos_artifact.sh`.

Verify a DMG artifact:

```bash
./scripts/verify_macos_artifact.sh --artifact dist/release/whisper-webui-mlx-v{version}-macos-arm64.dmg
```

Verify a ZIP artifact:

```bash
./scripts/verify_macos_artifact.sh --artifact dist/release/whisper-webui-mlx-v{version}-macos-arm64.zip --type zip
```

Verify an `.app` directly:

```bash
./scripts/verify_macos_artifact.sh --artifact dist/macos-arm64/"Whisper WebUI (MLX).app" --type app
```

Contract-driven path resolution:

```bash
./scripts/verify_macos_artifact.sh --target macos-arm64 --type dmg
```

## Outputs

Verification logs are written to:

```text
dist/release/verify/<artifact_stem>/
```

Each check writes a file; on failure, the script prints the last lines of the
relevant log to make triage fast.
