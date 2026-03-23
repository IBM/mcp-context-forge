# Release Management

This document describes the complete release process for ContextForge, from pre-release preparation through tagging, publishing, and post-release housekeeping. Every step must pass before a release is tagged.

---

## 📋 Release Checklist Overview

| Phase | Steps |
|-------|-------|
| [1. Version Update](#1-version-update) | Bump version, update references, CHANGELOG, roadmap, security advisories, base images |
| [2. Python Dependency Updates](#2-python-dependency-updates) | Update pyproject.toml/requirements.txt, pip-audit |
| [3. Rust, Go & JS Dependency Updates](#3-rust-go--javascript-dependency-updates) | cargo update, go get -u, npm update |
| [4. Quality Gates](#4-quality-gates) | Code formatting, linting, secrets scanning, security analysis |
| [5. Test Gates](#5-test-gates) | Unit tests, JS tests, UI tests, MCP tests, load tests |
| [6. Build Verification](#6-build-verification) | Docker build, compose stack, embedded mode, package validation |
| [7. SSO Verification](#7-sso-verification) | Keycloak SSO login flow |
| [8. Observability Verification](#8-observability-verification) | Monitoring stack under load |
| [9. Security & Analysis](#9-security--analysis) | SonarQube, container scanning |
| [10. Deployment Verification](#10-deployment-verification) | Helm chart lint, IaC scanning, Minikube deploy |
| [11. Documentation Verification](#11-documentation-verification) | Broken links, build, deploy |
| [12. Plugin Testing](#12-plugin-testing) | PII filter, plugin framework, tool invocation hooks |
| [13. Upgrade Testing](#13-upgrade-testing) | PostgreSQL upgrade, SQLite upgrade, fresh install |
| [14. Manual Testing](#14-manual-testing) | MCP servers, virtual servers, tokens, Inspector, VS Code |
| [15. Draft Release](#15-draft-release) | GitHub release, release notes, announcements |
| [16. Post-Release](#16-post-release) | Milestone cleanup, next iteration setup |

---

## 1. Version Update

### 1.1 Bump the version

Use `bump2version` to update all version references atomically:

```bash
bump2version --verbose --new-version=X.Y.Z-RC-N build
```

This updates the version string in the four canonical locations defined in `.bumpversion.cfg`:

| File | Field |
|------|-------|
| `mcpgateway/__init__.py` | `__version__` |
| `pyproject.toml` | `version` |
| `Containerfile` | `version` label |
| `Containerfile.lite` | `version` label |

!!! note "bump2version does not commit or tag"
    The project's `.bumpversion.cfg` has `commit = False` and `tag = False`. You must commit and tag manually after all gates pass.

### 1.2 Check for stale version references

Search the codebase for any remaining references to the **old** version and update them. Exclude files where the old version appears in a historical context:

- `CHANGELOG.md` (historical entries are expected)
- `docs/docs/architecture/roadmap.md` (closed milestones are expected)
- Git history

Common places to check:

- `charts/mcp-stack/Chart.yaml` (`appVersion`)
- `charts/mcp-stack/values.yaml` (image tag)
- `docs/docs/index.md` or overview pages
- `README.md` badge or installation snippets

### 1.3 Update `CHANGELOG.md`

Update `CHANGELOG.md` following [Keep a Changelog](https://keepachangelog.com/) format:

- Add a new section header: `## [X.Y.Z] - YYYY-MM-DD - Release Title`
- Include an **Overview** paragraph describing the release focus
- Document **Breaking Changes** with migration tables (old default vs. new default)
- Organize entries under standard headings: `Added`, `Changed`, `Deprecated`, `Removed`, `Fixed`, `Security`
- Link each entry to its GitHub issue or PR where applicable

### 1.4 Update `docs/docs/architecture/roadmap.md`

- Set the release's **Completion** to `100%` and **Status** to `Closed`
- Verify the **Due Date** matches the actual release date
- Move any incomplete issues from this milestone to the next release

### 1.5 Resolve GitHub security advisories

Review and resolve all items on the [Security tab](https://github.com/IBM/mcp-context-forge/security):

- **Dependabot alerts** — upgrade or dismiss every open alert. No critical or high severity alerts may remain open at release time.
- **Code scanning alerts** — review any CodeQL or third-party SAST findings and resolve or justify each one.
- **Secret scanning alerts** — verify no leaked secrets are flagged; rotate any that were exposed.

```bash
# Quick check via CLI
gh api repos/IBM/mcp-context-forge/dependabot/alerts --jq '[.[] | select(.state=="open")] | length'
gh api repos/IBM/mcp-context-forge/code-scanning/alerts --jq '[.[] | select(.state=="open")] | length'
```

**Acceptance criteria:** Zero open critical/high Dependabot alerts. All code scanning and secret scanning alerts reviewed and resolved or triaged with documented justification.

### 1.6 Update container base images

Update the `FROM` lines in `Containerfile` and `Containerfile.lite` to the latest available tags. Pinned image tags prevent silent drift but must be bumped manually before each release.

Check current base images:

```bash
grep '^FROM' Containerfile.lite
```

| Stage | Current image | What to check |
|-------|---------------|---------------|
| Rust builder | `quay.io/pypa/manylinux2014:<tag>` | [quay.io tags](https://quay.io/repository/pypa/manylinux2014?tab=tags) |
| Builder | `registry.access.redhat.com/ubi10/ubi:<tag>` | [Red Hat Container Catalog](https://catalog.redhat.com/software/containers/ubi10/ubi) |
| Runtime | `registry.access.redhat.com/ubi10/ubi-minimal:<tag>` | [Red Hat Container Catalog](https://catalog.redhat.com/software/containers/ubi10/ubi-minimal) |

Update both `Containerfile` and `Containerfile.lite` with the latest tags, then verify the images build:

```bash
make docker-prod DOCKER_BUILD_ARGS="--no-cache"
```

!!! warning "Keep Containerfile and Containerfile.lite in sync"
    Both files share the same base images. When updating one, update the other to match.

### 1.7 Close the GitHub milestone

- Move all remaining open issues to the next milestone
- Close the current milestone on GitHub

---

## 2. Python Dependency Updates

Update all Python dependencies across the repository before cutting a release. This ensures the release ships with current, patched versions.

### 2.1 Update dependencies with `update_dependencies.py`

The repository includes an async dependency updater at `.github/tools/update_dependencies.py`. Run it against every `pyproject.toml` and `requirements.txt` in the tree:

```bash
# Main project
python .github/tools/update_dependencies.py --file pyproject.toml

# MCP servers
python .github/tools/update_dependencies.py --file mcp-servers/python/data_analysis_server/pyproject.toml
python .github/tools/update_dependencies.py --file mcp-servers/python/graphviz_server/pyproject.toml
python .github/tools/update_dependencies.py --file mcp-servers/python/mcp-rss-search/pyproject.toml
python .github/tools/update_dependencies.py --file mcp-servers/python/python_sandbox_server/pyproject.toml
python .github/tools/update_dependencies.py --file mcp-servers/python/mcp_eval_server/pyproject.toml
python .github/tools/update_dependencies.py --file mcp-servers/python/qr_code_server/pyproject.toml
python .github/tools/update_dependencies.py --file mcp-servers/python/url_to_markdown_server/pyproject.toml
python .github/tools/update_dependencies.py --file mcp-servers/python/output_schema_test_server/pyproject.toml

# External plugins
python .github/tools/update_dependencies.py --file plugins/external/cedar/pyproject.toml
python .github/tools/update_dependencies.py --file plugins/external/llmguard/pyproject.toml
python .github/tools/update_dependencies.py --file plugins/external/opa/pyproject.toml

# Rust plugins (Python bindings)
python .github/tools/update_dependencies.py --file plugins_rust/pyproject.toml

# Requirements files
python .github/tools/update_dependencies.py --file docs/requirements.txt
python .github/tools/update_dependencies.py --file tests/load/requirements.txt
python .github/tools/update_dependencies.py --file tests/populate/requirements.txt
```

!!! tip "Dry-run first"
    Use `--dry-run` to preview changes before applying: `python .github/tools/update_dependencies.py --file pyproject.toml --dry-run`

### 2.2 Reinstall and verify

After updating, reinstall the dev environment and verify everything still resolves:

```bash
make install-dev
```

### 2.3 Audit for vulnerabilities

```bash
make pip-audit
```

**Acceptance criteria:** No known CVEs in the resolved dependency tree. If `pip-audit` reports vulnerabilities, evaluate whether a fix is available or whether the dependency must be pinned with a documented justification.

### 2.4 Rebuild and test

Verify the containers build with the updated dependencies and the test suite passes:

```bash
make docker-prod DOCKER_BUILD_ARGS="--no-cache"
make test
```

---

## 3. Rust, Go & JavaScript Dependency Updates

Update non-Python dependencies across the repository.

### 3.1 Rust dependencies

Update `Cargo.lock` files for all Rust crates and verify they build and pass tests:

```bash
# Update dependencies
cd plugins_rust && cargo update && cd ..
cd mcp-servers/rust/fast-test-server && cargo update && cd ../../..
cd mcp-servers/rust/filesystem-server && cargo update && cd ../../..
cd tools_rust/wrapper && cargo update && cd ../..

# Verify build + lint + tests
make rust-check
```

| What it runs | Description |
|--------------|-------------|
| `cargo fmt --check` | Verify Rust formatting |
| `cargo clippy -- -D warnings` | Lint for common mistakes and anti-patterns |
| `cargo test --lib --release` | Run Rust unit tests |

### 3.2 Go dependencies

Update `go.mod` and `go.sum` for all Go modules:

```bash
cd a2a-agents/go/a2a-echo-agent && go get -u ./... && go mod tidy && cd ../../..
cd mcp-servers/go/fast-time-server && go get -u ./... && go mod tidy && cd ../../..
cd mcp-servers/go/slow-time-server && go get -u ./... && go mod tidy && cd ../../..
cd mcp-servers/go/benchmark-server && go get -u ./... && go mod tidy && cd ../../..
```

Verify Go code compiles and passes security checks:

```bash
make linting-go-gosec
make linting-go-govulncheck
```

| Target | What it checks |
|--------|----------------|
| `linting-go-gosec` | Security static analysis across all Go modules |
| `linting-go-govulncheck` | Known vulnerability scanning in Go dependencies |

### 3.3 JavaScript dependencies (npm)

Update `package.json` and verify the frontend builds and passes linting:

```bash
npm update
npm audit
npm audit fix
```

Then run the full web linting and test suite:

```bash
make lint-web
make test-js-coverage
```

### 3.4 Frontend CDN dependencies

The Admin UI loads frontend libraries (Tailwind, HTMX, Alpine.js, Chart.js, CodeMirror, Font Awesome, Marked, DOMPurify) from CDNs at runtime, with pinned versions in three places that must be kept in sync:

| File | What it controls |
|------|------------------|
| `scripts/cdn_resources.py` | Single source of truth for CDN URLs and versions (used by SRI scripts) |
| `scripts/download-cdn-assets.sh` | Downloads pinned CDN assets into the container for airgapped deployment |
| `mcpgateway/templates/*.html` | `<script>` and `<link>` tags with hardcoded CDN URLs |

**Update procedure:**

1. **Check for new versions** of each library at its upstream (npm, cdnjs, jsdelivr). The current pinned versions are listed in `scripts/cdn_resources.py`.

2. **Update the version numbers** in all three files. Search-and-replace the old version with the new one:

    ```bash
    # Example: update Alpine.js from 3.15.8 to 3.16.0
    grep -rn "3.15.8" scripts/cdn_resources.py scripts/download-cdn-assets.sh mcpgateway/templates/
    # Replace in all matching files
    ```

3. **Regenerate SRI hashes** for the new CDN URLs:

    ```bash
    make sri-generate
    ```

    This fetches each resource from its CDN URL and writes SHA-384 hashes to `mcpgateway/sri_hashes.json`.

4. **Verify SRI hashes** match the live CDN content:

    ```bash
    make sri-verify
    ```

5. **Rebuild the container** to test the airgapped download path:

    ```bash
    make docker-prod DOCKER_BUILD_ARGS="--no-cache"
    ```

    The `Containerfile.lite` runs `scripts/download-cdn-assets.sh` during build to vendor all CDN assets into `mcpgateway/static/vendor/`. A build failure here means a URL is broken or a version was updated inconsistently.

6. **Smoke test the Admin UI** to verify all frontend libraries load correctly (both CDN and vendored modes).

!!! warning "Three files must stay in sync"
    A version bump in `cdn_resources.py` without matching changes in `download-cdn-assets.sh` and the HTML templates will cause SRI verification failures or broken airgapped builds. Always update all three together.

### 3.5 Rebuild containers

After updating all dependency ecosystems, rebuild the production container from scratch to verify everything integrates:

```bash
make docker-prod DOCKER_BUILD_ARGS="--no-cache"
```

---

## 4. Quality Gates

All formatting and linting checks must pass with zero errors.

### 4.1 Code formatting and pre-commit hooks

```bash
make autoflake isort black pre-commit
```

| Target | What it checks |
|--------|----------------|
| `autoflake` | Removes unused imports and variables |
| `isort` | Sorts imports (profile=black) |
| `black` | Formats Python code (line length 200) |
| `pre-commit` | Runs all configured pre-commit hooks |

### 4.2 Python linters

```bash
make flake8 ruff vulture bandit interrogate pylint verify
```

| Target | What it checks |
|--------|----------------|
| `flake8` | PEP 8 style violations (E3, E4, E7, E9, F, D1) |
| `ruff` | Fast lint pass (overlaps flake8, catches additional patterns) |
| `vulture` | Dead code detection (unused functions, variables, imports) |
| `bandit` | Security vulnerabilities in Python code |
| `interrogate` | Docstring coverage (must meet threshold) |
| `pylint` | Code quality score (must be ≥ 10, fails on errors) |
| `verify` | Package metadata validation (twine, check-manifest, pyroma) |

### 4.3 Configuration file validation

```bash
make yamllint tomllint jsonlint
```

| Target | What it checks |
|--------|----------------|
| `yamllint` | YAML syntax and style (compose files, CI workflows, plugin config) |
| `tomllint` | TOML syntax (`pyproject.toml`, Rust `Cargo.toml`) |
| `jsonlint` | JSON syntax (`package.json`, test fixtures, schemas) |

### 4.4 Web code linters

```bash
make lint-web
```

Runs eslint, nodejsscan, htmlhint, stylelint, retire.js, and npm audit against the frontend code.

### 4.5 Secrets scanning

```bash
make dodgy gitleaks
```

| Target | What it checks |
|--------|----------------|
| `dodgy` | Hardcoded passwords, suspicious code patterns, secret-like strings |
| `gitleaks` | Scans git history for leaked secrets, API keys, and tokens |

**Acceptance criteria:** No secrets or credentials detected. Any false positives should be added to `.gitleaksignore`.

!!! warning "Run before tagging"
    Secrets in git history survive even after deletion from the working tree. Always run `gitleaks` before creating a release tag.

### 4.6 Security best practices

```bash
make devskim prospector
```

| Target | What it checks |
|--------|----------------|
| `devskim` | Microsoft DevSkim security anti-patterns (crypto misuse, injection, hardcoded creds) |
| `prospector` | Comprehensive multi-tool analysis (pylint, pyflakes, mccabe, dodgy, pep8, pep257) |

Review the output for any high-severity findings. DevSkim results are also written to `devskim-results.sarif` for integration with CI dashboards.

### 4.7 License header compliance

```bash
make check-headers
```

Verifies all Python files have correct Apache-2.0 license headers, copyright year, and SPDX identifier. This is a dry-run check — no files are modified.

**Acceptance criteria:** Zero files reported as missing or having incorrect headers. If any are found, fix them with `make fix-all-headers` before release.

---

## 5. Test Gates

### 5.1 Python unit tests with coverage

```bash
make coverage
```

Runs the full pytest suite with coverage reporting. Review coverage for any significant regressions.

### 5.2 JavaScript unit tests with coverage

```bash
make test-js-coverage
```

Runs Vitest with Istanbul coverage against frontend JavaScript.

### 5.3 UI tests (Playwright)

Requires the compose stack to be running (see [Build Verification](#6-build-verification)).

```bash
make test-ui-headless
```

Runs the full Playwright test suite in headless Chromium against the live compose stack.

### 5.4 MCP protocol tests

Requires the compose stack to be running with SSE transport enabled.

```bash
make test-mcp-rbac test-mcp-cli
```

| Target | What it tests |
|--------|---------------|
| `test-mcp-rbac` | RBAC enforcement and multi-transport MCP protocol compliance |
| `test-mcp-cli` | MCP protocol via mcp-cli + wrapper stdio against the gateway |

### 5.5 Load testing

Requires the compose stack with the testing profile (includes Locust).

```bash
make load-test-cli
```

**Acceptance criteria:** 10-minute sustained run, 1000 RPS target, **0% error rate**.

The load test defaults are configured via Makefile variables (`LOADTEST_HOST`, `LOADTEST_USERS`, `LOADTEST_SPAWN_RATE`, `LOADTEST_RUN_TIME`, `LOADTEST_PROCESSES`). For release validation, ensure the test runs for a sufficient duration with realistic concurrency.

!!! tip "System tuning"
    For accurate load test results, run `sudo scripts/tune-loadtest.sh` to optimize kernel parameters before testing.

Additional load profiles are available for targeted validation:

```bash
make load-test-light      # Quick smoke: 10 users, 30s
make load-test-heavy      # Stress: 200 users, 120s
make load-test-sustained  # Endurance: 25 users, 300s
make load-test-stress     # Peak: 500 users, 60s
```

---

## 6. Build Verification

### 6.1 Production container build

Build the production image from scratch to verify there are no build regressions:

```bash
make docker-prod DOCKER_BUILD_ARGS="--no-cache"
```

This builds the lite production image with Docker Content Trust enabled.

### 6.2 Containerfile linting and image scanning

Lint the Dockerfiles for best-practice violations, then scan the built image for vulnerabilities and CIS benchmark compliance:

```bash
make hadolint dockle trivy
```

| Target | What it checks |
|--------|----------------|
| `hadolint` | Dockerfile best practices and shell linting for `Containerfile`, `Containerfile.lite`, and any `Dockerfile.*` |
| `dockle` | CIS Docker Benchmark compliance and image best practices (runs against the built image via tarball) |
| `trivy` | Vulnerability scan of the built image for HIGH and CRITICAL CVEs in OS packages and application dependencies |

**Acceptance criteria:** No HIGH or CRITICAL vulnerabilities in `trivy` output. No errors from `hadolint` (warnings are acceptable if documented). No failures from `dockle` at warn level.

### 6.3 Compose stack validation

Bring up the full stack with the testing profile and verify all services are healthy:

```bash
make testing-down compose-clean testing-up
```

This starts the gateway along with Locust, A2A echo server, fast test server, and MCP Inspector. Verify all services are healthy:

```bash
make compose-ps
```

!!! warning "Run compose tests before tearing down"
    The UI tests, MCP tests, and load tests in [Section 5](#5-test-gates) require this stack to be running. Run all compose-dependent tests before calling `make compose-clean`.

### 6.4 Embedded mode verification

Verify the gateway works correctly in embedded/iframe mode with benchmark servers:

```bash
make embedded-up
```

This starts the embedded stack with:

| Service | URL | Purpose |
|---------|-----|---------|
| iframe Harness | `http://localhost:8889` | UI inside iframe |
| Gateway (nginx) | `http://localhost:8080` | API proxy |
| Gateway Admin UI | `http://localhost:8080/admin/` | Direct admin access |
| Benchmark Servers | `http://localhost:9000-9099` | MCP benchmark targets |

Verify:

- The Admin UI renders correctly inside the iframe harness at `http://localhost:8889`
- Benchmark servers are auto-registered and their tools appear in the catalog
- Navigation, tool execution, and resource browsing work within the embedded context

Tear down when done:

```bash
make embedded-down
```

### 6.5 Python package build

```bash
make dist
make verify
```

Builds the wheel and sdist, then validates with twine, check-manifest, and pyroma.

---

## 7. SSO Verification

Verify the SSO login flow works end-to-end with Keycloak:

```bash
make compose-sso
```

This starts the full stack with the SSO profile, including a Keycloak instance:

| Service | URL | Credentials |
|---------|-----|-------------|
| Gateway | `http://localhost:8080` | SSO login via Keycloak |
| Keycloak | `http://localhost:8180` | `admin` / `changeme` |

Verify:

- Navigate to the Admin UI at `http://localhost:8080/admin/` and confirm the SSO login redirect to Keycloak
- Log in with the Keycloak credentials and verify the redirect back to the Admin UI with a valid session
- Confirm that RBAC roles from Keycloak tokens are correctly mapped and enforced
- Test logout and verify the session is invalidated

Tear down when done:

```bash
make compose-sso-down
```

---

## 8. Observability Verification

Verify the monitoring stack works correctly under active load. This must be done while the compose stack is running.

### 8.1 Start the monitoring stack

```bash
make monitoring-up
```

This starts Prometheus, Grafana, and Tempo with OTEL tracing enabled:

| Service | URL | Credentials |
|---------|-----|-------------|
| Grafana | `http://localhost:3000` | `admin` / `changeme` |
| Prometheus | `http://localhost:9090` | — |
| Tempo | `http://localhost:3200` | OTLP: 4317 (gRPC), 4318 (HTTP) |

### 8.2 Run a load test with monitoring active

```bash
make load-test-cli
```

While the load test is running, verify in Grafana:

- The **MCP Gateway Overview** dashboard populates with live metrics
- Request rate, latency percentiles, and error rate graphs are rendering
- Prometheus targets are all in `UP` state at `http://localhost:9090/targets`
- Traces are flowing into Tempo and visible from the Grafana Explore view

### 8.3 Teardown

```bash
make monitoring-down
```

---

## 9. Security & Analysis

### 9.1 SonarQube analysis

Start SonarQube and submit a scan:

```bash
# Start SonarQube (pick your runtime)
make sonar-up-docker    # or: make sonar-up-podman

# Submit the scan
make sonar-submit-docker  # or: make sonar-submit-podman
```

**Acceptance criteria:** Clean SonarQube report — no new bugs, vulnerabilities, or security hotspots. Review any code smells and technical debt.

!!! tip "First-time setup"
    Run `make sonar-info` for instructions on generating the SonarQube authentication token.

### 9.2 Semgrep security analysis

Run Semgrep with the auto ruleset to detect security anti-patterns, injection risks, and unsafe code:

```bash
make semgrep
```

Semgrep scans the `mcpgateway/` source for patterns including SQL injection, command injection, SSRF, insecure deserialization, and framework-specific misuse. Review any findings and fix or justify before release.

### 9.3 SBOM generation

Generate a Software Bill of Materials for the release:

```bash
make sbom
```

This produces a CycloneDX XML SBOM (`mcpgateway.sbom.xml`) listing all Python dependencies and their versions. Include the SBOM as a release artifact or attach it to the GitHub Release.

### 9.4 Container security scanning

The CI pipeline (`docker-scan.yml`) runs Trivy and Grype scans on the container image. Verify no critical or high vulnerabilities exist in the final image. For local verification, see also [Section 6.2](#62-containerfile-linting-and-image-scanning).

---

## 10. Deployment Verification

### 10.1 Helm chart lint and IaC security scanning

```bash
make helm-lint linting-security-kube-linter linting-security-checkov
```

| Target | What it checks |
|--------|----------------|
| `helm-lint` | Helm chart static analysis for correctness |
| `linting-security-kube-linter` | Kubernetes best-practice linting (resource limits, security contexts, probes) |
| `linting-security-checkov` | IaC security scanning across Dockerfiles, docker-compose files, Helm charts, and k8s manifests |

### 10.2 Helm chart package

```bash
make helm-package
```

Packages the chart into `dist/mcp-stack-<version>.tgz`.

### 10.3 Minikube deployment

Deploy to a local Minikube cluster to verify the Helm chart works end-to-end:

```bash
# Start Minikube (if not already running)
make minikube-start

# Load the freshly built image
make minikube-image-load

# Deploy via Helm
make helm-deploy

# Verify pods are healthy
make minikube-status

# Port-forward and smoke test
make minikube-port-forward
```

Verify the application starts, the health endpoint responds, and basic functionality works through the forwarded port.

### 10.4 Teardown

```bash
make helm-delete
make minikube-stop
```

---

## 11. Documentation Verification

Verify the documentation builds cleanly, has no broken links, and is ready for deployment.

### 11.1 Check for broken links

```bash
make linting-docs-markdown-links
```

Scans Markdown files for broken internal and external links. Fix any broken references before release.

### 11.2 Build and preview documentation

```bash
cd docs && make serve
```

This starts a local MkDocs development server. Manually review:

- The new version's content is accurate and complete
- Navigation structure is correct
- No rendering issues in code blocks, tables, or admonitions
- Release-specific pages (CHANGELOG, roadmap) reflect the current release

### 11.3 Deploy documentation

Once verified, deploy the documentation site:

```bash
cd docs && make deploy
```

This runs `mkdocs gh-deploy` to publish the site to GitHub Pages.

---

## 12. Plugin Testing

Verify the plugin framework and key plugins work correctly. This requires the compose stack to be running with `PLUGINS_ENABLED=true` (the default in `docker-compose.yml`).

### 12.1 Enable the PII filter plugin

Edit `plugins/config.yaml` to set the PII filter plugin to enforce mode:

```yaml
- name: "PIIFilterPlugin"
  kind: "plugins.pii_filter.pii_filter.PIIFilterPlugin"
  mode: "enforce"  # Change from "disabled" to "enforce"
  priority: 50
  config:
    detect_ssn: true
    detect_credit_card: true
    detect_email: true
    detect_phone: true
    detect_ip_address: true
    detect_aws_keys: true
    detect_api_keys: true
    default_mask_strategy: "partial"
    block_on_detection: false
    log_detections: true
    include_detection_details: true
```

Restart the compose stack to pick up the change:

```bash
make compose-restart
```

### 12.2 Test PII detection on tool invocation

Register a simple REST tool and invoke it with PII-laden arguments to verify the plugin intercepts and masks sensitive data:

```bash
# Create a tool that echoes its input
curl -s -X POST -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN" \
     -H "Content-Type: application/json" \
     -d '{
       "name": "echo_tool",
       "description": "Echoes input for testing",
       "url": "https://httpbin.org/post",
       "request_type": "POST",
       "integration_type": "REST",
       "input_schema": {
         "type": "object",
         "properties": {
           "message": {"type": "string", "description": "Message to echo"}
         }
       }
     }' \
     $BASE_URL/tools | jq
```

Invoke the tool with various PII types and verify masking:

```bash
# Test with SSN
curl -s -X POST -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN" \
     -H "Content-Type: application/json" \
     -d '{"arguments": {"message": "My SSN is 123-45-6789"}}' \
     $BASE_URL/tools/echo_tool/invoke | jq

# Test with credit card number
curl -s -X POST -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN" \
     -H "Content-Type: application/json" \
     -d '{"arguments": {"message": "Card: 4111-1111-1111-1111"}}' \
     $BASE_URL/tools/echo_tool/invoke | jq

# Test with email address
curl -s -X POST -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN" \
     -H "Content-Type: application/json" \
     -d '{"arguments": {"message": "Contact john.doe@example.com for details"}}' \
     $BASE_URL/tools/echo_tool/invoke | jq

# Test with AWS key
curl -s -X POST -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN" \
     -H "Content-Type: application/json" \
     -d '{"arguments": {"message": "Key: AKIAIOSFODNN7EXAMPLE"}}' \
     $BASE_URL/tools/echo_tool/invoke | jq
```

**Acceptance criteria:** Each response should show the PII values partially masked (e.g., `123-**-****`, `4111-****-****-1111`). The original PII must not appear in the tool invocation payload.

### 12.3 Test PII detection via MCP protocol

Connect through a virtual server's SSE or Streamable HTTP endpoint and invoke a tool with PII via the MCP protocol (using MCP Inspector or `mcp-cli`) to verify the plugin hooks fire on the MCP transport path as well.

### 12.4 Verify plugin health and status

Check the plugin framework is healthy via the Admin UI or API:

```bash
curl -s -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN" \
     $BASE_URL/admin/api/plugins | jq
```

Verify:

- The PII filter plugin shows `status: active` and `mode: enforce`
- Hook execution counts are incrementing after the test invocations above
- No plugin errors appear in the gateway logs (`make compose-logs | grep -i plugin`)

### 12.5 Run plugin unit tests

```bash
# PII filter unit tests
pytest tests/unit/mcpgateway/plugins/plugins/pii_filter/test_pii_filter.py -v

# Rust PII filter tests (if Rust toolchain is available)
make rust-test
```

### 12.6 Cleanup

Reset the plugin config back to disabled mode before proceeding:

```yaml
mode: "disabled"  # Revert to disabled
```

```bash
make compose-restart
```

---

## 13. Upgrade Testing

Verify that Alembic database migrations work correctly when upgrading from a previous release. The upgrade validation harness tests four scenarios: SQLite fresh, SQLite upgrade, PostgreSQL fresh, and PostgreSQL upgrade.

### 13.1 Automated upgrade validation

The `upgrade-validate` target runs the full validation harness automatically. It defaults to upgrading from `1.0.0-BETA-2` to the locally built image:

```bash
# Build the current image first
make docker-prod DOCKER_BUILD_ARGS="--no-cache"

# Run all four upgrade scenarios
make upgrade-validate
```

This executes `scripts/ci/run_upgrade_validation.sh`, which:

1. **SQLite fresh install** — starts the target image with a new SQLite database, verifies the Alembic head is correct
2. **SQLite upgrade** — starts the base image (`1.0.0-BETA-2`), seeds marker data, stops it, starts the target image against the same database file, verifies migrations ran and data is preserved
3. **PostgreSQL fresh install** — starts a fresh Postgres 18 container and the target image, verifies the Alembic head
4. **PostgreSQL upgrade** — starts the base image against Postgres, seeds marker data, swaps to the target image, verifies migrations and data preservation

**Acceptance criteria:** All four scenarios pass. The Alembic version in the database matches the expected single head, and seeded marker data survives the upgrade.

### 13.2 Custom base version

To test upgrades from a different release:

```bash
make upgrade-validate \
  UPGRADE_BASE_IMAGE=ghcr.io/ibm/mcp-context-forge:1.0.0-RC-1 \
  UPGRADE_TARGET_IMAGE=mcpgateway/mcpgateway:latest
```

### 13.3 Manual compose upgrade test (PostgreSQL)

For a more realistic test that exercises the full compose stack and PgBouncer:

```bash
# 1. Start with the old release image
make compose-clean
```

Edit `docker-compose.yml` to use the old release image:

```yaml
gateway:
  image: ghcr.io/ibm/mcp-context-forge:1.0.0-BETA-2
  #image: ${IMAGE_LOCAL:-mcpgateway/mcpgateway:latest}
```

```bash
# 2. Bring up the old stack and seed some data
make compose-up
make compose-ps   # verify all services are healthy

# Seed data: register a gateway, create a virtual server, create a tool
curl -s -X POST -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN" \
     -H "Content-Type: application/json" \
     -d '{"name":"upgrade_test_gw","url":"http://localhost:8002/sse"}' \
     http://localhost:8080/gateways | jq

curl -s -X POST -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN" \
     -H "Content-Type: application/json" \
     -d '{"name":"upgrade_test_server","description":"Pre-upgrade server"}' \
     http://localhost:8080/servers | jq

# 3. Stop the stack (preserves Postgres volume)
make compose-down
```

Swap back to the local latest image:

```yaml
gateway:
  image: ${IMAGE_LOCAL:-mcpgateway/mcpgateway:latest}
  #image: ghcr.io/ibm/mcp-context-forge:1.0.0-BETA-2
```

```bash
# 4. Bring up with the new image (Alembic auto-migrates on startup)
make compose-up
make compose-ps   # verify all services are healthy

# 5. Verify data survived the upgrade
curl -s -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN" \
     http://localhost:8080/gateways | jq '.[] | select(.name=="upgrade_test_gw")'

curl -s -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN" \
     http://localhost:8080/servers | jq '.[] | select(.name=="upgrade_test_server")'
```

Verify:

- The gateway starts without migration errors in the logs (`make compose-logs | grep -i alembic`)
- Previously created gateways, servers, and tools are present and intact
- The Admin UI loads and displays the pre-upgrade data
- New features from the current release are functional

### 13.4 Manual SQLite upgrade test

For SQLite, the upgrade path can be tested without compose:

```bash
# 1. Run the old image with a mounted SQLite volume
mkdir -p /tmp/upgrade-test-sqlite
docker run -d --name upgrade-old \
  -p 4444:4444 \
  -e "DATABASE_URL=sqlite:////app/data/mcp.db" \
  -e "AUTH_REQUIRED=false" \
  -e "HOST=0.0.0.0" -e "PORT=4444" \
  -e "MCPGATEWAY_UI_ENABLED=true" \
  -e "MCPGATEWAY_ADMIN_API_ENABLED=true" \
  -v /tmp/upgrade-test-sqlite:/app/data \
  ghcr.io/ibm/mcp-context-forge:1.0.0-BETA-2

# Wait for health, seed data, stop
curl --retry 30 --retry-delay 2 -sf http://localhost:4444/health
curl -s -X POST -H "Content-Type: application/json" \
     -d '{"name":"sqlite_upgrade_test","url":"http://example.com/sse"}' \
     http://localhost:4444/gateways | jq
docker stop upgrade-old && docker rm upgrade-old

# 2. Run the new image against the same database file
docker run -d --name upgrade-new \
  -p 4444:4444 \
  -e "DATABASE_URL=sqlite:////app/data/mcp.db" \
  -e "AUTH_REQUIRED=false" \
  -e "HOST=0.0.0.0" -e "PORT=4444" \
  -e "MCPGATEWAY_UI_ENABLED=true" \
  -e "MCPGATEWAY_ADMIN_API_ENABLED=true" \
  -v /tmp/upgrade-test-sqlite:/app/data \
  mcpgateway/mcpgateway:latest

# 3. Verify
curl --retry 30 --retry-delay 2 -sf http://localhost:4444/health
curl -s http://localhost:4444/gateways | jq '.[] | select(.name=="sqlite_upgrade_test")'

# 4. Cleanup
docker stop upgrade-new && docker rm upgrade-new
rm -rf /tmp/upgrade-test-sqlite
```

### 13.5 Comprehensive migration test suite

For deeper migration testing across multiple version pairs (forward, reverse, skip-version):

```bash
# Run the full migration test suite
make migration-test-all

# Or run database-specific tests
make migration-test-sqlite
make migration-test-postgres
make migration-test-performance
```

The migration test suite follows an **n-2 support policy** and tests sequential upgrades, downgrades, and skip-version jumps. See `tests/migration/README.md` for full documentation.

---

## 14. Manual Testing

These tests verify core user-facing workflows that automated tests do not fully cover. Perform them against the running compose stack (`make testing-up`).

### 14.1 Generate a JWT token

Create a token for API and client access:

```bash
export MCPGATEWAY_BEARER_TOKEN=$(python -m mcpgateway.utils.create_jwt_token \
  --username admin@example.com \
  --exp 10080 \
  --secret my-test-key)
```

Set the base URL (use `8080` for the nginx-proxied compose stack):

```bash
export BASE_URL="http://localhost:8080"
```

### 14.2 Register an MCP server via SSE

Start a sample MCP server and register it as an SSE gateway:

```bash
# Start a sample MCP time server exposed via SSE
python3 -m mcpgateway.translate \
  --stdio "uvx mcp_server_time -- --local-timezone=UTC" \
  --expose-sse \
  --port 8002 &

# Register it with the gateway
curl -s -X POST -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN" \
     -H "Content-Type: application/json" \
     -d '{"name":"release_test_sse","url":"http://localhost:8002/sse"}' \
     $BASE_URL/gateways | jq
```

Verify the tools from the server appear in the catalog:

```bash
curl -s -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN" $BASE_URL/tools | jq
```

### 14.3 Register an MCP server via Streamable HTTP

Register a server using the Streamable HTTP transport:

```bash
# Start a sample MCP server exposed via Streamable HTTP
python3 -m mcpgateway.translate \
  --stdio "uvx mcp_server_time -- --local-timezone=UTC" \
  --port 8003 &

# Register it with the gateway
curl -s -X POST -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN" \
     -H "Content-Type: application/json" \
     -d '{"name":"release_test_streamable","url":"http://localhost:8003/mcp"}' \
     $BASE_URL/gateways | jq
```

### 14.4 Create a virtual server and export it

Bundle the imported tools into a virtual MCP server:

```bash
# Create the virtual server
curl -s -X POST -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN" \
     -H "Content-Type: application/json" \
     -d '{"name":"release_test_server","description":"Release validation tools","associatedTools":["1","2"]}' \
     $BASE_URL/servers | jq
```

Verify the server was created:

```bash
curl -s -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN" $BASE_URL/servers | jq
```

Export the configuration for backup verification:

```bash
python -m mcpgateway.cli export --out release-test-export.json
```

### 14.5 Test with MCP Inspector

Connect interactively via MCP Inspector to validate the protocol layer:

```bash
npx -y @modelcontextprotocol/inspector
```

In the Inspector UI:

1. Set **Transport** to `SSE`
2. Set **URL** to `$BASE_URL/servers/<SERVER_UUID>/sse`
3. Set **Header** `Authorization` to `Bearer <YOUR_TOKEN>`
4. Click **Connect**
5. Verify: tools list loads, you can execute a tool call, and the response is correct

Repeat with **Streamable HTTP**:

1. Set **Transport** to `Streamable HTTP`
2. Set **URL** to `$BASE_URL/servers/<SERVER_UUID>/mcp`
3. Set the same Authorization header
4. Verify: tools list loads and tool calls execute correctly

### 14.6 Test with VS Code (GitHub Copilot)

Create a `.vscode/mcp.json` in a test workspace to verify the IDE integration end-to-end.

**SSE configuration:**

```json
{
  "servers": {
    "contextforge-sse": {
      "type": "sse",
      "url": "http://localhost:8080/servers/<SERVER_UUID>/sse",
      "headers": {
        "Authorization": "Bearer <YOUR_JWT_TOKEN>"
      }
    }
  }
}
```

**Streamable HTTP configuration:**

```json
{
  "servers": {
    "contextforge-http": {
      "type": "http",
      "url": "http://localhost:8080/servers/<SERVER_UUID>/mcp/",
      "headers": {
        "Authorization": "Bearer <YOUR_JWT_TOKEN>"
      }
    }
  }
}
```

Verify in VS Code (requires VS Code >= 1.99 with `"chat.mcp.enabled": true`):

1. Open the Copilot chat panel
2. Confirm the MCP server status indicator shows connected
3. Ask Copilot to use one of the registered tools (e.g., "What time is it?")
4. Verify the tool call executes and returns a valid response
5. Test with both SSE and Streamable HTTP configurations

### 14.7 Cleanup

Stop the sample MCP servers and remove test artifacts:

```bash
# Stop background translate processes
kill %1 %2 2>/dev/null || true

# Remove test export
rm -f release-test-export.json
```

---

## 15. Draft Release

### 15.1 Commit the version bump

Once all gates pass, commit the version changes:

```bash
git add -A
git commit -s -m "chore: bump version to X.Y.Z"
```

!!! note "DCO requirement"
    All commits must be signed off (`-s` flag) per the project's Developer Certificate of Origin policy.

### 15.2 Tag the release

```bash
git tag -s vX.Y.Z -m "Release vX.Y.Z"
git push origin main --tags
```

The tag format is `vX.Y.Z` (e.g., `v1.0.0`, `v1.0.0-RC-2`) as configured in `.bumpversion.cfg`.

### 15.3 Create the GitHub Release

Create a release on GitHub from the tag. The release notes should include:

1. **Summary** — One-paragraph description of the release focus
2. **Highlights** — Bullet list of the most notable changes
3. **Breaking Changes** — Migration instructions for any breaking changes (copy from CHANGELOG)
4. **New Features** — Key new capabilities
5. **Bug Fixes** — Notable fixes
6. **Security** — Security-related changes
7. **Upgrade Instructions** — Link to the [upgrade guide](../manage/upgrade.md) with any release-specific notes
8. **Full Changelog** — Link to the diff between the previous and current tag

```bash
gh release create vX.Y.Z \
  --title "vX.Y.Z - Release Title" \
  --notes-file release-notes.md
```

!!! important "CI triggers on release publish"
    Publishing the GitHub Release triggers the `docker-release.yml` workflow, which re-tags the multiplatform container image with the release version on GHCR. The release **must not be a draft or prerelease** for this workflow to trigger. It also verifies that all commit checks passed before tagging.

### 15.4 Verify CI release pipeline

After publishing, verify that the `docker-release.yml` workflow completes successfully:

```bash
gh run list --workflow=docker-release.yml --limit=1
```

Confirm the container image is available at `ghcr.io/ibm/mcp-context-forge:vX.Y.Z`.

---

## 16. Post-Release

### 16.1 Close the milestone

If not already done in step 1.5, close the GitHub milestone and ensure all issues are accounted for.

### 16.2 Create the next milestone

Create the next milestone on GitHub with the planned due date from the roadmap.

### 16.3 Verify documentation deployment

If the documentation site auto-deploys, verify the new version's docs are live and the release notes are visible.

### 16.4 Announce the release

Notify relevant channels (GitHub Discussions, Slack, mailing list, etc.) with a summary of the release highlights.

---

## Quick Reference: Gate Commands

Copy-paste checklist for running all gates in sequence:

```bash
# 0. Security advisories & base images
gh api repos/IBM/mcp-context-forge/dependabot/alerts --jq '[.[] | select(.state=="open")] | length'
# ... resolve all open Dependabot, code scanning, secret scanning alerts ...
# ... update FROM tags in Containerfile + Containerfile.lite ...
grep '^FROM' Containerfile.lite

# 1. Python dependency updates
python .github/tools/update_dependencies.py --file pyproject.toml
# ... repeat for all pyproject.toml and requirements.txt (see Section 2) ...
make install-dev
make pip-audit

# 2. Rust / Go / JS / CDN dependency updates
cd plugins_rust && cargo update && cd ..
# ... repeat for all Cargo.toml dirs (see Section 3) ...
make rust-check
# ... go get -u ./... && go mod tidy for all go.mod dirs ...
make linting-go-gosec linting-go-govulncheck
npm update && npm audit && npm audit fix
make lint-web test-js-coverage
# CDN deps: update versions in cdn_resources.py, download-cdn-assets.sh, templates/*.html
make sri-generate sri-verify

# 3. Rebuild after dep updates
make docker-prod DOCKER_BUILD_ARGS="--no-cache"
make test

# 4. Format, lint & security
make autoflake isort black pre-commit
make flake8 ruff vulture bandit interrogate pylint verify
make yamllint tomllint jsonlint
make lint-web
make dodgy gitleaks
make devskim prospector
make check-headers

# 5. Unit tests
make coverage
make test-js-coverage

# 6. Build, Containerfile lint & compose stack
make docker-prod DOCKER_BUILD_ARGS="--no-cache"
make hadolint dockle trivy
make testing-down compose-clean testing-up

# 7. Integration tests (compose stack must be running)
make test-ui-headless
make test-mcp-rbac test-mcp-cli
make load-test-cli

# 8. Embedded mode
make embedded-up
# ... verify iframe UI, benchmark servers ...
make embedded-down

# 9. SSO
make compose-sso
# ... verify Keycloak login flow ...
make compose-sso-down

# 10. Monitoring under load (compose stack must be running)
make monitoring-up
make load-test-cli
# ... verify Grafana dashboards, Prometheus targets, Tempo traces ...
make monitoring-down

# 11. Security & analysis
make semgrep
make sbom
make sonar-up-docker && make sonar-submit-docker

# 12. Helm / Minikube / IaC
make helm-lint linting-security-kube-linter linting-security-checkov
make helm-package
make minikube-start minikube-image-load helm-deploy
make minikube-status
make helm-delete minikube-stop

# 13. Documentation
make linting-docs-markdown-links
cd docs && make serve   # manual review
cd docs && make deploy

# 14. Plugin testing
# ... enable PII filter in plugins/config.yaml (mode: "enforce") ...
make compose-restart
# ... invoke tools with PII (SSN, credit card, email, AWS key) ...
# ... verify masking in responses ...
pytest tests/unit/mcpgateway/plugins/plugins/pii_filter/test_pii_filter.py -v
# ... revert plugin config, restart ...

# 15. Upgrade testing
make upgrade-validate
# ... or manual compose upgrade: swap image in docker-compose.yml ...
make migration-test-all

# 16. Manual testing (see Section 14 for full walkthrough)
# ... register SSE + Streamable HTTP servers, create virtual server,
#     export config, test with MCP Inspector, test with VS Code ...

# 17. Teardown
make testing-down compose-clean
```
