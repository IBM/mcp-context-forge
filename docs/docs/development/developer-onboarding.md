# ✅ Developer Onboarding Checklist

> Follow this checklist to set up your development environment, verify all features, and ensure consistent onboarding across the MCP Gateway project.

---

## 🛠 Environment Setup

???+ check "System prerequisites"

    - [ ] Python ≥ 3.11
    - [ ] Node.js and npm, npx (used for testing with `supergateway` and the HTML/JS Admin UI)
    - [ ] Docker, Docker Compose, and Podman
    - [ ] Make, GitHub CLI (`gh`), `curl`, `jq`, `openssl`
    - [ ] Optional: Visual Studio Code + Dev Containers extension (or WSL2 if on Windows) + Pyrefly
    - [ ] Optional: On Windows, install the WSL and Remote Development extensions

???+ check "Python tooling"

    - [ ] `pip install --upgrade pip`
    - [ ] `uv` and `uvx` installed - [install uv](https://github.com/astral-sh/uv)
    - [ ] `.venv` recreated with `make install-dev` (installs runtime + dev extras)

???+ check "Additional tools"

    - [ ] `helm` installed for Kubernetes deployments ([Helm install docs](https://helm.sh/docs/intro/install/))
    - [ ] Security tools in `$PATH`: `hadolint`, `dockle`, `trivy`, `osv-scanner`

???+ check "Useful VS Code extensions"

    - [ ] Python, Pylance
    - [ ] YAML, Even Better TOML
    - [ ] Docker, Dev Containers (useful on Windows)

???+ check "GitHub setup"

    - [ ] GitHub email configured in `git config`
    - [ ] See [GitHub config guide](./github.md#16-personal-git-configuration-recommended)

???+ check ".env configuration"

    - [ ] Copy `.env.example` to `.env`
    - [ ] Set various env variables, such as:
        - `JWT_SECRET_KEY`
        - `BASIC_AUTH_PASSWORD`
---

## 🔧 Makefile Targets

???+ check "Local setup"

    - [ ] `make check-env` (validates .env is complete)
    - [ ] `make install-dev serve`
    - [ ] `make smoketest` runs and passes

???+ check "Container builds"

    - [ ] Docker: `make docker-prod docker-run-ssl-host compose-up`
    - [ ] Podman: `make podman podman-prod podman-run-ssl-host`

???+ check "Packaging"

    - [ ] `make dist verify` builds packages
    - [ ] `make devpi-install devpi-init devpi-start devpi-setup-user devpi-upload devpi-test`
    - [ ] Install and test `mcpgateway` CLI locally

???+ check "Minikube & Helm"

    - [ ] `make helm-install minikube-install minikube-start minikube-k8s-apply helm-package helm-deploy`
    - [ ] See [minikube deployment](../deployment/minikube.md)

---

## 🧪 Testing

???+ check "Code quality"

    - [ ] `make lint`, `make lint-web`
    - [ ] `make shell-linters-install`, `make shell-lint`
    - [ ] `make hadolint` (Dockerfile linting)

???+ check "Python unit tests"

    - [ ] `make test` passes all cases
    - [ ] `make coverage` generates coverage report

???+ check "UI automation (Playwright)"

    - [ ] `playwright install` (one-time browser setup)
    - [ ] `pytest tests/playwright/` passes
    - [ ] `pytest tests/playwright/ -k admin` validates Admin UI flows

???+ check "Load testing (Locust)"

    - [ ] `locust -f tests/locust/locustfile.py --host=http://localhost:4444`
    - [ ] Access dashboard at http://localhost:8089
    - [ ] Verify no errors under moderate load (50-100 users)

???+ check "Frontend linting"

    - [ ] `make eslint` - JavaScript linting
    - [ ] `make lint-web` - ESLint + HTMLHint + Stylelint
    - [ ] `make format-web` - Prettier formatting
    - [ ] Note: JS unit tests not yet implemented

---

## 🔐 Security

???+ check "Vulnerability scans"

    - [ ] Run:
        ```bash
        make hadolint dockle osv-scan trivy pip-audit
        ```

???+ check "SonarQube analysis"

    - [ ] `make sonar-up-docker`
    - [ ] `make sonar-submit-docker` - ensure no critical violations

---

## 🔑 JWT Authentication

???+ check "Generate and use a Bearer token"

    - [ ] Export a token with:
        ```bash
        export MCPGATEWAY_BEARER_TOKEN=$(python3 -m mcpgateway.utils.create_jwt_token --username admin@example.com --exp 0 --secret my-test-key)
        ```

    - [ ] Verify authenticated API access:
        ```bash
        curl -k -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN" https://localhost:4444/version | jq
        ```

---

## 🤖 Client Integration

???+ check "Run wrapper and test transports"

    - [ ] Run: `python3 -m mcpgateway.wrapper` (stdio support)
    - [ ] Test transports:
        - Streamable HTTP
        - Server-Sent Events (SSE)
    - [ ] Optional: Integrate with Claude, Copilot, Continue ([usage guide](../using/index.md))

---

## 🧭 API Testing

???+ check "Authentication required"

    - [ ] Unauthenticated:
        ```bash
        curl http://localhost:4444/tools
        # -> should return 401 Unauthorized
        ```
    - [ ] Authenticated:
        ```bash
        curl -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN" http://localhost:4444/version | jq
        ```

???+ check "Endpoint coverage"

    - [ ] Confirm key routes:
        - `/version`
        - `/health`
        - `/tools`
        - `/servers`
        - `/resources`
        - `/prompts`
        - `/gateways`
    - [ ] Browse [Redoc docs](http://localhost:4444/redoc)

---

## 🖥 Admin UI

???+ check "Login and diagnostics"

    - [ ] Navigate to [`/admin`](http://localhost:4444/admin)
    - [ ] Log in with Basic Auth credentials from `.env`
    - [ ] `/version` shows healthy DB and Redis

???+ check "CRUD verification"

    - [ ] Create / edit / delete:
        - Servers
        - Tools
        - Resources
        - Prompts
        - Gateways
    - [ ] Toggle active/inactive switches
    - [ ] JWT stored in `HttpOnly` cookie, no errors in DevTools Console

???+ check "Metrics"

    - [ ] Confirm latency and error rate display under load

---

## 📚 Documentation

???+ check "Build and inspect docs"

    - [ ] `cd docs && make venv serve`
    - [ ] Open http://localhost:8000
    - [ ] Confirm:
        - `.pages` ordering
        - nav structure
        - working images
        - Mermaid diagrams

???+ check "Read and understand"

    - [ ] `README.md` in root
    - [ ] [Official docs site](https://ibm.github.io/mcp-context-forge/)
    - [ ] [MkDocs Admonitions guide](https://squidfunk.github.io/mkdocs-material/reference/admonitions/)

---

## ✅ Final Review

???+ check "Ready to contribute"

    - [ ] All items checked
    - [ ] PR description links to this checklist
    - [ ] Stuck? Open a [discussion](https://github.com/your-repo/discussions) or issue
