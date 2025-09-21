.PHONY: help install dev-install format lint test dev serve-http serve-sse test-http mcp-info clean

PYTHON ?= python3
HTTP_PORT ?= 8000
HTTP_HOST ?= 0.0.0.0
PACKAGE = pm_mcp_server

help: ## Show help
	@echo "Project Management MCP Server"
	@echo "  make install          Install in editable mode"
	@echo "  make dev              Run server over stdio"
	@echo "  make serve-http       Run native HTTP endpoint"
	@echo ""
	@awk 'BEGIN {FS=":.*?## "} /^[a-zA-Z_-]+:.*?## / {printf "  %-18s %s\n", $$1, $$2}' $(MAKEFILE_LIST)

install: ## Install in editable mode
	$(PYTHON) -m pip install -e .

dev-install: ## Install with dev extras
	$(PYTHON) -m pip install -e ".[dev]"

format: ## Format codebase
	black src tests && ruff check --fix src tests

lint: ## Run linters (ruff, mypy)
	ruff check src tests && mypy src/$(PACKAGE)

test: ## Run tests with coverage
	pytest -v --cov=$(PACKAGE) --cov-report=term-missing

dev: ## Run FastMCP server over stdio
	$(PYTHON) -m $(PACKAGE).server_fastmcp

serve-http: ## Run FastMCP HTTP server
	@echo "HTTP endpoint: http://$(HTTP_HOST):$(HTTP_PORT)/mcp/"
	$(PYTHON) -m $(PACKAGE).server_fastmcp --transport http --host $(HTTP_HOST) --port $(HTTP_PORT)

serve-sse: ## Run via mcpgateway translate SSE bridge
	@echo "SSE endpoint: http://$(HTTP_HOST):$(HTTP_PORT)/sse"
	$(PYTHON) -m mcpgateway.translate --stdio "$(PYTHON) -m $(PACKAGE).server_fastmcp" \
		--host $(HTTP_HOST) --port $(HTTP_PORT) --expose-sse

test-http: ## Smoke test HTTP endpoint
	curl -s -X POST -H 'Content-Type: application/json' \
		-d '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}' \
		http://$(HTTP_HOST):$(HTTP_PORT)/mcp/ | python3 -m json.tool | head -40 || true

mcp-info: ## Show MCP client configurations
	@echo '{"command": "python", "args": ["-m", "$(PACKAGE).server_fastmcp"]}'

clean: ## Remove caches and build artefacts
	rm -rf .pytest_cache .ruff_cache .mypy_cache __pycache__ */__pycache__ *.egg-info build dist
