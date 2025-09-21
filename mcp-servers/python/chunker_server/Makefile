# Makefile for Chunker MCP Server

.PHONY: help install dev-install install-nlp install-full format lint test dev mcp-info serve-http serve-sse test-http clean

PYTHON ?= python3
HTTP_PORT ?= 9010
HTTP_HOST ?= localhost

help: ## Show help
	@echo "Chunker MCP Server - Text chunking with multiple strategies"
	@echo ""
	@echo "Quick Start:"
	@echo "  make install-full     Install with all features (recommended)"
	@echo "  make dev              Run FastMCP server"
	@echo ""
	@echo "Available Commands:"
	@awk 'BEGIN {FS=":.*?## "} /^[a-zA-Z_-]+:.*?## / {printf "  %-20s %s\n", $$1, $$2}' $(MAKEFILE_LIST)

install: ## Install in editable mode (basic)
	$(PYTHON) -m pip install -e .

dev-install: ## Install with dev extras
	$(PYTHON) -m pip install -e ".[dev]"

install-nlp: ## Install with NLP libraries
	$(PYTHON) -m pip install -e ".[dev,nlp]"

install-langchain: ## Install with LangChain support
	$(PYTHON) -m pip install -e ".[dev,langchain]"

install-full: ## Install with all features
	$(PYTHON) -m pip install -e ".[dev,full]"

format: ## Format code (black + ruff --fix)
	black . && ruff --fix .

lint: ## Lint (ruff, mypy)
	ruff check . && mypy src/chunker_server

test: ## Run tests
	pytest -v --cov=chunker_server --cov-report=term-missing

dev: ## Run FastMCP server (stdio)
	@echo "Starting Chunker FastMCP server..."
	$(PYTHON) -m chunker_server.server_fastmcp

mcp-info: ## Show MCP client config
	@echo "==================== MCP CLIENT CONFIGURATION ===================="
	@echo ""
	@echo "FastMCP Server:"
	@echo '{"command": "python", "args": ["-m", "chunker_server.server_fastmcp"], "cwd": "'$(PWD)'"}'
	@echo ""
	@echo "=================================================================="

serve-http: ## Run with native FastMCP HTTP
	@echo "Starting FastMCP server with native HTTP support..."
	@echo "HTTP endpoint: http://$(HTTP_HOST):$(HTTP_PORT)/mcp/"
	@echo "API docs: http://$(HTTP_HOST):$(HTTP_PORT)/docs"
	$(PYTHON) -m chunker_server.server_fastmcp --transport http --host $(HTTP_HOST) --port $(HTTP_PORT)

serve-sse: ## Run with mcpgateway.translate (SSE bridge)
	@echo "Starting with translate SSE bridge..."
	@echo "SSE endpoint: http://$(HTTP_HOST):$(HTTP_PORT)/sse"
	@echo "HTTP endpoint: http://$(HTTP_HOST):$(HTTP_PORT)/"
	$(PYTHON) -m mcpgateway.translate --stdio "$(PYTHON) -m chunker_server.server_fastmcp" --host $(HTTP_HOST) --port $(HTTP_PORT) --expose-sse

test-http: ## Basic HTTP checks
	curl -s http://$(HTTP_HOST):$(HTTP_PORT)/ | head -20 || true
	curl -s -X POST -H 'Content-Type: application/json' \
	  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}' \
	  http://$(HTTP_HOST):$(HTTP_PORT)/ | head -40 || true

example-chunk: ## Example: Chunk sample text
	@echo "Chunking example text..."
	@echo '{"text": "This is the first paragraph.\n\nThis is the second paragraph.\n\nThis is the third paragraph."}' | \
		$(PYTHON) -c "import sys, json; \
		from chunker_server.server_fastmcp import chunker; \
		data = json.load(sys.stdin); \
		result = chunker.recursive_chunk(data['text'], chunk_size=50); \
		print(json.dumps(result, indent=2))"

clean: ## Remove caches and temporary files
	rm -rf .pytest_cache .ruff_cache .mypy_cache __pycache__ */__pycache__ *.egg-info build/ dist/ .coverage
