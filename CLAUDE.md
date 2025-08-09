# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

MCP Gateway (ContextForge) is a production-grade gateway, proxy, and registry for Model Context Protocol (MCP) servers. It federates MCP and REST services, providing unified discovery, auth, rate-limiting, observability, virtual servers, multi-transport protocols, and an optional Admin UI.

## Development Commands

### Core Development Workflow

```bash
# Setup and Installation
make venv            # Create virtual environment
make install-dev     # Install with development dependencies
make install-db      # Install with database adapters (Redis, PostgreSQL)

# Running the Gateway
make dev             # Run with hot reload on port 8000 (uvicorn)
make serve          # Run production server (gunicorn)
mcpgateway --host 0.0.0.0 --port 4444  # Run directly via CLI

# Testing
make doctest         # Run all doctest
make test            # Run all tests with coverage
pytest tests/unit/   # Run specific test directory
pytest -k "test_name" # Run specific test by name

# Code Quality
make lint            # Run all linters on mcpgateway/
make lint-web        # Run linters for web files (html, js, css)
make check-manifest  # Verify MANIFEST.in completeness

# Build & Distribution
make dist            # Build wheel and sdist packages
```

### Authentication & Token Generation

```bash
# Generate JWT bearer token
python3 -m mcpgateway.utils.create_jwt_token \
    --username admin --exp 10080 --secret my-test-key

# Export for API calls
export MCPGATEWAY_BEARER_TOKEN=$(python3 -m mcpgateway.utils.create_jwt_token \
    --username admin --exp 0 --secret my-test-key)
```

### Working with MCP Servers

```bash
# Run mcpgateway.translate to expose stdio servers via HTTP/SSE
python3 -m mcpgateway.translate \
    --stdio "uvx mcp-server-git" --port 9000

# Run the stdio wrapper for MCP clients
export MCP_AUTH_TOKEN=$MCPGATEWAY_BEARER_TOKEN
export MCP_SERVER_CATALOG_URLS=http://localhost:4444/servers/UUID
python3 -m mcpgateway.wrapper
```

## Architecture Overview

### Core Components

The gateway is built on **FastAPI** with **Pydantic** for validation and **SQLAlchemy** for persistence. Key architectural decisions are documented in `docs/docs/architecture/adr/`.

### Directory Structure

- **`mcpgateway/`** - Main application code
  - `main.py` - FastAPI application entry point
  - `cli.py` - Command-line interface
  - `models.py` - SQLAlchemy ORM models
  - `schemas.py` - Pydantic schemas for validation
  - `config.py` - Settings management via environment variables
  - `admin.py` - Admin UI routes (HTMX + Alpine.js)

- **`mcpgateway/services/`** - Business logic layer
  - `gateway_service.py` - Federation and peer gateway management
  - `server_service.py` - Virtual server composition
  - `tool_service.py` - Tool registry and invocation
  - `resource_service.py` - Resource caching and updates
  - `prompt_service.py` - Prompt template management

- **`mcpgateway/transports/`** - Protocol implementations
  - `sse_transport.py` - Server-Sent Events
  - `websocket_transport.py` - WebSocket bidirectional
  - `stdio_transport.py` - Standard I/O for CLI tools
  - `streamablehttp_transport.py` - HTTP streaming

- **`mcpgateway/plugins/`** - Plugin framework
  - `framework/` - Plugin loader, manager, and registry
  - Plugin configurations in `plugins/config.yaml`

### Database & Caching

- **SQLite** default (`sqlite:///./mcp.db`)
- **PostgreSQL** support via `psycopg2-binary`
- **Redis** for distributed caching and federation
- **Alembic** for database migrations (`mcpgateway/alembic/`)

### Service Federation

The gateway supports multi-instance federation:
- Auto-discovery via mDNS/Zeroconf
- Manual peer registration via API
- Health checks and automatic failover
- Shared tool/resource catalogs across peers

### Virtual Servers

Virtual servers bundle tools, prompts, and resources:
- Compose multiple MCP servers into one logical unit
- Control tool visibility per virtual server
- Support multiple protocol endpoints per server

## Key Environment Variables

```bash
# Core Settings
HOST=0.0.0.0
PORT=4444
DATABASE_URL=sqlite:///./mcp.db  # or postgresql://...
REDIS_URL=redis://localhost:6379

# Authentication
JWT_SECRET_KEY=your-secret-key
BASIC_AUTH_USER=admin
BASIC_AUTH_PASSWORD=changeme
AUTH_REQUIRED=true

# UI & Admin
MCPGATEWAY_UI_ENABLED=true
MCPGATEWAY_ADMIN_API_ENABLED=true

# Federation
MCPGATEWAY_ENABLE_MDNS_DISCOVERY=true
MCPGATEWAY_ENABLE_FEDERATION=true

# Development
LOG_LEVEL=INFO
RELOAD=true  # For development hot-reload
```

## Testing Strategy

### Unit Tests
- Located in `tests/unit/`
- Cover all services, transports, and utilities
- Use pytest fixtures for database and async testing

### Integration Tests
- Located in `tests/integration/`
- Test API endpoints and cross-service workflows
- Mock external dependencies

### UI Tests
- Located in `tests/playwright/`
- Use Playwright for browser automation
- Test admin UI interactions and real-time features

### Running Specific Tests
```bash
# Run tests for a specific module
pytest tests/unit/mcpgateway/services/test_tool_service.py

# Run with verbose output
pytest -v tests/

# Run with specific markers
pytest -m "not slow"
```

## Common Development Tasks

### Adding a New MCP Server
1. Start the server (e.g., via `mcpgateway.translate` for stdio servers)
2. Register it as a gateway peer via POST `/gateways`
3. Create a virtual server bundling its tools via POST `/servers`
4. Access via the virtual server's SSE/WebSocket endpoints

### Debugging Federation Issues
1. Check peer health: `GET /gateways`
2. Verify mDNS discovery: `MCPGATEWAY_ENABLE_MDNS_DISCOVERY=true`
3. Check Redis connectivity if using distributed cache
4. Review logs for connection errors

### Plugin Development
1. Create plugin in `plugins/your_plugin/`
2. Add manifest in `plugin-manifest.yaml`
3. Register in `plugins/config.yaml`
4. Implement required hooks (pre/post request/response)

## API Endpoints Overview

### Core MCP Operations
- `POST /` - JSON-RPC endpoint for MCP protocol
- `GET /servers/{id}/sse` - SSE transport for MCP
- `WS /servers/{id}/ws` - WebSocket transport

### Admin APIs (when enabled)
- `GET/POST /tools` - Tool management
- `GET/POST /resources` - Resource management
- `GET/POST /prompts` - Prompt templates
- `GET/POST /servers` - Virtual servers
- `GET/POST /gateways` - Peer gateways
- `GET /admin` - Admin UI dashboard

# You have access to cli tools
- You can use `gh` for github commands, e.g. gh issue view 586

# To test everything:

make autoflake isort black pre-commit
make doctest test smoketest lint-web flake8 pylint

# Rules
- When using git commit always add a -s to sign commits
