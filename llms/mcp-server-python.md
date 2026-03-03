FastMCP 2 Python Servers: Create, Build, and Run

- Scope: Practical guide for authoring, packaging, containerizing, and exposing Python MCP servers with FastMCP 2.x.
- References: See full implementations under `mcp-servers/python/*/server_fastmcp.py` (20 example servers available), e.g. `mcp-servers/python/chunker_server/src/chunker_server/server_fastmcp.py` and `mcp-servers/python/url_to_markdown_server/src/url_to_markdown_server/server_fastmcp.py`.

**Project Layout**
- Recommended structure for a new server `awesome_server`:

```
awesome_server/
  pyproject.toml
  Makefile
  Containerfile
  README.md
  src/
    awesome_server/
      __init__.py
      server_fastmcp.py  # FastMCP entry point
      tools.py           # optional: keep tool logic separate
  tests/
    test_server.py
```

**Minimal Server (stdio + http)**
- Implements a basic FastMCP server with one tool (`echo`). Type hints define schemas.

```python
# src/awesome_server/server_fastmcp.py
from fastmcp import FastMCP

mcp = FastMCP("awesome-server", version="0.1.0")


@mcp.tool
def echo(text: str) -> str:
    """Return the provided text."""
    return text


def main() -> None:
    """Entry point for `python -m awesome_server.server_fastmcp`."""
    mcp.run()  # stdio by default


if __name__ == "__main__":  # pragma: no cover
    main()
```

**Enhanced Server with Native HTTP Support**
- For better flexibility, add argument parsing to support both stdio and HTTP modes natively:

```python
# src/awesome_server/server_fastmcp.py
from fastmcp import FastMCP
import argparse

mcp = FastMCP("awesome-server", version="0.1.0")


@mcp.tool
def echo(text: str) -> str:
    """Return the provided text."""
    return text


def main() -> None:
    """Entry point with transport selection."""
    parser = argparse.ArgumentParser(description="Awesome FastMCP Server")
    parser.add_argument("--transport", choices=["stdio", "http"], default="stdio",
                        help="Transport mode (stdio or http)")
    parser.add_argument("--host", default="0.0.0.0", help="HTTP host")
    parser.add_argument("--port", type=int, default=8000, help="HTTP port")

    args = parser.parse_args()

    if args.transport == "http":
        mcp.run(transport="http", host=args.host, port=args.port)
    else:
        mcp.run()


if __name__ == "__main__":  # pragma: no cover
    main()
```

- Run over stdio: `python -m awesome_server.server_fastmcp`
- Run over HTTP: `python -m awesome_server.server_fastmcp --transport http --host 0.0.0.0 --port 8000`
- Alternative with CLI: `fastmcp run src/awesome_server/server_fastmcp.py:mcp --transport http --host 0.0.0.0 --port 8000`

**pyproject.toml (template)**
- Pin FastMCP for production deployments; adjust metadata and optional extras.

```toml
[project]
name = "awesome-server"
version = "0.1.0"
description = "Example FastMCP 2 server"
authors = [
  { name = "ContextForge", email = "noreply@example.com" }
]
license = { text = "MIT" }
readme = "README.md"
requires-python = ">=3.11"
dependencies = [
  "fastmcp==2.11.3",
  "pydantic>=2.5.0",
]

[project.optional-dependencies]
dev = [
  "pytest>=7.0.0",
  "pytest-asyncio>=0.21.0",
  "pytest-cov>=4.0.0",
  "black>=23.0.0",
  "mypy>=1.5.0",
  "ruff>=0.0.290",
]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/awesome_server"]

[project.scripts]
awesome-server = "awesome_server.server_fastmcp:main"

[tool.black]
line-length = 100
target-version = ["py311"]

[tool.mypy]
python_version = "3.11"
strict = true
warn_return_any = true
warn_unused_configs = true

[tool.ruff]
line-length = 100
target-version = "py311"
select = ["E", "W", "F", "B", "I", "N", "UP"]

[tool.pytest.ini_options]
testpaths = ["tests"]
asyncio_mode = "auto"
addopts = "--cov=awesome_server --cov-report=term-missing"
```

Notes:
- Use exact FastMCP versions (`fastmcp==…`) in production to avoid breaking changes.
- See richer examples in `data_analysis_server/pyproject.toml` and `mcp_eval_server/pyproject.toml` for additional extras and entry points.

