# Makefile for compliance-reference-server

.PHONY: help install dev-install format lint test dev serve-sse serve-http clean

PYTHON ?= python3
HTTP_PORT ?= 9100
HTTP_HOST ?= 127.0.0.1

help: ## Show help
	@awk 'BEGIN {FS=":.*?## "} /^[a-zA-Z_-]+:.*?## / {printf "%-18s %s\n", $$1, $$2}' $(MAKEFILE_LIST)

install: ## Install in editable mode
	$(PYTHON) -m pip install -e .

dev-install: ## Install with dev extras
	$(PYTHON) -m pip install -e ".[dev]"

format: ## Format (ruff --fix)
	ruff check --fix . && ruff format .

lint: ## Lint (ruff)
	ruff check .

test: ## Run tests
	pytest -v

dev: ## Run stdio MCP server
	$(PYTHON) -m compliance_reference_server.server --transport stdio

serve-sse: ## Run SSE MCP server
	$(PYTHON) -m compliance_reference_server.server --transport sse --host $(HTTP_HOST) --port $(HTTP_PORT)

serve-http: ## Run Streamable HTTP MCP server
	$(PYTHON) -m compliance_reference_server.server --transport http --host $(HTTP_HOST) --port $(HTTP_PORT)

clean: ## Remove caches
	rm -rf .pytest_cache .ruff_cache .mypy_cache __pycache__ */__pycache__ src/*/__pycache__
