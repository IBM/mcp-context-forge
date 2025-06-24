# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and this project **adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html)**.

---

## [0.2.0] - 2025-06-24

### Added

* **Streamable HTTP transport** – full first-class support for MCP's new default transport (deprecated SSE):

  * gateway accepts Streamable HTTP client connections (stateful & stateless). SSE support retained.
  * UI & API allow registering Streamable HTTP MCP servers with health checks, auth & time-outs
  * UI now shows a *transport* column for each gateway/tool;
* **Authentication & stateful sessions** for Streamable HTTP clients/servers (Basic/Bearer headers, session persistence).
* **Gateway hardening** – connection-level time-outs and smarter health-check retries to avoid UI hangs
* **Fast Go MCP server example** – high-performance reference server for benchmarking/demos.
* **Exportable connection strings** – one-click download & `/servers/{id}/connect` API that generates ready-made configs for LangChain, Claude Desktop, etc. (closed #154).
* **Infrastructure as Code** – initial Terraform & Ansible scripts for cloud installs.
* **Developer tooling & UX**

  * `tox`, GH Actions *pytest + coverage* workflow
  * pre-commit linters (ruff, flake8, yamllint) & security scans
  * dark-mode theme and compact version-info panel in Admin UI
  * developer onboarding checklist in docs.
* **Deployment assets** – Helm charts now accept external secrets/Redis; Fly.io guide; Docker-compose local-image switch; Helm deployment walkthrough.

### Changed

* **Minimum supported Python is now 3.11**; CI upgraded to Ubuntu 24.04 / Python 3.12.
* Added detailed **context-merging algorithm** notes to docs.
* Refreshed Helm charts, Makefile targets, JWT helper CLI and SBOM generation; tightened typing & linting.
* 333 unit-tests now pass; major refactors in federation, tool, resource & gateway services improve reliability.

### Fixed

* SBOM generation failure in `make docs` (#132) and Makefile `images` target (#131).
* GitHub Remote MCP server addition flow (#152).
* REST path-parameter & payload substitution issues (#100).
* Numerous flaky tests, missing dependencies and mypy/flake8 violations across the code-base .

### Security

* Dependency bumps and security-policy updates; CVE scans added to pre-commit & CI (commit ed972a8).

### 🙌 New contributors in 0.2.0

Thanks to the new **first-time contributors** who jumped in between 0.1.1 → 0.2.0:

| Contributor              | First delivered in 0.2.0                                                          |
| ------------------------ | --------------------------------------------------------------------------------- |
| **Abdul Samad**          | Dark-mode styling across the Admin UI and a more compact version-info panel       |
| **Arun Babu Neelicattu** | Bumped the minimum supported Python to 3.11 in pyproject.toml                     |
| **Manoj Jahgirdar**      | Polished the Docs home page / index                                               |
| **Shoumi Mukherjee**     | General documentation clean-ups and quick-start clarifications                    |
| **Thong Bui**            | REST adapter: path-parameter (`{id}`) support, `PATCH` handling and 204 responses |

Welcome aboard—your PRs made 0.2.0 measurably better! 🎉

---

### 🙏 Returning contributors who went the extra mile in 0.2.0

| Contributor          | Highlights this release                                                                                                                                                                                                                                                                                                                                   |
| -------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Mihai Criveti**    | Release management & 0.2.0 version bump, Helm-chart refactor + deployment guide, full CI revamp (pytest + coverage, pre-commit linters, tox), **333 green unit tests**, security updates, build updates, fully automated deployment to Code Engine, improved helm stack, doc & GIF refresh                                                                                                                                                    |
| **Keval Mahajan**    | Implemented **Streamable HTTP** transport (client + server) with auth & stateful sessions, transport column in UI, gateway time-outs, extensive test fixes and linting                                                                                                                                                                                    |
| **Madhav Kandukuri** |• Wrote **ADRs for tool-federation & dropdown UX** <br>• Polished the new **dark-mode** theme<br>• Authored **Issue #154** that specified the connection-string export feature<br>• Plus multiple stability fixes (async DB, gateway add/del, UV sync, Basic-Auth headers) |
| **Manav Gupta**      | Fixed SBOM generation & license verification, repaired Makefile image/doc targets, improved Docker quick-start and Fly.io deployment docs                                                                                                                                                                                                                 |

*Huge thanks for keeping the momentum going! 🚀*


## [0.1.1] - 2025‑06-14

### Added

* Added mcpgateway/translate.py (initial version) to convert stdio -> SSE
* Moved mcpgateway-wrapper to mcpgateway/wrapper.py so it can run as a Python module (python3 -m mcpgateway.wrapper)
* Integrated version into UI. API and separate /version endpoint also available.
* Added /ready endpoint
* Multiple new Makefile and packaging targets for maintaing the release
* New helm charts and associated documentation

### Fixed

* Fixed errors related to deleting gateways when metrics are associated with their tools
* Fixed gateway addition errors when tools overlap. We add the missing tools when tool names overlap.
* Improved logging by capturing ExceptionGroups correctly and showing specific errors
* Fixed headers for basic authorization in tools and gateways

## [0.1.0] - 2025‑06‑01

### Added

Initial public release of MCP Gateway — a FastAPI‑based gateway and federation layer for the Model Context Protocol (MCP). This preview brings a fully‑featured core, production‑grade deployment assets and an opinionated developer experience.

Setting up GitHub repo, CI/CD with GitHub Actions, templates, `good first issue`, etc.

#### 🚪 Core protocol & gateway
* 📡 **MCP protocol implementation** – initialise, ping, completion, sampling, JSON-RPC fallback
* 🌐 **Gateway layer** in front of multiple MCP servers with peer discovery & federation

#### 🔄 Adaptation & transport
* 🧩 **Virtual-server wrapper & REST-to-MCP adapter** with JSON-Schema validation, retry & rate-limit policies
* 🔌 **Multi-transport support** – HTTP/JSON-RPC, WebSocket, Server-Sent Events and stdio

#### 🖥️ User interface & security
* 📊 **Web-based Admin UI** (HTMX + Alpine.js + Tailwind) with live metrics
* 🛡️ **JWT & HTTP-Basic authentication**, AES-encrypted credential storage, per-tool rate limits

#### 📦 Packaging & deployment recipes
* 🐳 **Container images** on GHCR, self-signed TLS recipe, health-check endpoint
* 🚀 **Deployment recipes** – Gunicorn config, Docker/Podman/Compose, Kubernetes, Helm, IBM Cloud Code Engine, AWS, Azure, Google Cloud Run

#### 🛠️ Developer & CI tooling
* 📝 **Comprehensive Makefile** (80 + targets), linting, > 400 tests, CI pipelines & badges
* ⚙️ **Dev & CI helpers** – hot-reload dev server, Ruff/Black/Mypy/Bandit, Trivy image scan, SBOM generation, SonarQube helpers

#### 🗄️ Persistence & performance
* 🐘 **SQLAlchemy ORM** with pluggable back-ends (SQLite default; PostgreSQL, MySQL, etc.)
* 🚦 **Fine-tuned connection pooling** (`DB_POOL_SIZE`, `DB_MAX_OVERFLOW`, `DB_POOL_RECYCLE`) for high-concurrency deployments

### 📈 Observability & metrics
* 📜 **Structured JSON logs** and **/metrics endpoint** with per-tool / per-gateway counters

### 📚 Documentation
* 🔗 **Comprehensive MkDocs site** – [https://ibm.github.io/mcp-context-forge/deployment/](https://ibm.github.io/mcp-context-forge/deployment/)


### Changed

* *Nothing – first tagged version.*

### Fixed

* *N/A*

---

### Release links

* **Source diff:** [`v0.1.0`](https://github.com/IBM/mcp-context-forge/releases/tag/v0.1.0)
