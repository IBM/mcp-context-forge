# AGENTS.md

Guidelines for AI coding assistants working with this repository.

For domain-specific guidance, see subdirectory AGENTS.md files:
- `tests/AGENTS.md` - Testing conventions and workflows
- `plugins/AGENTS.md` - Plugin framework and development
- `charts/AGENTS.md` - Helm chart operations
- `docs/AGENTS.md` - Documentation authoring

**Note:** The `llms/` directory holds LLM guidance of two kinds: end-user runtime guidance for using ContextForge, and work prompts for agents changing this repository. Where `llms/` guidance overlaps an `AGENTS.md` file, the `AGENTS.md` file is authoritative.

## Skills

Task-specific guidance lives in `.agents/skills/`. `.bob/skills` links to that directory. Load the matching skill before you start the task:

- `asd-ste100`: write or rewrite prose for humans (review findings, issue and PR text, commit bodies) in ASD-STE100 style.
- `pr-review`: write review findings, assign severity, judge blocking criteria.
- `alembic-migrations`: add or change a database model, column, or migration.
- `observability-audit-sessions`: change trace, span, metric, or audit writes.
- `secret-detection`: resolve a `detect-secrets` finding or `.secrets.baseline` change.
- `github-issues`: create, label, or triage an issue.
- `contextforge-web-ui`: run or configure the `web_ui` compose service.
- `mcp-helpers`: generate a JWT or register an MCP server locally.

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
charts/                     # Helm charts (see charts/AGENTS.md)
docs/                       # Architecture and usage documentation (see docs/AGENTS.md)
a2a-agents/                 # A2A agent implementations (used for testing/examples)
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
- Explicit exception: when `MCP_REQUIRE_AUTH` is `false`, unauthenticated `/mcp` requests are allowed with public-only visibility — **unless** the target virtual server has `oauth_enabled` set to `True`, in which case unauthenticated requests are rejected with 401 regardless of the global setting.
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
| `developer` | team | CRUD on gateways, servers, tools, resources, prompts, and A2A agents; execution/invocation; token self-service; dashboard access; team read/join |
| `viewer` | team | tools.read/execute, resources.read |

The `developer` role includes gateway registration, update, and deletion.
See the [complete built-in permission table](docs/docs/manage/rbac.md#built-in-rbac-roles) before assigning this role.

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

**Two accessors**: `get_user_email()` in `mcpgateway/auth_context.py` is the e-mail-attribute accessor. `get_user_id()` in the same module is the identity accessor. Phase 1 populates both with the same value. Audit (`AuditTrail.user_id`) and observability (`ObservabilityTrace.user_email`) identity fields hold the canonical user_id from `get_user_id()`; the column names stay unchanged for compatibility. Routers compute `get_user_id(user)` and pass it to services as the `user_id` keyword; services keep `user_email` for ownership checks.


## Separate-Session Writes

Observability and audit writes use sessions separate from the request transaction. Never pass `db=db` to `AuditTrailService.log_action()` or `log_audit()`. Load the `observability-audit-sessions` skill before you change either write path.


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
BASIC_AUTH_PASSWORD=changeme        # pragma: allowlist secret
AUTH_REQUIRED=true                   # Set false ONLY for development
AUTH_ENCRYPTION_SECRET=             # REQUIRED: generate with: make init-secrets-patch-env  # pragma: allowlist secret

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

## Technology Stack

- **FastAPI** with **Pydantic** validation and **SQLAlchemy** ORM (Starlette ASGI)
- **HTMX + Alpine.js** for admin UI
- **SQLite** default, **PostgreSQL** support, **Redis** for caching/federation
- **Alembic** for migrations

### Synchronous SQLAlchemy in Async Handlers (Design Decision)

The codebase deliberately uses synchronous SQLAlchemy sessions (e.g. `SessionLocal().begin()`) inside async FastAPI handlers and ASGI middleware, relying on FastAPI's event-loop management to handle blocking operations. Do not flag this as a bug or attempt to convert individual call sites to async without a broader migration plan. This design decision may be revisited in the future alongside a potential migration to async database drivers.

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

Apply the `asd-ste100` skill (STE-flavored mode) to rewrite prose. Full rules and worked examples per artifact: [`docs/docs/development/agent-prose.md`](docs/docs/development/agent-prose.md).

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
| `make test` | Full rstest suite |
| `make coverage diff-cover` | Coverage of changed lines vs. base |
| `make docker-nuke docker-prod testing-up` | Rebuilds and launches the production-style gateway stack |
| `make test-e2e` | MCP protocol E2E and RBAC against the live gateway |
| `make detect-secrets-scan` | No new secrets in files changed vs `main`; exits non-zero on live/unaudited findings (jq merge preserves out-of-scope audited entries; remediate with `make detect-secrets-audit`) |

Distinct from the per-edit hygiene chain in *Essential Commands → Code Quality* (`make autoflake isort black pre-commit`, then `make ruff bandit interrogate pylint verify`): hygiene runs continuously; this gate runs once before declaring a PR ready.

## Maintenance Guardrails (Brief)

- Source of truth precedence: `mcpgateway/config.py` and runtime code > `Makefile` targets/dependencies > `.env.example` (dev overrides) > docs/comments.
- When auditing repo state, prioritize active source directories and ignore transient/workbench content unless explicitly requested: `todo/`, `tmp/`, `artifacts/`, `logs/`, `coverage/`.
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
- Dev-group tools installed in the venv: `rstest`, `pytest`, `mypy`, `bandit`, `pre-commit`, etc. (see `pyproject.toml` `[dependency-groups]`)
- Formatters and linters (`ruff`, `vulture`, `interrogate`, `radon`, `yamllint`, `tomlcheck`) are pinned in the `Makefile` and invoked on demand via `uv tool run`; always prefer the Makefile targets (`make black`, `make ruff`, etc.) over calling the underlying tools directly
