# AGENTS.md

Guidelines for AI coding assistants working with this repository.

For domain-specific guidance, see subdirectory AGENTS.md files:
- `tests/AGENTS.md` - Testing conventions and workflows
- `plugins/AGENTS.md` - Plugin framework and development
- `charts/AGENTS.md` - Helm chart operations
- `docs/AGENTS.md` - Documentation authoring
- `mcp-servers/AGENTS.md` - MCP server implementation
- `crates/mcp_runtime/DEVELOPING.md` - Rust MCP runtime development workflows, command matrix, and validation

**Note:** The `llms/` directory holds LLM guidance of two kinds: end-user runtime guidance for using ContextForge, and work prompts for agents changing this repository. Where `llms/` guidance overlaps an `AGENTS.md` file, the `AGENTS.md` file is authoritative.

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
├── plugins/                # Plugin integration (uses cpex external package)
└── alembic/                # Database migrations

tests/                      # Test suite (see tests/AGENTS.md)
plugins/                    # Plugin implementations (see plugins/AGENTS.md)
plugins_rust/               # Rust plugin implementations for performance-sensitive paths
charts/                     # Helm charts (see charts/AGENTS.md)
docs/                       # Architecture and usage documentation (see docs/AGENTS.md)
a2a-agents/                 # A2A agent implementations (used for testing/examples)
mcp-servers/                # MCP server templates (see mcp-servers/AGENTS.md)
crates/                     # Direct Rust crate folders (runtime)
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
make pre-commit

# Before committing, use ty, mypy and pyrefly to check just the new files, then run:
make ruff bandit interrogate pylint verify

