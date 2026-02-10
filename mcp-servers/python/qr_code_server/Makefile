# Makefile for QR Code Server

.PHONY: help install dev-install format lint test dev mcp-info serve-http test-http clean

PYTHON ?= python3
HTTP_PORT ?= 9000
HTTP_HOST ?= localhost

help: ## Show help
	@awk 'BEGIN {FS=":.*?## "} /^[a-zA-Z_-]+:.*?## / {printf "%-18s %s\n", $$1, $$2}' $(MAKEFILE_LIST)

install: ## Install in editable mode
	$(PYTHON) -m pip install -e .

dev-install: ## Install with dev extras
	$(PYTHON) -m pip install -e ".[dev]"

format: ## Format (black + ruff --fix)
	black . && ruff check --fix .

lint: ## Lint (ruff, mypy)
	ruff check . && mypy src/qr_code_server

test: ## Run tests
	pytest -v --cov=qr_code_server --cov-report=term-missing

dev: ## Run stdio MCP server
	@echo "Starting QR Code Server (stdio)..."
	$(PYTHON) -m qr_code_server.server

mcp-info: ## Show stdio client config snippet
	@echo '{"command": "python", "args": ["-m", "qr_code_server.server"], "cwd": "'$(PWD)'"}'

serve-http: ## Expose stdio server over HTTP (JSON-RPC + SSE)
	@echo "HTTP: http://$(HTTP_HOST):$(HTTP_PORT)"
	$(PYTHON) -m mcpgateway.translate --stdio "$(PYTHON) -m qr_code_server.server" --host $(HTTP_HOST) --port $(HTTP_PORT) --expose-sse

test-http: ## Basic HTTP checks
	curl -s http://$(HTTP_HOST):$(HTTP_PORT)/ | head -20 || true
	curl -s -X POST -H 'Content-Type: application/json' \
	  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}' \
	  http://$(HTTP_HOST):$(HTTP_PORT)/ | head -40 || true

clean: ## Remove caches
	rm -rf .pytest_cache .ruff_cache .mypy_cache __pycache__ */__pycache__
