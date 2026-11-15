# Development

Welcome! This guide is for developers contributing to ContextForge. Whether you're fixing bugs, adding features, or extending federation or protocol support, this doc will help you get up and running quickly and consistently.

---

## 🧰 What You'll Find Here

| Page                                                                              | Description                                                                    |
| --------------------------------------------------------------------------------- | ------------------------------------------------------------------------------ |
| [Building Locally](building.md)                                                   | How to install dependencies, set up a virtual environment, and run the gateway |
| [Developer Workstation](developer-workstation.md)                                 | Local workstation setup, troubleshooting, and Keycloak SSO development login   |
| [Packaging](packaging.md)                                                         | How to build a release, container image, or prebuilt binary                    |
| [Database Performance](db-performance.md)                                         | N+1 query detection, query logging, and database optimization                  |
| [Doctest Coverage](doctest-coverage.md)                                           | Comprehensive doctest coverage implementation and guidelines                    |
| [Coding Standards](coding-standards.md)                                           | Clean Code rules for readable, self-documenting Python and TypeScript         |
| [Agent Prose Standard](agent-prose.md)                                            | ASD-STE100 prose rules for code comments, commits, PRs, reviews, and issues    |
| [DEVELOPING.md](https://github.com/IBM/mcp-context-forge/blob/main/DEVELOPING.md) | Development setup, project architecture, workflow, and debugging              |

---

## 🛠 Developer Environment

ContextForge is built with:

* **Python 3.12+**
* **FastAPI** + **SQLAlchemy (async)** + **Pydantic Settings**
* **HTMX**, **Alpine.js**, **TailwindCSS** for the Admin UI

Development tools:

* Linters: `ruff`, `mypy`
* Testing: `rstest` with pytest fixtures, `httpx`
* Serving: `uvicorn`, `gunicorn`

Frontend tools (Admin UI):

* Linters: ESLint, HTMLHint, Biome
* Formatting: Prettier
* Security: Retire.js (vulnerability scanning)

Code style and consistency is enforced via:

```bash
make lint          # runs ruff, mypy
make lint-web      # runs ESLint, HTMLHint, Biome (CSS)
make pre-commit    # runs pre-commit hooks on staged files
```

As well as GitHub Actions code scanning.

---

## 🧪 Testing

Test coverage includes:

* Unit tests under `tests/unit/`
* Integration tests under `tests/integration/`
* End-to-end tests under `tests/e2e/` (in-process FastAPI) and `tests/live_gateway/` (live infrastructure: MCP / SSO)
* UI automation under `tests/playwright/` (Playwright)
* Load testing under `tests/loadtest/` (Locust)
* Example payload performance testing under `tests/hey/`

Use:

```bash
make test                        # run full suite (in-process; no live services required)
rstest tests/unit/               # run only unit tests
rstest tests/e2e/                # run in-process end-to-end scenarios
make test-live-gateway           # run live-gateway tests (mcp + sso)
rstest tests/playwright/         # run UI automation tests
locust -f tests/loadtest/locustfile.py --host=http://localhost:4444  # load testing
```

Note: JavaScript unit tests are not yet implemented; frontend testing relies on Playwright for UI automation.

### Database Performance Testing

```bash
make dev-query-log         # start server with query logging
make query-log-tail        # watch query log in real-time
make query-log-analyze     # analyze logs for N+1 patterns
make test-db-perf          # run N+1 detection tests
```

See [Database Performance](db-performance.md) for details.

---

## 🔍 Linting and Hooks

CI will fail your PR if code does not pass lint checks.

You should manually run:

```bash
make lint
make pre-commit
```

Enable hooks with:

```bash
pre-commit install
```

---

## 🐳 Containers

Build and run with Podman or Docker:

```bash
make podman            # build production image
make podman-run-ssl    # run with self-signed TLS at https://localhost:4444
```

---

## 🔐 Authentication

Admin UI uses email/password authentication (`PLATFORM_ADMIN_EMAIL`/`PASSWORD`). API endpoints require JWT tokens (Basic Auth is disabled by default).

To generate a JWT token:

```bash
export MCPGATEWAY_BEARER_TOKEN=$(python3 -m mcpgateway.utils.create_jwt_token --username admin@example.com --exp 10080 --secret my-test-key-but-now-longer-than-32-bytes)
echo $MCPGATEWAY_BEARER_TOKEN
```

Then test:

```bash
curl -sX GET \
  -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN" \
  http://localhost:4444/tools | jq
```

---

## 📦 Configuration

Edit `.env` or set environment variables. A complete list is documented in the [Configuration Reference](../manage/configuration.md).

Use:

```bash
cp .env.example .env
```

Key configs include:

| Variable            | Purpose                      |
| ------------------- | ---------------------------- |
| `DATABASE_URL`      | Database connection          |
| `JWT_SECRET_KEY`    | Signing key for JWTs         |
| `DEV_MODE=true`     | Enables relaxed development defaults (set together with `RELOAD=true` if you rely on `run.sh`) |
| `CACHE_TYPE=memory` | Options: memory, redis, none |

---

## 🚧 Contribution Tips

* Pick a [`good first issue`](https://github.com/IBM/mcp-context-forge/issues?q=is%3Aissue+label%3A%22good+first+issue%22+is%3Aopen)
* Read the [`CONTRIBUTING.md`](https://github.com/IBM/mcp-context-forge/blob/main/CONTRIBUTING.md)
* Fork, branch, commit with purpose
* Submit PRs against `main` with clear titles and linked issues

---

## ✅ CI/CD

GitHub Actions enforce:

* CodeQL security scanning
* Pre-commit linting
* Dependency audits
* Docker image builds

CI configs live in `.github/workflows/`.

---

## Experimental MCP Events providers

`MCPGATEWAY_MCP_EVENTS_ENABLED=false` keeps application Events disabled by default.
Enable it only with a trusted provider registered for an exact virtual server.
Authorized callers discover `capabilities.events` through `initialize` or `server/discover`.
The same authenticated MCP endpoint handles `events/list`, `events/subscribe`, and `events/unsubscribe`.

The gateway checks token permission limits, current RBAC, virtual-server visibility, and provider authorization.
Assign the explicit `events.read`, `events.subscribe`, and `events.unsubscribe` permissions through normal role governance.
Existing role records are unchanged. Wildcard permissions retain their existing semantics.

Register providers through the trusted application lifespan on every worker:

```python
from contextlib import asynccontextmanager
from mcpgateway.services.mcp_events import event_provider


def attach_event_owner(app, server_id, owner):
    original_lifespan = app.router.lifespan_context

    @asynccontextmanager
    async def lifespan(application):
        with event_provider(server_id, owner):
            async with original_lifespan(application):
                yield

    app.router.lifespan_context = lifespan
```

The owner implements the `EventProvider` protocol in `mcpgateway/services/mcp_events.py`:

- `authorize(context, method)` checks current application rights before discovery or a method call.
- `request(context, method, params)` validates event names and arguments under the original caller's authority.
- `context.server_id`, `context.user`, and `context.headers` come from native transport authentication.
- Application input and `_meta` never establish identity or replace the original caller with a privileged service identity.

The application owner supplies durable subscriptions, protected signing-secret custody, callback verification,
expiration, rotation, revocation, and delivery receipts. Recheck current rights before a subscription commit and every delivery.
Validate public HTTPS destinations at connection time, preserve TLS hostname verification, and reject redirects.
Keep subscription parameters and bearer tokens out of provider logs and stored identity snapshots.
The gateway omits Events parameters from detailed request logs and returns sanitized provider errors.

This dispatch path supports the webhook-based draft documented in
[OpenAI MCP Events](https://developers.openai.com/plugins/build/mcp-events).
Application owners define replay behavior and return `cursor: null` when replay is unsupported.
Only register providers whose callback and subscription lifecycle satisfy that contract.

The native black-box journey uses the full gateway, synthetic accounts, and a private temporary SQLite database:

```bash
pytest -o addopts='' tests/live_gateway/mcp/test_mcp_events.py
```

Its synthetic owner qualifies protocol dispatch and gateway authorization.
Production acceptance additionally requires the real application owner's durable lifecycle and client processing evidence.
