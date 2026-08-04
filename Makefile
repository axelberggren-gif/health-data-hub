# Health Data Hub — developer commands.
# These are the Python equivalents of `npm run <script>`. CI runs the same ones,
# so "green locally" == "green in CI". Run `make check` before opening a PR.
#
# Every tool runs as `$(PY) -m <tool>`, NOT as a bare `ruff` / `mypy` / `pytest` on PATH.
# A bare name can resolve to some globally installed copy at a different version than the
# one pinned in requirements-dev.txt, which silently breaks the "green locally == green in
# CI" promise (the same code can pass one version and fail another). Going through the
# interpreter guarantees we use the pinned version in the active environment.
PY ?= python

.PHONY: help install lint format typecheck test check audit dev

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

install: ## Install runtime + dev dependencies into the active environment
	$(PY) -m pip install --upgrade pip
	$(PY) -m pip install -r requirements.txt -r requirements-dev.txt

lint: ## Lint with ruff (style, imports, common bugs)
	$(PY) -m ruff check .

format: ## Auto-format with ruff
	$(PY) -m ruff format .

typecheck: ## Static type check with mypy
	$(PY) -m mypy app

test: ## Run the test suite
	$(PY) -m pytest

check: ## The full verify loop CI runs: lint + format-check + typecheck + test
	$(PY) -m ruff check .
	$(PY) -m ruff format --check .
	$(PY) -m mypy app
	$(PY) -m pytest

audit: ## Scan dependencies for known vulnerabilities
	$(PY) -m pip_audit -r requirements.txt

dev: ## Run the API locally with auto-reload (http://localhost:8000)
	$(PY) -m uvicorn app.main:app --reload
