# MCP Gateway Development Guide

This guide provides comprehensive information for developers working on the MCP Gateway (ContextForge) project.

## Table of Contents
- [Quick Start](#quick-start)
- [Development Setup](#development-setup)
- [Project Architecture](#project-architecture)
- [Development Workflow](#development-workflow)
- [Code Quality](#code-quality)
- [Database Management](#database-management)
- [API Development](#api-development)
- [Plugin Development](#plugin-development)
- [Testing MCP Servers](#testing-mcp-servers)
- [Debugging](#debugging)
- [Performance Optimization](#performance-optimization)
- [Contributing](#contributing)

## Quick Start

```bash
# Clone and setup
git clone https://github.com/IBM/mcp-context-forge.git
cd mcp-context-forge

# Complete setup with uv (recommended)
cp .env.example .env && make venv install-dev check-env

# Start development server with hot-reload
make dev

# Run quality checks before committing
make autoflake isort black pre-commit
make doctest test htmlcov flake8 pylint verify
```

## Development Setup

### Prerequisites

- **Python 3.11+** (3.10 minimum)
- **uv** (recommended) or pip/virtualenv
- **Make** for automation
- **Docker/Podman** (optional, for container development)
- **Node.js 18+** (for UI development and MCP Inspector)
- **PostgreSQL/MySQL** (optional, for production database testing)

### Environment Setup

#### Using uv (Recommended)

```bash
# Install uv
curl -LsSf https://astral.sh/uv/install.sh | sh

# Create virtual environment and install dependencies
make venv install-dev

# Verify environment
make check-env
```

#### Traditional Setup

```bash
# Create virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install in editable mode with all extras
pip install -e ".[dev,test,docs,otel,redis]"
```

### Configuration

```bash
# Copy example configuration
cp .env.example .env

# Edit configuration
vim .env

# Key development settings
ENVIRONMENT=development          # Enables debug features
DEV_MODE=true                   # Additional development helpers
DEBUG=true                      # Verbose error messages
RELOAD=true                     # Auto-reload on code changes
LOG_LEVEL=DEBUG                 # Maximum logging verbosity
MCPGATEWAY_UI_ENABLED=true      # Enable Admin UI
MCPGATEWAY_ADMIN_API_ENABLED=true  # Enable Admin API
```

## Project Architecture

### Directory Structure

```
mcp-context-forge/
├── mcpgateway/                 # Main application package
│   ├── main.py                # FastAPI application entry
│   ├── cli.py                 # CLI commands
│   ├── config.py              # Settings management
│   ├── models.py              # SQLAlchemy models
│   ├── schemas.py             # Pydantic schemas
│   ├── admin.py               # Admin UI routes
│   ├── auth.py                # Authentication logic
│   ├── services/              # Business logic layer
│   │   ├── gateway_service.py    # Federation management
│   │   ├── server_service.py     # Virtual server composition
│   │   ├── tool_service.py       # Tool registry
│   │   ├── a2a_service.py        # Agent-to-Agent
│   │   └── export_service.py     # Bulk operations
│   ├── transports/            # Protocol implementations
│   │   ├── sse_transport.py      # Server-Sent Events
│   │   ├── websocket_transport.py # WebSocket
│   │   └── stdio_transport.py    # Standard I/O wrapper
│   ├── plugins/               # Plugin framework
│   │   ├── framework/            # Core plugin system
│   │   └── [plugin_dirs]/       # Individual plugins
│   ├── validation/            # Input validation
│   ├── utils/                 # Utility modules
│   ├── templates/             # Jinja2 templates (Admin UI)
│   └── static/                # Static assets
├── tests/                     # Test suites
│   ├── unit/                  # Unit tests
│   ├── integration/           # Integration tests
│   ├── e2e/                   # End-to-end tests
│   ├── playwright/            # UI tests
│   └── conftest.py            # Pytest fixtures
├── alembic/                   # Database migrations
├── docs/                      # Documentation
├── plugins/                   # Plugin configurations
└── mcp-servers/               # Example MCP servers
```

### Technology Stack

- **Web Framework**: FastAPI 0.115+
- **Database ORM**: SQLAlchemy 2.0+
- **Validation**: Pydantic 2.0+
- **Admin UI**: HTMX + Alpine.js
- **Testing**: Pytest + Playwright
- **Package Management**: uv (or pip)
- **Database**: SQLite (dev), PostgreSQL/MySQL (production)
- **Caching**: Redis (optional)
- **Observability**: OpenTelemetry

### Key Components

#### 1. Core Services
- **GatewayService**: Manages federation and peer discovery
- **ServerService**: Handles virtual server composition
- **ToolService**: Tool registry and invocation
- **A2AService**: Agent-to-Agent integration
- **AuthService**: JWT authentication and authorization

#### 2. Transport Layers
- **SSE Transport**: Server-Sent Events for streaming
- **WebSocket Transport**: Bidirectional real-time communication
- **HTTP Transport**: Standard JSON-RPC over HTTP
- **Stdio Wrapper**: Bridge for stdio-based MCP clients

#### 3. Plugin System
- **Hook-based**: Pre/post request/response hooks
- **Filters**: PII, deny-list, regex, resource filtering
- **Custom plugins**: Extensible framework for custom logic

## Development Workflow

### Running the Development Server

```bash
# Development server with hot-reload (port 8000)
make dev

# Production-like server (port 4444)
make serve

# With SSL/TLS
make certs serve-ssl

# Custom host/port
python3 -m mcpgateway --host 0.0.0.0 --port 8080
```

### Code Formatting and Linting

```bash
# Auto-format code (run before committing)
make autoflake isort black pre-commit

# Comprehensive linting
make flake8 bandit interrogate pylint verify

# Quick lint for changed files only
make lint-changed

# Watch mode for auto-linting
make lint-watch

# Fix common issues automatically
make lint-fix
```

### Pre-commit Workflow

```bash
# Install git hooks
make pre-commit-install

# Run pre-commit checks manually
make pre-commit

# Complete quality pipeline (recommended before commits)
make autoflake isort black pre-commit
make doctest test htmlcov smoketest
make flake8 bandit interrogate pylint verify
```

## Code Quality

### Style Guidelines

- **Python**: PEP 8 with Black formatting (line length 200)
- **Type hints**: Required for all public APIs
- **Docstrings**: Google style, required for all public functions
- **Imports**: Organized with isort (black profile)
- **Naming**:
  - Functions/variables: `snake_case`
  - Classes: `PascalCase`
  - Constants: `UPPER_SNAKE_CASE`

### Quality Tools

```bash
# Format code
make black              # Python formatter
make isort              # Import sorter
make autoflake          # Remove unused imports

# Lint code
make flake8             # Style checker
make pylint             # Advanced linting
make mypy               # Type checking
make bandit             # Security analysis

# Documentation
make interrogate        # Docstring coverage
make doctest            # Test code examples

# All checks
make verify             # Run all quality checks
```

## Database Management

### Migrations with Alembic

```bash
# Create a new migration
alembic revision --autogenerate -m "Add new feature"

# Apply migrations
alembic upgrade head

# Rollback one revision
alembic downgrade -1

# Show migration history
alembic history

# Reset database (CAUTION: destroys data)
alembic downgrade base && alembic upgrade head
```

### Database Operations

```bash
# Different database backends
DATABASE_URL=sqlite:///./dev.db make dev           # SQLite
DATABASE_URL=postgresql://localhost/mcp make dev   # PostgreSQL
DATABASE_URL=mysql+pymysql://localhost/mcp make dev # MySQL

# Database utilities
python3 -m mcpgateway.cli db upgrade    # Apply migrations
python3 -m mcpgateway.cli db reset      # Reset database
python3 -m mcpgateway.cli db seed       # Seed test data
```

## API Development

### Adding New Endpoints

```python
# mcpgateway/main.py or separate router file
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from mcpgateway.database import get_db
from mcpgateway.schemas import MySchema

router = APIRouter(prefix="/api/v1")

@router.post("/my-endpoint", response_model=MySchema)
async def my_endpoint(
    data: MySchema,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """
    Endpoint description.

    Args:
        data: Input data
        db: Database session
        current_user: Authenticated user

    Returns:
        MySchema: Response data
    """
    # Implementation
    return result

# Register router in main.py
app.include_router(router, tags=["my-feature"])
```

### Schema Validation

```python
# mcpgateway/schemas.py
from pydantic import BaseModel, Field, validator

class MySchema(BaseModel):
    """Schema for my feature."""

    name: str = Field(..., min_length=1, max_length=255)
    value: int = Field(..., gt=0, le=100)

    @validator('name')
    def validate_name(cls, v):
        """Custom validation logic."""
        if not v.isalnum():
            raise ValueError('Name must be alphanumeric')
        return v

    class Config:
        """Pydantic config."""
        str_strip_whitespace = True
        use_enum_values = True
```

### Testing APIs

```python
# tests/integration/test_my_endpoint.py
import pytest
from fastapi.testclient import TestClient

def test_my_endpoint(test_client: TestClient, auth_headers):
    """Test my endpoint."""
    response = test_client.post(
        "/api/v1/my-endpoint",
        json={"name": "test", "value": 50},
        headers=auth_headers
    )
    assert response.status_code == 200
    assert response.json()["name"] == "test"
```

## Plugin Development

### Creating a Plugin

```yaml
# plugins/my_plugin/plugin-manifest.yaml
name: my_plugin
version: 1.0.0
description: Custom plugin for X functionality
enabled: true
hooks:
  - type: pre_request
    handler: my_plugin.hooks:pre_request_hook
  - type: post_response
    handler: my_plugin.hooks:post_response_hook
config:
  setting1: value1
  setting2: value2
```

```python
# plugins/my_plugin/hooks.py
from typing import Dict, Any
import logging

logger = logging.getLogger(__name__)

async def pre_request_hook(request: Dict[str, Any], config: Dict[str, Any]) -> Dict[str, Any]:
    """Process request before handling."""
    logger.info(f"Pre-request hook: {request.get('method')}")
    # Modify request if needed
    return request

async def post_response_hook(response: Dict[str, Any], config: Dict[str, Any]) -> Dict[str, Any]:
    """Process response before sending."""
    logger.info(f"Post-response hook: {response.get('result')}")
    # Modify response if needed
    return response
```

### Registering Plugins

```yaml
# plugins/config.yaml
plugins:
  - path: plugins/my_plugin
    enabled: true
    config:
      custom_setting: value
```

```bash
# Enable plugin system
export PLUGINS_ENABLED=true
export PLUGIN_CONFIG_FILE=plugins/config.yaml

# Test plugin
make dev
```

## Testing MCP Servers

### Using MCP Inspector

```bash
# Setup environment
export MCP_GATEWAY_BASE_URL=http://localhost:4444
export MCP_SERVER_URL=http://localhost:4444/servers/UUID/mcp
export MCP_AUTH="Bearer $(python3 -m mcpgateway.utils.create_jwt_token --username admin --exp 0 --secret my-test-key)"

# Launch Inspector with SSE (direct)
npx @modelcontextprotocol/inspector

# Launch with stdio wrapper
npx @modelcontextprotocol/inspector python3 -m mcpgateway.wrapper

# Open browser to http://localhost:5173
# Add server: http://localhost:4444/servers/UUID/sse
# Add header: Authorization: Bearer <token>
```

### Using mcpgateway.translate

```bash
# Expose stdio server over HTTP/SSE
python3 -m mcpgateway.translate \
    --stdio "uvx mcp-server-git" \
    --expose-sse \
    --port 9000

# Test with curl
curl http://localhost:9000/sse

# Register with gateway
curl -X POST http://localhost:4444/gateways \
    -H "Authorization: Bearer $TOKEN" \
    -H "Content-Type: application/json" \
    -d '{"name":"git_server","url":"http://localhost:9000/sse"}'
```

### Using SuperGateway Bridge

```bash
# Install and run SuperGateway
npm install -g supergateway
npx supergateway --stdio "uvx mcp-server-git"

# Register with MCP Gateway
curl -X POST http://localhost:4444/gateways \
    -H "Authorization: Bearer $TOKEN" \
    -H "Content-Type: application/json" \
    -d '{"name":"supergateway","url":"http://localhost:8000/sse"}'
```

## Debugging

### Debug Mode

```bash
# Enable debug mode
export DEBUG=true
export LOG_LEVEL=DEBUG
export DEV_MODE=true

# Run with debugger
python3 -m debugpy --listen 5678 --wait-for-client -m mcpgateway

# Or use IDE debugger with launch.json (VS Code)
```

### VS Code Configuration

```json
// .vscode/launch.json
{
    "version": "0.2.0",
    "configurations": [
        {
            "name": "Debug MCP Gateway",
            "type": "python",
            "request": "launch",
            "module": "mcpgateway",
            "args": ["--host", "0.0.0.0", "--port", "8000"],
            "env": {
                "DEBUG": "true",
                "LOG_LEVEL": "DEBUG",
                "ENVIRONMENT": "development"
            },
            "console": "integratedTerminal"
        }
    ]
}
```

### Logging

```python
# Add debug logging in code
import logging
logger = logging.getLogger(__name__)

def my_function():
    logger.debug(f"Debug info: {variable}")
    logger.info("Operation started")
    logger.warning("Potential issue")
    logger.error("Error occurred", exc_info=True)
```

```bash
# View logs
tail -f mcpgateway.log          # If LOG_TO_FILE=true
journalctl -u mcpgateway -f     # Systemd service
docker logs -f mcpgateway        # Docker container
```

### Request Tracing

```bash
# Enable OpenTelemetry tracing
export OTEL_ENABLE_OBSERVABILITY=true
export OTEL_TRACES_EXPORTER=console  # Or otlp, jaeger

# Run with tracing
make dev

# View traces in console or tracing backend
```

### Database Debugging

```bash
# Enable SQL echo
export DATABASE_ECHO=true

# Query database directly
sqlite3 mcp.db "SELECT * FROM tools LIMIT 10;"
psql mcp -c "SELECT * FROM servers;"

# Database profiling
python3 -m mcpgateway.utils.db_profiler
```

## Performance Optimization

### Profiling

```python
# Profile code execution
import cProfile
import pstats

def profile_function():
    profiler = cProfile.Profile()
    profiler.enable()

    # Code to profile
    expensive_operation()

    profiler.disable()
    stats = pstats.Stats(profiler)
    stats.sort_stats('cumulative')
    stats.print_stats(10)
```

### Caching Strategies

```python
# Use Redis caching
from mcpgateway.cache import cache_get, cache_set

async def get_expensive_data(key: str):
    # Try cache first
    cached = await cache_get(f"data:{key}")
    if cached:
        return cached

    # Compute if not cached
    result = expensive_computation()
    await cache_set(f"data:{key}", result, ttl=3600)
    return result
```

### Database Optimization

```python
# Use eager loading to avoid N+1 queries
from sqlalchemy.orm import joinedload

def get_servers_with_tools(db: Session):
    return db.query(Server)\
        .options(joinedload(Server.tools))\
        .all()

# Use bulk operations
def bulk_insert_tools(db: Session, tools: List[Dict]):
    db.bulk_insert_mappings(Tool, tools)
    db.commit()
```

### Async Best Practices

```python
# Use async/await properly
import asyncio
from typing import List

async def process_items(items: List[str]):
    # Process concurrently
    tasks = [process_item(item) for item in items]
    results = await asyncio.gather(*tasks)
    return results

# Use connection pooling
from aiohttp import ClientSession

async def make_requests():
    async with ClientSession() as session:
        # Reuse session for multiple requests
        async with session.get(url1) as resp1:
            data1 = await resp1.json()
        async with session.get(url2) as resp2:
            data2 = await resp2.json()
```

## Contributing

### Development Process

1. **Fork and clone** the repository
2. **Create a feature branch**: `git checkout -b feature/my-feature`
3. **Set up environment**: `make venv install-dev`
4. **Make changes** and write tests
5. **Run quality checks**: `make verify`
6. **Commit with sign-off**: `git commit -s -m "feat: add new feature"`
7. **Push and create PR**: `git push origin feature/my-feature`

### Commit Guidelines

Follow [Conventional Commits](https://www.conventionalcommits.org/):

- `feat:` New feature
- `fix:` Bug fix
- `docs:` Documentation changes
- `style:` Code style changes (formatting, etc.)
- `refactor:` Code refactoring
- `test:` Test additions or changes
- `chore:` Build process or auxiliary tool changes

### Code Review Process

1. **Self-review** your changes
2. **Run all tests**: `make test`
3. **Update documentation** if needed
4. **Ensure CI passes**
5. **Address review feedback**
6. **Squash commits** if requested

### Getting Help

- **Documentation**: [docs/](docs/)
- **Issues**: [GitHub Issues](https://github.com/IBM/mcp-context-forge/issues)
- **Discussions**: [GitHub Discussions](https://github.com/IBM/mcp-context-forge/discussions)
- **Contributing Guide**: [CONTRIBUTING.md](CONTRIBUTING.md)

## Advanced Topics

### Multi-tenancy Development

```python
# Implement tenant isolation
from mcpgateway.auth import get_current_tenant

@router.get("/tenant-data")
async def get_tenant_data(
    tenant = Depends(get_current_tenant),
    db: Session = Depends(get_db)
):
    # Filter by tenant
    return db.query(Model).filter(Model.tenant_id == tenant.id).all()
```

### Custom Transport Implementation

```python
# mcpgateway/transports/custom_transport.py
from mcpgateway.transports.base import BaseTransport

class CustomTransport(BaseTransport):
    """Custom transport implementation."""

    async def connect(self, url: str):
        """Establish connection."""
        # Implementation

    async def send(self, message: dict):
        """Send message."""
        # Implementation

    async def receive(self) -> dict:
        """Receive message."""
        # Implementation
```

### Federation Development

```python
# Test federation locally
# Start multiple instances
PORT=4444 make dev  # Instance 1
PORT=4445 make dev  # Instance 2

# Register peers
curl -X POST http://localhost:4444/gateways \
    -H "Authorization: Bearer $TOKEN" \
    -d '{"name":"peer2","url":"http://localhost:4445/sse"}'
```

## Security Considerations

### Authentication Testing

```bash
# Generate test tokens
python3 -m mcpgateway.utils.create_jwt_token \
    --username test@example.com \
    --exp 60 \
    --secret test-key

# Test with different auth methods
curl -H "Authorization: Bearer $TOKEN" http://localhost:4444/api/test
curl -u admin:changeme http://localhost:4444/api/test
```

### Security Scanning

```bash
# Static analysis
make bandit

# Dependency scanning
make security-scan

# OWASP checks
pip install safety
safety check
```

## Troubleshooting

### Common Issues

1. **Import errors**: Ensure package installed with `pip install -e .`
2. **Database locked**: Use PostgreSQL for concurrent access
3. **Port in use**: Change with `PORT=8001 make dev`
4. **Missing dependencies**: Run `make install-dev`
5. **Permission errors**: Check file permissions and user context

### Debug Commands

```bash
# Check environment
make check-env

# Verify installation
python3 -c "import mcpgateway; print(mcpgateway.__version__)"

# Test configuration
python3 -m mcpgateway.config

# Database status
alembic current

# Clear caches
redis-cli FLUSHDB
```

## Resources

- [MCP Specification](https://modelcontextprotocol.io/)
- [FastAPI Documentation](https://fastapi.tiangolo.com/)
- [SQLAlchemy Documentation](https://docs.sqlalchemy.org/)
- [Pydantic Documentation](https://docs.pydantic.dev/)
- [HTMX Documentation](https://htmx.org/)
- [Alpine.js Documentation](https://alpinejs.dev/)
