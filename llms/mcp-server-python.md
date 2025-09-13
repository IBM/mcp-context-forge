Python MCP Servers: Create, Build, and Run

- Scope: Practical guide to author, package, containerize, and expose Python MCP servers.
- References: See working examples under `mcp-servers/python/`:
  - `mcp-servers/python/data_analysis_server` (focused, minimal dependencies)
  - `mcp-servers/python/mcp_eval_server` (larger, optional REST mode + many extras)

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
      server.py      # MCP entry (stdio)
      tools.py       # optional: keep tool logic separate
  tests/
    test_server.py
```

**Minimal Server (stdio)**
- Implements a basic MCP server with 1 tool (`echo`).

```python
# src/awesome_server/server.py
import asyncio
import json
import logging
import sys
from mcp.server import Server
from mcp.server.models import InitializationOptions
from mcp.types import TextContent, Tool

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stderr)],  # stderr avoids protocol noise
)
log = logging.getLogger("awesome_server")

server = Server("awesome-server")


@server.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="echo",
            description="Return the provided text.",
            inputSchema={
                "type": "object",
                "properties": {"text": {"type": "string"}},
                "required": ["text"],
            },
        )
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    if name == "echo":
        return [TextContent(type="text", text=json.dumps({"ok": True, "echo": arguments["text"]}))]
    return [TextContent(type="text", text=json.dumps({"ok": False, "error": f"unknown tool: {name}"}))]


async def main() -> None:
    log.info("Starting Awesome MCP server (stdio)...")
    from mcp.server.stdio import stdio_server

    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            InitializationOptions(
                server_name="awesome-server",
                server_version="0.1.0",
                capabilities={"tools": {}, "logging": {}},
            ),
        )


if __name__ == "__main__":  # pragma: no cover
    asyncio.run(main())
```

**pyproject.toml (template)**
- Minimal, typed, with common dev extras; adjust metadata and dependencies.

```toml
[project]
name = "awesome-server"
version = "0.1.0"
description = "Example Python MCP server (stdio + containerizable)"
authors = [
  { name = "MCP Context Forge", email = "noreply@example.com" }
]
license = { text = "MIT" }
readme = "README.md"
requires-python = ">=3.11"
dependencies = [
  "mcp>=1.0.0",
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
awesome-server = "awesome_server.server:main"

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
- See richer examples in `data_analysis_server/pyproject.toml` and `mcp_eval_server/pyproject.toml` for add‑on extras, entry points, and packaging knobs.

**Makefile (template)**
- Provides dev install, format/lint/test, stdio run, and HTTP bridge via the gateway.

```makefile
# Makefile for Awesome MCP Server

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
    ruff check . && mypy src/awesome_server

test: ## Run tests
    pytest -v --cov=awesome_server --cov-report=term-missing

dev: ## Run stdio MCP server
    @echo "Starting Awesome MCP server (stdio)..."
    $(PYTHON) -m awesome_server.server

mcp-info: ## Show stdio client config snippet
    @echo '{"command": "python", "args": ["-m", "awesome_server.server"], "cwd": "'$(PWD)'"}'

serve-http: ## Expose stdio server over HTTP (JSON-RPC + SSE)
    @echo "HTTP: http://$(HTTP_HOST):$(HTTP_PORT)"
    $(PYTHON) -m mcpgateway.translate --stdio "$(PYTHON) -m awesome_server.server" --host $(HTTP_HOST) --port $(HTTP_PORT) --expose-sse

test-http: ## Basic HTTP checks
    curl -s http://$(HTTP_HOST):$(HTTP_PORT)/ | head -20 || true
    curl -s -X POST -H 'Content-Type: application/json' \
      -d '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}' \
      http://$(HTTP_HOST):$(HTTP_PORT)/ | head -40 || true

clean: ## Remove caches
    rm -rf .pytest_cache .ruff_cache .mypy_cache __pycache__ */__pycache__
```

Notes:
- For a complete, production‑grade Makefile with additional targets (container build, examples, rich info), see `data_analysis_server/Makefile` and `mcp_eval_server/Makefile`.

**Containerfile (template)**
- Minimal, pragmatic container using `python:3.11-slim`.
- For hardened scratch‑based images with UBI9 and multi‑stage rootfs, review `data_analysis_server/Containerfile` and `mcp_eval_server/Containerfile`.

```Dockerfile
# syntax=docker/dockerfile:1
FROM python:3.11-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app

# System deps (optional: add build-essential if compiling wheels)
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates curl && \
    rm -rf /var/lib/apt/lists/*

# Copy metadata early for layer caching
COPY pyproject.toml README.md ./

# Create venv and install
RUN python -m venv /app/.venv && \
    /app/.venv/bin/pip install --upgrade pip setuptools wheel && \
    /app/.venv/bin/pip install -e .

# Copy source
COPY src/ ./src/

# Non-root user
RUN useradd -u 1001 -m appuser && chown -R 1001:1001 /app
USER 1001

CMD ["python", "-m", "awesome_server.server"]
```

Notes:
- Switch to the scratch‑based, hardened pattern when you need smallest images, reproducible Python from UBI9, and extra hardening. The advanced Containerfiles in this repo demonstrate:
  - Multi‑stage build with UBI9 builder + scratch runtime
  - Pre‑compiled bytecode (`-OO`), setuid/gid cleanup, minimal `/etc/{passwd,group}`
  - Non‑root user (1001), healthchecks, and SSE/HTTP exposure via the gateway

**Run Locally**
- Stdio mode (for Claude Desktop, IDEs, or direct JSON‑RPC piping):
  - `make dev`
  - Test tools via JSON‑RPC: `echo '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}' | python -m awesome_server.server`
- HTTP bridge (wrap stdio through the gateway's translate module):
  - `make serve-http`
  - `make test-http`

**Tips & Patterns**
- Separate tool logic from the transport layer (keep `server.py` thin; put domain logic in `tools.py` or subpackages).
- Always log to stderr to avoid corrupting the MCP stdio protocol.
- Keep tool schemas explicit and stable; return exactly one of `result` or `error` payload per call.
- Prefer small, focused servers with clear tool boundaries; use the gateway for aggregation, auth, and policy.
- Look at `data_analysis_server/src/data_analysis_server/server.py` for a clean stdio pattern with `mcp.server` and `InitializationOptions`.

**Scaffold With Copier**
- Generate a new Python MCP server from the template:
  - `mcp-servers/scaffold-python-server.sh awesome_server` (defaults to `mcp-servers/python/awesome_server`)
  - Follow prompts (project name, package, version, etc.)
  - Then: `cd mcp-servers/python/awesome_server && python -m pip install -e .[dev] && make dev`
