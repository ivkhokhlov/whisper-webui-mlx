VENV ?= .venv
PYTHON ?= $(VENV)/bin/python
PIP ?= $(VENV)/bin/pip
PYTEST ?= $(VENV)/bin/pytest
RUFF ?= $(VENV)/bin/ruff

.PHONY: venv deps dev-deps check-venv test lint fmt run

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
