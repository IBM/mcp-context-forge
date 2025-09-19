# Makefile for Graphviz MCP Server

.PHONY: help install dev-install format lint test dev mcp-info serve-http test-http example-create clean

PYTHON ?= python3
HTTP_PORT ?= 9005
HTTP_HOST ?= localhost

help: ## Show help
	@echo "Graphviz MCP Server - Create and render Graphviz graphs"
	@echo ""
	@echo "Quick Start:"
	@echo "  make install          Install FastMCP server"
	@echo "  make dev              Run FastMCP server"
	@echo ""
	@echo "Available Commands:"
	@awk 'BEGIN {FS=":.*?## "} /^[a-zA-Z_-]+:.*?## / {printf "  %-20s %s\n", $$1, $$2}' $(MAKEFILE_LIST)

install: ## Install in editable mode
	$(PYTHON) -m pip install -e .

dev-install: ## Install with dev extras
	$(PYTHON) -m pip install -e ".[dev]"

format: ## Format (black + ruff --fix)
	black . && ruff --fix .

lint: ## Lint (ruff, mypy)
	ruff check . && mypy src/graphviz_server

test: ## Run tests
	pytest -v --cov=graphviz_server --cov-report=term-missing

dev: ## Run FastMCP server (stdio)
	@echo "Starting Graphviz FastMCP server..."
	$(PYTHON) -m graphviz_server.server_fastmcp

mcp-info: ## Show MCP client config
	@echo "==================== MCP CLIENT CONFIGURATION ===================="
	@echo ""
	@echo "FastMCP Server:"
	@echo '{"command": "python", "args": ["-m", "graphviz_server.server_fastmcp"], "cwd": "'$(PWD)'"}'
	@echo ""
	@echo "=================================================================="

serve-http: ## Expose FastMCP server over HTTP
	@echo "HTTP: http://$(HTTP_HOST):$(HTTP_PORT)"
	$(PYTHON) -m mcpgateway.translate --stdio "$(PYTHON) -m graphviz_server.server_fastmcp" --host $(HTTP_HOST) --port $(HTTP_PORT) --expose-sse

test-http: ## Basic HTTP checks
	curl -s http://$(HTTP_HOST):$(HTTP_PORT)/ | head -20 || true
	curl -s -X POST -H 'Content-Type: application/json' \
	  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}' \
	  http://$(HTTP_HOST):$(HTTP_PORT)/ | head -40 || true

example-create: ## Example: Create simple graph
	@echo "Creating example graph..."
	@$(PYTHON) -c "from graphviz_server.server_fastmcp import processor; \
	result = processor.create_graph('/tmp/test_graph.dot', 'digraph', 'TestGraph', {'rankdir': 'LR'}); \
	import json; print(json.dumps(result, indent=2))"

clean: ## Remove caches
	rm -rf .pytest_cache .ruff_cache .mypy_cache __pycache__ */__pycache__ *.egg-info build/ dist/
