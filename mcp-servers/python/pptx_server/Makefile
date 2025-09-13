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
	@$(PYTHON) -c "
import json
from src.pptx_server.server import create_presentation, add_slide, set_slide_title, set_slide_content, add_image, add_table, add_chart, save_presentation
import asyncio

async def create_demo():
    # Create presentation
    await create_presentation('demo.pptx', 'PowerPoint MCP Server Demo')

    # Add content slide
    await add_slide('demo.pptx', 1)  # Content layout
    await set_slide_title('demo.pptx', 1, 'Features Overview')
    await set_slide_content('demo.pptx', 1, 'Text editing\\nImage insertion\\nTable creation\\nChart generation\\nShape management')

    # Add table slide
    await add_slide('demo.pptx', 1)
    await set_slide_title('demo.pptx', 2, 'Sample Data Table')
    await add_table('demo.pptx', 2, 3, 4, 1.0, 2.0, 8.0, 3.0)

    # Add chart slide
    await add_slide('demo.pptx', 1)
    await set_slide_title('demo.pptx', 3, 'Sample Chart')
    chart_data = {
        'categories': ['Q1', 'Q2', 'Q3', 'Q4'],
        'series': [{'name': 'Sales', 'values': [100, 150, 120, 200]}]
    }
    await add_chart('demo.pptx', 3, chart_data, 'column', 1.0, 2.0, 8.0, 4.0, 'Quarterly Sales')

    await save_presentation('demo.pptx')
    print('Demo presentation created: demo.pptx')

asyncio.run(create_demo())
"

test-tools: ## Test individual PowerPoint tools
	@echo "Testing PowerPoint MCP tools..."
	@echo '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}' | $(PYTHON) -m pptx_server.server | head -20

validate: ## Validate PowerPoint files can be opened
	@echo "Validating generated PowerPoint files..."
	@$(PYTHON) -c "
from pptx import Presentation
import os
if os.path.exists('demo.pptx'):
    prs = Presentation('demo.pptx')
    print(f'Successfully opened demo.pptx with {len(prs.slides)} slides')
else:
    print('No demo.pptx found. Run make demo first.')
"