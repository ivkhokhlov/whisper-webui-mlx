VENV ?= .venv
PYTHON ?= $(VENV)/bin/python
PIP ?= $(VENV)/bin/pip
PYTEST ?= $(VENV)/bin/pytest
RUFF ?= $(VENV)/bin/ruff

.PHONY: venv deps dev-deps check-venv test lint fmt run \
	macos-app macos-app-arm64 macos-app-intel \
	macos-dmg macos-dmg-arm64 macos-dmg-intel \
	macos-sign macos-sign-arm64 macos-sign-intel \
	macos-notarize macos-notarize-arm64 macos-notarize-intel \
	macos-verify macos-verify-arm64 macos-verify-intel \
	macos-release-arm64 macos-release-intel

venv:
	@if [ ! -d "$(VENV)" ]; then \
		if command -v python3.12 >/dev/null 2>&1; then \
			python3.12 -m venv "$(VENV)"; \
		else \
			python3 -m venv "$(VENV)"; \
		fi; \
	fi

deps: venv
	$(PIP) install -r requirements.txt

dev-deps: deps
	$(PIP) install -r requirements-dev.txt

check-venv:
	@if [ ! -x "$(PYTHON)" ]; then \
		echo "Virtualenv missing. Run ./scripts/setup_and_run.sh or make deps."; \
		exit 1; \
	fi

test: dev-deps
	$(PYTEST)

lint: dev-deps
	$(RUFF) check .

fmt: dev-deps
	$(RUFF) format .

run: check-venv
	$(PYTHON) -m uvicorn mlx_ui.app:app --host 127.0.0.1 --port 8000

# ---------------------------------------------------------------------------
# macOS packaged release entry points (maintainers)
#
# These targets are ergonomic wrappers around scripts/* and are intentionally
# separate from the developer bootstrap flow (./run.sh).
#
# Override script args using:
#   make macos-app-arm64 MACOS_APP_ARGS="--with-cohere --python /path/to/python --force"
#   make macos-sign-arm64 MACOS_SIGN_ARGS="--identity 'Developer ID Application: ...'"
#   make macos-notarize-arm64 MACOS_NOTARY_ARGS="--keychain-profile whisper-webui-notary"
# ---------------------------------------------------------------------------

MACOS_TARGET ?= macos-arm64
MACOS_APP_ARGS ?=
MACOS_DMG_ARGS ?=
MACOS_SIGN_ARGS ?=
MACOS_NOTARY_ARGS ?=
MACOS_VERIFY_ARGS ?=

MACOS_BUNDLE_NAME = $(shell python3 -c "import tomllib, pathlib; d=tomllib.loads(pathlib.Path('docs/release/macos_targets.toml').read_text(encoding='utf-8')); print(d['macos']['bundle_name'])")

macos-app:
	./scripts/build_macos_app.sh --target $(MACOS_TARGET) $(MACOS_APP_ARGS)

macos-app-arm64:
	$(MAKE) macos-app MACOS_TARGET=macos-arm64

macos-app-intel:
	$(MAKE) macos-app MACOS_TARGET=macos-intel

macos-dmg:
	./scripts/build_macos_dmg.sh --target $(MACOS_TARGET) $(MACOS_DMG_ARGS)

macos-dmg-arm64:
	$(MAKE) macos-dmg MACOS_TARGET=macos-arm64

macos-dmg-intel:
	$(MAKE) macos-dmg MACOS_TARGET=macos-intel

macos-sign:
	./scripts/sign_macos_app.sh --app "dist/$(MACOS_TARGET)/$(MACOS_BUNDLE_NAME)" $(MACOS_SIGN_ARGS)

macos-sign-arm64:
	$(MAKE) macos-sign MACOS_TARGET=macos-arm64

macos-sign-intel:
	$(MAKE) macos-sign MACOS_TARGET=macos-intel

macos-notarize:
	./scripts/notarize_macos_artifact.sh --target $(MACOS_TARGET) --type dmg $(MACOS_NOTARY_ARGS)

macos-notarize-arm64:
	$(MAKE) macos-notarize MACOS_TARGET=macos-arm64

macos-notarize-intel:
	$(MAKE) macos-notarize MACOS_TARGET=macos-intel

macos-verify:
	./scripts/verify_macos_artifact.sh --target $(MACOS_TARGET) --type dmg $(MACOS_VERIFY_ARGS)

macos-verify-arm64:
	$(MAKE) macos-verify MACOS_TARGET=macos-arm64

macos-verify-intel:
	$(MAKE) macos-verify MACOS_TARGET=macos-intel

macos-release-arm64:
	$(MAKE) macos-app-arm64
	$(MAKE) macos-sign-arm64
	$(MAKE) macos-dmg-arm64
	$(MAKE) macos-notarize-arm64
	$(MAKE) macos-verify-arm64

macos-release-intel:
	$(MAKE) macos-app-intel
	$(MAKE) macos-sign-intel
	$(MAKE) macos-dmg-intel
	$(MAKE) macos-notarize-intel
	$(MAKE) macos-verify-intel
