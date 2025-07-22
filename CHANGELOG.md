# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and this project **adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html)**.

---

## [0.4.0] - 2025-07-22 - Security, Bugfixes, Resilience & Code Quality

### Security Notice

> **This is a security-focused release. Upgrading is highly recommended.**
> 
> This release continues our security-first approach with the Admin UI and Admin API **disabled by default**. To enable these features for local development, update your `.env` file:
> ```bash
> # Enable the visual Admin UI (true/false)
> MCPGATEWAY_UI_ENABLED=true
> 
> # Enable the Admin API endpoints (true/false)
> MCPGATEWAY_ADMIN_API_ENABLED=true
> ```

### Overview

This release represents a major milestone in code quality, security, and reliability. With [52 issues resolved](https://github.com/IBM/mcp-context-forge/issues?q=is%3Aissue%20state%3Aclosed%20milestone%3A%22Release%200.4.0%22), we've achieved:
- **100% security scanner compliance** (Bandit, Grype, nodejsscan)
- **60% docstring coverage** with enhanced documentation
- **82% pytest coverage** including end-to-end testing and security tests
- **10/10 Pylint score** across the entire codebase (along existing 100% pass for ruff, pre-commit)
- **Comprehensive input validation** security test suite, checking for security issues and input validation
- **Smart retry mechanisms** with exponential backoff for resilient connections

### Added

* **Resilience & Reliability**:
  * **HTTPX Client with Smart Retry** (#456) - Automatic retry with exponential backoff and jitter for failed requests
  * **Docker HEALTHCHECK** (#362) - Container health monitoring for production deployments
  * **Enhanced Error Handling** - Replaced assert statements with proper exceptions throughout codebase

* **Developer Experience**:
  * **Test MCP Server Connectivity Tool** (#181) - Debug and validate gateway connections directly from Admin UI
  * **Persistent Admin UI Filter State** (#177) - Filters and preferences persist across page refreshes
  * **Contextual Hover-Help Tooltips** (#233) - Inline help throughout the UI for better user guidance
  * **mcp-cli Documentation** (#46) - Comprehensive guide for using MCP Gateway with the official CLI
  * **JSON-RPC Developer Guide** (#19) - Complete curl command examples for API integration

* **Security Enhancements**:
  * **Comprehensive Input Validation Test Suite** (#552) - Extensive security tests for all input scenarios
  * **Additional Security Scanners** (#415) - Added nodejsscan (#499) for JavaScript security analysis
  * **Enhanced Validation Rules** (#339, #340) - Stricter input validation across all API endpoints
  * **Output Escaping in UI** (#336) - Proper HTML escaping for all user-controlled content

* **Code Quality Tools**:
  * **Dead Code Detection** (#305) - Vulture and unimport integration for cleaner codebase
  * **Security Vulnerability Scanning** (#279) - Grype integration in CI/CD pipeline
  * **60% Doctest Coverage** (#249) - Executable documentation examples with automated testing

### Fixed

* **Critical Bugs**:
  * **STREAMABLEHTTP Transport** (#213) - Fixed critical issues preventing use of Streamable HTTP
  * **Authentication Handling** (#232) - Resolved "Auth to None" failures
  * **Gateway Authentication** (#471, #472) - Fixed auth_username and auth_password not being set correctly
  * **XSS Prevention** (#361) - Prompt and RPC endpoints now properly validate content
  * **Transport Validation** (#359) - Gateway validation now correctly rejects invalid transport types

* **UI/UX Improvements**:
  * **Dark Theme Visibility** (#366) - Fixed contrast and readability issues in dark mode
  * **Test Server Connectivity** (#367) - Repaired broken connectivity testing feature
  * **Duplicate Server Names** (#476) - UI now properly shows errors for duplicate names
  * **Edit Screen Population** (#354) - Fixed fields not populating when editing entities
  * **Annotations Editor** (#356) - Annotations are now properly editable
  * **Resource Data Handling** (#352) - Fixed incorrect data mapping in resources
  * **UI Element Spacing** (#355) - Removed large empty spaces in text editors
  * **Metrics Loading Warning** (#374) - Eliminated console warnings for missing elements

* **API & Backend**:
  * **Federation HTTPS Detection** (#424) - Gateway now respects X-Forwarded-Proto headers
  * **Version Endpoint** (#369, #382) - API now returns proper semantic version
  * **Test Server URL** (#396) - Fixed incorrect URL construction for test connections
  * **Gateway Tool Separator** (#387) - Now respects GATEWAY_TOOL_NAME_SEPARATOR configuration
  * **UI-Disabled Mode** (#378) - Unit tests now properly handle disabled UI scenarios

* **Infrastructure & CI/CD**:
  * **Makefile Improvements** (#371, #433) - Fixed Docker/Podman detection and venv handling
  * **GHCR Push Logic** (#384) - Container images no longer incorrectly pushed on PRs
  * **OpenAPI Documentation** (#522) - Fixed title formatting in API specification
  * **Test Isolation** (#495) - Fixed test_admin_tool_name_conflict affecting actual database
  * **Unused Config Removal** (#419) - Removed deprecated lock_file_path from configuration

### Changed

* **Code Quality Achievements**:
  * **60% Docstring Coverage** (#467) - Every function and class now fully documented, complementing 82% pytest coverage
  * **Zero Bandit Issues** (#421) - All security linting issues resolved
  * **10/10 Pylint Score** (#210) - Perfect code quality score maintained
  * **Zero Web Stack Lint Issues** (#338) - Clean JavaScript and HTML throughout

* **Security Improvements**:
  * **Enhanced Input Validation** - Stricter backend validation rules with configurable limits, with additional UI validation rules
  * **Removed Git Commands** (#416) - Version detection no longer uses subprocess calls
  * **Secure Error Handling** (#412) - Better exception handling without information leakage

* **Developer Workflow**:
  * **E2E Acceptance Test Documentation** (#399) - Comprehensive testing guide
  * **Security Policy Documentation** (#376) - Clear security guidelines on GitHub Pages
  * **Pre-commit Configuration** (#375) - yamllint now correctly ignores node_modules
  * **PATCH Method Support** (#508) - REST API integration now properly supports PATCH

### Security

* All security scanners now pass with zero issues: Bandit, Grype, nodejsscan
* Comprehensive input validation prevents XSS, SQL injection, and other attacks
* Secure defaults with UI and Admin API disabled unless explicitly enabled
* Enhanced error handling prevents information disclosure
* Regular security scanning integrated into CI/CD pipeline

### Infrastructure

* Docker health checks for production readiness
* Improved Makefile with OS detection and better error handling
* Enhanced CI/CD with security scanning and code quality gates
* Better test isolation and coverage reporting

---

### 🌟 Release Contributors

**This release represents our commitment to enterprise-grade security and code quality. Thanks to our amazing contributors who made this security-focused release possible!**

#### 🏆 Top Contributors in 0.4.0
- **Mihai Criveti** (@crivetimihai) - Release coordinator, security improvements, and extensive testing infrastructure
- **Madhav Kandukuri** (@madhav165) - Major input validation framework, security fixes, and test coverage improvements  
- **Keval Mahajan** (@kevalmahajan) - HTTPX retry mechanism implementation and UI improvements
- **Manav Gupta** (@manavgup) - Comprehensive doctest coverage and Playwright test suite

#### 🎉 New Contributors
Welcome to our first-time contributors who joined us in 0.4.0:

- **Satya** (@TS0713) - Fixed duplicate server name handling and invalid transport type validation
- **Guoqiang Ding** (@dgq8211) - Improved tool description display with proper line wrapping
- **Rakhi Dutta** (@rakdutta) - Enhanced error messages for better user experience
- **Nayana R Gowda** - Fixed CodeMirror layout spacing issues
- **Mohan Lakshmaiah** - Contributed UI/UX improvements and test case updates
- **Shoumi Mukherjee** - Fixed resource data handling in the UI
- **Reeve Barreto** (@reevebarreto) - Implemented the Test MCP Server Connectivity feature
- **ChrisPC-39/Sebastian** - Achieved 10/10 Pylint score and added security scanners
- **Jason Frey** (@fryguy9) - Improved GitHub Actions with official IBM Cloud CLI action

#### 💪 Returning Contributors
Thank you to our dedicated contributors who continue to strengthen MCP Gateway:

- **Thong Bui** - REST API enhancements including PATCH support and path parameters
- **Abdul Samad** - Dark mode improvements and UI polish

This release represents a true community effort with contributions from developers around the world. Your dedication to security, code quality, and user experience has made MCP Gateway more robust and enterprise-ready than ever!

---

## [0.3.1] - 2025-07-11 - Security and Data Validation (Pydantic, UI)

### Security Improvements

> This release adds enhanced validation rules in the Pydantic data models to help prevent XSS injection when data from untrusted MCP servers is displayed in downstream UIs. You should still ensure any downstream agents and applications perform data sanitization coming from untrusted MCP servers (apply defense in depth).

> Data validation has been strengthened across all API endpoints (/admin and main), with additional input and output validation in the UI to improve overall security.

> The Admin UI continues to follow security best practices with localhost-only access by default and feature flag controls - now set to disabled by default, as shown in `.env.example` file (`MCPGATEWAY_UI_ENABLED=false` and `MCPGATEWAY_ADMIN_API_ENABLED=false`).

* **Comprehensive Input Validation Framework** (#339, #340):
  * Enhanced data validation for all `/admin` endpoints - tools, resources, prompts, gateways, and servers
  * Extended validation framework to all non-admin API endpoints for consistent data integrity
  * Implemented configurable validation rules with sensible defaults:
    - Character restrictions: names `^[a-zA-Z0-9_\-\s]+$`, tool names `^[a-zA-Z][a-zA-Z0-9_]*$`
    - URL scheme validation for approved protocols (`http://`, `https://`, `ws://`, `wss://`)
    - JSON nesting depth limits (default: 10 levels) to prevent resource exhaustion
    - Field-specific length limits (names: 255, descriptions: 4KB, content: 1MB)
    - MIME type validation for resources
  * Clear, helpful error messages guide users to correct input formats

* **Enhanced Output Handling in Admin UI** (#336):
  * Improved data display safety - all user-controlled content now properly HTML-escaped
  * Protected fields include prompt templates, tool names/annotations, resource content, gateway configs
  * Ensures user data displays as intended without unexpected behavior

### Added

* **Test MCP Server Connectivity Tool** (#181) - new debugging feature in Admin UI to validate gateway connections
* **Persistent Admin UI Filter State** (#177) - filters and view preferences now persist across page refreshes
* **Revamped UI Components** - metrics and version tabs rewritten from scratch for consistency with overall UI layout

### Changed

* **Code Quality - Zero Lint Status** (#338):
  * Resolved all 312 code quality issues across the web stack
  * Updated 14 JavaScript patterns to follow best practices
  * Corrected 2 HTML structure improvements
  * Standardized JavaScript naming conventions
  * Removed unused code for cleaner maintenance

* **Validation Configuration** - new environment variables for customization. Update your `.env`:
  ```bash
  VALIDATION_MAX_NAME_LENGTH=255
  VALIDATION_MAX_DESCRIPTION_LENGTH=4096
  VALIDATION_MAX_JSON_DEPTH=10
  VALIDATION_ALLOWED_URL_SCHEMES=["http://", "https://", "ws://", "wss://"]
  ```

* **Performance** - validation overhead kept under 10ms per request with efficient patterns

---

## [0.3.0] - 2025-07-08

### Added

* **Transport-Translation Bridge (`mcpgateway.translate`)** - bridges local JSON-RPC/stdio servers to HTTP/SSE and vice versa:
  * Expose local stdio MCP servers over SSE endpoints with session management
  * Bridge remote SSE endpoints to local stdio for seamless integration
  * Built-in keepalive mechanisms and unique session identifiers
  * Full CLI support: `python3 -m mcpgateway.translate --stdio "uvx mcp-server-git" --port 9000`

* **Tool Annotations & Metadata** - comprehensive tool annotation system:
  * New `annotations` JSON column in tools table for storing rich metadata
  * UI support for viewing and managing tool annotations
  * Alembic migration scripts for smooth database upgrades (`e4fc04d1a442`)

* **Multi-server Tool Federations** - resolved tool name conflicts across gateways (#116):
  * **Composite Key & UUIDs for Tool Identity** - tools now uniquely identified by `(gateway_id, name)` instead of global name uniqueness
  * Generated `qualified_name` field (`gateway.tool`) for human-readable tool references
  * UUID primary keys for Gateways, Tools, and Servers for future-proof references
  * Enables adding multiple gateways with same-named tools (e.g., multiple `google` tools)

* **Auto-healing & Visibility** - enhanced gateway and tool status management (#159):
  * **Separated `is_active` into `enabled` and `reachable` fields** for better status granularity (#303)
  * Auto-activation of MCP servers when they come back online after being marked unreachable
  * Improved status visibility in Admin UI with proper enabled/reachable indicators

* **Export Connection Strings** - one-click client integration (#154):
  * Generate ready-made configs for LangChain, Claude Desktop, and other MCP clients
  * `/servers/{id}/connect` API endpoint for programmatic access
  * Download connection strings directly from Admin UI

* **Configurable Connection Retries** - resilient startup behavior (#179):
  * `DB_MAX_RETRIES` and `DB_RETRY_INTERVAL_MS` for database connections
  * `REDIS_MAX_RETRIES` and `REDIS_RETRY_INTERVAL_MS` for Redis connections
  * Prevents gateway crashes during slow service startup in containerized environments
  * Sensible defaults (3 retries × 2000ms) with full configurability

* **Dynamic UI Picker** - enhanced tool/resource/prompt association (#135):
  * Searchable multi-select dropdowns replace raw CSV input fields
  * Preview tool metadata (description, request type, integration type) in picker
  * Maintains API compatibility with CSV backend format

* **Developer Experience Improvements**:
  * **Developer Workstation Setup Guide** for Mac (Intel/ARM), Linux, and Windows (#18)
  * Comprehensive environment setup instructions including Docker/Podman, WSL2, and common gotchas
  * Signing commits guide with proper gitconfig examples

* **Infrastructure & DevOps**:
  * **Enhanced Helm charts** with health probes, HPA support, and migration jobs
  * **Fast Go MCP server example** (`mcp-fast-time-server`) for high-performance demos (#265)
  * Database migration management with proper Alembic integration
  * Init containers for database readiness checks

### Changed

* **Database Schema Evolution**:
  * `tools.name` no longer globally unique - now uses composite key `(gateway_id, name)`
  * Migration from single `is_active` field to separate `enabled` and `reachable` boolean fields
  * Added UUID primary keys for better federation support and URL-safe references
  * Moved Alembic configuration inside `mcpgateway` package for proper wheel packaging

* **Enhanced Federation Manager**:
  * Updated to use new `enabled` and `reachable` fields instead of deprecated `is_active`
  * Improved gateway synchronization and health check logic
  * Better error handling for offline tools and gateways

* **Improved Code Quality**:
  * **Fixed Pydantic v2 compatibility** - replaced deprecated patterns:
    * `Field(..., env=...)` → `model_config` with BaseSettings
    * `class Config` → `model_config = ConfigDict(...)`
    * `@validator` → `@field_validator`
    * `.dict()` → `.model_dump()`, `.parse_obj()` → `.model_validate()`
  * **Replaced deprecated stdlib functions** - `datetime.utcnow()` → `datetime.now(timezone.utc)`
  * **Pylint improvements** across codebase with better configuration and reduced warnings

* **File System & Deployment**:
  * **Fixed file lock path** - now correctly uses `/tmp/gateway_service_leader.lock` instead of current directory (#316)
  * Improved Docker and Helm deployment with proper health checks and resource limits
  * Better CI/CD integration with updated linting and testing workflows

### Fixed

* **UI/UX Fixes**:
  * **Close button for parameter input** in Global Tools tab now works correctly (#189)
  * **Gateway modal status display** - fixed `isActive` → `enabled && reachable` logic (#303)
  * Dark mode improvements and consistent theme application (#26)

* **API & Backend Fixes**:
  * **Gateway reactivation warnings** - fixed 'dict' object Pydantic model errors (#28)
  * **GitHub Remote Server addition** - resolved server registration flow issues (#152)
  * **REST path parameter substitution** - improved payload handling for REST APIs (#100)
  * **Missing await on coroutine** - fixed async response handling in tool service

* **Build & Packaging**:
  * **Alembic configuration packaging** - migration scripts now properly included in pip wheels (#302)
  * **SBOM generation failure** - fixed documentation build issues (#132)
  * **Makefile image target** - resolved Docker build and documentation generation (#131)

* **Testing & Quality**:
  * **Improved test coverage** - especially in `test_tool_service.py` reaching 90%+ coverage
  * **Redis connection handling** - better error handling and lazy imports
  * **Fixed flaky tests** and improved stability across test suite
  * **Pydantic v2 compatibility warnings** - resolved deprecated patterns and stdlib functions (#197)

### Security

* **Enhanced connection validation** with configurable retry mechanisms
* **Improved credential handling** in Basic Auth and JWT implementations
* **Better error handling** to prevent information leakage in federation scenarios

---

### 🙌 New contributors in 0.3.0

Thanks to the **first-time contributors** who delivered features in 0.3.0:

| Contributor              | Contributions                                                               |
| ------------------------ | --------------------------------------------------------------------------- |
| **Irusha Basukala**      | Comprehensive Developer Workstation Setup Guide for Mac, Linux, and Windows |
| **Michael Moyles**       | Fixed close button functionality for parameter input scheme in UI           |
| **Reeve Barreto**        | Configurable connection retries for DB and Redis with extensive testing     |
| **Chris PC-39**          | Major pylint improvements and code quality enhancements                     |
| **Ruslan Magana**        | Watsonx.ai Agent documentation and integration guides                       |
| **Shaikh Quader**        | macOS-specific setup documentation                                          |
| **Mohan Lakshmaiah**     | Test case updates and coverage improvements                                 |

### 🙏 Returning contributors who delivered in 0.3.0

| Contributor          | Key contributions                                                                                                                                                                                                                   |
| -------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Mihai Criveti**    | **Release coordination**, code reviews, mcpgateway.translate stdio ↔ SSE, overall architecture, Issue Creation, Helm chart enhancements, HPA support, pylint configuration, documentation updates, isort cleanup, and infrastructure improvements                                                                         |
| **Manav Gupta**      | **Transport-Translation Bridge** mcpgateway.translate Reverse SSE ↔ stdio bridging,                                                                                                                |
| **Madhav Kandukuri** | **Composite Key & UUIDs migration**, Alembic integration, extensive test coverage improvements, database schema evolution, and tool service enhancements                                                                            |
| **Keval Mahajan**    | **Auto-healing capabilities**, enabled/reachable status migration, federation UI improvements, file lock path fixes, and wrapper functionality                                                                                      |

## [0.2.0] - 2025-06-24

### Added

* **Streamable HTTP transport** - full first-class support for MCP's new default transport (deprecated SSE):

  * gateway accepts Streamable HTTP client connections (stateful & stateless). SSE support retained.
  * UI & API allow registering Streamable HTTP MCP servers with health checks, auth & time-outs
  * UI now shows a *transport* column for each gateway/tool;
* **Authentication & stateful sessions** for Streamable HTTP clients/servers (Basic/Bearer headers, session persistence).
* **Gateway hardening** - connection-level time-outs and smarter health-check retries to avoid UI hangs
* **Fast Go MCP server example** - high-performance reference server for benchmarking/demos.
* **Exportable connection strings** - one-click download & `/servers/{id}/connect` API that generates ready-made configs for LangChain, Claude Desktop, etc. (closed #154).
* **Infrastructure as Code** - initial Terraform & Ansible scripts for cloud installs.
* **Developer tooling & UX**

  * `tox`, GH Actions *pytest + coverage* workflow
  * pre-commit linters (ruff, flake8, yamllint) & security scans
  * dark-mode theme and compact version-info panel in Admin UI
  * developer onboarding checklist in docs.
* **Deployment assets** - Helm charts now accept external secrets/Redis; Fly.io guide; Docker-compose local-image switch; Helm deployment walkthrough.

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

Welcome aboard-your PRs made 0.2.0 measurably better! 🎉

---

### 🙏 Returning contributors who went the extra mile in 0.2.0

| Contributor          | Highlights this release                                                                                                                                                                                                                                                                                                                                   |
| -------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Mihai Criveti**    | Release management & 0.2.0 version bump, Helm-chart refactor + deployment guide, full CI revamp (pytest + coverage, pre-commit linters, tox), **333 green unit tests**, security updates, build updates, fully automated deployment to Code Engine, improved helm stack, doc & GIF refresh                                                                                                                                                    |
| **Keval Mahajan**    | Implemented **Streamable HTTP** transport (client + server) with auth & stateful sessions, transport column in UI, gateway time-outs, extensive test fixes and linting                                                                                                                                                                                    |
| **Madhav Kandukuri** |- Wrote **ADRs for tool-federation & dropdown UX** <br>- Polished the new **dark-mode** theme<br>- Authored **Issue #154** that specified the connection-string export feature<br>- Plus multiple stability fixes (async DB, gateway add/del, UV sync, Basic-Auth headers) |
| **Manav Gupta**      | Fixed SBOM generation & license verification, repaired Makefile image/doc targets, improved Docker quick-start and Fly.io deployment docs                                                                                                                                                                                                                 |

*Huge thanks for keeping the momentum going! 🚀*


## [0.1.1] - 2025-06-14

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

## [0.1.0] - 2025-06-01

### Added

Initial public release of MCP Gateway - a FastAPI-based gateway and federation layer for the Model Context Protocol (MCP). This preview brings a fully-featured core, production-grade deployment assets and an opinionated developer experience.

Setting up GitHub repo, CI/CD with GitHub Actions, templates, `good first issue`, etc.

#### 🚪 Core protocol & gateway
* 📡 **MCP protocol implementation** - initialise, ping, completion, sampling, JSON-RPC fallback
* 🌐 **Gateway layer** in front of multiple MCP servers with peer discovery & federation

#### 🔄 Adaptation & transport
* 🧩 **Virtual-server wrapper & REST-to-MCP adapter** with JSON-Schema validation, retry & rate-limit policies
* 🔌 **Multi-transport support** - HTTP/JSON-RPC, WebSocket, Server-Sent Events and stdio

#### 🖥️ User interface & security
* 📊 **Web-based Admin UI** (HTMX + Alpine.js + Tailwind) with live metrics
* 🛡️ **JWT & HTTP-Basic authentication**, AES-encrypted credential storage, per-tool rate limits

#### 📦 Packaging & deployment recipes
* 🐳 **Container images** on GHCR, self-signed TLS recipe, health-check endpoint
* 🚀 **Deployment recipes** - Gunicorn config, Docker/Podman/Compose, Kubernetes, Helm, IBM Cloud Code Engine, AWS, Azure, Google Cloud Run

#### 🛠️ Developer & CI tooling
* 📝 **Comprehensive Makefile** (80 + targets), linting, > 400 tests, CI pipelines & badges
* ⚙️ **Dev & CI helpers** - hot-reload dev server, Ruff/Black/Mypy/Bandit, Trivy image scan, SBOM generation, SonarQube helpers

#### 🗄️ Persistence & performance
* 🐘 **SQLAlchemy ORM** with pluggable back-ends (SQLite default; PostgreSQL, MySQL, etc.)
* 🚦 **Fine-tuned connection pooling** (`DB_POOL_SIZE`, `DB_MAX_OVERFLOW`, `DB_POOL_RECYCLE`) for high-concurrency deployments

### 📈 Observability & metrics
* 📜 **Structured JSON logs** and **/metrics endpoint** with per-tool / per-gateway counters

### 📚 Documentation
* 🔗 **Comprehensive MkDocs site** - [https://ibm.github.io/mcp-context-forge/deployment/](https://ibm.github.io/mcp-context-forge/deployment/)


### Changed

* *Nothing - first tagged version.*

### Fixed

* *N/A*

---

### Release links

* **Source diff:** [`v0.1.0`](https://github.com/IBM/mcp-context-forge/releases/tag/v0.1.0)
