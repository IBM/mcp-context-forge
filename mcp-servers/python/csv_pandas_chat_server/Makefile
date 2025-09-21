# Makefile for CSV Pandas Chat MCP Server

.PHONY: help install dev-install format lint test dev mcp-info serve-http serve-sse test-http example-basic clean

PYTHON ?= python3
HTTP_PORT ?= 9003
HTTP_HOST ?= localhost

help: ## Show help
	@echo "CSV Pandas Chat MCP Server - Secure CSV data analysis with AI"
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
	ruff check . && mypy src/csv_pandas_chat_server

test: ## Run tests
	pytest -v --cov=csv_pandas_chat_server --cov-report=term-missing

dev: ## Run FastMCP server (stdio)
	@echo "Starting CSV Pandas Chat FastMCP server..."
	$(PYTHON) -m csv_pandas_chat_server.server_fastmcp

mcp-info: ## Show MCP client config
	@echo "==================== MCP CLIENT CONFIGURATION ===================="
	@echo ""
	@echo "FastMCP Server:"
	@echo '{  "command": "python", "args": ["-m", "csv_pandas_chat_server.server_fastmcp"], "cwd": "'$(PWD)'"}'
	@echo ""
	@echo "=================================================================="

serve-http: ## Run with native FastMCP HTTP
	@echo "Starting FastMCP server with native HTTP support..."
	@echo "HTTP endpoint: http://$(HTTP_HOST):$(HTTP_PORT)/mcp/"
	@echo "API docs: http://$(HTTP_HOST):$(HTTP_PORT)/docs"
	$(PYTHON) -m csv_pandas_chat_server.server_fastmcp --transport http --host $(HTTP_HOST) --port $(HTTP_PORT)

serve-sse: ## Run with mcpgateway.translate (SSE bridge)
	@echo "Starting with translate SSE bridge..."
	@echo "SSE endpoint: http://$(HTTP_HOST):$(HTTP_PORT)/sse"
	@echo "HTTP endpoint: http://$(HTTP_HOST):$(HTTP_PORT)/"
	$(PYTHON) -m mcpgateway.translate --stdio "$(PYTHON) -m csv_pandas_chat_server.server_fastmcp" --host $(HTTP_HOST) --port $(HTTP_PORT) --expose-sse

test-http: ## Basic HTTP checks
	curl -s http://$(HTTP_HOST):$(HTTP_PORT)/ | head -20 || true
	curl -s -X POST -H 'Content-Type: application/json' \
	  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}' \
	  http://$(HTTP_HOST):$(HTTP_PORT)/ | head -40 || true

example-basic: ## Basic example with CSV content
	@echo "Testing basic CSV analysis..."
	@echo '{"tool": "get_csv_info", "arguments": {"csv_content": "name,age,city\nAlice,30,NYC\nBob,25,LA\nCharlie,35,Chicago"}}' | \
	$(PYTHON) -c "import sys, json; data = json.load(sys.stdin); \
	from csv_pandas_chat_server.server_fastmcp import processor; \
	import asyncio; \
	result = asyncio.run(processor.get_csv_info(csv_content=data['arguments']['csv_content'])); \
	print(json.dumps(result, indent=2))"

clean: ## Remove caches and temporary files
	rm -rf .pytest_cache .ruff_cache .mypy_cache __pycache__ */__pycache__ *.egg-info build/ dist/