# Before committing Rust changes (crates/mcp_runtime/):
# Run fmt-check, clippy -D warnings, and cargo test for Rust crates
cd crates/mcp_runtime && cargo fmt --check && cargo clippy -- -D warnings && cargo test
```

## PR Review

A review is a set of findings the author can act on. Verify scope before writing findings: cross-reference the PR description against linked issues (`gh pr view`, `gh issue view`). Partial coverage of an issue is acceptable when the PR says so; unstated gaps and scope drift are findings.

### Finding Format

One line per finding:

```text
severity | path:line | problem | fix
```

Add an indented paragraph under a finding only when one line cannot carry it. Delivery channel (file, agent toolkit, `gh pr review`) is per-PR; confirm before posting externally.

### Severity

| Severity | Meaning | Disposition |
|----------|---------|-------------|
| blocking | Meets a blocking criterion with evidence in the diff or linked artifacts | Merge gate; no waiver |
| functionally-impacting | Affects behavior or maintainability, below the blocking bar | Fix before merge unless the PR documents a waiver |
| suggestion | A better way exists; optional | May be deferred |
| minor | Polish | May be deferred |

### Blocking Criteria

A finding is blocking if and only if it meets one of these criteria with evidence in the diff or linked artifacts. If there is no evidence, it is not blocking:

1. Correctness bug in changed code, reachable in real use (includes data loss).
2. Security regression, or a security-sensitive change without deny-path regression tests (unauthenticated, wrong team, insufficient permission, feature disabled).
3. Violates a documented Security Invariant or design decision (see *Authentication & RBAC Overview*; *Synchronous SQLAlchemy in Async Handlers*).
4. Breaks a consumer contract unflagged: HTTP API, environment variables or their defaults, database schema, Helm values, MCP/A2A wire behavior.
5. Adds or changes a model without a matching Alembic migration.
6. The PR does not deliver what it claims.

When severity stays ambiguous after investigation, mark the finding blocking and name the missing evidence. The next pass resolves it.

Not blocking: style and naming (Ruff owns these), the sync-SQLAlchemy-in-async pattern, doc polish, test-count aesthetics.

### Tone

Courteous by structure, direct by sentence. Lead with what works. State severity so the author knows what must change. Write as a respectful senior colleague: direct about problems, never harsh, never hedged. Prose follows *Agent Prose*.

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
- **Token creation defaults to the creator's personal team**: `POST /tokens` (and admin-delegated creation) with no `team_id` no longer mints a `teams: null` (public-only) token for non-admin callers. `TokenCatalogService.get_default_team_id()` resolves the caller's (or, for admin delegation, the target's) personal team and `routers/tokens.py::create_token` uses it when the caller belongs to that team; it falls back to single-team inheritance, then to `team_id=None` plus a `TokenCreateResponse.warnings` entry only when neither applies (no personal team and multiple/zero teams). Un-narrowed admins are exempt — `team_id=None` for them is a deliberate global-scope token. The permission-containment check (`_get_caller_permissions`) still uses the *requested* `team_id`, not the defaulted one, so this does not raise the ceiling on what `scope.permissions` a caller may request. Separately, `derive_token_team_id()` in `mcpgateway/auth.py` — the function that turns a single-team token's claim into `request.state.team_id` for RBAC/rate-limit/routing context — excludes personal teams, since a personal team auto-grants `team_admin`; a personal-team-scoped token instead falls through to `check_any_team`, matching how `PermissionService._get_user_roles` already treats personal teams.
- **Session tokens**: Admin bypass is determined by the DB `is_admin` flag, not the JWT `teams` claim. Non-admin sessions can be narrowed via JWT `teams`. `resolve_session_teams()` in `mcpgateway/auth.py` is the single policy point.
- **Layer 1 only**: Token scoping controls visibility (what you can see). RBAC (Layer 2) is evaluated independently — session-token narrowing does not restrict which team roles are checked for permissions.
- **External IdP tokens**: identities provisioned from trusted external SSO providers (see `SSO_API_TOKEN_AUTH_ENABLED`) are dispatched through the session-token table above (`resolve_session_teams()`), not the API/legacy table — `is_admin`/`teams` come from the persisted local user record, never from the external token's claims.

### Implementation Helpers

Layer-1 derivation is centralized in `mcpgateway/auth_context.py`. Route handlers must call these rather than re-deriving the rule inline:

- `get_scoped_resource_access_context(request, user)` → `(user_email, token_teams)` — the visibility scope to pass into service fetch/list/read calls. Admin bypass is signalled by `token_teams=None` while `user_email` is **kept**, so the service can still owner-match the admin's own private rows. Public-only is `(email, [])`.
- `get_request_identity(request, user)` → `(user_email, is_admin)` — the requester's own identity, for audit capture and header masking. Use when you need the identity independent of the visibility scope.
- `get_rpc_filter_context(request, user)` → `(user_email, token_teams, is_admin)` — the raw pre-rule triple. Reserved for the few sites that genuinely need `is_admin` or the un-normalized teams (auth-context forwarding, run-ownership capture, tool-execution authorization); these carry a `Layer-1 exception` comment naming the reason.

The derived triple is memoized on `request.state` per principal, so calling the scope and identity helpers together costs one derivation rather than two.

### Security Invariants (Required)

- Treat `public` as platform-public scope, not internet-anonymous scope.
- Explicit exception: when `MCP_REQUIRE_AUTH=false`, unauthenticated `/mcp` requests are allowed with public-only visibility — **unless** the target virtual server has `oauth_enabled=True`, in which case unauthenticated requests are rejected with 401 regardless of the global setting.
- Keep the two-layer model on every path:
  - Layer 1: token scoping controls what a caller can see.
  - Layer 2: RBAC controls what a caller can do.
- Do not re-implement token team interpretation logic; use `normalize_token_teams()` for API/legacy tokens and `resolve_session_teams()` for session tokens (both in `mcpgateway/auth.py`).
- Do not re-implement Layer 1 token scope semantics; use `token_scope_grants()` in `mcpgateway/middleware/rbac.py`, the single policy point shared by the RBAC decorators and `TokenScopingMiddleware`. Empty token scopes mean "inherit from RBAC at runtime" (what `TokenCatalogService._generate_token()` emits for tokens created without an explicit scope) and must never be treated as deny-all; `*` grants everything and `<category>.*` grants that category.
- Do not accept inbound client auth tokens via URL query parameters.
- Legacy `INSECURE_ALLOW_QUERYPARAM_AUTH` is interop-only for outbound peer auth and must remain opt-in and host-restricted.
- High-risk transports must be feature-flagged and disabled by default.
- Transport/session endpoints must authenticate before session establishment (or message forwarding) and enforce RBAC before processing actions.
- Token-scoped route authorization must be default-deny for unmapped protected paths.
- Never trust client-provided ownership fields (`owner_email`, `team_id`, session owner); derive authorization from authenticated identity and server-side state.
- Security-sensitive changes must include deny-path regression tests (unauthenticated, wrong team, insufficient permissions, feature disabled).
- A `token-exchange` OAuth grant (RFC 8693 / On-Behalf-Of) exists for gateways; with it, the user's inbound JWT is exchanged with a trusted Authorization Server and **never forwarded upstream** — only the exchanged token is sent to the downstream MCP server.
- `token_url` on a `token-exchange` gateway is an SSRF / egress boundary: the user's ContextForge JWT is POSTed to it as the `subject_token`, it is validated at config time, and creating or modifying token-exchange gateways is a privileged action.
- Audit token-exchange operations via the structured logging sink with a `correlation_id`; never log raw subject tokens or exchanged tokens.

#### UAID Cross-Gateway Security

- UAID cross-gateway routing requires explicit domain allowlist (fail-closed default)
- Empty `UAID_ALLOWED_DOMAINS` blocks all cross-gateway routing unless `UAID_ALLOW_ALL_DOMAINS=true`
- Cross-gateway calls forward bearer tokens for RBAC enforcement on remote gateways
- Both gateways must trust the same JWT issuer (shared `JWT_SECRET_KEY` or federated SSO)
- `UAID_ALLOW_ALL_DOMAINS=true` is unsafe for production (bypasses allowlist validation)
- Startup validation logs ERROR if A2A enabled but allowlist not configured
- Remote gateway 401/403 responses raise `A2AAgentError` with troubleshooting guidance

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
### User Identity Extraction

**Canonical Email Precedence**: All user-email extraction helpers use a consistent **email-over-sub** precedence order to ensure forensic accuracy across visibility checks and audit logs:

- When a user dict contains both `email` and `sub` keys, `email` takes precedence
- The canonical implementation is `get_user_email()` in `mcpgateway/auth_context.py`
- All other helpers (including `admin.get_user_email`) re-export or delegate to this canonical implementation
- This ensures that the identity used for RBAC evaluation matches the identity logged in audit trails

**Rationale**: The `email` field is the human-readable identifier used throughout AGENTS.md and user-facing documentation. Consistent precedence prevents forensic confusion where an incident review pivots on a logged email that differs from the principal actually evaluated by RBAC.


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

## Audit Trail Transaction Behavior

**Issue #2871 - Separate Session Pattern**

`AuditTrailService.log_action()` (`mcpgateway/services/audit_trail_service.py`) always opens its own `SessionLocal()` when no `db` is supplied, and closes/rolls back that session itself. Callers in `tool_service.py`, `resource_service.py`, `gateway_service.py`, `prompt_service.py`, `server_service.py`, and `admin.py` must **never** pass `db=db` (the caller's request-scoped session) to `log_action()`. In `admin.py`, plugin-view audit logging goes through `log_audit()`, which is a thin wrapper over `log_action()` and inherits the same optional-session behavior.

Passing the shared session caused **"This transaction is inactive"** errors: the main CRUD operation already calls `db.commit()` before the audit call, and reusing that same session for a second commit after it has already committed leaves the session in a state that breaks rollback on subsequent errors.

- `log_action()` swallows its own exceptions internally and returns `None` on failure — it does not propagate them to the caller in production.
- The main resource (tool/gateway/resource/prompt/server) is committed **before** `log_action()` runs, so an audit-logging failure never rolls back already-persisted data — but callers' generic `except Exception` handlers still call `db.rollback()` and surface an error to the API caller even though the underlying row was already committed.
- Do not add `db: Session` back to a `log_action()` call site. If a service needs the audit entry guaranteed within the same transaction as the main write, that is a deliberate design change requiring review, not a default.

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
AUTH_ENCRYPTION_SECRET=             # REQUIRED: generate with: make init-secrets-patch-env

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

## ContextForge Web UI (Experimental)

A BFF-style frontend for the gateway API, separate from the built-in Admin UI (`MCPGATEWAY_UI_ENABLED`). Source and docs: https://github.com/contextforge-org/contextforge-web-ui

- Runs as `web_ui` + a dedicated `web_ui_redis` session store in `docker-compose.yml`.
- Enabled via `--profile experimental` (or `--profile testing`, which pulls it in too).
- `web_ui` depends on `gateway` and `web_ui_redis` being healthy before it starts.

```bash
# Start the gateway plus the web UI
docker compose --profile experimental up -d

