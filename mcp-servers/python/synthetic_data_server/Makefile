# Synthetic Data FastMCP Server Makefile

PYTHON ?= python3
PACKAGE = synthetic_data_server
HTTP_HOST ?= 0.0.0.0
HTTP_PORT ?= 8000

.PHONY: install dev serve-http serve-sse lint test clean

install:
	uv pip install -e .[dev]

lint:
	uv pip install -q ruff mypy
	ruff check src/ tests/
	mypy src/${PACKAGE}

format:
	uv pip install -q black isort
	black src/ tests/
	isort src/ tests/

format-check:
	black --check src/ tests/
	isort --check-only src/ tests/

pre-commit:
	make format lint

test:
	uv pip install -q pytest pytest-cov
	pytest -v --cov=${PACKAGE} --cov-report=term-missing

dev:
	${PYTHON} -m ${PACKAGE}.server_fastmcp

serve-http:
	@echo "HTTP endpoint: http://${HTTP_HOST}:${HTTP_PORT}/mcp/"
	${PYTHON} -m ${PACKAGE}.server_fastmcp --transport http --host ${HTTP_HOST} --port ${HTTP_PORT}

serve-sse:
	@echo "SSE endpoint: http://${HTTP_HOST}:${HTTP_PORT}/sse"
	${PYTHON} -m mcpgateway.translate --stdio "${PYTHON} -m ${PACKAGE}.server_fastmcp" \
	  --host ${HTTP_HOST} --port ${HTTP_PORT} --expose-sse

clean:
	rm -rf .pytest_cache .ruff_cache .mypy_cache __pycache__ */__pycache__ *.egg-info dist build