**Makefile (template)**
- Provides dev install, format/lint/test targets, multiple transport modes (stdio, native HTTP, SSE bridge).

```makefile
# Makefile for Awesome FastMCP Server

.PHONY: help install dev-install format lint test dev serve-http serve-sse test-http mcp-info clean

PYTHON ?= python3
HTTP_PORT ?= 8000
HTTP_HOST ?= 0.0.0.0

help: ## Show help
    @echo "Quick Start:"
    @echo "  make install          Install FastMCP server"
    @echo "  make dev              Run FastMCP server (stdio)"
    @echo "  make serve-http       Run with native FastMCP HTTP"
    @echo "  make serve-sse        Run with translate SSE bridge"
    @echo ""
    @awk 'BEGIN {FS=":.*?## "} /^[a-zA-Z_-]+:.*?## / {printf "  %-18s %s\n", $$1, $$2}' $(MAKEFILE_LIST)

install: ## Install in editable mode
    $(PYTHON) -m pip install -e .

dev-install: ## Install with dev extras
    $(PYTHON) -m pip install -e ".[dev]"

format: ## Format (black + ruff --fix)
    black . && ruff check --fix .

lint: ## Lint (ruff, mypy)
    ruff check . && mypy src/awesome_server

test: ## Run tests
    pytest -v --cov=awesome_server --cov-report=term-missing

dev: ## Run FastMCP server (stdio)
    $(PYTHON) -m awesome_server.server_fastmcp

serve-http: ## Run with native FastMCP HTTP
    @echo "HTTP endpoint: http://$(HTTP_HOST):$(HTTP_PORT)/mcp/"
    $(PYTHON) -m awesome_server.server_fastmcp --transport http --host $(HTTP_HOST) --port $(HTTP_PORT)

serve-sse: ## Run with mcpgateway.translate (SSE bridge)
    @echo "SSE endpoint: http://$(HTTP_HOST):$(HTTP_PORT)/sse"
    $(PYTHON) -m mcpgateway.translate --stdio "$(PYTHON) -m awesome_server.server_fastmcp" \
      --host $(HTTP_HOST) --port $(HTTP_PORT) --expose-sse

test-http: ## Test native HTTP endpoint
    curl -s -X POST -H 'Content-Type: application/json' \
      -d '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}' \
      http://$(HTTP_HOST):$(HTTP_PORT)/mcp/ | python3 -m json.tool | head -40 || true

mcp-info: ## Show MCP client configs
    @echo "1. FastMCP Server (stdio - for Claude Desktop):"
    @echo '{"command": "python", "args": ["-m", "awesome_server.server_fastmcp"]}'
    @echo ""
    @echo "2. Native HTTP: make serve-http"
    @echo "3. SSE bridge: make serve-sse"

clean: ## Remove caches
    rm -rf .pytest_cache .ruff_cache .mypy_cache __pycache__ */__pycache__ *.egg-info
```

Notes:
- Use `uv pip install -e .` if your team standardizes on uv.
- For richer Makefiles (container build, smoke tests, docs), see `mcp_eval_server/Makefile`.

**Containerfile (template)**
- Minimal container using `python:3.11-slim`; installs your project in a virtualenv with a non-root user.

```Dockerfile
# syntax=docker/dockerfile:1
FROM python:3.11-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates curl && \
    rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md ./
COPY src/ ./src/

RUN python -m venv /app/.venv && \
    /app/.venv/bin/pip install --upgrade pip setuptools wheel && \
    /app/.venv/bin/pip install -e .

RUN useradd -u 1001 -m appuser && chown -R 1001:1001 /app
USER 1001

CMD ["python", "-m", "awesome_server.server_fastmcp"]
```

Notes:
- Swap the container entrypoint to `fastmcp run /app/src/awesome_server/server_fastmcp.py:mcp --transport http --host 0.0.0.0 --port 8000` (or similar) when you need remote HTTP access.
- For hardened multi-stage builds (scratch base, non-root, healthchecks), study `data_analysis_server/Containerfile` and `mcp_eval_server/Containerfile`.

**Run Locally**
- Stdio mode (for local LLM clients or direct JSON-RPC piping):
  - `make dev`
  - `fastmcp run src/awesome_server/server_fastmcp.py:mcp`
