# Makefile for Python Sandbox MCP Server

.PHONY: help install dev-install format lint test dev mcp-info serve-http serve-sse test-http clean build-sandbox

PYTHON ?= python3
HTTP_PORT ?= 9015
HTTP_HOST ?= localhost

help: ## Show help
	@awk 'BEGIN {FS=":.*?## "} /^[a-zA-Z_-]+:.*?## / {printf "%-18s %s\n", $$1, $$2}' $(MAKEFILE_LIST)

install: ## Install in editable mode
	$(PYTHON) -m pip install -e .

dev-install: ## Install with dev extras
	$(PYTHON) -m pip install -e ".[dev,sandbox]"

format: ## Format (black + ruff --fix)
	black . && ruff --fix .

lint: ## Lint (ruff, mypy)
	ruff check . && mypy src/python_sandbox_server

test: ## Run tests
	pytest -v --cov=python_sandbox_server --cov-report=term-missing

dev: ## Run FastMCP server (stdio)
	@echo "Starting Python Sandbox FastMCP server (stdio)..."
	$(PYTHON) -m python_sandbox_server.server_fastmcp

mcp-info: ## Show stdio client config snippet
	@echo '{"command": "python", "args": ["-m", "python_sandbox_server.server_fastmcp"], "cwd": "'$(PWD)'"}'

serve-http: ## Run with native FastMCP HTTP
	@echo "Starting FastMCP server with native HTTP support..."
	@echo "HTTP endpoint: http://$(HTTP_HOST):$(HTTP_PORT)/mcp/"
	@echo "API docs: http://$(HTTP_HOST):$(HTTP_PORT)/docs"
	$(PYTHON) -m python_sandbox_server.server_fastmcp --transport http --host $(HTTP_HOST) --port $(HTTP_PORT)

serve-sse: ## Run with mcpgateway.translate (SSE bridge)
	@echo "Starting with translate SSE bridge..."
	@echo "SSE endpoint: http://$(HTTP_HOST):$(HTTP_PORT)/sse"
	@echo "HTTP endpoint: http://$(HTTP_HOST):$(HTTP_PORT)/"
	$(PYTHON) -m mcpgateway.translate --stdio "$(PYTHON) -m python_sandbox_server.server_fastmcp" --host $(HTTP_HOST) --port $(HTTP_PORT) --expose-sse

test-http: ## Basic HTTP checks
	curl -s http://$(HTTP_HOST):$(HTTP_PORT)/ | head -20 || true
	curl -s -X POST -H 'Content-Type: application/json' \
	  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}' \
	  http://$(HTTP_HOST):$(HTTP_PORT)/ | head -40 || true

build-sandbox: ## Build the Python sandbox container
	cd docker && ./build-sandbox.sh

test-sandbox: ## Test the sandbox container
	@echo "Testing sandbox container..."
	@echo 'print("Hello from sandbox!")' > /tmp/test_sandbox.py
	@docker run --rm -v /tmp/test_sandbox.py:/tmp/code.py:ro python-sandbox:latest || echo "Container not built. Run 'make build-sandbox' first."
	@rm -f /tmp/test_sandbox.py

clean: ## Remove caches and temporary files
	rm -rf .pytest_cache .ruff_cache .mypy_cache __pycache__ */__pycache__ *.egg-info build/ dist/
