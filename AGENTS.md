# AGENTS.md

Guidelines for AI coding assistants working with this repository.

For domain-specific guidance, see subdirectory AGENTS.md files:
- `tests/AGENTS.md` - Testing conventions and workflows
- `plugins/AGENTS.md` - Plugin framework and development
- `charts/AGENTS.md` - Helm chart operations
- `docs/AGENTS.md` - Documentation authoring
- `mcp-servers/AGENTS.md` - MCP server implementation
- `crates/mcp_runtime/DEVELOPING.md` - Rust MCP runtime development workflows, command matrix, and validation

**Note:** The `llms/` directory contains guidance for LLMs *using* ContextForge solution (end-user runtime guidance), not for code agents working on this codebase.

## Project Overview

ContextForge is an open source registry and proxy that federates MCP, A2A, and REST/gRPC APIs with centralized governance, discovery, and observability. It federates tools, agents, and APIs, optimizes agent and tool calling, and supports plugins, auth/RBAC, rate-limiting, virtual servers, multi-transport protocols, and an optional Admin UI.

## Project Structure

```
mcpgateway/                 # Core FastAPI application
├── main.py                 # Application entry point
├── config.py               # Environment configuration
├── db.py                   # SQLAlchemy ORM models and session management
├── schemas.py              # Pydantic validation schemas
├── services/               # Business logic layer (50+ services)
├── routers/                # HTTP endpoint definitions (19 routers)
├── middleware/             # Cross-cutting concerns (16 middleware)
├── transports/             # Protocol implementations (SSE, WebSocket, stdio, streamable HTTP)
├── plugins/                # Plugin framework infrastructure
└── alembic/                # Database migrations

tests/                      # Test suite (see tests/AGENTS.md)
plugins/                    # Plugin implementations (see plugins/AGENTS.md)
plugin_templates/           # Starter templates for building new plugins
charts/                     # Helm charts (see charts/AGENTS.md)
docs/                       # Architecture and usage documentation (see docs/AGENTS.md)
a2a-agents/                 # A2A agent implementations (used for testing/examples)
mcp-servers/                # MCP server templates (see mcp-servers/AGENTS.md)
crates/                     # Direct Rust crate folders (runtime and wrapper)
llms/                       # End-user LLM guidance (not for code agents)
```

## Essential Commands

### Setup
```bash
cp .env.example .env && make install-dev check-env    # Complete setup
make venv                          # Create virtual environment with uv
make install-dev                   # Install with dev dependencies (includes build-ui)
make check-env                     # Verify .env against .env.example
make build-ui                      # Rebuild Admin UI JS bundle (requires npm)
```

### Development
```bash
make dev                          # Dev server on :8000 with autoreload
make serve                        # Production gunicorn on :4444
make serve-ssl                    # HTTPS on :4444 (creates certs if needed)
```

### Code Quality
```bash
# After writing code
make autoflake isort black pre-commit

# Before committing, use ty, mypy and pyrefly to check just the new files, then run:
make ruff bandit interrogate pylint verify

# Before committing Rust changes (tools_rust/):
# Run fmt-check, clippy -D warnings, and cargo test for Rust crates
cd tools_rust/mcp_runtime && cargo fmt --check && cargo clippy -- -D warnings && cargo test
```

## Authentication & RBAC Overview

ContextForge implements a **two-layer security model**:

1. **Token Scoping (Layer 1)**: Controls what resources a user CAN SEE (data filtering)
2. **RBAC (Layer 2)**: Controls what actions a user CAN DO (permission checks)

### Token Scoping Quick Reference

**API / legacy tokens** — JWT `teams` claim is the sole authority (`normalize_token_teams()`):

