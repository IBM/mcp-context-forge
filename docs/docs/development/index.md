# Development

Welcome! This guide is for developers contributing to MCP Gateway. Whether you're fixing bugs, adding features, or extending federation or protocol support, this doc will help you get up and running quickly and consistently.

---

## 🧰 What You'll Find Here

| Page                                                                              | Description                                                                    |
| --------------------------------------------------------------------------------- | ------------------------------------------------------------------------------ |
| [Building Locally](building.md)                                                   | How to install dependencies, set up a virtual environment, and run the gateway |
| [Packaging](packaging.md)                                                         | How to build a release, container image, or prebuilt binary                    |
| [Database Performance](db-performance.md)                                         | N+1 query detection, query logging, and database optimization                  |
| [Doctest Coverage](doctest-coverage.md)                                           | Comprehensive doctest coverage implementation and guidelines                    |
| [DEVELOPING.md](https://github.com/IBM/mcp-context-forge/blob/main/DEVELOPING.md) | Coding standards, commit conventions, and review workflow                      |

---

## 🛠 Developer Environment

MCP Gateway is built with:

* **Python 3.11+**
* **FastAPI** + **SQLAlchemy (async)** + **Pydantic Settings**
* **HTMX**, **Alpine.js**, **TailwindCSS** for the Admin UI

Development tools:

* Linters: `ruff`, `mypy`, `black`, `isort`
* Testing: `pytest`, `httpx`
* Serving: `uvicorn`, `gunicorn`

Frontend tools (Admin UI):

* Linters: ESLint, Stylelint, HTMLHint, Biome
* Formatting: Prettier
* Security: Retire.js (vulnerability scanning)

Code style and consistency is enforced via:

```bash
make lint          # runs ruff, mypy, black, isort
make lint-web      # runs ESLint, HTMLHint, Stylelint
make pre-commit    # runs pre-commit hooks on staged files
```

As well as GitHub Actions code scanning.

---

## 🧪 Testing

Test coverage includes:

* Unit tests under `tests/unit/`
* Integration tests under `tests/integration/`
* End-to-end tests under `tests/e2e/`
* UI automation under `tests/playwright/` (Playwright)
* Load testing under `tests/locust/` (Locust)
* Example payload performance testing under `tests/hey/`

Use:

```bash
make test                        # run full suite
pytest tests/unit/               # run only unit tests
pytest tests/e2e/                # run end-to-end scenarios
pytest tests/playwright/         # run UI automation tests
locust -f tests/locust/locustfile.py --host=http://localhost:4444  # load testing
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

Admin UI and API are protected by Basic Auth or JWT.

To generate a JWT token:

```bash
export MCPGATEWAY_BEARER_TOKEN=$(python3 -m mcpgateway.utils.create_jwt_token --username admin@example.com --exp 0 --secret my-test-key)
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

Edit `.env` or set environment variables. A complete list is documented in the [README](https://github.com/IBM/mcp-context-forge#configuration-env-or-env-vars).

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
