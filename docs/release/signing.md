# Code signing (macOS packaged app)

Packaged macOS builds should be code-signed in a repeatable, deterministic
order:

1. Sign nested code (embedded Python, `.dylib`/`.so`, helper binaries, launcher)
2. Sign the top-level `.app`
3. Verify the resulting signature

This repo’s signing step is intentionally **separate** from notarization.

## Script

Use `scripts/sign_macos_app.sh`.

Example (Developer ID identity):

```bash
export MACOS_SIGNING_IDENTITY="Developer ID Application: Your Name (TEAMID)"
./scripts/sign_macos_app.sh --app dist/macos-arm64/"Whisper WebUI (MLX).app"
```

You can also pass the identity explicitly:

```bash
./scripts/sign_macos_app.sh \
  --app dist/macos-arm64/"Whisper WebUI (MLX).app" \
  --identity "Developer ID Application: Your Name (TEAMID)"
```

Local testing options:

- Dry-run (no changes):

```bash
./scripts/sign_macos_app.sh --app dist/macos-arm64/"Whisper WebUI (MLX).app" --dry-run
```

- Ad-hoc signing (no credentials):

```bash
./scripts/sign_macos_app.sh --app dist/macos-arm64/"Whisper WebUI (MLX).app" --adhoc
```

## Notes

- By default, timestamping is disabled (`--timestamp=none`) for determinism. Use
  `--timestamp` if you want RFC3161 timestamps (requires network).
- Notarization is intentionally not performed here.
