PYTHON ?= python
POETRY ?= poetry
POETRY_RUN ?= $(POETRY) run

.PHONY: test lint fmt run

test:
	$(POETRY_RUN) pytest

lint:
	$(POETRY_RUN) ruff check .

fmt:
	$(POETRY_RUN) ruff format .

run:
	$(POETRY_RUN) uvicorn mlx_ui.app:app --host 127.0.0.1 --port 8000
