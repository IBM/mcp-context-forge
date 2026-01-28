MCP Gateway: Full Project Overview

- Purpose: One-stop guidance for LLMs to develop, run, test, document, and deploy the MCP Context Forge gateway.
- Tech: FastAPI + Pydantic + SQLAlchemy; optional Redis; Alembic migrations; hybrid plugin framework (native + external MCP).

**Core Capabilities**
- Unified gateway for MCP servers: tools, prompts, and resources via HTTP/SSE/WebSocket/STDIO/streamable HTTP.
- Plugin framework: AI safety, content filtering, policy enforcement, and transformations with pre/post hooks (42 built-in plugins).
- Federation and administration: register servers, list tools/prompts/resources, manage teams/tokens, admin UI.
- Agent-to-Agent (A2A) communication between MCP agents.
- LLM proxying and chat interface with integrated tools/resources.
- RBAC (Role-Based Access Control) with team and permission management.
- Comprehensive observability: OpenTelemetry, Prometheus metrics, structured logging.

**Project Structure**
- App: `mcpgateway/` (FastAPI entrypoints, db.py ORM models, 50+ services, 19 routers, 15 middleware, transports, plugins framework, alembic migrations)
- Plugins: `plugins/` (42 built-in native plugins and external plugin example)
- MCP Servers: `mcp-servers/` (5 Go servers, 20 Python servers, scaffolding templates)
- Docs: `docs/` (MkDocs site + docs Makefile)
- Charts: `charts/` (Helm chart `mcp-stack`)
- Tests: `tests/{unit,integration,e2e,performance,security,fuzz,playwright}`
- Infrastructure: `infra/` (PostgreSQL, Redis, monitoring Docker Compose)
- Deployment: `deployment/` (k8s, knative, terraform, ansible)

**Environment & Setup**
- Requirements: Python 3.11+, GNU Make
- Create venv and install dev deps:
  - `make venv`
  - `make install-dev`
- Copy env and set secrets:
  - `cp .env.example .env`
  - Set `JWT_SECRET_KEY`, optional Redis/DB settings
- Optional helpers:
  - JWT: `python -m mcpgateway.utils.create_jwt_token --username admin@example.com --exp 10080 --secret KEY`
  - Expose stdio server through wrapper: `python -m mcpgateway.translate --stdio "uvx mcp-server-git" --port 9000`

**Run the Gateway**
- Dev (reload, :8000): `make dev`
- Prod (Gunicorn, :4444): `make serve`
- Prod with TLS (self-signed certs in ./certs):
  - `make certs`
  - `make serve-ssl`
- CLI entry:
  - `mcpgateway --host 0.0.0.0 --port 4444`

**Configuration**
- Copy `.env.example` → `.env`; verify with `make check-env`.
- Plugin config path via `PLUGIN_CONFIG_FILE=plugins/config.yaml`.
- Enable plugin framework: `PLUGINS_ENABLED=true` in `.env`.
- Prefer environment variables for security-sensitive settings.

**Plugins (Overview)**
- Architecture: hybrid model supports native (in‑process) Python plugins and external MCP servers; unified hook interface.
- Hooks (production): `prompt_pre_fetch`, `prompt_post_fetch`, `tool_pre_invoke`, `tool_post_invoke`, `resource_pre_fetch`, `resource_post_fetch`.
- Configuration: `plugins/config.yaml` with `plugins`, `plugin_dirs`, `plugin_settings`.
- Modes: `enforce | enforce_ignore_error | permissive | disabled`; priority ascending.
- Built‑ins: Argument Normalizer, PII filter, regex search/replace, denylist, resource filter; OPA external example.
  - Default ordering (lower runs first): Argument Normalizer (40) → PII Filter (50) → Resource Filter (75) → Deny/Regex (100+/150). This ensures inputs are stabilized before detection/redaction.
- Authoring helpers:
  - Bootstrap templates: `mcpplugins bootstrap --destination <dir> --type native|external`
  - External runtime default: Streamable HTTP at `http://localhost:8000/mcp`
- See also: `llms/plugins-llms.md` (deep-dive + testing patterns)

**API Usage**
- Auth: HTTP Bearer (JWT). Generate token and send `Authorization: Bearer <token>`.
- Core endpoints (auth): `/servers`, `/tools`, `/prompts`, `/resources`, `/rpc`, `/sse`.
- JSON‑RPC 2.0 tool invocation via `POST /rpc`.
- Health: `/health`, Readiness: `/ready`.
- See: `llms/api.md` for curl examples and parameter details.

**Testing & Quality**
- Quick runs:
  - Unit tests: `make test`
  - Doctest + test: `make doctest test`
  - Coverage (md/HTML/XML/badge/annotated): `make coverage`; HTML at `docs/docs/coverage/index.html`
  - HTML coverage only: `make htmlcov`
- Selective pytest: `pytest -k "fragment"`, `pytest -m "not slow"`
- Lint & static analysis:
  - Format & hooks: `make autoflake isort black pre-commit`
  - Static: `make pylint flake8`, full lint: `make lint`
  - Security/docs QA (as configured): `make bandit interrogate verify check-manifest`
- PR readiness (recommended):
  - `make doctest test htmlcov smoketest lint-web flake8 bandit interrogate pylint verify`
- Structure & conventions:
  - Tests in `tests/{unit,integration,e2e,playwright}`; mark `slow|ui|api|smoke|e2e` to keep defaults fast.
  - Prefer editing existing test files; target coverage gaps first.
- See: `llms/testing.md` for a coverage-first workflow and tips.

**Documentation (MkDocs)**
- Location: `docs/` (content in `docs/docs/` only)
- First-time setup: `cd docs && make venv`
- Live preview: `make serve` → http://127.0.0.1:8000 (hot reload)
- Build site: `make build` (exports combined HTML/Docx to `docs/site/out/`)
- Deploy (GitHub Pages): `make deploy`
- Authoring tips: use `.pages` per folder to define nav; images under `docs/docs/images/`.
- See: `llms/mkdocs.md` for full details.

**Kubernetes (Helm)**
- Chart: `charts/mcp-stack` (gateway + Postgres + Redis; optional UIs)
- Common tasks (from chart dir):
  - Lint/validate: `make validate-all`
  - Template/dry-run: `make test-template` / `make test-dry-run`
  - Install/upgrade: `make install` / `make upgrade`
  - Package/push: `make package` / `make push`
- Dev overrides via `my-values.yaml`.
- See: `llms/helm.md` for workflows and examples.

**Security**
- Secrets: never commit; set via `.env` or Kubernetes `Secret`.
- Auth: set `JWT_SECRET_KEY`; emit bearer tokens with the token utility for API calls.
- TLS: generate with `make certs` and run `make serve-ssl`.
- Plugins: external URLs validated; STDIO scripts must be `.py`. Timeouts and payload size guards in plugin executor.

**Makefile Reference (root)**
- Dev/prod: `make dev`, `make serve`, `make serve-ssl`, `make certs`
- Quality: `make lint`, `make lint-web`, `make check-manifest`
- Tests: `make test`, `make doctest`, `make htmlcov`, `make coverage`
- Clean: `make clean` (caches, build artefacts, venv, coverage, docs, certs)

**Contributing**
- Conventional Commits; sign off (`git commit -s`); link issues.
- Include tests/docs for behavior changes. Keep code typed (Py ≥ 3.11), formatted, and lint‑clean.
- Do not mention competitive assistants in PRs; avoid effort estimates.
