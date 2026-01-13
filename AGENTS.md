# AGENTS.md

Guidelines for AI coding assistants working with this repository.

For domain-specific guidance, see subdirectory AGENTS.md files:
- `tests/AGENTS.md` - Testing conventions and workflows
- `plugins/AGENTS.md` - Plugin framework and development
- `charts/AGENTS.md` - Helm chart operations
- `deployment/AGENTS.md` - Infrastructure and deployment
- `docs/AGENTS.md` - Documentation authoring
- `mcp-servers/AGENTS.md` - MCP server implementation

**Note:** The `llms/` directory contains guidance for LLMs *using* the Context Forge solution (end-user runtime guidance), not for code agents working on this codebase.

## Project Overview

MCP Gateway (ContextForge) is a production-grade gateway, proxy, and registry for Model Context Protocol (MCP) servers and A2A Agents. It federates MCP and REST services, providing unified discovery, auth, rate-limiting, observability, virtual servers, multi-transport protocols, and an optional Admin UI.

## Project Structure

```
mcpgateway/                 # Core FastAPI application
├── main.py                 # Application entry point
├── config.py               # Environment configuration
├── models.py               # SQLAlchemy ORM models
├── schemas.py              # Pydantic validation schemas
├── services/               # Business logic layer
├── routers/                # HTTP endpoint definitions
├── middleware/             # Cross-cutting concerns
├── transports/             # Protocol implementations (SSE, WebSocket, stdio)
├── plugins/                # Plugin framework infrastructure
└── alembic/                # Database migrations

tests/                      # Test suite (see tests/AGENTS.md)
plugins/                    # Plugin implementations (see plugins/AGENTS.md)
charts/                     # Helm charts (see charts/AGENTS.md)
deployment/                 # Infrastructure configs (see deployment/AGENTS.md)
docs/                       # Architecture and usage documentation (see docs/AGENTS.md)
mcp-servers/                # MCP server templates (see mcp-servers/AGENTS.md)
llms/                       # End-user LLM guidance (not for code agents)
```

## Essential Commands

### Setup
```bash
cp .env.example .env && make venv install-dev check-env    # Complete setup
make venv                          # Create virtual environment with uv
make install-dev                   # Install with dev dependencies
make check-env                     # Verify .env against .env.example
```

### Development
```bash
make dev                          # Dev server on :8000 with autoreload
make serve                        # Production gunicorn on :4444
make certs && make serve-ssl      # HTTPS on :4444
```

### Code Quality
```bash
# After writing code
make autoflake isort black pre-commit

# Before committing, use ty, mypy and pyrefly to check just the new files, then run:
make flake8 bandit interrogate pylint verify
```

## Key Environment Variables

```bash
# Core
HOST=0.0.0.0
PORT=4444
DATABASE_URL=sqlite:///./mcp.db   # or postgresql://...
REDIS_URL=redis://localhost:6379
RELOAD=true

# Auth
JWT_SECRET_KEY=your-secret-key
BASIC_AUTH_USER=admin
BASIC_AUTH_PASSWORD=changeme
AUTH_REQUIRED=true

# Features
MCPGATEWAY_UI_ENABLED=true
MCPGATEWAY_ADMIN_API_ENABLED=true
MCPGATEWAY_A2A_ENABLED=true

# Logging
LOG_LEVEL=INFO
LOG_TO_FILE=false
STRUCTURED_LOGGING_DATABASE_ENABLED=false
```

## MCP Helpers

```bash
# Generate JWT token
python -m mcpgateway.utils.create_jwt_token --username admin@example.com --exp 10080 --secret KEY

# Export for API calls
export MCPGATEWAY_BEARER_TOKEN=$(python -m mcpgateway.utils.create_jwt_token --username admin@example.com --exp 0 --secret KEY)

# Expose stdio server via HTTP/SSE
python -m mcpgateway.translate --stdio "uvx mcp-server-git" --port 9000
```

### Adding an MCP Server
1. Start: `python -m mcpgateway.translate --stdio "server-command" --port 9000`
2. Register: `POST /gateways`
3. Create virtual server: `POST /servers`
4. Access via SSE/WebSocket endpoints

## Technology Stack

- **FastAPI** with **Pydantic** validation and **SQLAlchemy** ORM (Starlette ASGI)
- **HTMX + Alpine.js** for admin UI
- **SQLite** default, **PostgreSQL** support, **Redis** for caching/federation
- **Alembic** for migrations

## Coding Standards

- **Python >= 3.11** with type hints; strict mypy
- **Formatting**: Black (line length 200), isort (profile=black)
- **Linting**: Ruff (F,E,W,B,ASYNC), Pylint per `pyproject.toml`
- **Naming**: `snake_case` functions/modules, `PascalCase` classes, `UPPER_CASE` constants
- **Imports**: Group per isort sections (stdlib, third-party, first-party `mcpgateway`, local)

## Commit & PR Standards

- **Sign commits**: `git commit -s` (DCO requirement)
- **Conventional Commits**: `feat:`, `fix:`, `docs:`, `refactor:`, `chore:`
- **Link issues**: `Closes #123`
- Include tests for behavior changes
- Require green lint and tests before PR

## Important Constraints

- Never mention AI assistants in PRs/diffs
- Do not include test plans or effort estimates in PRs
- Never create files unless absolutely necessary; prefer editing existing files
- Never proactively create documentation files unless explicitly requested
- Never commit secrets; use `.env` for configuration

## Key Files

- `mcpgateway/main.py` - Application entry point
- `mcpgateway/config.py` - Environment configuration
- `mcpgateway/models.py` - ORM models
- `mcpgateway/schemas.py` - Pydantic schemas
- `pyproject.toml` - Project configuration
- `Makefile` - Build automation
- `.env.example` - Environment template

## CLI Tools Available

- `gh` for GitHub operations
- `make` for build/test automation
- `uv` for virtual environment management
- Standard tools: pytest, black, isort, ruff, pylint
