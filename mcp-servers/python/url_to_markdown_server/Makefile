# Makefile for URL-to-Markdown MCP Server

.PHONY: help install dev-install install-html install-docs install-full format lint test dev mcp-info serve-http serve-sse test-http clean

PYTHON ?= python3
HTTP_PORT ?= 9016
HTTP_HOST ?= localhost

help: ## Show help
	@awk 'BEGIN {FS=":.*?## "} /^[a-zA-Z_-]+:.*?## / {printf "%-18s %s\n", $$1, $$2}' $(MAKEFILE_LIST)

install: ## Install in editable mode (basic)
	$(PYTHON) -m pip install -e .

dev-install: ## Install with dev extras
	$(PYTHON) -m pip install -e ".[dev]"

install-html: ## Install with HTML conversion engines
	$(PYTHON) -m pip install -e ".[dev,html]"

install-docs: ## Install with document conversion engines
	$(PYTHON) -m pip install -e ".[dev,documents]"

install-full: ## Install with all features
	$(PYTHON) -m pip install -e ".[dev,full]"

format: ## Format (black + ruff --fix)
	black . && ruff --fix .

lint: ## Lint (ruff, mypy)
	ruff check . && mypy src/url_to_markdown_server

test: ## Run tests
	pytest -v --cov=url_to_markdown_server --cov-report=term-missing

dev: ## Run FastMCP server (stdio)
	@echo "Starting URL-to-Markdown FastMCP server..."
	$(PYTHON) -m url_to_markdown_server.server_fastmcp

mcp-info: ## Show MCP client config
	@echo "FastMCP server:"
	@echo '  {"command": "python", "args": ["-m", "url_to_markdown_server.server_fastmcp"], "cwd": "'$(PWD)'"}'

serve-http: ## Run with native FastMCP HTTP
	@echo "Starting FastMCP server with native HTTP support..."
	@echo "HTTP endpoint: http://$(HTTP_HOST):$(HTTP_PORT)/mcp/"
	@echo "API docs: http://$(HTTP_HOST):$(HTTP_PORT)/docs"
	$(PYTHON) -m url_to_markdown_server.server_fastmcp --transport http --host $(HTTP_HOST) --port $(HTTP_PORT)

serve-sse: ## Run with mcpgateway.translate (SSE bridge)
	@echo "Starting with translate SSE bridge..."
	@echo "SSE endpoint: http://$(HTTP_HOST):$(HTTP_PORT)/sse"
	@echo "HTTP endpoint: http://$(HTTP_HOST):$(HTTP_PORT)/"
	$(PYTHON) -m mcpgateway.translate --stdio "$(PYTHON) -m url_to_markdown_server.server_fastmcp" --host $(HTTP_HOST) --port $(HTTP_PORT) --expose-sse

test-http: ## Basic HTTP checks
	curl -s http://$(HTTP_HOST):$(HTTP_PORT)/ | head -20 || true
	curl -s -X POST -H 'Content-Type: application/json' \
	  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}' \
	  http://$(HTTP_HOST):$(HTTP_PORT)/ | head -40 || true

clean: ## Remove caches and temporary files
	rm -rf .pytest_cache .ruff_cache .mypy_cache __pycache__ */__pycache__ *.egg-info build/ dist/
