.PHONY: install dev test clean run-http run-sse run-stdio

install:
	uv pip install -e .

dev:
	uv pip install -e ".[dev]"

test:
	pytest tests/ -v

clean:
	rm -rf build/ dist/ *.egg-info
	find . -type d -name __pycache__ -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete

run-http:
	uv run python -m test_reverse_proxy_mcp_server --transport http --port 9020

run-sse:
	uv run python -m test_reverse_proxy_mcp_server --transport sse --port 9020

run-stdio:
	uv run python -m test_reverse_proxy_mcp_server