# Makefile for Output Schema Test MCP Server

.PHONY: help install dev-install format lint test dev serve-http serve-sse test-http test-tools mcp-info clean

PYTHON ?= python3
HTTP_PORT ?= 9100
HTTP_HOST ?= 0.0.0.0

help: ## Show help
	@echo "Output Schema Test MCP Server"
	@echo ""
	@echo "Quick Start:"
	@echo "  make install          Install server"
	@echo "  make dev              Run server (stdio)"
	@echo "  make serve-http       Run with native FastMCP HTTP"
	@echo "  make test-tools       Test tool listing with output schemas"
	@echo ""
	@awk 'BEGIN {FS=":.*?## "} /^[a-zA-Z_-]+:.*?## / {printf "  %-18s %s\n", $$1, $$2}' $(MAKEFILE_LIST)

install: ## Install in editable mode
	$(PYTHON) -m pip install -e .

dev-install: ## Install with dev extras
	$(PYTHON) -m pip install -e ".[dev]"

format: ## Format (black + ruff --fix)
	black . && ruff check --fix .

lint: ## Lint (ruff, mypy)
	ruff check . && mypy src/output_schema_test_server

test: ## Run tests
	pytest -v --cov=output_schema_test_server --cov-report=term-missing

dev: ## Run server (stdio)
	$(PYTHON) -m output_schema_test_server.server_fastmcp

serve-http: ## Run with native FastMCP HTTP
	@echo "HTTP endpoint: http://$(HTTP_HOST):$(HTTP_PORT)/mcp/"
	@echo "Test with: make test-http"
	$(PYTHON) -m output_schema_test_server.server_fastmcp --transport http --host $(HTTP_HOST) --port $(HTTP_PORT)

serve-sse: ## Run with mcpgateway.translate (SSE bridge)
	@echo "SSE endpoint: http://$(HTTP_HOST):$(HTTP_PORT)/sse"
	$(PYTHON) -m mcpgateway.translate --stdio "$(PYTHON) -m output_schema_test_server.server_fastmcp" \
	  --host $(HTTP_HOST) --port $(HTTP_PORT) --expose-sse

test-http: ## Test native HTTP endpoint - list tools with output schemas
	@echo "=== Listing tools (should show outputSchema field) ==="
	curl -s -X POST -H 'Content-Type: application/json' \
	  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}' \
	  http://$(HTTP_HOST):$(HTTP_PORT)/mcp/ | python3 -m json.tool

test-tools: ## Test tools with output schemas
	@echo "=== Test 1: List all tools ==="
	curl -s -X POST -H 'Content-Type: application/json' \
	  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}' \
	  http://$(HTTP_HOST):$(HTTP_PORT)/mcp/ | python3 -m json.tool | grep -A 50 "add_numbers" || true
	@echo ""
	@echo "=== Test 2: Call add_numbers tool ==="
	curl -s -X POST -H 'Content-Type: application/json' \
	  -d '{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"add_numbers","arguments":{"a":5,"b":3}}}' \
	  http://$(HTTP_HOST):$(HTTP_PORT)/mcp/ | python3 -m json.tool
	@echo ""
	@echo "=== Test 3: Call create_user tool ==="
	curl -s -X POST -H 'Content-Type: application/json' \
	  -d '{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"create_user","arguments":{"name":"John Doe","email":"john@example.com","age":30,"roles":["admin","user"]}}}' \
	  http://$(HTTP_HOST):$(HTTP_PORT)/mcp/ | python3 -m json.tool

mcp-info: ## Show MCP client configs
	@echo "1. FastMCP Server (stdio - for Claude Desktop):"
	@echo '{"command": "python", "args": ["-m", "output_schema_test_server.server_fastmcp"]}'
	@echo ""
	@echo "2. Native HTTP: make serve-http"
	@echo "   Then test: make test-http"
	@echo ""
	@echo "3. SSE bridge: make serve-sse"

clean: ## Remove caches
	rm -rf .pytest_cache .ruff_cache .mypy_cache __pycache__ */__pycache__ *.egg-info
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
