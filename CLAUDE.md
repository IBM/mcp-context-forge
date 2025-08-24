# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

Never mention Claude or Claude Code in your PRs, diffs, etc.

## Project Overview

MCP Gateway (ContextForge) is a production-grade gateway, proxy, and registry for Model Context Protocol (MCP) servers and A2A Agents. It federates MCP and REST services, providing unified discovery, auth, rate-limiting, observability, virtual servers, multi-transport protocols, and an optional Admin UI.

## Essential Commands

### Setup & Installation
```bash
cp .env.example .env && make venv install-dev check-env    # Complete setup workflow
make venv                          # Create fresh virtual environment with uv
make install-dev                   # Install with development dependencies
make check-env                     # Verify .env against .env.example
```

### Development Workflow
```bash
make dev                          # Start development server (port 8000) with autoreload
make serve                        # Production server (gunicorn, port 4444)
```

### Code Quality Pipeline
```bash
# After writing code (auto-format & cleanup)
make autoflake isort black pre-commit

# Before committing (comprehensive quality checks)
make flake8 bandit interrogate pylint verify

# Web assets
make lint-web                     # HTML/CSS/JS linting
```

### Testing & Coverage
```bash
# Complete testing workflow
make doctest test htmlcov smoketest lint-web flake8 bandit interrogate pylint verify

# Core testing
make doctest test htmlcov         # Doctests + unit tests + coverage (→ docs/docs/coverage/index.html)
make smoketest                    # End-to-end container testing

# Testing individual files (activate env first)
. /home/cmihai/.venv/mcpgateway/bin/activate && pytest --cov-report=annotate tests/unit/mcpgateway/test_translate.py
```

## Architecture Overview

### Technology Stack
- **FastAPI** with **Pydantic** validation and **SQLAlchemy** ORM
- **HTMX + Alpine.js** for admin UI
- **SQLite** default, **PostgreSQL** support, **Redis** for caching/federation
- **Alembic** for database migrations

### Key Directory Structure
```
mcpgateway/
├── main.py              # FastAPI application entry point
├── cli.py               # Command-line interface
├── config.py            # Environment variable settings
├── models.py            # SQLAlchemy ORM models
├── schemas.py           # Pydantic validation schemas
├── admin.py             # Admin UI routes (HTMX)
├── services/            # Business logic layer
│   ├── gateway_service.py      # Federation & peer management
│   ├── server_service.py       # Virtual server composition
│   ├── tool_service.py         # Tool registry & invocation
│   ├── a2a_service.py          # Agent-to-Agent integration
│   └── export_service.py       # Bulk operations
├── transports/          # Protocol implementations
│   ├── sse_transport.py        # Server-Sent Events
│   ├── websocket_transport.py  # WebSocket bidirectional
│   └── stdio_transport.py      # Standard I/O wrapper
├── plugins/             # Plugin framework
│   ├── framework/              # Plugin loader & manager
│   └── [pii_filter, deny_filter, regex_filter, resource_filter]/
└── alembic/             # Database migrations

tests/
├── unit/               # Unit tests with pytest fixtures
├── integration/        # API endpoints & cross-service workflows
├── e2e/               # End-to-end workflows
├── playwright/        # UI automation with Playwright
├── security/          # Security validation
└── fuzz/             # Fuzzing & property-based testing
```

## Key Environment Variables

### Core Settings
```bash
HOST=0.0.0.0
PORT=4444
DATABASE_URL=sqlite:///./mcp.db        # or postgresql://...
REDIS_URL=redis://localhost:6379
RELOAD=true                            # Development hot-reload
```

### Authentication & Security
```bash
JWT_SECRET_KEY=your-secret-key
BASIC_AUTH_USER=admin
BASIC_AUTH_PASSWORD=changeme
AUTH_REQUIRED=true
```

### Features & UI
```bash
MCPGATEWAY_UI_ENABLED=true
MCPGATEWAY_ADMIN_API_ENABLED=true
MCPGATEWAY_BULK_IMPORT_ENABLED=true
MCPGATEWAY_BULK_IMPORT_MAX_TOOLS=200
```

### A2A (Agent-to-Agent) Features
```bash
MCPGATEWAY_A2A_ENABLED=true            # Master switch for A2A features
MCPGATEWAY_A2A_MAX_AGENTS=100          # Agent limit
MCPGATEWAY_A2A_DEFAULT_TIMEOUT=30      # HTTP timeout (seconds)
MCPGATEWAY_A2A_METRICS_ENABLED=true    # Metrics collection
```

### Federation & Discovery
```bash
MCPGATEWAY_ENABLE_FEDERATION=true
MCPGATEWAY_ENABLE_MDNS_DISCOVERY=true  # mDNS/Zeroconf discovery
```

### Logging
```bash
LOG_LEVEL=INFO
LOG_TO_FILE=false                      # Enable file logging
LOG_ROTATION_ENABLED=false             # Size-based rotation
LOG_FILE=mcpgateway.log
LOG_FOLDER=logs
```

## Common Development Tasks

