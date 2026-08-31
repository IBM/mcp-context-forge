# Makefile for Graphviz MCP Server

.PHONY: help install dev-install format lint test dev serve-http serve-http-native serve-sse test-http test-http-native example-create clean mcp-info

PYTHON ?= python3
HTTP_PORT ?= 9005
HTTP_HOST ?= 0.0.0.0

help: ## Show help
	@echo "Graphviz MCP Server - Create and render Graphviz graphs"
	@echo ""
	@echo "Quick Start:"
	@echo "  make install          Install FastMCP server"
	@echo "  make dev              Run FastMCP server (stdio)"
	@echo "  make serve-http       Run with native FastMCP HTTP"
	@echo "  make serve-sse        Run with translate SSE bridge"
	@echo ""
	@echo "Available Commands:"
	@awk 'BEGIN {FS=":.*?## "} /^[a-zA-Z_-]+:.*?## / {printf "  %-20s %s\n", $$1, $$2}' $(MAKEFILE_LIST)

install: ## Install in editable mode
	$(PYTHON) -m pip install -e .

dev-install: ## Install with dev extras
	$(PYTHON) -m pip install -e ".[dev]"

format: ## Format (black + ruff --fix)
	black . && ruff check --fix .

lint: ## Lint (ruff, mypy)
	ruff check . && mypy src/graphviz_server

test: ## Run tests
	pytest -v --cov=graphviz_server --cov-report=term-missing

dev: ## Run FastMCP server (stdio)
	@echo "Starting Graphviz FastMCP server (stdio mode)..."
	$(PYTHON) -m graphviz_server.server_fastmcp

serve-http: ## Run FastMCP server with native HTTP
	@echo "Starting FastMCP server with native HTTP support..."
	@echo "HTTP endpoint: http://$(HTTP_HOST):$(HTTP_PORT)/mcp/"
	@echo "API docs: http://$(HTTP_HOST):$(HTTP_PORT)/docs"
	$(PYTHON) -m graphviz_server.server_fastmcp --transport http --host $(HTTP_HOST) --port $(HTTP_PORT)

serve-http-native: serve-http ## Alias for serve-http

serve-sse: ## Run with mcpgateway.translate (SSE bridge)
	@echo "Starting with translate SSE bridge..."
	@echo "SSE endpoint: http://$(HTTP_HOST):$(HTTP_PORT)/sse"
	@echo "HTTP endpoint: http://$(HTTP_HOST):$(HTTP_PORT)/"
	$(PYTHON) -m mcpgateway.translate --stdio "$(PYTHON) -m graphviz_server.server_fastmcp" --host $(HTTP_HOST) --port $(HTTP_PORT) --expose-sse

test-http: ## Test native HTTP endpoint
	@echo "Testing native FastMCP HTTP endpoint..."
	curl -s -X POST -H 'Content-Type: application/json' \
	  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}' \
	  http://$(HTTP_HOST):$(HTTP_PORT)/mcp/ | python3 -m json.tool | head -50 || true

test-http-native: test-http ## Alias for test-http

test-sse: ## Test translate SSE endpoint
	@echo "Testing translate HTTP endpoint..."
	curl -s -X POST -H 'Content-Type: application/json' \
	  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}' \
	  http://$(HTTP_HOST):$(HTTP_PORT)/ | python3 -m json.tool | head -50 || true

example-create: ## Example: Create and render graph
	@echo "Creating example graph..."
	@$(PYTHON) -c "from graphviz_server.server_fastmcp import processor; \
	import json; \
	# Create graph \
	result = processor.create_graph('/tmp/example.dot', 'digraph', 'Example', {'rankdir': 'TB', 'bgcolor': 'white'}); \
	print('Created:', json.dumps(result, indent=2)); \
	# Add nodes \
	processor.add_node('/tmp/example.dot', 'Start', 'Start', {'shape': 'ellipse', 'color': 'green'}); \
	processor.add_node('/tmp/example.dot', 'Process', 'Process', {'shape': 'box', 'color': 'blue'}); \
	processor.add_node('/tmp/example.dot', 'End', 'End', {'shape': 'ellipse', 'color': 'red'}); \
	# Add edges \
	processor.add_edge('/tmp/example.dot', 'Start', 'Process', 'begin'); \
	processor.add_edge('/tmp/example.dot', 'Process', 'End', 'finish'); \
	# Render \
	result = processor.render_graph('/tmp/example.dot', '/tmp/example.png'); \
	print('\nRendered:', json.dumps(result, indent=2)); \
	# Show DOT file \
	print('\n--- Generated DOT ---'); \
	with open('/tmp/example.dot') as f: print(f.read())"

mcp-info: ## Show MCP client config
	@echo "==================== MCP CLIENT CONFIGURATION ===================="
	@echo ""
	@echo "1. FastMCP Server (stdio - for Claude Desktop, etc.):"
	@echo '{"command": "python", "args": ["-m", "graphviz_server.server_fastmcp"], "cwd": "'$(PWD)'"}'
	@echo ""
	@echo "2. Native HTTP endpoint:"
	@echo "Run: make serve-http"
	@echo "Endpoint: http://$(HTTP_HOST):$(HTTP_PORT)/mcp/"
	@echo ""
	@echo "3. SSE bridge with translate:"
	@echo "Run: make serve-sse"
	@echo "SSE: http://$(HTTP_HOST):$(HTTP_PORT)/sse"
	@echo ""
	@echo "=================================================================="

clean: ## Remove caches
	rm -rf .pytest_cache .ruff_cache .mypy_cache __pycache__ */__pycache__ *.egg-info build/ dist/
