# MCP Gateway Roadmap

!!! info "Release Overview"
    This roadmap outlines the planned development milestones for MCP Gateway, organized by release version with completion status and due dates.

## Release Status Summary

| Release | Due Date    | Completion | Status     | Description |
| ------- | ----------- | ---------- | ---------- | ----------- |
| 1.6.0   | 06 Jan 2026 | 0 %        | Open       | TBD |
| 1.5.0   | 23 Dec 2025 | 0 %        | Open       | TBD |
| 1.4.0   | 09 Dec 2025 | 0 %        | Open       | TBD |
| 1.3.0   | 25 Nov 2025 | 0 %        | Open       | Catalog Improvements, A2A Improvements, MCP Standard Review and Sync, Technical Debt |
| 1.2.0   | 11 Nov 2025 | 0 %        | Open       | Catalog Enhancements, Ratings, experience and UI |
| 1.1.0   | 28 Oct 2025 | 0 %        | Open       | Post-GA Testing, Bugfixing, Documentation, Performance and Scale |
| 1.0.0   | 14 Oct 2025 | 0 %        | Open       | General Availability & Release Candidate Hardening - stable & audited |
| 0.9.0   | 30 Sep 2025 | 8 %        | Open       | Interoperability, marketplaces & advanced connectivity |
| 0.8.0   | 16 Sep 2025 | 0 %        | Open       | Enterprise Security & Policy Guardrails |
| 0.7.0   | 02 Sep 2025 | 0 %        | Open       | Multitenancy and RBAC (Private/Team/Global catalogs), Extended Connectivity, Core Observability & Starter Agents (OpenAI and A2A) |
| 0.6.0   | 19 Aug 2025 | 0 %        | Open       | Security, Scale & Smart Automation |
| 0.5.0   | 05 Aug 2025 | 0 %        | Open       | Enterprise Operability, Auth, Configuration & Observability |
| 0.4.0   | 22 Jul 2025 | 19 %       | Open       | Bugfixes, Resilience (retry with exponential backoff), code quality and technical debt |
| 0.3.0   | 08 Jul 2025 | 100 %      | **Closed** | Annotations and multi-server tool federations |
| 0.2.0   | 24 Jun 2025 | 100 %      | **Closed** | Streamable HTTP, Infra-as-Code, Dark Mode |
| 0.1.0   | 05 Jun 2025 | 100 %      | **Closed** | Initial release |

---

## Release 0.1.0 - Initial Release

!!! success "Release 0.1.0 - Completed (100%)"
    **Due:** June 5, 2025 | **Status:** Closed
    Initial release with core functionality and basic deployment support.