| JWT `teams` State | `is_admin: true` | `is_admin: false` |
|-------------------|------------------|-------------------|
| Key MISSING | PUBLIC-ONLY `[]` | PUBLIC-ONLY `[]` |
| `teams: null` | ADMIN BYPASS | PUBLIC-ONLY `[]` |
| `teams: []` | PUBLIC-ONLY `[]` | PUBLIC-ONLY `[]` |
| `teams: ["t1"]` | Team + Public | Team + Public |

**Session tokens** (`token_use: "session"`) — DB is the authority; JWT `teams` only narrows (`resolve_session_teams()`):

| JWT `teams` State | DB admin? | Result | Access Level |
|-------------------|-----------|--------|--------------|
| any | yes | `None` | ADMIN BYPASS (DB authority) |
| Missing/null/`[]` | no | DB teams | Full DB membership |
| `["t1"]` | no | intersection | Narrowed to overlap |
| `["revoked"]` | no | `[]` | Public-only (fail-closed) |

**Key behaviors:**

- **API/legacy tokens**: Missing `teams` key = public-only access (secure default). Admin bypass requires BOTH `teams: null` AND `is_admin: true`. `normalize_token_teams()` in `mcpgateway/auth.py` is the single source of truth.
- **Session tokens**: Admin bypass is determined by the DB `is_admin` flag, not the JWT `teams` claim. Non-admin sessions can be narrowed via JWT `teams`. `resolve_session_teams()` in `mcpgateway/auth.py` is the single policy point.
- **Layer 1 only**: Token scoping controls visibility (what you can see). RBAC (Layer 2) is evaluated independently — session-token narrowing does not restrict which team roles are checked for permissions.

### Security Invariants (Required)

- Treat `public` as platform-public scope, not internet-anonymous scope.
- Explicit exception: when `MCP_REQUIRE_AUTH=false`, unauthenticated `/mcp` requests are allowed with public-only visibility — **unless** the target virtual server has `oauth_enabled=True`, in which case unauthenticated requests are rejected with 401 regardless of the global setting.
- Keep the two-layer model on every path:
  - Layer 1: token scoping controls what a caller can see.
  - Layer 2: RBAC controls what a caller can do.
- Do not re-implement token team interpretation logic; use `normalize_token_teams()` for API/legacy tokens and `resolve_session_teams()` for session tokens (both in `mcpgateway/auth.py`).
- Do not accept inbound client auth tokens via URL query parameters.
- Legacy `INSECURE_ALLOW_QUERYPARAM_AUTH` is interop-only for outbound peer auth and must remain opt-in and host-restricted.
- High-risk transports must be feature-flagged and disabled by default.
- Transport/session endpoints must authenticate before session establishment (or message forwarding) and enforce RBAC before processing actions.
- Token-scoped route authorization must be default-deny for unmapped protected paths.
- Never trust client-provided ownership fields (`owner_email`, `team_id`, session owner); derive authorization from authenticated identity and server-side state.
- Security-sensitive changes must include deny-path regression tests (unauthenticated, wrong team, insufficient permissions, feature disabled).

### Built-in Roles

| Role | Scope | Key Permissions |
|------|-------|-----------------|
| `platform_admin` | global | `*` (all) |
| `team_admin` | team | teams.*, tools.read/execute, resources.read |
| `developer` | team | tools.read/execute, resources.read |
| `viewer` | team | tools.read/execute, resources.read |

### Documentation

- **Full RBAC guide**: `docs/docs/manage/rbac.md`
- **Multi-tenancy architecture**: `docs/docs/architecture/multitenancy.md`
- **OAuth token delegation**: `docs/docs/architecture/oauth-design.md`

## Observability Transaction Behavior

**Issue #3883 - Separate Session Pattern**

Observability write operations use **independent database sessions** that commit immediately (best-effort pattern). This means:

- Observability data persists even when the main request fails
- Traces may show "in progress" or partial states for failed requests
- **NOT atomic** with main request transaction (intentional trade-off)
- Provides visibility into partial failures at the cost of atomicity

### Implementation Details

