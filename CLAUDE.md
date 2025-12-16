# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

Never mention Claude or Claude Code in your PRs, diffs, etc.

## Project Overview

MCP Gateway (ContextForge) is a production-grade gateway, proxy, and registry for Model Context Protocol (MCP) servers
and A2A Agents. It federates MCP and REST services, providing unified discovery, auth, rate-limiting, observability,
virtual servers, multi-transport protocols, and an optional Admin UI.

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

### Database Performance Debugging
```bash
make dev-query-log                # Dev server with query logging to file (recommended)
make query-log-tail               # Tail the query log in another terminal
make query-log-analyze            # Analyze logs for N+1 patterns
make dev-echo                     # Dev server with SQL output to stdout
make test-db-perf                 # Run database performance/N+1 detection tests
```
See [Database Performance Guide](docs/docs/development/db-performance.md) for N+1 detection and query optimization.

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

# Testing individual files (using uv environment manager)
uv run pytest --cov-report=annotate tests/unit/mcpgateway/test_translate.py
```

## Architecture Overview

### Technology Stack
- **FastAPI** with **Pydantic** validation and **SQLAlchemy** ORM
  - FastAPI is build on Starlette ASGI framework
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
├── performance/        # Database performance & N+1 detection tests
├── helpers/            # Test utilities (query_counter.py)
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

### Generating Support Bundles
```bash
# Generate a support bundle for troubleshooting
mcpgateway --support-bundle --output-dir /tmp --log-lines 1000

# Customize what's included
mcpgateway --support-bundle --no-logs --log-lines 500

# Alternative: Use the service directly
python -c "from mcpgateway.services.support_bundle_service import create_support_bundle; print(create_support_bundle())"
```

The support bundle includes:
- Version and system information
- Configuration (with secrets automatically redacted)
- Application logs (sanitized)
- Platform details
- Service status
- Database and cache information

**Security**: All sensitive data (passwords, tokens, API keys, secrets) are automatically sanitized before inclusion in the bundle.

**API Endpoint**: `GET /admin/support-bundle/generate?log_lines=1000`

**Admin UI**: Available in the Diagnostics tab with a "Download Support Bundle" button

### Authentication & Tokens
```bash
# Generate JWT bearer token
python3 -m mcpgateway.utils.create_jwt_token --username admin@example.com --exp 10080 --secret my-test-key

# Export for API calls
export MCPGATEWAY_BEARER_TOKEN=$(python3 -m mcpgateway.utils.create_jwt_token --username admin@example.com --exp 0 --secret my-test-key)
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

## Development Guidelines

### Git & Commit Standards
- **Always sign commits**: Use `git commit -s` (DCO requirement)
- **Conventional Commits**: `feat:`, `fix:`, `docs:`, `refactor:`, `chore:`
- **Link Issues**: Include `Closes #123` in commit messages
- **No Claude mentions**: Never mention Claude or Claude Code in PRs/diffs
- DO NOT include test plans in pull requests
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
- uv for managing virtual environments
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

## Documentation Quick Links

### Getting Started
- [Developer Onboarding](docs/docs/development/developer-onboarding.md) - Complete setup guide for new contributors
- [Building & Testing](docs/docs/development/building.md) - Build system, testing workflows, coverage
- [Configuration Reference](docs/docs/manage/configuration.md) - Environment variables and settings

### API & Protocol Reference
- [REST API Usage](docs/docs/manage/api-usage.md) - Comprehensive REST API guide with curl examples
- [MCP JSON-RPC Guide](docs/docs/development/mcp-developer-guide-json-rpc.md) - Low-level MCP protocol implementation
- [OpenAPI Interactive Docs](http://localhost:4444/docs) - Swagger UI (requires running server)
- [OpenAPI Schema](http://localhost:4444/openapi.json) - Machine-readable API specification

### Core Features
- [A2A Agent Integration](docs/docs/using/agents/a2a.md) - Agent-to-Agent setup, authentication, monitoring
- [Plugin Development](docs/docs/architecture/plugins.md) - Plugin framework, hooks, creating custom plugins
- [Virtual Servers](docs/docs/manage/api-usage.md#virtual-server-management) - Creating and managing composite MCP servers
- [Export/Import Reference](docs/docs/manage/export-import-reference.md) - Bulk operations and configuration migration

### Architecture & Design
- [Architecture Overview](docs/docs/architecture/index.md) - System design, components, data flow
- [ADR Index](docs/docs/architecture/adr/index.md) - Architecture Decision Records
- [Security Architecture](docs/docs/architecture/security-features.md) - Authentication, authorization, security features
- [Multi-Transport Design](docs/docs/architecture/adr/003-expose-multi-transport-endpoints.md) - HTTP, WebSocket, SSE, STDIO

### Operations & Management
- [Logging & Monitoring](docs/docs/manage/logging.md) - Log configuration, rotation, analysis
- [Performance Tuning](docs/docs/testing/performance.md) - Benchmarks, optimization, profiling
- [Scaling & High Availability](docs/docs/manage/scale.md) - Horizontal scaling, load balancing, federation
- [Well-Known URIs](docs/docs/manage/well-known-uris.md) - Standard endpoints (robots.txt, security.txt)

### Deployment
- [Container Deployment](docs/docs/deployment/container.md) - Docker/Podman setup and configuration
- [Kubernetes Deployment](docs/docs/deployment/kubernetes.md) - K8s manifests and Helm charts
- [Cloud Deployments](docs/docs/deployment/) - AWS, Azure, GCP, Fly.io guides

### Testing & Quality
- [Testing Guide](docs/docs/testing/basic.md) - Unit, integration, E2E, security testing
- [Fuzzing & Property Testing](docs/docs/testing/fuzzing.md) - Advanced testing techniques
- [Documentation Standards](docs/docs/development/documentation.md) - Writing and maintaining docs

### Integration Guides
- [Agent Frameworks](docs/docs/using/agents/) - LangChain, CrewAI, LangGraph, AutoGen
- [MCP Clients](docs/docs/using/clients/) - Claude Desktop, Continue, Zed, OpenWebUI
- [MCP Servers](docs/docs/using/servers/) - Example server integrations