???+ check "✨ Features (3)"
    - [**#27**](https://github.com/IBM/mcp-context-forge/issues/27) - Add /ready endpoint for readiness probe
    - [**#24**](https://github.com/IBM/mcp-context-forge/issues/24) - Publish Helm chart for Kubernetes deployment
    - [**#23**](https://github.com/IBM/mcp-context-forge/issues/23) - Add VS Code Devcontainer support for instant onboarding

???+ check "🐛 Bugs (3)"
    - [**#49**](https://github.com/IBM/mcp-context-forge/issues/49) - Make venv install serve fails with "python: command not found"
    - [**#37**](https://github.com/IBM/mcp-context-forge/issues/37) - Issues with the gateway Container Image
    - [**#35**](https://github.com/IBM/mcp-context-forge/issues/35) - Error when running in Docker Desktop for Windows

???+ check "📚 Documentation (2)"
    - [**#50**](https://github.com/IBM/mcp-context-forge/issues/50) - Virtual env location is incorrect
    - [**#30**](https://github.com/IBM/mcp-context-forge/issues/30) - Deploying to Google Cloud Run

---

## Release 0.2.0 - Streamable HTTP, Infra-as-Code, Dark Mode

!!! success "Release 0.2.0 - Completed (100%)"
    **Due:** June 24, 2025 | **Status:** Closed
    Enhanced transport capabilities and improved user experience.

???+ check "✨ Features (3)"
    - [**#125**](https://github.com/IBM/mcp-context-forge/issues/125) - Add Streamable HTTP MCP servers to Gateway
    - [**#109**](https://github.com/IBM/mcp-context-forge/issues/109) - Implement Streamable HTTP Transport for Client Connections to MCP Gateway
    - [**#25**](https://github.com/IBM/mcp-context-forge/issues/25) - Add "Version and Environment Info" tab to Admin UI

???+ check "🐛 Bugs (2)"
    - [**#85**](https://github.com/IBM/mcp-context-forge/issues/85) - Internal server error comes if there is any error while adding an entry or any crud operation is happening
    - [**#51**](https://github.com/IBM/mcp-context-forge/issues/51) - Internal server running when running gunicorn after install

???+ check "📚 Documentation (3)"
    - [**#98**](https://github.com/IBM/mcp-context-forge/issues/98) - Add additional information for using the mcpgateway with Claude desktop
    - [**#71**](https://github.com/IBM/mcp-context-forge/issues/71) - Documentation Over Whelming Cannot figure out the basic task of adding an MCP server
    - [**#21**](https://github.com/IBM/mcp-context-forge/issues/21) - Deploying to Fly.io

---

## Release 0.3.0 - Annotations and Multi-Server Tool Federations

!!! success "Release 0.3.0 - Completed (100%)"
    **Due:** July 8, 2025 | **Status:** Closed
    Focus on tool federation and server management improvements.

???+ check "✨ Features (7)"
    - [**#265**](https://github.com/IBM/mcp-context-forge/issues/265) - Sample MCP Server - Go (fast-time-server)
    - [**#159**](https://github.com/IBM/mcp-context-forge/issues/159) - Add auto activation of mcp-server, when it goes up back again
    - [**#154**](https://github.com/IBM/mcp-context-forge/issues/154) - Export connection strings to various clients from UI and via API
    - [**#135**](https://github.com/IBM/mcp-context-forge/issues/135) - Dynamic UI Picker for Tool, Resource, and Prompt Associations
    - [**#116**](https://github.com/IBM/mcp-context-forge/issues/116) - Namespace Composite Key & UUIDs for Tool Identity
    - [**#100**](https://github.com/IBM/mcp-context-forge/issues/100) - Add path parameter or replace value in input payload for a REST API
    - [**#26**](https://github.com/IBM/mcp-context-forge/issues/26) - Add dark mode toggle to Admin UI

???+ check "🐛 Bugs (7)"
    - [**#316**](https://github.com/IBM/mcp-context-forge/issues/316) - Correctly create filelock_path: str = "tmp/gateway_service_leader.lock" in /tmp not current directory
    - [**#303**](https://github.com/IBM/mcp-context-forge/issues/303) - Update manager.py and admin.js removed `is_active` field - replace with separate `enabled` and `reachable` fields from migration
    - [**#302**](https://github.com/IBM/mcp-context-forge/issues/302) - Alembic configuration not packaged with pip wheel, `pip install . && mcpgateway` fails on db migration
    - [**#197**](https://github.com/IBM/mcp-context-forge/issues/197) - Pytest run exposes warnings from outdated Pydantic patterns, deprecated stdlib functions
    - [**#189**](https://github.com/IBM/mcp-context-forge/issues/189) - Close button for parameter input scheme does not work
    - [**#179**](https://github.com/IBM/mcp-context-forge/issues/179) - Configurable Connection Retries for DB and Redis
    - [**#152**](https://github.com/IBM/mcp-context-forge/issues/152) - Not able to add Github Remote Server
    - [**#132**](https://github.com/IBM/mcp-context-forge/issues/132) - SBOM Generation Failure
    - [**#131**](https://github.com/IBM/mcp-context-forge/issues/131) - Documentation Generation fails due to error in Makefile's image target
    - [**#28**](https://github.com/IBM/mcp-context-forge/issues/28) - Reactivating a gateway logs warning due to 'dict' object used as Pydantic model

???+ check "📚 Documentation (1)"
    - [**#18**](https://github.com/IBM/mcp-context-forge/issues/18) - Add Developer Workstation Setup Guide for Mac (Intel/ARM), Linux, and Windows

---

## Release 0.4.0 - Bugfixes, Resilience & Code Quality

!!! danger "Release 0.4.0 - Open (19%)"
    **Due:** July 22, 2025 | **Status:** Open
    Focus on bugfixes, resilience (retry with exponential backoff), code quality and technical debt (test coverage, linting, security scans, GitHub Actions, Makefile, Helm improvements).

???+ danger "🐛 Open Bugs (2)"
    - [**#232**](https://github.com/IBM/mcp-context-forge/issues/232) - Leaving Auth to None fails
    - [**#213**](https://github.com/IBM/mcp-context-forge/issues/213) - Can't use `STREAMABLEHTTP`

???+ check "🐛 Completed Bugs (2)"
    - [**#340**](https://github.com/IBM/mcp-context-forge/issues/340) - Add input validation for main API endpoints (depends on #339 /admin API validation)
    - [**#339**](https://github.com/IBM/mcp-context-forge/issues/339) - Add input validation for /admin endpoints

???+ danger "✨ Open Features (4)"
    - [**#323**](https://github.com/IBM/mcp-context-forge/issues/323) - [Docs]: Add Developer Guide for using fast-time-server via JSON-RPC commands using curl or stdio
    - [**#320**](https://github.com/IBM/mcp-context-forge/issues/320) - [Feature Request]: Update Streamable HTTP to fully support Virtual Servers
    - [**#258**](https://github.com/IBM/mcp-context-forge/issues/258) - Universal Client Retry Mechanisms with Exponential Backoff & Random Jitter
    - [**#234**](https://github.com/IBM/mcp-context-forge/issues/234) - 🧠 Protocol Feature - Elicitation Support (MCP 2025-06-18)
    - [**#233**](https://github.com/IBM/mcp-context-forge/issues/233) - Contextual Hover-Help Tooltips in UI
    - [**#217**](https://github.com/IBM/mcp-context-forge/issues/217) - Graceful-Shutdown Hooks for API & Worker Containers (SIGTERM-safe rollouts, DB-pool cleanup, zero-drop traffic)
    - [**#172**](https://github.com/IBM/mcp-context-forge/issues/172) - Enable Auto Refresh and Reconnection for MCP Servers in Gateways

???+ check "✨ Completed Features (2)"
    - [**#181**](https://github.com/IBM/mcp-context-forge/issues/181) - Test MCP Server Connectivity Debugging Tool
    - [**#177**](https://github.com/IBM/mcp-context-forge/issues/177) - Persistent Admin UI Filter State

???+ danger "🔧 Open Chores (23)"
    - [**#351**](https://github.com/IBM/mcp-context-forge/issues/351) - Checklist for complete End-to-End Validation Testing for All API Endpoints, UI and Data Validation
    - [**#344**](https://github.com/IBM/mcp-context-forge/issues/344) - Implement additional security headers and CORS configuration
    - [**#342**](https://github.com/IBM/mcp-context-forge/issues/342) - Implement database-level security constraints and SQL injection prevention
    - [**#341**](https://github.com/IBM/mcp-context-forge/issues/341) - Enhance UI security with DOMPurify and content sanitization
    - [**#317**](https://github.com/IBM/mcp-context-forge/issues/317) - [CHORE]: Script to add relative file path header to each file and verify top level docstring
    - [**#315**](https://github.com/IBM/mcp-context-forge/issues/315) - [CHORE] Check SPDX headers Makefile and GitHub Actions target - ensure all files have File, Author(s) and SPDX headers
    - [**#312**](https://github.com/IBM/mcp-context-forge/issues/312) - [CHORE]: End-to-End MCP Gateway Stack Testing Harness (mcpgateway, translate, wrapper, mcp-servers)
    - [**#307**](https://github.com/IBM/mcp-context-forge/issues/307) - [CHORE]: GitHub Actions to build docs, with diagrams and test report, and deploy to GitHub Pages using MkDocs on every push to main
    - [**#305**](https://github.com/IBM/mcp-context-forge/issues/305) - [CHORE]: Add vulture (dead code detect) and unimport (unused import detect) to Makefile and GitHub Actions
    - [**#292**](https://github.com/IBM/mcp-context-forge/issues/292) - [CHORE]: Enable AI Alliance Analytics Stack Integration
    - [**#281**](https://github.com/IBM/mcp-context-forge/issues/281) - [CHORE]: Set up contract testing with Pact (pact-python) including Makefile and GitHub Actions targets
    - [**#280**](https://github.com/IBM/mcp-context-forge/issues/280) - [CHORE]: Add mutation testing with mutmut for test quality validation
    - [**#279**](https://github.com/IBM/mcp-context-forge/issues/279) - [CHORE]: Implement security audit and vulnerability scanning with grype in Makefile and GitHub Actions
    - [**#261**](https://github.com/IBM/mcp-context-forge/issues/261) - [CHORE]: Implement 90% Test Coverage Quality Gate and automatic badge and coverage html / markdown report publication
    - [**#260**](https://github.com/IBM/mcp-context-forge/issues/260) - [CHORE]: Manual security testing plan and template for release validation and production deployments
    - [**#259**](https://github.com/IBM/mcp-context-forge/issues/259) - [CHORE]: SAST (Semgrep) and DAST (OWASP ZAP) automated security testing Makefile targets and GitHub Actions
    - [**#256**](https://github.com/IBM/mcp-context-forge/issues/256) - [CHORE]: Implement comprehensive fuzz testing automation and Makefile targets (hypothesis, atheris, schemathesis , RESTler)
    - [**#255**](https://github.com/IBM/mcp-context-forge/issues/255) - [CHORE]: Implement comprehensive Playwright test automation for the entire MCP Gateway Admin UI with Makefile targets and GitHub Actions
    - [**#254**](https://github.com/IBM/mcp-context-forge/issues/254) - [CHORE]: Async Code Testing and Performance Profiling Makefile targets (flake8-async, cprofile, snakeviz, aiomonitor)
    - [**#253**](https://github.com/IBM/mcp-context-forge/issues/253) - [CHORE]: Implement chaos engineering tests for fault tolerance validation (network partitions, service failures)
    - [**#252**](https://github.com/IBM/mcp-context-forge/issues/252) - [CHORE]: Establish database migration testing pipeline with rollback validation across SQLite, Postgres, and Redis
    - [**#251**](https://github.com/IBM/mcp-context-forge/issues/251) - [CHORE]: Automatic performance testing and tracking for every build (hey) including SQLite and Postgres / Redis configurations
    - [**#250**](https://github.com/IBM/mcp-context-forge/issues/250) - [CHORE]: Implement automatic API documentation generation using mkdocstrings and update Makefile
    - [**#249**](https://github.com/IBM/mcp-context-forge/issues/249) - [CHORE]: Achieve 100% doctest coverage and add Makefile and CI/CD targets for doctest and coverage
    - [**#223**](https://github.com/IBM/mcp-context-forge/issues/223) - [CHORE]: Helm Chart Test Harness & Red Hat chart-verifier
    - [**#222**](https://github.com/IBM/mcp-context-forge/issues/222) - [CHORE]: Helm chart build Makefile with lint and values.schema.json validation + CODEOWNERS, CHANGELOG.md, .helmignore and CONTRIBUTING.md
    - [**#216**](https://github.com/IBM/mcp-context-forge/issues/216) - [CHORE]: Add spec-validation targets and make the OpenAPI build go green
    - [**#212**](https://github.com/IBM/mcp-context-forge/issues/212) - [CHORE]: Achieve zero flagged Bandit / SonarQube issues
    - [**#211**](https://github.com/IBM/mcp-context-forge/issues/211) - [CHORE]: Achieve Zero Static-Type Errors Across All Checkers (mypy, ty, pyright, pyrefly)
    - [**#210**](https://github.com/IBM/mcp-context-forge/issues/210) - [CHORE]: Raise pylint from 9.16/10 -> 10/10

???+ check "🔧 Completed Chores (2)"
    - [**#338**](https://github.com/IBM/mcp-context-forge/issues/338) - Eliminate all lint issues in web stack
    - [**#336**](https://github.com/IBM/mcp-context-forge/issues/336) - Implement output escaping for user data in UI

???+ danger "📚 Open Documentation (2)"
    - [**#94**](https://github.com/IBM/mcp-context-forge/issues/94) - [Feature Request]: Transport-Translation Bridge (`mcpgateway.translate`) any to any protocol conversion cli tool
    - [**#46**](https://github.com/IBM/mcp-context-forge/issues/46) - [Docs]: Add documentation for using mcp-cli with MCP Gateway
    - [**#19**](https://github.com/IBM/mcp-context-forge/issues/19) - [Docs]: Add Developer Guide for using MCP via the CLI (curl commands, JSON-RPC)

---

## Release 0.5.0 - Enterprise Operability, Auth, Configuration & Observability

!!! danger "Release 0.5.0 - Open (0%)"
    **Due:** August 5, 2025 | **Status:** Open
    Enterprise-grade authentication, configuration management, and comprehensive observability.

???+ danger "✨ Open Features (13)"
    - [**#284**](https://github.com/IBM/mcp-context-forge/issues/284) - [Feature Request]: LDAP / Active-Directory Integration
    - [**#278**](https://github.com/IBM/mcp-context-forge/issues/278) - [Feature Request]: Authentication & Authorization - Google SSO Integration Tutorial (Depends on #220)
    - [**#277**](https://github.com/IBM/mcp-context-forge/issues/277) - [Feature Request]: Authentication & Authorization - GitHub SSO Integration Tutorial (Depends on #220)
    - [**#272**](https://github.com/IBM/mcp-context-forge/issues/272) - [Feature Request]: Observability - Pre-built Grafana Dashboards & Loki Log Export
    - [**#220**](https://github.com/IBM/mcp-context-forge/issues/220) - [Feature Request]: Authentication & Authorization - SSO + Identity-Provider Integration
    - [**#218**](https://github.com/IBM/mcp-context-forge/issues/218) - [Feature Request]: Prometheus Metrics Instrumentation using prometheus-fastapi-instrumentator
    - [**#186**](https://github.com/IBM/mcp-context-forge/issues/186) - [Feature Request]: Granular Configuration Export & Import (via UI & API)
    - [**#185**](https://github.com/IBM/mcp-context-forge/issues/185) - [Feature Request]: Portable Configuration Export & Import CLI (registry, virtual servers and prompts)
    - [**#138**](https://github.com/IBM/mcp-context-forge/issues/138) - [Feature Request]: View & Export Logs from Admin UI
    - [**#137**](https://github.com/IBM/mcp-context-forge/issues/137) - [Feature Request]: Track Creator & Timestamp Metadata for Servers, Tools, and Resources
    - [**#136**](https://github.com/IBM/mcp-context-forge/issues/136) - [Feature Request]: Downloadable JSON Client Config Generator from Admin UI
    - [**#87**](https://github.com/IBM/mcp-context-forge/issues/87) - [Feature Request]: Epic: JWT Token Catalog with Per-User Expiry and Revocation
    - [**#80**](https://github.com/IBM/mcp-context-forge/issues/80) - [Feature Request]: Publish a multi-architecture container (including ARM64) support

---

## Release 0.6.0 - Security, Scale & Smart Automation

!!! danger "Release 0.6.0 - Open (0%)"
    **Due:** August 19, 2025 | **Status:** Open
    Advanced security features, scalability improvements, and intelligent automation capabilities.

???+ danger "✨ Open Features (10)"
    - [**#301**](https://github.com/IBM/mcp-context-forge/issues/301) - [Feature Request]: Full Circuit Breakers for Unstable MCP Server Backends support (extend existing healthchecks with half-open state)
    - [**#289**](https://github.com/IBM/mcp-context-forge/issues/289) - [Feature Request]: Multi-Layer Caching System (Memory + Redis)
    - [**#287**](https://github.com/IBM/mcp-context-forge/issues/287) - [Feature Request]: API Path Versioning /v1 and /experimental prefix
    - [**#286**](https://github.com/IBM/mcp-context-forge/issues/286) - [Feature Request]: Dynamic Configuration UI & Admin API (store config in database after db init)
    - [**#282**](https://github.com/IBM/mcp-context-forge/issues/282) - [Feature Request]: Per-Virtual-Server API Keys with Scoped Access
    - [**#276**](https://github.com/IBM/mcp-context-forge/issues/276) - [Feature Request]: Terraform Module - "mcp-gateway-ibm-cloud" supporting IKS, ROKS, Code Engine targets
    - [**#275**](https://github.com/IBM/mcp-context-forge/issues/275) - [Feature Request]: Terraform Module - "mcp-gateway-gcp" supporting GKE and Cloud Run
    - [**#274**](https://github.com/IBM/mcp-context-forge/issues/274) - [Feature Request]: Terraform Module - "mcp-gateway-azure" supporting AKS and ACA
    - [**#273**](https://github.com/IBM/mcp-context-forge/issues/273) - [Feature Request]: Terraform Module - "mcp-gateway-aws" supporting both EKS and ECS Fargate targets
    - [**#208**](https://github.com/IBM/mcp-context-forge/issues/208) - [Feature Request]: HTTP Header Passthrough

???+ danger "🔧 Open Chores (1)"
    - [**#313**](https://github.com/IBM/mcp-context-forge/issues/313) - [DESIGN]: Architecture Decisions and Discussions for AI Middleware and Plugin Framework (Enables #319)

---

## Release 0.7.0 - Multitenancy and RBAC

!!! danger "Release 0.7.0 - Open (0%)"
    **Due:** September 2, 2025 | **Status:** Open
    Multitenancy and RBAC (Private/Team/Global catalogs), Extended Connectivity, Core Observability & Starter Agents (OpenAI and A2A).

???+ danger "✨ Open Features (7)"
    - [**#300**](https://github.com/IBM/mcp-context-forge/issues/300) - [Feature Request]: Structured JSON Logging with Correlation IDs
    - [**#283**](https://github.com/IBM/mcp-context-forge/issues/283) - [Feature Request]: Role-Based Access Control (RBAC) - User/Team/Global Scopes for full multi-tenancy support
    - [**#270**](https://github.com/IBM/mcp-context-forge/issues/270) - [Feature Request]: MCP Server - Go Implementation ("libreoffice-server")
    - [**#269**](https://github.com/IBM/mcp-context-forge/issues/269) - [Feature Request]: MCP Server - Go Implementation (LaTeX Service)
    - [**#263**](https://github.com/IBM/mcp-context-forge/issues/263) - [Feature Request]: Sample Agent - CrewAI Integration (OpenAI & A2A Endpoints)
    - [**#262**](https://github.com/IBM/mcp-context-forge/issues/262) - [Feature Request]: Sample Agent - LangChain Integration (OpenAI & A2A Endpoints)
    - [**#175**](https://github.com/IBM/mcp-context-forge/issues/175) - [Feature Request]: Add OpenLLMetry Integration for Observability

---

## Release 0.8.0 - Enterprise Security & Policy Guardrails

!!! danger "Release 0.8.0 - Open (0%)"
    **Due:** September 16, 2025 | **Status:** Open
    Comprehensive enterprise security features and policy enforcement mechanisms.

???+ danger "✨ Open Features (8)"
    - [**#319**](https://github.com/IBM/mcp-context-forge/issues/319) - [Feature Request]: AI Middleware Integration / Plugin Framework for extensible gateway capabilities
    - [**#285**](https://github.com/IBM/mcp-context-forge/issues/285) - [Feature Request]: Configuration Validation & Schema Enforcement using Pydantic V2 models, config validator cli flag
    - [**#271**](https://github.com/IBM/mcp-context-forge/issues/271) - [Feature Request]: Policy-as-Code Engine - Rego Prototype
    - [**#257**](https://github.com/IBM/mcp-context-forge/issues/257) - [Feature Request]: Gateway-Level Rate Limiting, DDoS Protection & Abuse Detection
    - [**#230**](https://github.com/IBM/mcp-context-forge/issues/230) - [Feature Request]: Cryptographic Request & Response Signing
    - [**#229**](https://github.com/IBM/mcp-context-forge/issues/229) - [Feature Request]: Guardrails - Input/Output Sanitization & PII Masking
    - [**#221**](https://github.com/IBM/mcp-context-forge/issues/221) - [Feature Request]: Gateway-Level Input Validation & Output Sanitization (prevent traversal)
    - [**#182**](https://github.com/IBM/mcp-context-forge/issues/182) - [Feature Request]: Semantic tool auto-filtering

???+ danger "🔧 Open Chores (1)"
    - [**#291**](https://github.com/IBM/mcp-context-forge/issues/291) - [CHORE]: Comprehensive Scalability & Soak-Test Harness (Long-term Stability & Load) - locust, pytest-benchmark, smocker mocked MCP servers

---

## Release 0.9.0 - Interoperability, Marketplaces & Advanced Connectivity

!!! danger "Release 0.9.0 - Open (8%)"
    **Due:** September 30, 2025 | **Status:** Open
    Enhanced interoperability, marketplace features, and advanced connectivity options.

???+ danger "✨ Open Features (11)"
    - [**#298**](https://github.com/IBM/mcp-context-forge/issues/298) - [Feature Request]: A2A Initial Support - Add A2A Servers as Tools
    - [**#295**](https://github.com/IBM/mcp-context-forge/issues/295) - [Feature Request]: MCP Server Marketplace
    - [**#294**](https://github.com/IBM/mcp-context-forge/issues/294) - [Feature Request]: Automated MCP Server Testing and Certification
    - [**#288**](https://github.com/IBM/mcp-context-forge/issues/288) - [Feature Request]: MariaDB Support Testing, Documentation, CI/CD (alongside PostgreSQL & SQLite)
    - [**#268**](https://github.com/IBM/mcp-context-forge/issues/268) - [Feature Request]: Sample MCP Server - Haskell Implementation ("pandoc-server") (html, docx, pptx, latex conversion)
    - [**#267**](https://github.com/IBM/mcp-context-forge/issues/267) - [Feature Request]: Sample MCP Server - Java Implementation ("plantuml-server")
    - [**#266**](https://github.com/IBM/mcp-context-forge/issues/266) - [Feature Request]: Sample MCP Server - Rust Implementation ("filesystem-server")
    - [**#209**](https://github.com/IBM/mcp-context-forge/issues/209) - [Feature Request]: Anthropic Desktop Extensions DTX directory/marketplace
    - [**#130**](https://github.com/IBM/mcp-context-forge/issues/130) - [Feature Request]: Dynamic LLM-Powered Tool Generation via Prompt
    - [**#123**](https://github.com/IBM/mcp-context-forge/issues/123) - [Feature Request]: Dynamic Server Catalog via Rule, Regexp, Tags - or LLM-Based Selection
    - [**#114**](https://github.com/IBM/mcp-context-forge/issues/114) - [Feature Request]: Connect to Dockerized MCP Servers via STDIO

???+ danger "🔧 Open Chores (1)"
    - [**#290**](https://github.com/IBM/mcp-context-forge/issues/290) - [CHORE]: Enhance Gateway Tuning Guide with PostgreSQL Deep-Dive

???+ check "✨ Completed Features (1)"
    - [**#243**](https://github.com/IBM/mcp-context-forge/issues/243) - [Feature Request]: a2a compatibility?

---

## Release 1.0.0 - General Availability & Release Candidate Hardening

!!! danger "Release 1.0.0 - Open (0%)"
    **Due:** October 14, 2025 | **Status:** Open
    Stable and audited release for general availability.

???+ danger "📚 Open Documentation (1)"
    - [**#264**](https://github.com/IBM/mcp-context-forge/issues/264) - [DOCS]: GA Documentation Review & End-to-End Validation Audit

---

## Release 1.1.0 - Post-GA Testing, Bugfixing, Documentation, Performance and Scale

!!! danger "Release 1.1.0 - Open (0%)"
    **Due:** October 28, 2025 | **Status:** Open
    Post-launch improvements and performance optimizations.

???+ danger "✨ Open Features (1)"
    - [**#293**](https://github.com/IBM/mcp-context-forge/issues/293) - [Feature Request]: Intelligent Load Balancing for Redundant MCP Servers

---

## Release 1.2.0 - Catalog Enhancements, Ratings, Experience and UI

!!! danger "Release 1.2.0 - Open (0%)"
    **Due:** November 11, 2025 | **Status:** Open
    Enhanced catalog features and improved user experience.

???+ danger "✨ Open Features (1)"
    - [**#296**](https://github.com/IBM/mcp-context-forge/issues/296) - [Feature Request]: MCP Server Rating and Review System

---

## Release 1.3.0 - Catalog Improvements, A2A Improvements, MCP Standard Review and Sync, Technical Debt

!!! danger "Release 1.3.0 - Open (0%)"
    **Due:** November 25, 2025 | **Status:** Open
    Catalog improvements, A2A enhancements, and technical debt resolution.

???+ danger "✨ Open Features (1)"
    - [**#299**](https://github.com/IBM/mcp-context-forge/issues/299) - [Feature Request]: A2A Ecosystem Integration & Marketplace (Extends A2A support)

---

## Release 1.4.0

!!! danger "Release 1.4.0 - Open (0%)"
    **Due:** December 9, 2025 | **Status:** Open
    TBD

*No issues currently assigned to this release.*

---

## Release 1.5.0

!!! danger "Release 1.5.0 - Open (0%)"
    **Due:** December 23, 2025 | **Status:** Open
    TBD

*No issues currently assigned to this release.*

---

## Release 1.6.0

!!! danger "Release 1.6.0 - Open (0%)"
    **Due:** January 6, 2026 | **Status:** Open
    TBD

*No issues currently assigned to this release.*

---

## Unassigned Issues

!!! warning "Issues Without Release Assignment"
    The following issues are currently open but not assigned to any specific release:

???+ warning "🐛 Open Bugs (1)"
    - [**#352**](https://github.com/IBM/mcp-context-forge/issues/352) - Resources - All data going into content

???+ warning "🔧 Open Chores (1)"
    - [**#318**](https://github.com/IBM/mcp-context-forge/issues/318) - [CHORE]: Publish Agents and Tools that leverage codebase and templates (draft)

???+ warning "📚 Open Documentation (1)"
    - [**#22**](https://github.com/IBM/mcp-context-forge/issues/22) - [Docs]: Add BeeAI Framework client integration (Python & TypeScript)

---

## Recently Closed Issues

!!! success "Recently Completed"
    The following issues have been recently closed:

???+ check "✨ Completed Features (1)"
    - [**#306**](https://github.com/IBM/mcp-context-forge/issues/306) - [Bug]: Quick Start (manual install) gunicorn fails

---

## Legend

- ✨ **Feature Request** - New functionality or enhancement
- 🐛 **Bug** - Issues that need to be fixed
- 🔧 **Chore** - Maintenance, tooling, or infrastructure work
- 📚 **Documentation** - Documentation improvements or additions

!!! tip "Contributing"
    Want to contribute to any of these features? Check out the individual GitHub issues for more details and discussion!

## Pending Issue Creation

### ⚙️ Lifecycle & Management
1. **Virtual Server Protocol Version Selection** - Allow choosing which MCP protocol version each virtual server uses dynamically (mentioned as possible through ENV variables but should be dynamic)

2. **CLI Enhancements for Admin Operations** - CLI subcommands for registering tools, flushing caches, exporting configs for CI/CD integration

3. **Cache Management API** - Endpoints to view cache stats and clear entries for data freshness management

### 🛠️ Developer Experience
4. **Prompt Template Tester & Validator** - Preview and validate Jinja2 templates with sample data to avoid runtime errors

5. **System Diagnostics & Self-Check Report** - Self-contained system report (config, health, metrics) for troubleshooting

6. **Auto-Tuning of Timeout & Retry Policies** - Automatically adjust timeouts and retry intervals based on observed latencies

7. **Chrome MCP Plugin Integration** - Browser extension for managing MCP configurations, servers, and connections

### 🔐 Secrets & Sensitive Data
8. **Secure Secrets Management & Masking** - External secrets store integration (Vault)