### Authentication & Tokens
```bash
# Generate JWT bearer token
python3 -m mcpgateway.utils.create_jwt_token --username admin --exp 10080 --secret my-test-key

# Export for API calls
export MCPGATEWAY_BEARER_TOKEN=$(python3 -m mcpgateway.utils.create_jwt_token --username admin --exp 0 --secret my-test-key)
```

### Working with MCP Servers
```bash
# Expose stdio servers via HTTP/SSE
python3 -m mcpgateway.translate --stdio "uvx mcp-server-git" --port 9000
```

### Adding a New MCP Server
1. Start server: `python3 -m mcpgateway.translate --stdio "server-command" --port 9000`
2. Register as gateway peer: `POST /gateways`
3. Create virtual server: `POST /servers`
4. Access via SSE/WebSocket endpoints

### Container Operations
```bash
make container-build                   # Build using auto-detected runtime (Docker/Podman)
make container-run-ssl-host            # Run with TLS on port 4444 and host networking
make container-stop                    # Stop & remove container
make container-logs                    # Show container logs

### Security & Quality Assurance
```bash
make security-scan                   # Trivy + Grype vulnerability scans
```

### Plugin Development
1. Create directory: `plugins/your_plugin/`
2. Add manifest: `plugin-manifest.yaml`
3. Register in: `plugins/config.yaml`
4. Implement hooks: pre/post request/response
5. Test: `pytest tests/unit/mcpgateway/plugins/`

## A2A (Agent-to-Agent) Integration

A2A agents are external AI agents (OpenAI, Anthropic, custom) integrated as tools within virtual servers.

### Integration Workflow
1. **Register Agent**: Add via `/a2a` API or Admin UI
2. **Associate with Server**: Include agent ID in virtual server's `associated_a2a_agents`
3. **Auto-Tool Creation**: Gateway creates tools for associated agents
4. **Tool Invocation**: Standard tool invocation routes to A2A agents
5. **Metrics Collection**: Comprehensive interaction tracking

### Configuration Effects
- `MCPGATEWAY_A2A_ENABLED=false`: Disables all A2A features (API 404, UI hidden)
- `MCPGATEWAY_A2A_METRICS_ENABLED=false`: Disables metrics collection only

## API Endpoints Overview

### Core MCP Protocol
- `POST /` - JSON-RPC endpoint for MCP protocol
- `GET /servers/{id}/sse` - Server-Sent Events transport
- `WS /servers/{id}/ws` - WebSocket transport
- `GET /.well-known/mcp` - Well-known URI handler

### Admin APIs (when `MCPGATEWAY_ADMIN_API_ENABLED=true`)
- `GET/POST /tools` - Tool management and invocation
- `GET/POST /resources` - Resource management
- `GET/POST /prompts` - Prompt templates
- `GET/POST /servers` - Virtual server management
- `GET/POST /gateways` - Peer gateway federation
- `GET/POST /a2a` - A2A agent management
- `GET/POST /tags` - Tag management system
- `POST /bulk-import` - Bulk import operations
- `GET /admin` - Admin UI dashboard

### Observability
- `GET /health` - Health check endpoint
- `GET /metrics` - Prometheus metrics (when enabled)
- `GET /openapi.json` - OpenAPI specification

## Development Guidelines

### Git & Commit Standards
- **Always sign commits**: Use `git commit -s` (DCO requirement)
- **Conventional Commits**: `feat:`, `fix:`, `docs:`, `refactor:`, `chore:`
- **Link Issues**: Include `Closes #123` in commit messages
- **No Claude mentions**: Never mention Claude or Claude Code in PRs/diffs
- **No estimates**: Don't include effort estimates or "phases"

### Code Style & Standards
- **Python >= 3.11** with type hints (strict mypy settings)
- **Formatting**: Black (line length 200), isort (profile=black)
- **Linting**: Ruff (F,E,W,B,ASYNC), Pylint per `pyproject.toml`
- **Naming**: `snake_case` functions, `PascalCase` classes, `UPPER_CASE` constants
- **Imports**: Group per isort sections (stdlib, third-party, first-party, local)

### File Creation Policy
- **NEVER create files** unless absolutely necessary for the goal
- **ALWAYS prefer editing** existing files over creating new ones
- **NEVER proactively create** documentation files (*.md) or README files
- Only create documentation if explicitly requested by the user

### CLI Tools Available
- `gh` for GitHub operations: `gh issue view 586`, `gh pr create`
- `make` for all build/test operations
- Standard development tools: pytest, black, isort, etc.

## Quick Reference

### Key Files
- `mcpgateway/main.py` - FastAPI application entry point
- `mcpgateway/config.py` - Environment variable configuration
- `mcpgateway/models.py` - SQLAlchemy ORM models
- `mcpgateway/schemas.py` - Pydantic validation schemas
- `pyproject.toml` - Project configuration and dependencies
- `Makefile` - Comprehensive build and development automation
- `.env.example` - Environment variable template

### Most Common Commands
```bash
# Development cycle
make autoflake isort black pre-commit

# Complete quality pipeline
make doctest test htmlcov smoketest lint-web flake8 bandit interrogate pylint verify
```