**Write methods** (use independent sessions):
- `start_trace()`, `end_trace()`
- `start_span()`, `end_span()`
- `add_event()`, `record_token_usage()`, `record_metric()`, `delete_old_traces()`

**Query methods** (use request-scoped sessions):
- `get_trace()`, `get_traces()`, `get_spans()`, etc.
- These accept a `db: Session` parameter for RBAC/token scoping

**Context managers** (create single independent session for lifecycle):
- `trace_span()`, `trace_tool_invocation()`, `trace_a2a_request()`

**Pattern**: Follows existing SQL instrumentation approach in `instrumentation/sqlalchemy.py:58-87`

**Middleware**: `ObservabilityMiddleware` no longer creates `request.state.db`. Each observability operation creates its own short-lived session.

**Security**: Query operations use request-scoped sessions for RBAC/token scoping. Write operations are not RBAC-protected (observability visibility is platform-wide).

**Connection Pool Sizing**: The separate session pattern creates 4-6 independent database sessions per traced request (trace start/end, span start/end, metrics, events). Default configuration (`DB_POOL_SIZE=200`, `DB_MAX_OVERFLOW=10`) provides 210 total connections, supporting ~35 concurrent traced requests. This is adequate for typical deployments. High-traffic production systems (>50 req/sec sustained) should increase pool size via environment variables: `DB_POOL_SIZE=500`, `DB_MAX_OVERFLOW=100` to support 80+ concurrent requests. Monitor for "QueuePool limit exceeded" errors and adjust pool sizing accordingly. Note: SQLite connections are capped at 50 due to file-based limitations.

## Key Environment Variables

Defaults come from `mcpgateway/config.py`. `.env.example` intentionally overrides a few for local/dev convenience.

```bash
# Core
HOST=127.0.0.1                  # .env.example uses 0.0.0.0
PORT=4444
DATABASE_URL=sqlite:///./mcp.db   # or postgresql+psycopg://...
REDIS_URL=redis://localhost:6379/0
RELOAD=false

# Auth
JWT_SECRET_KEY=your-secret-key
BASIC_AUTH_USER=admin
BASIC_AUTH_PASSWORD=changeme
AUTH_REQUIRED=true                   # Set false ONLY for development
AUTH_ENCRYPTION_SECRET=my-test-salt  # For encrypting stored secrets

# Features
MCPGATEWAY_UI_ENABLED=false          # .env.example sets true
MCPGATEWAY_ADMIN_API_ENABLED=false   # .env.example sets true
MCPGATEWAY_A2A_ENABLED=true
PLUGINS_ENABLED=false
PLUGINS_CONFIG_FILE=plugins/config.yaml

# Logging
LOG_LEVEL=ERROR
LOG_TO_FILE=false
STRUCTURED_LOGGING_DATABASE_ENABLED=false

# Observability
OBSERVABILITY_ENABLED=false
OTEL_EXPORTER_OTLP_ENDPOINT=          # .env.example sets http://localhost:4317
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

### Synchronous SQLAlchemy in Async Handlers (Design Decision)

The codebase deliberately uses synchronous SQLAlchemy sessions (e.g. `SessionLocal().begin()`) inside async FastAPI handlers and ASGI middleware, relying on FastAPI's event-loop management to handle blocking operations. Do not flag this as a bug or attempt to convert individual call sites to async without a broader migration plan. This design decision may be revisited in the future alongside a potential migration to async database drivers.

## Alembic Database Migrations

When adding new database columns or tables, create an Alembic migration.

### Creating Migrations

```bash
# CRITICAL: Always check the current head FIRST
cd mcpgateway && alembic heads

# Generate a new migration (auto-generates from model changes)
alembic revision --autogenerate -m "add_column_to_table"

