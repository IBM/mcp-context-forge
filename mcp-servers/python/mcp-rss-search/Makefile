# Makefile for MCP RSS Search Server

.PHONY: help install dev-install format lint test dev serve-http serve-sse test-http mcp-info clean

PYTHON ?= python3
VENV ?= /home/cmihai/.venv/mcpgateway
HTTP_PORT ?= 9100
HTTP_HOST ?= 0.0.0.0

# Activate virtual environment if it exists
ACTIVATE = . $(VENV)/bin/activate &&

help: ## Show help
	@echo "MCP RSS Search Server - Makefile Commands"
	@echo ""
	@echo "Quick Start:"
	@echo "  make install               Install RSS search server (basic)"
	@echo "  make install-similarity    Install with AI similarity search (recommended!)"
	@echo "  make dev                   Run server (stdio mode)"
	@echo "  make serve-http            Run with native FastMCP HTTP"
	@echo "  make test                  Run tests with coverage"
	@echo ""
	@echo "📚 For AI similarity features, see: SIMILARITY.md"
	@echo ""
	@awk 'BEGIN {FS=":.*?## "} /^[a-zA-Z_-]+:.*?## / {printf "  %-25s %s\n", $$1, $$2}' $(MAKEFILE_LIST)

install: ## Install in editable mode
	$(ACTIVATE) $(PYTHON) -m pip install -e .

install-similarity: ## Install with AI similarity search features
	$(ACTIVATE) $(PYTHON) -m pip install -e ".[similarity]"

install-full: ## Install with all features (similarity + dev)
	$(ACTIVATE) $(PYTHON) -m pip install -e ".[full]"

dev-install: ## Install with dev extras
	$(ACTIVATE) $(PYTHON) -m pip install -e ".[dev]"

format: ## Format code (black + ruff --fix)
	$(ACTIVATE) black . && ruff check --fix .

lint: ## Lint code (ruff, mypy)
	$(ACTIVATE) ruff check . && mypy src/mcp_rss_search

test: ## Run tests with coverage
	$(ACTIVATE) pytest -v --cov=mcp_rss_search --cov-report=term-missing --cov-report=html

dev: ## Run RSS search server (stdio mode)
	$(ACTIVATE) $(PYTHON) -m mcp_rss_search.server_fastmcp

serve-http: ## Run with native FastMCP HTTP
	@echo "HTTP endpoint: http://$(HTTP_HOST):$(HTTP_PORT)/mcp/"
	@echo "Test with: make test-http"
	$(ACTIVATE) $(PYTHON) -m mcp_rss_search.server_fastmcp --transport http --host $(HTTP_HOST) --port $(HTTP_PORT)

serve-sse: ## Run with mcpgateway.translate (SSE bridge)
	@echo "SSE endpoint: http://$(HTTP_HOST):$(HTTP_PORT)/sse"
	$(ACTIVATE) $(PYTHON) -m mcpgateway.translate --stdio "$(PYTHON) -m mcp_rss_search.server_fastmcp" \
	  --host $(HTTP_HOST) --port $(HTTP_PORT) --expose-sse

test-http: ## Test native HTTP endpoint
	@echo "Testing tools/list endpoint..."
	curl -s -X POST -H 'Content-Type: application/json' \
	  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}' \
	  http://$(HTTP_HOST):$(HTTP_PORT)/mcp/ | python3 -m json.tool | head -60 || true

test-fetch: ## Test RSS fetch with NPR feed
	@echo "Testing fetch_rss with NPR feed..."
	curl -s -X POST -H 'Content-Type: application/json' \
	  -d '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"fetch_rss","arguments":{"url":"https://feeds.npr.org/1001/rss.xml","use_cache":false}}}' \
	  http://$(HTTP_HOST):$(HTTP_PORT)/mcp/ | python3 -m json.tool | head -80 || true

mcp-info: ## Show MCP client configs
	@echo "1. RSS Search Server (stdio - for Claude Desktop):"
	@echo '{"command": "python", "args": ["-m", "mcp_rss_search.server_fastmcp"]}'
	@echo ""
	@echo "2. Native HTTP: make serve-http"
	@echo "3. SSE bridge: make serve-sse"
	@echo ""
	@echo "Example feeds to try:"
	@echo "  - NPR News: https://feeds.npr.org/1001/rss.xml"
	@echo "  - NY Times: https://rss.nytimes.com/services/xml/rss/nyt/HomePage.xml"
	@echo "  - BBC News: http://feeds.bbci.co.uk/news/rss.xml"

clean: ## Remove caches and build artifacts
	rm -rf .pytest_cache .ruff_cache .mypy_cache __pycache__ */__pycache__ *.egg-info
	rm -rf htmlcov .coverage
	rm -rf dist build
	rm -rf src/*.egg-info
