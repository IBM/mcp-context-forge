# Makefile for Code Splitter MCP Server

.PHONY: help install dev-install format lint test dev mcp-info serve-http serve-sse test-http example-split clean

PYTHON ?= python3
HTTP_PORT ?= 9011
HTTP_HOST ?= localhost

help: ## Show help
	@echo "Code Splitter MCP Server - AST-based code analysis and splitting"
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

format: ## Format code (black + ruff --fix)
	black . && ruff --fix .

lint: ## Lint (ruff, mypy)
	ruff check . && mypy src/code_splitter_server

test: ## Run tests
	pytest -v --cov=code_splitter_server --cov-report=term-missing

dev: ## Run FastMCP server (stdio)
	@echo "Starting Code Splitter FastMCP server..."
	$(PYTHON) -m code_splitter_server.server_fastmcp

mcp-info: ## Show MCP client config
	@echo "==================== MCP CLIENT CONFIGURATION ===================="
	@echo ""
	@echo "FastMCP Server:"
	@echo '{"command": "python", "args": ["-m", "code_splitter_server.server_fastmcp"], "cwd": "'$(PWD)'"}'
	@echo ""
	@echo "=================================================================="

serve-http: ## Run with native FastMCP HTTP
	@echo "Starting FastMCP server with native HTTP support..."
	@echo "HTTP endpoint: http://$(HTTP_HOST):$(HTTP_PORT)/mcp/"
	@echo "API docs: http://$(HTTP_HOST):$(HTTP_PORT)/docs"
	$(PYTHON) -m code_splitter_server.server_fastmcp --transport http --host $(HTTP_HOST) --port $(HTTP_PORT)

serve-sse: ## Run with mcpgateway.translate (SSE bridge)
	@echo "Starting with translate SSE bridge..."
	@echo "SSE endpoint: http://$(HTTP_HOST):$(HTTP_PORT)/sse"
	@echo "HTTP endpoint: http://$(HTTP_HOST):$(HTTP_PORT)/"
	$(PYTHON) -m mcpgateway.translate --stdio "$(PYTHON) -m code_splitter_server.server_fastmcp" --host $(HTTP_HOST) --port $(HTTP_PORT) --expose-sse

test-http: ## Basic HTTP checks
	curl -s http://$(HTTP_HOST):$(HTTP_PORT)/ | head -20 || true
	curl -s -X POST -H 'Content-Type: application/json' \
	  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}' \
	  http://$(HTTP_HOST):$(HTTP_PORT)/ | head -40 || true

example-split: ## Example: Split Python code
	@echo "Splitting example Python code..."
	@echo 'def hello():\n    print("Hello")\n\nclass MyClass:\n    def method(self):\n        pass' | \
		$(PYTHON) -c "import sys; \
		from code_splitter_server.server_fastmcp import splitter; \
		code = sys.stdin.read(); \
		result = splitter.split_python_code(code, split_level='all'); \
		import json; print(json.dumps(result, indent=2))" | head -50

example-analyze: ## Example: Analyze code complexity
	@echo "Analyzing code complexity..."
	@echo 'def complex_func():\n    if True:\n        for i in range(10):\n            if i > 5:\n                print(i)' | \
		$(PYTHON) -c "import sys; \
		from code_splitter_server.server_fastmcp import splitter; \
		code = sys.stdin.read(); \
		result = splitter.analyze_code_structure(code); \
		import json; print(json.dumps(result, indent=2))"

clean: ## Remove caches and temporary files
	rm -rf .pytest_cache .ruff_cache .mypy_cache __pycache__ */__pycache__ *.egg-info build/ dist/