# Or create an empty migration for manual edits
alembic revision -m "add_column_to_table"
```

### Migration File Requirements

The `down_revision` MUST point to the current head. **Never guess or copy from older migrations.**

```python
# CORRECT: Points to actual current head (verified via `alembic heads`)
revision: str = "abc123def456"
down_revision: Union[str, Sequence[str], None] = "43c07ed25a24"  # Current head

# WRONG: Creates multiple heads (breaks all tests)
down_revision: Union[str, Sequence[str], None] = "some_old_revision"
```

### Idempotent Migrations Pattern

Always write idempotent migrations that check before modifying:

```python
def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())

    # Skip if table doesn't exist (fresh DB uses db.py models directly)
    if "my_table" not in inspector.get_table_names():
        return

    # Skip if column already exists
    columns = [col["name"] for col in inspector.get_columns("my_table")]
    if "new_column" in columns:
        return

    op.add_column("my_table", sa.Column("new_column", sa.String(), nullable=True))
```

### Verification

```bash
# Verify single head after creating migration
cd mcpgateway && alembic heads
# Should show only ONE head

# Run tests to confirm migrations work
make test
```

### Common Errors

- **"Multiple heads are present"**: Your `down_revision` points to wrong parent. Fix by updating to actual current head.
- **"Target database is not up to date"**: Run `alembic upgrade head` first.

### Hermetic Downgrade: Config Snapshot Pattern

Any migration whose `downgrade()` logic depends on runtime configuration (i.e., reads from
`mcpgateway.config.settings`) **must** snapshot those values into `migration_metadata` during
`upgrade()` and read them back during `downgrade()`. This makes the migration hermetic —
its behaviour is determined by database state, not the current environment.

```python
from mcpgateway.config import settings
from sqlalchemy import inspect, text

REVISION = "your_revision_id"

def upgrade() -> None:
    bind = op.get_bind()
    # ... schema changes ...

    # Snapshot any settings values used in downgrade
    if "migration_metadata" in inspect(bind).get_table_names():
        bind.execute(
            text(
                "INSERT INTO migration_metadata (revision, key, value, created_at) "
                "VALUES (:rev, :key, :val, CURRENT_TIMESTAMP) "
                "ON CONFLICT (revision, key) DO UPDATE SET value = excluded.value"
            ),
            {"rev": REVISION, "key": "some_setting", "val": settings.some_setting},
        )

def downgrade() -> None:
    bind = op.get_bind()

    # Read from snapshot; fall back to live settings only if table is absent
    # (pre-existing DB that was upgraded before this pattern was introduced)
    cfg = {}
    if "migration_metadata" in inspect(bind).get_table_names():
        rows = bind.execute(
            text("SELECT key, value FROM migration_metadata WHERE revision = :rev"),
            {"rev": REVISION},
        ).all()
        cfg = {r[0]: r[1] for r in rows}

    some_setting = cfg.get("some_setting") or settings.some_setting

    # ... use some_setting for downgrade logic ...

    # Clean up snapshot rows
    if "migration_metadata" in inspect(bind).get_table_names():
        bind.execute(
            text("DELETE FROM migration_metadata WHERE revision = :rev"),
            {"rev": REVISION},
        )
```

**Rule:** If your migration imports `settings` and uses it in `downgrade()`, you must follow this
pattern. Migrations that only use `settings` in `upgrade()` (e.g., for seeding initial data) are
exempt.

## Coding Standards

- **Python >= 3.11** with type hints; strict mypy
- **Formatting**: Black (line length 200), isort (profile=black)
- **Linting**: Ruff (`E3`,`E4`,`E7`,`E9`,`F`,`D1`), Pylint per `pyproject.toml`
- **Naming**: `snake_case` functions/modules, `PascalCase` classes, `UPPER_CASE` constants
- **Imports**: Group per isort sections (stdlib, third-party, first-party `mcpgateway`, local)

## Commit & PR Standards

- **Sign commits**: `git commit -s` (DCO requirement)
- **Conventional Commits**: `feat:`, `fix:`, `docs:`, `refactor:`, `chore:`
- **Link issues**: `Closes #123`
- Include tests for behavior changes
- Require green lint and tests before PR
- Don't push until asked, and if it's an external contributor, see todo/force-push.md first to push to the contributor's branch.