- HTTP mode:
  - `make serve-http`
  - Call with curl: `curl -s -X POST http://localhost:8000/mcp/ -H 'Content-Type: application/json' -d '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}'`

**Tips & Patterns**
- Keep FastMCP objects (`FastMCP`, `@mcp.tool`, `@mcp.prompt`, `@mcp.resource`) in `server_fastmcp.py`; move heavy business logic into `tools.py` or subpackages.
- Log to stderr when running under stdio transports to avoid corrupting the protocol stream.
- Prefer Pydantic models for complex tool arguments/returns; FastMCP exposes them as structured schemas automatically.
- Add argparse for flexible transport selection (stdio/HTTP) in the same codebase.
- Combine FastMCP with the gateway by registering the HTTP endpoint (`/mcp`) or by wrapping stdio servers with `mcpgateway.translate` if you need SSE bridging.

**Best Practices (from production experience)**
1. **Single Implementation**: Use only FastMCP 2.x - avoid maintaining both MCP 1.0 and FastMCP versions
2. **Version Pinning**: Always pin FastMCP to exact version (`fastmcp==2.11.3`) to avoid breaking changes
3. **Error Handling**: Gracefully handle missing dependencies (e.g., Graphviz) with clear error messages
4. **Transport Flexibility**: Support multiple transports in the same server:
   - stdio for Claude Desktop and local clients
   - Native HTTP for REST API access
   - SSE bridge via translate for streaming clients
5. **Testing**: Write tests that work directly with processor classes, not just via MCP protocol
6. **Project Structure**: Keep it simple - one `server_fastmcp.py` file is often sufficient for small/medium servers

**FastMCP 2 Resources**
- Core docs: [Welcome to FastMCP 2.0](https://gofastmcp.com/getting-started/welcome.md), [Installation](https://gofastmcp.com/getting-started/installation.md), [Quickstart](https://gofastmcp.com/getting-started/quickstart.md), [Changelog](https://gofastmcp.com/changelog.md).
- Client guides: [Client overview](https://gofastmcp.com/clients/client.md), [Authentication (Bearer)](https://gofastmcp.com/clients/auth/bearer.md), [Authentication (OAuth)](https://gofastmcp.com/clients/auth/oauth.md), [User elicitation](https://gofastmcp.com/clients/elicitation.md), [Logging](https://gofastmcp.com/clients/logging.md), [Messages](https://gofastmcp.com/clients/messages.md), [Progress](https://gofastmcp.com/clients/progress.md), [Prompts](https://gofastmcp.com/clients/prompts.md), [Resources](https://gofastmcp.com/clients/resources.md), [Tools](https://gofastmcp.com/clients/tools.md), [Transports](https://gofastmcp.com/clients/transports.md), [LLM sampling](https://gofastmcp.com/clients/sampling.md).
- Server guides: [Server fundamentals](https://gofastmcp.com/servers/server.md), [Context](https://gofastmcp.com/servers/context.md), [Tools](https://gofastmcp.com/servers/tools.md), [Resources & templates](https://gofastmcp.com/servers/resources.md), [Prompts](https://gofastmcp.com/servers/prompts.md), [Logging](https://gofastmcp.com/servers/logging.md), [Progress](https://gofastmcp.com/servers/progress.md), [Middleware](https://gofastmcp.com/servers/middleware.md), [Authentication](https://gofastmcp.com/servers/auth/authentication.md), [Proxy](https://gofastmcp.com/servers/proxy.md), [LLM sampling](https://gofastmcp.com/servers/sampling.md).
- Operations: [Running your server](https://gofastmcp.com/deployment/running-server.md), [Self-hosted remote MCP](https://gofastmcp.com/deployment/self-hosted.md), [FastMCP Cloud](https://gofastmcp.com/deployment/fastmcp-cloud.md), [Project configuration](https://gofastmcp.com/deployment/server-configuration.md).
- Integrations: [FastAPI](https://gofastmcp.com/integrations/fastapi.md), [Anthropic API](https://gofastmcp.com/integrations/anthropic.md), [OpenAI API](https://gofastmcp.com/integrations/openai.md), [Claude Desktop](https://gofastmcp.com/integrations/claude-desktop.md), [Cursor](https://gofastmcp.com/integrations/cursor.md).
