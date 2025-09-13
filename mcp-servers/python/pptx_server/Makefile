# Makefile for PowerPoint MCP Server

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
	black . && ruff --fix .

lint: ## Lint (ruff, mypy)
	ruff check . && mypy src/pptx_server

test: ## Run tests
	pytest -v --cov=pptx_server --cov-report=term-missing

dev: ## Run stdio MCP server
	@echo "Starting PowerPoint MCP server (stdio)..."
	$(PYTHON) -m pptx_server.server

mcp-info: ## Show stdio client config snippet
	@echo '{"command": "python", "args": ["-m", "pptx_server.server"], "cwd": "'$(PWD)'"}'

serve-http: ## Expose stdio server over HTTP (JSON-RPC + SSE)
	@echo "HTTP: http://$(HTTP_HOST):$(HTTP_PORT)"
	$(PYTHON) -m mcpgateway.translate --stdio "$(PYTHON) -m pptx_server.server" --host $(HTTP_HOST) --port $(HTTP_PORT) --expose-sse

test-http: ## Basic HTTP checks
	curl -s http://$(HTTP_HOST):$(HTTP_PORT)/ | head -20 || true
	curl -s -X POST -H 'Content-Type: application/json' \
	  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}' \
	  http://$(HTTP_HOST):$(HTTP_PORT)/ | head -40 || true

clean: ## Remove caches
	rm -rf .pytest_cache .ruff_cache .mypy_cache __pycache__ */__pycache__

# PowerPoint-specific targets
demo: ## Create a sample PowerPoint presentation
	@echo "Creating sample PowerPoint presentation..."
	@$(PYTHON) demo.py

test-tools: ## Test individual PowerPoint tools
	@echo "Testing PowerPoint MCP tools..."
	@echo '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}' | $(PYTHON) -m pptx_server.server | head -20

validate: ## Validate PowerPoint files can be opened
	@echo "Validating generated PowerPoint files..."
	@$(PYTHON) -c "from pptx import Presentation; import os; files = [f for f in os.listdir('examples/demos/') if f.endswith('.pptx')]; [print(f'Valid: {f} ({len(Presentation(f\"examples/demos/{f}\").slides)} slides)') for f in files[:3]]"

enhanced-demo: ## Run comprehensive enhanced demo
	@echo "Running enhanced PowerPoint MCP demo..."
	@$(PYTHON) enhanced_demo.py

serve-http-only: ## Start only HTTP download server
	@echo "Starting HTTP download server..."
	@$(PYTHON) -m pptx_server.http_server

serve-combined: ## Start combined MCP + HTTP server
	@echo "Starting combined MCP + HTTP server..."
	@$(PYTHON) -m pptx_server.combined_server

test-download: ## Test HTTP download functionality
	@echo "Testing HTTP download server..."
	@curl -s http://localhost:9000/health | head -10 || echo "HTTP server not running"
	@echo "Start server with: make serve-http-only"
