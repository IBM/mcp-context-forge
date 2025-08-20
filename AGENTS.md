# Repository Guidelines

## Project Structure & Module Organization
- `mcpgateway/`: FastAPI gateway source (entry `main.py`, `cli.py`, services, transports, templates/static, Alembic).
- Services: `mcpgateway/services/` (gateway, server, tool, resource, prompt logic).
- Transports: `mcpgateway/transports/` (SSE, WebSocket, stdio, streamable HTTP).
- Plugins: `plugins/` (`framework/`, plugin configs in `plugins/config.yaml`).
- Plugins: `plugins/` (built-in filters and utilities like `pii_filter/`, `deny_filter/`, `regex_filter/`, `resource_filter/`; main configuration in `plugins/config.yaml`).
- Tests: `tests/unit`, `tests/integration`, `tests/e2e`, `tests/playwright`.
- Docs & ops: `docs/`, `deployment/`, `charts/`, `examples/`. Build artefacts: `build/`, `dist/`.

## Build, Test, and Development Commands
- Pre-commit: `make autoflake isort black pre-commit`
- Setup: `make venv`, `make install-dev`.
- Run: `make dev` (hot reload on :8000), `make serve` (gunicorn), or `mcpgateway --host 0.0.0.0 --port 4444`.
- Quality: `make lint`, `make lint-web`, `make check-manifest`.
- Tests: `make test`, `make doctest`, `make htmlcov` (HTML to `docs/docs/coverage/index.html`).
- Final check: `make doctest test htmlcov smoketest lint-web flake8 bandit interrogate pylint verify`

## Makefile Quick Reference
- `make dev`: Run fast-reload dev server on `:8000`.
- `make serve`: Run production Gunicorn server on `:4444`.
- `make certs`: Generate self-signed TLS certs in `./certs/`.
- `make serve-ssl`: Run Gunicorn behind HTTPS on `:4444` (uses `./certs`).
- `make lint`: Run full lint suite; `make install-web-linters` once before `make lint-web`.
- `make test`: Run unit tests; `make coverage` writes HTML to `docs/docs/coverage/`.
- `make doctest`: Run doctests across `mcpgateway/` modules.
- `make check-env`: Verify `.env` keys match `.env.example`.
- `make clean`: Remove caches, build artefacts, venv, coverage, docs, certs.

MCP helpers
- JWT token: `python -m mcpgateway.utils.create_jwt_token --username admin --exp 10080 --secret KEY`.
- Expose stdio server: `python -m mcpgateway.translate --stdio "uvx mcp-server-git" --port 9000`.

## Coding Style & Naming Conventions
- Python >= 3.11. Type hints required; strict `mypy` settings.
- Formatters/linters: Black (line length 200), isort (profile=black), Ruff (F,E,W,B,ASYNC), Pylint as configured in `pyproject.toml` and dotfiles.
- Naming: `snake_case` for modules/functions, `PascalCase` for classes, `UPPER_CASE` for constants.
- Group imports per isort sections (stdlib, third-party, first-party `mcpgateway`, local).

## Testing Guidelines
- Pytest with async; discovery configured in `pyproject.toml`.
- Layout: unit (`tests/unit`), integration (`tests/integration`), e2e (`tests/e2e`), UI (`tests/playwright`).
- Naming: files `test_*.py`, classes `Test*`, functions `test_*`; marks: `slow`, `ui`, `api`, `smoke`, `e2e`.
- Commands: `make test`, `pytest -k "name"`, `pytest -m "not slow"`. Use `make coverage` for reports.
- Keep tests deterministic, isolated, and fast by default.

## Commit & Pull Request Guidelines
- Conventional Commits (`feat:`, `fix:`, `docs:`, `refactor:`, `chore:`). Link issues (e.g., `Closes #123`).
- Sign every commit with DCO: `git commit -s`.
- Do not mention Claude or Claude Code in PRs/diffs. Do not include effort estimates or "phases".
- Include tests and docs for behavior changes; attach screenshots for UI changes when relevant.
- Require green lint and tests locally before opening a PR.

## Architecture Overview
- Core: FastAPI + Pydantic with SQLAlchemy. Architectural decisions live under `docs/docs/architecture/adr/`.
- Data: SQLite by default; PostgreSQL via extras. Migrations managed with Alembic in `mcpgateway/alembic/`.
- Caching & Federation: Optional Redis, mDNS/Zeroconf discovery, peer registration, health checks and failover.
- Virtual Servers: Compose tools, prompts, and resources across multiple MCP servers; control tool visibility per server.
- Transports: SSE, WebSocket, stdio wrapper, and streamable HTTP endpoints.

## Security & Configuration Tips
- Copy `.env.example` → `.env`; verify with `make check-env`. Never commit secrets.
- Auth: set `JWT_SECRET_KEY`; export `MCPGATEWAY_BEARER_TOKEN` using the token utility for API calls.
- Wrapper: set `MCP_SERVER_URL` and `MCP_AUTH` when using `mcpgateway.wrapper`.
- TLS: `make certs` → `make serve-ssl`. Prefer environment variables for config; see `README.md`.
