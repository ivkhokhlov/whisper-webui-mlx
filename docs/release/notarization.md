# Notarization (macOS distribution)

Notarization is a separate, explicit release step that happens **after**:

1. Build a self-contained `.app` (`scripts/build_macos_app.sh`)
2. Sign the `.app` (`scripts/sign_macos_app.sh`)
3. Wrap it into a DMG (`scripts/build_macos_dmg.sh`)

Then:

4. Notarize the signed artifact and staple the ticket (`scripts/notarize_macos_artifact.sh`)

This repo intentionally keeps **signing** and **notarization** as separate scripts.

## Preferred auth: notarytool keychain profile

Store credentials once in your Keychain:

```bash
xcrun notarytool store-credentials "whisper-webui-notary" \
  --apple-id "you@example.com" \
  --team-id "TEAMID" \
  --password "app-specific-password"
```

Then notarize using the profile:

```bash
./scripts/notarize_macos_artifact.sh \
  --artifact dist/release/whisper-webui-mlx-v{version}-macos-arm64.dmg \
  --keychain-profile "whisper-webui-notary"
```

## Artifact selection (contract-driven)

To resolve the artifact path from `docs/release/macos_targets.toml`:

```bash
./scripts/notarize_macos_artifact.sh --target macos-arm64 --type dmg --keychain-profile "whisper-webui-notary"
```

## Outputs

The notarization script writes logs to:

```text
dist/release/notary/<artifact_stem>/
  notary_submit.json
  notary_submit.stderr.txt
  notary_log.json
  stapler_staple.txt
  stapler_validate.txt
```

## Notes

- `notarytool submit --wait` requires network access and valid credentials.
- On success, the script staples the ticket using `xcrun stapler`:
  - DMG: staples the DMG directly.
  - ZIP: extracts, staples the top-level `.app`, and re-zips in place (expects a single top-level `.app`).
- Notarization is **not** required for local development.
