# Development

Welcome! This guide is for developers contributing to MCP Gateway. Whether you're fixing bugs, adding features, or extending federation or protocol support, this doc will help you get up and running quickly and consistently.

---

## 🧰 What You'll Find Here

| Page                                                                              | Description                                                                    |
| --------------------------------------------------------------------------------- | ------------------------------------------------------------------------------ |
| [Building Locally](building.md)                                                   | How to install dependencies, set up a virtual environment, and run the gateway |
| [Packaging](packaging.md)                                                         | How to build a release, container image, or prebuilt binary                    |
| [DEVELOPING.md](https://github.com/IBM/mcp-context-forge/blob/main/DEVELOPING.md) | Coding standards, commit conventions, and review workflow                      |

---

## 🛠 Developer Environment

MCP Gateway is built with:

* **Python 3.10+**
* **FastAPI** + **SQLAlchemy (async)** + **Pydantic Settings**
* **HTMX**, **Alpine.js**, **TailwindCSS** for the Admin UI

Development tools:

* Linters: `ruff`, `mypy`, `black`, `isort`
* Testing: `pytest`, `httpx`
* Serving: `uvicorn`, `gunicorn`

Code style and consistency is enforced via:

```bash
make lint          # runs ruff, mypy, black, isort
make pre-commit    # runs pre-commit hooks on staged files
```

As well as GitHub Actions code scanning.

---

## 🧪 Testing

Test coverage includes:

* Unit tests under `tests/unit/`
* Integration tests under `tests/integration/`
* End-to-end tests under `tests/e2e/`
* Example payload performance testing under `tests/hey/`

Use:

```bash
make test          # run all tests
make test-unit     # run only unit tests
make test-e2e      # run end-to-end
```

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

To generate a JWT:

```bash
python -m mcpgateway.utils.create_jwt_token \
  -u admin \
  -e 10080 | tee token.txt

export MCPGATEWAY_BEARER_TOKEN=$(cat token.txt)
```

Then test:

```bash
curl -k -sX GET \
  -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN" \
  https://localhost:4444/tools | jq
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
| `DEV_MODE=true`     | Enables hot reload and debug |
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

Let me know if you'd like a shorter version or want to customize for internal team handoff.
