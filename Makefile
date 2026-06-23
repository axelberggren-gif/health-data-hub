# Health Data Hub — developer commands.
# These are the Python equivalents of `npm run <script>`. CI runs the same ones,
# so "green locally" == "green in CI". Run `make check` before opening a PR.

.PHONY: help install lint format typecheck test check audit dev

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

install: ## Install runtime + dev dependencies into the active environment
	python -m pip install --upgrade pip
	pip install -r requirements.txt -r requirements-dev.txt

lint: ## Lint with ruff (style, imports, common bugs)
	ruff check .

format: ## Auto-format with ruff
	ruff format .

typecheck: ## Static type check with mypy
	mypy app

test: ## Run the test suite
	pytest

check: ## The full verify loop CI runs: lint + format-check + typecheck + test
	ruff check .
	ruff format --check .
	mypy app
	pytest

audit: ## Scan dependencies for known vulnerabilities
	pip-audit -r requirements.txt

dev: ## Run the API locally with auto-reload (http://localhost:8000)
	uvicorn app.main:app --reload
