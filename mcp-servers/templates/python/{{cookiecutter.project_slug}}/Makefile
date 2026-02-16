# Makefile for {{ cookiecutter.project_name }}

.PHONY: help install dev-install format lint test dev mcp-info{% if cookiecutter.include_http_bridge %} serve-http test-http{% endif %} clean

PYTHON ?= python3
{% if cookiecutter.include_http_bridge %}HTTP_PORT ?= 9000
HTTP_HOST ?= localhost{% endif %}

help: ## Show help
	@awk 'BEGIN {FS=":.*?## "} /^[a-zA-Z_-]+:.*?## / {printf "%-18s %s\n", $$1, $$2}' $(MAKEFILE_LIST)

install: ## Install in editable mode
	$(PYTHON) -m pip install -e .

dev-install: ## Install with dev extras
	$(PYTHON) -m pip install -e ".[dev]"

format: ## Format (black + ruff --fix)
	black . && ruff --fix .

lint: ## Lint (ruff, mypy)
	ruff check . && mypy src/{{ cookiecutter.package_name }}

test: ## Run tests
	pytest -v --cov={{ cookiecutter.package_name }} --cov-report=term-missing

dev: ## Run stdio MCP server
	@echo "Starting {{ cookiecutter.project_name }} (stdio)..."
	$(PYTHON) -m {{ cookiecutter.package_name }}.server

mcp-info: ## Show stdio client config snippet
	@echo '{"command": "python", "args": ["-m", "{{ cookiecutter.package_name }}.server"], "cwd": "'$(PWD)'"}'

{% if cookiecutter.include_http_bridge -%}
serve-http: ## Expose stdio server over HTTP (JSON-RPC + SSE)
	@echo "HTTP: http://$(HTTP_HOST):$(HTTP_PORT)"
	$(PYTHON) -m mcpgateway.translate --stdio "$(PYTHON) -m {{ cookiecutter.package_name }}.server" --host $(HTTP_HOST) --port $(HTTP_PORT) --expose-sse

test-http: ## Basic HTTP checks
	curl -s http://$(HTTP_HOST):$(HTTP_PORT)/ | head -20 || true
	curl -s -X POST -H 'Content-Type: application/json' \
	  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}' \
	  http://$(HTTP_HOST):$(HTTP_PORT)/ | head -40 || true
{%- endif %}

clean: ## Remove caches
	rm -rf .pytest_cache .ruff_cache .mypy_cache __pycache__ */__pycache__