### Tone for GitHub Comments

When posting PR reviews, issue comments, or any public-facing text on GitHub, use a collaborative and constructive tone:

- Lead with what's good before raising concerns.
- Frame issues as questions or options ("worth considering", "a couple of approaches") rather than directives.
- Remember contributors are people doing their jobs — be direct about problems without being harsh.
- Categorize findings clearly (blocking, suggestions, minor notes) so the author knows what must change vs. what's optional.
- Avoid sounding algorithmic or robotic; write the way a respectful senior colleague would in a code review.

## GitHub Issues (Brief)

- Prefer issue templates in `.github/ISSUE_TEMPLATE/`: `bug-report-code.md`, `feature-request.md`, `docs-issue.md`, `testing--bug--unit--manual--or-new-test-.md`, `chore-task--devops--linting--maintenance-.md`.
- Title style should include type prefix, for example: `[BUG]: ...`, `[FEATURE]: ...`, `[DOCS]: ...`, `[TESTING]: ...`, `[CHORE]: ...`.
- Label baseline: one primary type label (`bug` or `enhancement` or `documentation` or `testing` or `chore`) plus `triage` on new issues.
- Add 1-3 optional scope labels as needed (for example `security`, `performance`, `ui`, `api`, `python`, `devops`, `a2a`, `mcp-protocol`).
- Epic title format: `[EPIC][SECURITY]: Security clearance levels plugin - Bell-LaPadula MAC implementation #1245`.
- Epic labels: `epic`, `security`, `enhancement`, `triage` (plus optional scope labels).

## Maintenance Guardrails (Brief)

- Source of truth precedence: `mcpgateway/config.py` and runtime code > `Makefile` targets/dependencies > `.env.example` (dev overrides) > docs/comments.
- When auditing repo state, prioritize active source directories and ignore transient/workbench content unless explicitly requested: `todo/`, `tmp/`, `artifacts/`, `logs/`, `coverage/`.
- Issue lifecycle labels: use `awaiting-user` when blocked on reporter feedback, `blocked` for dependency blockers, `planned` when accepted but deferred, and `fixed` only after the resolving change is merged.
- Avoid brittle numeric claims (counts of services/routers/middleware/plugins) unless you are actively validating and updating them in the same change; otherwise describe with approximate wording.

## Important Constraints

- Never mention AI assistants in PRs/diffs
- Do not include test plans or effort estimates in PRs
- Never create files unless absolutely necessary; prefer editing existing files
- Never proactively create documentation files unless explicitly requested
- Never commit secrets; use `.env` for configuration

## Key Files

- `README.md` - Canonical project overview and quick start
- `mcpgateway/main.py` - Application entry point
- `mcpgateway/config.py` - Environment configuration
- `mcpgateway/db.py` - SQLAlchemy ORM models and session management
- `mcpgateway/schemas.py` - Pydantic schemas
- `pyproject.toml` - Project configuration
- `Makefile` - Build automation
- `.env.example` - Environment template

## CLI Tools Available

- `gh` for GitHub operations
- `make` for build/test automation
- `uv` for virtual environment management and for `uv tool run` linter invocations
- Dev-group tools installed in the venv: `pytest`, `mypy`, `bandit`, `pre-commit`, `prospector`, etc. (see `pyproject.toml` `[dependency-groups]`)
- Formatters and linters (`black`, `isort`, `ruff`, `pylint`, `vulture`, `interrogate`, `radon`, `yamllint`, `tomlcheck`) are pinned in the `Makefile` and invoked on demand via `uv tool run`; always prefer the Makefile targets (`make black`, `make ruff`, `make pylint`, etc.) over calling the underlying tools directly