# Access
open http://localhost:${WEB_UI_PORT:-3001}
```

Configuration (see the commented `WEB_UI_*` block in `.env.example`):

| Variable | Default | Purpose |
|----------|---------|---------|
| `WEB_UI_IMAGE` | `ghcr.io/contextforge-org/contextforge-web-ui:latest` | Image to pull |
| `WEB_UI_PORT` | `3001` | Host **and** container port (the image reads `PORT` at startup, so both sides of the mapping stay in sync) |
| `WEB_UI_HOST` | `0.0.0.0` | Bind address inside the container — must stay `0.0.0.0` in Docker |
| `WEB_UI_CONTEXTFORGE_URL` | `http://gateway:4444` | Gateway API base URL the UI talks to (internal compose network) |
| `WEB_UI_COOKIE_SECURE` | `false` | Set `true` once the UI is served over HTTPS |
| `WEB_UI_REDIS_URL` | `redis://web_ui_redis:6379/0` | Session store, separate from the gateway's cache `redis` service |

Refer to the [contextforge-web-ui repo](https://github.com/contextforge-org/contextforge-web-ui) for feature docs, auth flow details, and upstream configuration options beyond what's wired into this compose file.

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

- **Python >= 3.12** with type hints; strict mypy
- **Formatting**: Ruff (line length 200)
- **Linting**: Ruff (`E3`,`E4`,`E7`,`E9`,`F`,`D1`), Pylint per `pyproject.toml`
- **Naming**: `snake_case` functions/modules, `PascalCase` classes, `UPPER_CASE` constants
- **Imports**: Group per isort sections (stdlib, third-party, first-party `mcpgateway`, local)
- **Readability**: *Clean Code* — implement per [`docs/docs/development/coding-standards.md`](docs/docs/development/coding-standards.md)

### Code Comments

- Comments are a last resort. Make the code self-documenting first: extract a function or rename a thing until the comment becomes redundant.
- A comment earns its place only when code cannot express a durable constraint: security rationale, upstream workaround, dependency-pin reason.
- Comments never carry transient implementation process or decisions. Decisions go to an ADR (`docs/docs/architecture/adr/`), process to the commit body, tasks to an issue.
- Docstrings are API contract, not comments: Ruff `D1`/`D417` and interrogate enforce presence and parameter coverage; summary line first, then the contract.
- Fix a comment in the same change that fixes its code.

## Agent Prose (ASD-STE100)

All agent-authored prose follows the ASD-STE100 writing rules. The controlled dictionary is not enforced; domain, protocol, and code terms count as technical names.

- One instruction per sentence: 20 words or fewer for instructions, 25 for description.
- Active voice, present tense. Imperative for instructions: "Add a test", never "a test should be added".
- One word, one meaning: a token stays a token, never also a credential or a key.
- Positive constructions. No hedging ("worth considering"), no idioms.
- Technical names verbatim: `normalize_token_teams()`, `DB_POOL_SIZE`, `QueuePool limit exceeded`.

Covers code comments and docstrings, commit bodies, PR descriptions, review findings, issue bodies and comments, CHANGELOG entries. Exempt: identifiers, log and error strings, `docs/` prose, ephemeral working notes.

Full rules and worked examples per artifact: [`docs/docs/development/agent-prose.md`](docs/docs/development/agent-prose.md).

## Commit & PR Standards

- **Sign commits**: `git commit -s` (DCO requirement). Preserve sign-off on rewritten commits (rebases, conflict resolutions).
- **Conventional Commits**: `feat:`, `fix:`, `docs:`, `refactor:`, `chore:`. Subjects keep that format; bodies follow *Agent Prose*.
- **Link issues**: `Closes #123`
- Include tests for behavior changes.
- Every PR whose behavior can be exercised through a live gateway must include a full black-box test against a running gateway; see [`tests/live_gateway/`](tests/live_gateway/) for examples.
- Green lint and tests before PR.
- Don't push until asked.

### Pre-Merge Validation Gate

Run from the worktree root, in order. Each command must pass, or the PR must document a waiver, before the PR is ready:

| Command | Validates |
|---------|-----------|
| `make ruff interrogate pylint` | Lint, docstring coverage, deeper static analysis |
| `make test` | Full pytest suite |
| `make coverage diff-cover` | Coverage of changed lines vs. base |
| `make docker-nuke docker-prod-rust testing-up RUST_MCP_MODE=` | Rebuilds and launches the production-style gateway stack |
| `make test-mcp-protocol-e2e test-mcp-rbac` | MCP protocol E2E and RBAC against the live gateway |
| `make detect-secrets-scan` | No new secrets in files changed vs `main`; exits non-zero on live/unaudited findings (jq merge preserves out-of-scope audited entries; remediate with `make detect-secrets-audit`) |

Distinct from the per-edit hygiene chain in *Essential Commands → Code Quality* (`make autoflake isort black pre-commit`, then `make ruff bandit interrogate pylint verify`): hygiene runs continuously; this gate runs once before declaring a PR ready.

### Secret Detection (detect-secrets)

When `detect-secrets` identifies false positives:

- **Python files**: suppress inline with `# pragma: allowlist secret` so they don't appear in `.secrets.baseline` after `make detect-secrets-scan`.
  - Exception: doctest strings where the comment breaks the assertion. Rely on `.secrets.baseline` and audit with `make detect-secrets-audit`.
- **All other file types**: regenerate the baseline with `make detect-secrets-scan`.
- **Merge conflicts**: resolve `.secrets.baseline` using the version from `main`.

## GitHub Issues

- Start from the matching template in `.github/ISSUE_TEMPLATE/`; the template's fields define the body.
- Title style includes a type prefix: `[BUG]: ...`, `[FEATURE]: ...`, `[DOCS]: ...`, `[TESTING]: ...`, `[CHORE]: ...`. Epics: `[EPIC][SCOPE]: ...`.
- Label baseline: one primary type label (`bug`, `enhancement`, `documentation`, `testing`, `chore`) plus `triage` on new issues. Add 1-3 optional scope labels (`security`, `performance`, `ui`, `api`, `python`, `devops`, `a2a`, `mcp-protocol`); epics add `epic`.
- Bodies and comments follow *Agent Prose*. For public tone, see *PR Review → Tone*.

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
- Dev-group tools installed in the venv: `pytest`, `mypy`, `bandit`, `pre-commit`, etc. (see `pyproject.toml` `[dependency-groups]`)
- Formatters and linters (`ruff`, `vulture`, `interrogate`, `radon`, `yamllint`, `tomlcheck`) are pinned in the `Makefile` and invoked on demand via `uv tool run`; always prefer the Makefile targets (`make black`, `make ruff`, etc.) over calling the underlying tools directly
