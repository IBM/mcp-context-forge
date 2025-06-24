# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and this project **adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html)**.

---

## [0.2.0] - 2025-06-24


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
