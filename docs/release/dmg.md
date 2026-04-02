# DMG packaging (macOS distribution)

Once a self-contained `.app` bundle is built (see `scripts/build_macos_app.sh`),
create an end-user DMG that supports standard drag-to-Applications install.

This step is:
- Offline (no network)
- Deterministic and scriptable
- Unsigned / un-notarized (by design in this phase)

## Script

Use `scripts/build_macos_dmg.sh`.

Apple Silicon (`macos-arm64`):

```bash
./scripts/build_macos_dmg.sh --target macos-arm64
```

Intel (`macos-intel`):

```bash
./scripts/build_macos_dmg.sh --target macos-intel
```

## Inputs and outputs

- Default `.app` input path:
  - `dist/<target>/<bundle_name>` (from `docs/release/macos_targets.toml`)
- Output DMG path:
  - `dist/release/<dmg_artifact_name>` (from `docs/release/macos_targets.toml`)

The DMG root contains:
- The `.app` bundle
- An `Applications` symlink (to `/Applications`)

## Notes

- This script uses built-in macOS tooling (`hdiutil`, `ditto`).
- It validates the `.app` bundle structure via `scripts/validate_macos_app_bundle.py` before creating the DMG.
- Signing/notarization is intentionally not performed in this step.
