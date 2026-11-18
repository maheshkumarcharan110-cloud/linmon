PYTHON ?= python3
VENV ?= .venv
VENV_PY := $(VENV)/bin/python

.PHONY: install test lint format run clean

## install: install linmon (plus dev tools) into the virtual environment in editable mode
install:
	$(VENV_PY) -m pip install -e ".[dev]"

## test: run the pytest suite
test:
	$(VENV_PY) -m pytest

## lint: check code style with ruff
lint:
	$(VENV)/bin/ruff check src tests

## format: auto-format code with ruff
format:
	$(VENV)/bin/ruff format src tests

## run: run linmon with any extra ARGS, e.g. make run ARGS="--live --top 5"
run:
	$(VENV)/bin/linmon $(ARGS)

## clean: remove caches and build artefacts (keeps the virtual environment)
clean:
	rm -rf build dist *.egg-info .pytest_cache .ruff_cache .mypy_cache
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
