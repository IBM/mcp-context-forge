# MCP Gateway Roadmap

!!! info "Release Overview"
    This roadmap outlines the planned development milestones for MCP Gateway, organized by release version with completion status and due dates.


## Release Status Summary

| Release | Due Date    | Completion | Status       | Description |
| ------- | ----------- | ---------- | ------------ | ----------- |
| 1.3.0   | 26 May 2026 |  0 %       | Open         | New MCP Servers and Agents |
| 1.2.0   | 28 Apr 2026 |  0 %       | Open         | Documentation, Technical Debt, Bugfixes |
| 1.1.0   | 31 Mar 2026 |  0 %       | Open         | Technical Debt and Quality |
| 1.0.0-GA | 24 Feb 2026 |  0 %       | Open         | Catalog Improvements, A2A Improvements, MCP Standard Review and Sync, Technical Debt |
| 1.0.0-RC1 | 03 Feb 2026 |  0 %       | Open         | Release Candidate 1 - Catalog Enhancements, Ratings, experience and UI |
| 1.0.0-BETA-2 | 20 Jan 2026 |  1 %       | Open         | Testing, Bugfixing, Documentation, Performance and Scale |
| 1.0.0-BETA-1 | 16 Dec 2025 | 100 %       | **Closed**   | Release 1.0.0-BETA-1 |
| 0.9.0   | 09 Nov 2025 | 100 %      | **Closed**   | Interoperability, marketplaces & advanced connectivity |
| 0.8.0   | 07 Oct 2025 | 100 %      | **Closed**   | Enterprise Security & Policy Guardrails |
| 0.7.0   | 16 Sep 2025 | 100 %      | **Closed**   | Multitenancy and RBAC (Private/Team/Global catalogs), Extended Connectivity, Core Observability & Starter Agents (OpenAI and A2A) |
| 0.6.0   | 19 Aug 2025 | 100 %      | **Closed**   | Security, Scale & Smart Automation |
| 0.5.0   | 05 Aug 2025 | 100 %      | **Closed**   | Enterprise Operability, Auth, Configuration & Observability |
| 0.4.0   | 22 Jul 2025 | 100 %      | **Closed**   | Bugfixes, Security, Resilience (retry with exponential backoff), code quality and technical debt (test coverage, linting, security scans, GitHub Actions, Makefile, Helm improvements) |
| 0.3.0   | 08 Jul 2025 | 100 %      | **Closed**   | Annotations and multi-server tool federations |
| 0.2.0   | 24 Jun 2025 | 100 %      | **Closed**   | Streamable HTTP, Infra-as-Code, Dark Mode |
| 0.1.0   | 05 Jun 2025 | 100 %      | **Closed**   | Initial release |

---

## Release 1.3.0

!!! warning "Release 1.3.0 - In Progress (0%)"
    **Due:** 26 May 2026 | **Status:** Open
    New MCP Servers and Agents

???+ info "✨ Features - Remaining (37)"

    - ⏳ [**#114**](https://github.com/IBM/mcp-context-forge/issues/114) - [Feature Request]: Connect to Dockerized MCP Servers via STDIO
    - ⏳ [**#175**](https://github.com/IBM/mcp-context-forge/issues/175) - [Feature Request]: Add OpenLLMetry Integration for Observability
    - ⏳ [**#209**](https://github.com/IBM/mcp-context-forge/issues/209) - [Feature Request]: Anthropic Desktop Extensions DTX directory/marketplace
    - ⏳ [**#218**](https://github.com/IBM/mcp-context-forge/issues/218) - [Feature Request]: Prometheus Metrics Instrumentation using prometheus-fastapi-instrumentator
    - ⏳ [**#258**](https://github.com/IBM/mcp-context-forge/issues/258) - [Feature Request]: Universal Client Retry Mechanisms with Exponential Backoff & Random Jitter
    - ⏳ [**#266**](https://github.com/IBM/mcp-context-forge/issues/266) - [Feature Request]: Sample MCP Server - Rust Implementation ("filesystem-server")
    - ⏳ [**#267**](https://github.com/IBM/mcp-context-forge/issues/267) - [Feature Request]: Sample MCP Server – Java Implementation ("plantuml-server")
    - ⏳ [**#272**](https://github.com/IBM/mcp-context-forge/issues/272) - [Feature Request]: Observability - Pre-built Grafana Dashboards & Loki Log Export
    - ⏳ [**#273**](https://github.com/IBM/mcp-context-forge/issues/273) - [Feature Request]: Terraform Module - "mcp-gateway-aws" supporting both EKS and ECS Fargate targets
    - ⏳ [**#274**](https://github.com/IBM/mcp-context-forge/issues/274) - [Feature Request]: Terraform Module - "mcp-gateway-azure" supporting AKS and ACA
    - ⏳ [**#275**](https://github.com/IBM/mcp-context-forge/issues/275) - [Feature Request]: Terraform Module - "mcp-gateway-gcp" supporting GKE and Cloud Run
    - ⏳ [**#276**](https://github.com/IBM/mcp-context-forge/issues/276) - [Feature Request]: Terraform Module – "mcp-gateway-ibm-cloud" supporting IKS, ROKS, Code Engine targets
    - ⏳ [**#286**](https://github.com/IBM/mcp-context-forge/issues/286) - [Feature Request]: Dynamic Configuration UI & Admin API (store config in database after db init)
    - ⏳ [**#295**](https://github.com/IBM/mcp-context-forge/issues/295) - [Feature Request]: MCP Server Marketplace and Registry
    - ⏳ [**#300**](https://github.com/IBM/mcp-context-forge/issues/300) - [Feature Request]: Structured JSON Logging with Correlation IDs
    - ⏳ [**#301**](https://github.com/IBM/mcp-context-forge/issues/301) - [Feature Request]: Full Circuit Breakers for Unstable MCP Server Backends support (extend existing healthchecks with half-open state)
    - ⏳ [**#505**](https://github.com/IBM/mcp-context-forge/issues/505) - [Feature Request]: Add ENV token forwarding management per tool (draft)
    - ⏳ [**#546**](https://github.com/IBM/mcp-context-forge/issues/546) - [Feature Request]: Protocol Version Negotiation & Backward Compatibility
    - ⏳ [**#548**](https://github.com/IBM/mcp-context-forge/issues/548) - [Feature]: GraphQL API Support for Tool Discovery
    - ⏳ [**#565**](https://github.com/IBM/mcp-context-forge/issues/565) - [Feature Request]: Docs for https://github.com/block/goose (draft)
    - ⏳ [**#751**](https://github.com/IBM/mcp-context-forge/issues/751) - [Feature] MCP Server - Implement MCP Evaluation Benchmarks Suite
    - ⏳ [**#896**](https://github.com/IBM/mcp-context-forge/issues/896) - Add Prompt Authoring Tools Category to MCP Eval Server
    - ⏳ [**#897**](https://github.com/IBM/mcp-context-forge/issues/897) - Sample MCP Server - Go (database-query-server)
    - ⏳ [**#899**](https://github.com/IBM/mcp-context-forge/issues/899) - Sample MCP Server - Python (ml-inference-server)
    - ⏳ [**#901**](https://github.com/IBM/mcp-context-forge/issues/901) - Sample MCP Server - Rust (crypto-tools-server)
    - ⏳ [**#902**](https://github.com/IBM/mcp-context-forge/issues/902) - Sample MCP Server - Rust (performance-benchmark-server)
    - ⏳ [**#903**](https://github.com/IBM/mcp-context-forge/issues/903) - Sample MCP Server - TypeScript (web-automation-server)
    - ⏳ [**#904**](https://github.com/IBM/mcp-context-forge/issues/904) - Sample MCP Server - TypeScript (real-time-collaboration-server)
    - ⏳ [**#905**](https://github.com/IBM/mcp-context-forge/issues/905) - Create IBM Granite Language Models MCP Server
    - ⏳ [**#906**](https://github.com/IBM/mcp-context-forge/issues/906) - Create IBM Granite Vision Models MCP Server
    - ⏳ [**#907**](https://github.com/IBM/mcp-context-forge/issues/907) - Create IBM Granite Speech Models MCP Server
    - ⏳ [**#908**](https://github.com/IBM/mcp-context-forge/issues/908) - Create IBM Granite Time Series Models MCP Server
    - ⏳ [**#909**](https://github.com/IBM/mcp-context-forge/issues/909) - Create IBM Granite Guardian Safety Models MCP Server
    - ⏳ [**#910**](https://github.com/IBM/mcp-context-forge/issues/910) - Create IBM Granite Geospatial Models MCP Server
    - ⏳ [**#911**](https://github.com/IBM/mcp-context-forge/issues/911) - Create IBM Granite Embedding Models MCP Server
    - ⏳ [**#919**](https://github.com/IBM/mcp-context-forge/issues/919) - Sample MCP Server - Python (qr-code-server)
    - ⏳ [**#921**](https://github.com/IBM/mcp-context-forge/issues/921) - Sample MCP Server - Python (weather-data-server)

???+ info "🔒 Security - Remaining (1)"

    - ⏳ [**#542**](https://github.com/IBM/mcp-context-forge/issues/542) - [SECURITY FEATURE]: Helm Chart - Enterprise Secrets Management Integration (Vault)

???+ info "📚 Documentation - Remaining (1)"

    - ⏳ [**#22**](https://github.com/IBM/mcp-context-forge/issues/22) - [Docs]: Add BeeAI Framework client integration (Python & TypeScript)

---


## Release 1.2.0

!!! warning "Release 1.2.0 - In Progress (0%)"
    **Due:** 28 Apr 2026 | **Status:** Open
    Documentation, Technical Debt, Bugfixes

???+ info "📋 Epics - Remaining (3)"

    - ⏳ [**#1245**](https://github.com/IBM/mcp-context-forge/issues/1245) - 🔌 Epic: Security Clearance Levels Plugin - Bell-LaPadula MAC Implementation
    - ⏳ [**#1247**](https://github.com/IBM/mcp-context-forge/issues/1247) - 🔌 Epic: Per-Virtual-Server Plugin Selection with Multi-Level RBAC
    - ⏳ [**#1286**](https://github.com/IBM/mcp-context-forge/issues/1286) - [Epic] 🔍 MCP Compliance Checker - Automated Specification Testing Tool

???+ info "✨ Features - Remaining (6)"

    - ⏳ [**#284**](https://github.com/IBM/mcp-context-forge/issues/284) - [AUTH FEATURE]: LDAP / Active-Directory Integration
    - ⏳ [**#285**](https://github.com/IBM/mcp-context-forge/issues/285) - [Feature Request]: Configuration Validation & Schema Enforcement using Pydantic V2 models, config validator cli flag
    - ⏳ [**#683**](https://github.com/IBM/mcp-context-forge/issues/683) - [Feature Request]: Debug headers and passthrough headers, e.g. X-Tenant-Id, X-Trace-Id, Authorization for time server (go) (draft)
    - ⏳ [**#706**](https://github.com/IBM/mcp-context-forge/issues/706) - [Feature Request]: ABAC Virtual Server Support
    - ⏳ [**#738**](https://github.com/IBM/mcp-context-forge/issues/738) - [Feature Request]: Configuration Database for Dynamic Settings Management
    - ⏳ [**#912**](https://github.com/IBM/mcp-context-forge/issues/912) - Sample Agent - IBM BeeAI Framework Integration (OpenAI & A2A Endpoints)

---


## Release 1.1.0

!!! warning "Release 1.1.0 - In Progress (0%)"
    **Due:** 31 Mar 2026 | **Status:** Open
    Technical Debt and Quality

???+ info "✨ Features - Remaining (4)"

    - ⏳ [**#123**](https://github.com/IBM/mcp-context-forge/issues/123) - [Feature Request]: Dynamic Server Catalog via Rule, Regexp, Tags - or Embedding / LLM-Based Selection
    - ⏳ [**#130**](https://github.com/IBM/mcp-context-forge/issues/130) - [Feature Request]: Dynamic LLM-Powered Tool Generation via Prompt
    - ⏳ [**#182**](https://github.com/IBM/mcp-context-forge/issues/182) - [Feature Request]: Semantic tool auto-filtering
    - ⏳ [**#294**](https://github.com/IBM/mcp-context-forge/issues/294) - [Feature Request]: Automated MCP Server Testing and Certification

???+ info "🔧 Chores - Remaining (1)"

    - ⏳ [**#1290**](https://github.com/IBM/mcp-context-forge/issues/1290) - [CHORE] Remove redundant import checkers: importchecker and unimport

---


## Release 1.0.0-GA

!!! warning "Release 1.0.0-GA - In Progress (0%)"
    **Due:** 24 Feb 2026 | **Status:** Open
    Catalog Improvements, A2A Improvements, MCP Standard Review and Sync, Technical Debt

???+ info "✨ Features - Remaining (1)"

    - ⏳ [**#299**](https://github.com/IBM/mcp-context-forge/issues/299) - [Feature Request]: A2A Ecosystem Integration & Marketplace (Extends A2A support)

???+ info "🔒 Security - Remaining (1)"

    - ⏳ [**#257**](https://github.com/IBM/mcp-context-forge/issues/257) - [SECURITY FEATURE]: Gateway-Level Rate Limiting, DDoS Protection & Abuse Detection

---


## Release 1.0.0-RC1

!!! warning "Release 1.0.0-RC1 - In Progress (0%)"
    **Due:** 03 Feb 2026 | **Status:** Open
    Release Candidate 1 - Catalog Enhancements, Ratings, experience and UI

???+ info "✨ Features - Remaining (5)"

    - ⏳ [**#287**](https://github.com/IBM/mcp-context-forge/issues/287) - [Feature Request]: API Path Versioning /v1 and /experimental prefix
    - ⏳ [**#296**](https://github.com/IBM/mcp-context-forge/issues/296) - [Feature Request]: MCP Server Rating and Review System
    - ⏳ [**#547**](https://github.com/IBM/mcp-context-forge/issues/547) - [Feature]: Built-in MCP Server Health Dashboard
    - ⏳ [**#636**](https://github.com/IBM/mcp-context-forge/issues/636) - [Feature]: Add PyInstaller support for building standalone binaries for all platforms
    - ⏳ [**#1413**](https://github.com/IBM/mcp-context-forge/issues/1413) - [Feature]: Add maturity levels to plugins

???+ info "🔧 Chores - Remaining (12)"

    - ⏳ [**#211**](https://github.com/IBM/mcp-context-forge/issues/211) - [CHORE]: Achieve Zero Static-Type Errors Across All Checkers (mypy, ty, pyright, pyrefly)
    - ⏳ [**#212**](https://github.com/IBM/mcp-context-forge/issues/212) - [CHORE]: Achieve zero flagged SonarQube issues
    - ⏳ [**#216**](https://github.com/IBM/mcp-context-forge/issues/216) - [CHORE]: Add spec-validation targets and make the OpenAPI build go green
    - ⏳ [**#222**](https://github.com/IBM/mcp-context-forge/issues/222) - [CHORE]: Helm chart build Makefile with lint and values.schema.json validation + CODEOWNERS, CHANGELOG.md, .helmignore and CONTRIBUTING.md
    - ⏳ [**#223**](https://github.com/IBM/mcp-context-forge/issues/223) - [CHORE]: Helm Chart Test Harness & Red Hat chart-verifier
    - ⏳ [**#250**](https://github.com/IBM/mcp-context-forge/issues/250) - [CHORE]: Implement automatic API documentation generation using mkdocstrings and update Makefile
    - ⏳ [**#252**](https://github.com/IBM/mcp-context-forge/issues/252) - [CHORE]: Establish database migration testing pipeline with rollback validation across SQLite, Postgres, and Redis
    - ⏳ [**#255**](https://github.com/IBM/mcp-context-forge/issues/255) - [CHORE]: Implement comprehensive Playwright test automation for the entire MCP Gateway Admin UI with Makefile targets and GitHub Actions
    - ⏳ [**#292**](https://github.com/IBM/mcp-context-forge/issues/292) - [CHORE]: Enable AI Alliance Analytics Stack Integration
    - ⏳ [**#307**](https://github.com/IBM/mcp-context-forge/issues/307) - [CHORE]: GitHub Actions to build docs, with diagrams and test report, and deploy to GitHub Pages using MkDocs on every push to main
    - ⏳ [**#318**](https://github.com/IBM/mcp-context-forge/issues/318) - [CHORE]: Publish Agents and Tools that leverage codebase and templates (draft)
    - ⏳ [**#1340**](https://github.com/IBM/mcp-context-forge/issues/1340) - [CHORE] Proposal: Split Monorepo into Separate Repositories

---


## Release 1.0.0-BETA-2

!!! warning "Release 1.0.0-BETA-2 - In Progress (1%)"
    **Due:** 20 Jan 2026 | **Status:** Open
    Testing, Bugfixing, Documentation, Performance and Scale

???+ check "✨ Features - Completed (2)"

    - ✅ [**#1148**](https://github.com/IBM/mcp-context-forge/issues/1148) - [Feature]: Full Stack CICD build and deployment of MCP CF through single configuration
    - ✅ [**#1318**](https://github.com/IBM/mcp-context-forge/issues/1318) - [Feature Request]: While creating Virtual Server can we have tool list in <server_name>_<tool_name> format

???+ info "📋 Epics - Remaining (19)"

    - ⏳ [**#1224**](https://github.com/IBM/mcp-context-forge/issues/1224) - Epic: REST API and UI Pagination for Large-Scale Multi-Tenant Deployments
    - ⏳ [**#1285**](https://github.com/IBM/mcp-context-forge/issues/1285) - [Epic]: Fully implement MCP 2025-06-18 compliance across all endpoints
    - ⏳ [**#1293**](https://github.com/IBM/mcp-context-forge/issues/1293) - [Epic] 🌐 Performance - HTTP/2 & Keep-Alive Transport
    - ⏳ [**#1295**](https://github.com/IBM/mcp-context-forge/issues/1295) - [Epic] 📦 Performance - Static Asset Caching & CDN
    - ⏳ [**#1296**](https://github.com/IBM/mcp-context-forge/issues/1296) - [Epic] 💾 Performance - Redis Endpoint Response Caching
    - ⏳ [**#1297**](https://github.com/IBM/mcp-context-forge/issues/1297) - [Epic] ⚙️ Performance - Production Server Tuning
    - ⏳ [**#1304**](https://github.com/IBM/mcp-context-forge/issues/1304) - [Epic]: Implement SEP-1649 MCP Server Cards Discovery
    - ⏳ [**#1305**](https://github.com/IBM/mcp-context-forge/issues/1305) - [Epic] AI Service Discovery and Gateway Proxy
    - ⏳ [**#1306**](https://github.com/IBM/mcp-context-forge/issues/1306) - [Epic] Billing and Metering Plugin with Guaranteed Message Delivery
    - ⏳ [**#1315**](https://github.com/IBM/mcp-context-forge/issues/1315) - [Epic] 📚 UI Field Documentation - Context-Sensitive Help
    - ⏳ [**#1353**](https://github.com/IBM/mcp-context-forge/issues/1353) - [Epic] 💾 Performance - Database Indexing Optimization
    - ⏳ [**#1354**](https://github.com/IBM/mcp-context-forge/issues/1354) - [Epic] 🐘 Performance - PostgreSQL Database Tuning & Optimization
    - ⏳ [**#1355**](https://github.com/IBM/mcp-context-forge/issues/1355) - [Epic] 💾 Document Backup & Restore - Data Protection Strategy
    - ⏳ [**#1358**](https://github.com/IBM/mcp-context-forge/issues/1358) - 🏷️ Epic: Configurable Tag Restrictions - Whitelist Enforcement
    - ⏳ [**#1359**](https://github.com/IBM/mcp-context-forge/issues/1359) - 📋 Epic: Custom Metadata Fields - Rich Extensible Metadata System
    - ⏳ [**#1365**](https://github.com/IBM/mcp-context-forge/issues/1365) - 📋 Epic: Unified Search & Filter - Consistent Cross-Tab Discovery
    - ⏳ [**#1374**](https://github.com/IBM/mcp-context-forge/issues/1374) - 🔐 Epic: Two-Factor Authentication (2FA) - TOTP/Google Authenticator Support
    - ⏳ [**#1377**](https://github.com/IBM/mcp-context-forge/issues/1377) - 🛡️ Epic: A2AS Framework - Runtime Security and Self-Defense for MCP and A2A
    - ⏳ [**#1417**](https://github.com/IBM/mcp-context-forge/issues/1417) - [Epic]: Improve plugins hygiene

???+ info "✨ Features - Remaining (66)"

    - ⏳ [**#172**](https://github.com/IBM/mcp-context-forge/issues/172) - [Feature Request]: Enable Auto Refresh and Reconnection for MCP Servers in Gateways
    - ⏳ [**#217**](https://github.com/IBM/mcp-context-forge/issues/217) - [Feature Request]: Graceful-Shutdown Hooks for API & Worker Containers (SIGTERM-safe rollouts, DB-pool cleanup, zero-drop traffic)
    - ⏳ [**#234**](https://github.com/IBM/mcp-context-forge/issues/234) - [Feature Request]: 🧠 Protocol Feature – Elicitation Support (MCP 2025-06-18)
    - ⏳ [**#262**](https://github.com/IBM/mcp-context-forge/issues/262) - [Feature Request]: Sample Agent - LangChain Integration (OpenAI & A2A Endpoints)
    - ⏳ [**#263**](https://github.com/IBM/mcp-context-forge/issues/263) - [Feature Request]: Sample Agent - CrewAI Integration (OpenAI & A2A Endpoints)
    - ⏳ [**#268**](https://github.com/IBM/mcp-context-forge/issues/268) - [Feature Request]: Sample MCP Server - Haskell Implementation ("pandoc-server") (html, docx, pptx, latex conversion)
    - ⏳ [**#269**](https://github.com/IBM/mcp-context-forge/issues/269) - [Feature Request]: MCP Server - Go Implementation (LaTeX Service)
    - ⏳ [**#270**](https://github.com/IBM/mcp-context-forge/issues/270) - [Feature Request]: MCP Server – Go Implementation ("libreoffice-server")
    - ⏳ [**#289**](https://github.com/IBM/mcp-context-forge/issues/289) - [Feature Request]: Multi-Layer Caching System (Memory + Redis)
    - ⏳ [**#293**](https://github.com/IBM/mcp-context-forge/issues/293) - [Feature Request]: Intelligent Load Balancing for Redundant MCP Servers
    - ⏳ [**#545**](https://github.com/IBM/mcp-context-forge/issues/545) - [Feature Request]: Hot-Reload Configuration Without Restart (move from .env to configuration database table) (draft)
    - ⏳ [**#566**](https://github.com/IBM/mcp-context-forge/issues/566) - [Feature Request]: Add support for limiting specific fields to user defined values (draft)
    - ⏳ [**#568**](https://github.com/IBM/mcp-context-forge/issues/568) - [Feature]: mTLS support (gateway and plugins), configurable client require TLS cert, and certificate setup for MCP Servers with private CA
    - ⏳ [**#647**](https://github.com/IBM/mcp-context-forge/issues/647) - Configurable caching for tools (draft)
    - ⏳ [**#654**](https://github.com/IBM/mcp-context-forge/issues/654) - [Feature Request]: Pre-register checks (mcp server scan) (draft)
    - ⏳ [**#707**](https://github.com/IBM/mcp-context-forge/issues/707) - [Feature Request]: Customizable Admin Panel
    - ⏳ [**#732**](https://github.com/IBM/mcp-context-forge/issues/732) - [Feature Request]: Enhance Handling of Long Tool Descriptions
    - ⏳ [**#743**](https://github.com/IBM/mcp-context-forge/issues/743) - [Feature Request]: Enhance Server Creation/Editing UI for Prompt and Resource Association
    - ⏳ [**#756**](https://github.com/IBM/mcp-context-forge/issues/756) - [Feature Request]: REST Passthrough APIs with Pre/Post Plugins (JSONPath and filters)
    - ⏳ [**#758**](https://github.com/IBM/mcp-context-forge/issues/758) - Implement missing MCP protocol methods
    - ⏳ [**#782**](https://github.com/IBM/mcp-context-forge/issues/782) - [Feature Request]: OAuth Enhancement following PR 768
    - ⏳ [**#848**](https://github.com/IBM/mcp-context-forge/issues/848) - [Feature Request]: Allow same prompt name when adding two different mcp server
    - ⏳ [**#871**](https://github.com/IBM/mcp-context-forge/issues/871) - Document Langflow integration with MCP Gateway
    - ⏳ [**#872**](https://github.com/IBM/mcp-context-forge/issues/872) - Document watsonx.ai integration with MCP Gateway
    - ⏳ [**#873**](https://github.com/IBM/mcp-context-forge/issues/873) - Document watsonx Orchestrate integration with MCP Gateway
    - ⏳ [**#874**](https://github.com/IBM/mcp-context-forge/issues/874) - Document IBM Decision Intelligence MCP Server integration with MCP Gateway
    - ⏳ [**#875**](https://github.com/IBM/mcp-context-forge/issues/875) - Document IBM MQ Server MCP integration with MCP Gateway
    - ⏳ [**#876**](https://github.com/IBM/mcp-context-forge/issues/876) - Document IBM ODM MCP Server integration with MCP Gateway
    - ⏳ [**#877**](https://github.com/IBM/mcp-context-forge/issues/877) - Document IBM watsonx.data Document Retrieval MCP Server integration with MCP Gateway
    - ⏳ [**#878**](https://github.com/IBM/mcp-context-forge/issues/878) - Document IBM Cloud MCP Server integration with MCP Gateway
    - ⏳ [**#879**](https://github.com/IBM/mcp-context-forge/issues/879) - Document IBM Cloud Code Engine MCP Server integration with MCP Gateway
    - ⏳ [**#880**](https://github.com/IBM/mcp-context-forge/issues/880) - Document IBM Cloud VPC MCP Server integration with MCP Gateway
    - ⏳ [**#881**](https://github.com/IBM/mcp-context-forge/issues/881) - Document IBM Instana MCP Server integration with MCP Gateway
    - ⏳ [**#882**](https://github.com/IBM/mcp-context-forge/issues/882) - Document IBM Storage Insights MCP Server integration with MCP Gateway
    - ⏳ [**#883**](https://github.com/IBM/mcp-context-forge/issues/883) - Document IBM API Connect for GraphQL MCP integration with MCP Gateway
    - ⏳ [**#884**](https://github.com/IBM/mcp-context-forge/issues/884) - Document WxMCPServer (webMethods Hybrid Integration) integration with MCP Gateway
    - ⏳ [**#885**](https://github.com/IBM/mcp-context-forge/issues/885) - Document Terraform MCP Server integration with MCP Gateway
    - ⏳ [**#886**](https://github.com/IBM/mcp-context-forge/issues/886) - Document Vault Radar MCP Server integration with MCP Gateway
    - ⏳ [**#887**](https://github.com/IBM/mcp-context-forge/issues/887) - Document DataStax Astra DB MCP Server integration with MCP Gateway
    - ⏳ [**#888**](https://github.com/IBM/mcp-context-forge/issues/888) - Document Docling MCP Server integration with MCP Gateway
    - ⏳ [**#889**](https://github.com/IBM/mcp-context-forge/issues/889) - Document MCP Composer integration with MCP Gateway
    - ⏳ [**#890**](https://github.com/IBM/mcp-context-forge/issues/890) - Document Langflow as MCP Server integration with MCP Gateway
    - ⏳ [**#891**](https://github.com/IBM/mcp-context-forge/issues/891) - Document BeeAI Framework integration with MCP Gateway
    - ⏳ [**#892**](https://github.com/IBM/mcp-context-forge/issues/892) - Update and test IBM Cloud deployment documentation and automation
    - ⏳ [**#913**](https://github.com/IBM/mcp-context-forge/issues/913) - Document Atlassian MCP Server integration with MCP Gateway
    - ⏳ [**#914**](https://github.com/IBM/mcp-context-forge/issues/914) - Document Box MCP Server integration with MCP Gateway
    - ⏳ [**#915**](https://github.com/IBM/mcp-context-forge/issues/915) - Document GitHub MCP Server integration with MCP Gateway
    - ⏳ [**#916**](https://github.com/IBM/mcp-context-forge/issues/916) - Document monday.com MCP Server integration with MCP Gateway
    - ⏳ [**#917**](https://github.com/IBM/mcp-context-forge/issues/917) - Document Hugging Face MCP Server integration with MCP Gateway
    - ⏳ [**#918**](https://github.com/IBM/mcp-context-forge/issues/918) - Document Javadocs.dev MCP Server integration with MCP Gateway
    - ⏳ [**#950**](https://github.com/IBM/mcp-context-forge/issues/950) - Session Management & Tool Invocation with Gateway vs Direct MCP Client–Server
    - ⏳ [**#974**](https://github.com/IBM/mcp-context-forge/issues/974) - [Feature Request]: Make users change default admin passwords and secrets for production deployments
    - ⏳ [**#975**](https://github.com/IBM/mcp-context-forge/issues/975) - Feature Request: Implement Session Persistence & Pooling for Improved Performance and State Continuity
    - ⏳ [**#1042**](https://github.com/IBM/mcp-context-forge/issues/1042) - [Feature Request]: Implementation Plan for Root Directory
    - ⏳ [**#1122**](https://github.com/IBM/mcp-context-forge/issues/1122) - [Feature Request]: Investigate Bearer Token Validation in MCP/Forge with Keycloak JWT
    - ⏳ [**#1135**](https://github.com/IBM/mcp-context-forge/issues/1135) - [Feature Request]: Support OPA Bundling for External Policy Downloads
    - ⏳ [**#1136**](https://github.com/IBM/mcp-context-forge/issues/1136) - [Feature Request]: Feature Request: Add depends_on key in plugin configurations
    - ⏳ [**#1140**](https://github.com/IBM/mcp-context-forge/issues/1140) - [Feature]: Reduce Complexity in Plugin Configuration Framework
    - ⏳ [**#1160**](https://github.com/IBM/mcp-context-forge/issues/1160) - [FEATURE REQUEST]: Add Roundtable External MCP Server for Enterprise AI Assistant Orchestration
    - ⏳ [**#1191**](https://github.com/IBM/mcp-context-forge/issues/1191) - [Feature]: Content Limit Plugin - Resource Exhaustion Protection
    - ⏳ [**#1223**](https://github.com/IBM/mcp-context-forge/issues/1223) - [Feature Request]: Resource access audit trail for compliance and security
    - ⏳ [**#1264**](https://github.com/IBM/mcp-context-forge/issues/1264) - [Feature Request]: Support for LDAP Integration with Multiple Domains
    - ⏳ [**#1265**](https://github.com/IBM/mcp-context-forge/issues/1265) - [Feature Request]: Teams has to map to roles & permission
    - ⏳ [**#1266**](https://github.com/IBM/mcp-context-forge/issues/1266) - [Feature Request]: Visibility -> Share it with one or more teams or one or more users
    - ⏳ [**#1267**](https://github.com/IBM/mcp-context-forge/issues/1267) - [Feature Request]: Approval based Promotion of MCP Server to MCP Registry
    - ⏳ [**#1308**](https://github.com/IBM/mcp-context-forge/issues/1308) - [Feature Request]: Add optional persistence support for PostgreSQL and Redis in mcp-stack Helm chart
    - ⏳ [**#1338**](https://github.com/IBM/mcp-context-forge/issues/1338) - [Feature Request]: Enhance REST API Gateway to Support Form Data, Path Parameters, and Dynamic Path Variables
    - ⏳ [**#1356**](https://github.com/IBM/mcp-context-forge/issues/1356) - [Feature Request]: Headers passthrough from mcp server configuration
    - ⏳ [**#1361**](https://github.com/IBM/mcp-context-forge/issues/1361) - [Feature Request]: OpenAPI to REST Protocol Conversion Tool
    - ⏳ [**#1456**](https://github.com/IBM/mcp-context-forge/issues/1456) - [Feature Request]: Migrate from JWT Tokens to Short Opaque API Tokens

???+ info "🦀 Rust Rewrites - Remaining (9)"

    - ⏳ [**#1617**](https://github.com/IBM/mcp-context-forge/issues/1617) - [RUST]: Rewrite translate module in Rust
    - ⏳ [**#1618**](https://github.com/IBM/mcp-context-forge/issues/1618) - [RUST]: Rewrite wrapper module in Rust
    - ⏳ [**#1619**](https://github.com/IBM/mcp-context-forge/issues/1619) - [RUST]: Rewrite reverse-proxy module in Rust
    - ⏳ [**#1620**](https://github.com/IBM/mcp-context-forge/issues/1620) - [RUST]: Implement performance-sensitive plugins in Rust/PyO3
    - ⏳ [**#1621**](https://github.com/IBM/mcp-context-forge/issues/1621) - [RUST]: Rewrite transport layer in Rust
    - ⏳ [**#1622**](https://github.com/IBM/mcp-context-forge/issues/1622) - [RUST]: Implement translate-grpc module in Rust
    - ⏳ [**#1623**](https://github.com/IBM/mcp-context-forge/issues/1623) - [RUST]: Build translate-graphql module in Rust
    - ⏳ [**#1624**](https://github.com/IBM/mcp-context-forge/issues/1624) - [RUST]: Rewrite A2A invocation core in Rust
    - ⏳ [**#1625**](https://github.com/IBM/mcp-context-forge/issues/1625) - [RUST]: Implement high-performance metrics aggregation in Rust

???+ info "⚡ Performance - Remaining (11)"

    - ⏳ [**#251**](https://github.com/IBM/mcp-context-forge/issues/251) - [PERFORMANCE]: Automatic performance testing and tracking for every build (hey) including SQLite and Postgres / Redis configurations
    - ⏳ [**#432**](https://github.com/IBM/mcp-context-forge/issues/432) - [PERFORMANCE]: Performance Optimization Implementation and Guide for MCP Gateway (baseline)
    - ⏳ [**#1608**](https://github.com/IBM/mcp-context-forge/issues/1608) - [PERFORMANCE]: Plugin Framework Memory Optimization: Copy-on-Write for Context State
    - ⏳ [**#1609**](https://github.com/IBM/mcp-context-forge/issues/1609) - [PERFORMANCE]: Fix N+1 and Redundant Query Patterns
    - ⏳ [**#1610**](https://github.com/IBM/mcp-context-forge/issues/1610) - [PERFORMANCE]: Optimize Performance Tracker Buffer Management (O(n) → O(1))
    - ⏳ [**#1611**](https://github.com/IBM/mcp-context-forge/issues/1611) - [PERFORMANCE]: Optimize Startup Slug Refresh with Batch Processing
    - ⏳ [**#1612**](https://github.com/IBM/mcp-context-forge/issues/1612) - [PERFORMANCE]: Reduce SQLite busy_timeout from 30s to 5s (configurable)
    - ⏳ [**#1613**](https://github.com/IBM/mcp-context-forge/issues/1613) - [PERFORMANCE]: Optimize stream parser buffer management (O(n²) → O(n))
    - ⏳ [**#1614**](https://github.com/IBM/mcp-context-forge/issues/1614) - [PERFORMANCE]: Optimize LRU cache eviction (O(n) → O(1))
    - ⏳ [**#1615**](https://github.com/IBM/mcp-context-forge/issues/1615) - [PERFORMANCE]: Eliminate redundant JSON encoding in session registry
    - ⏳ [**#1616**](https://github.com/IBM/mcp-context-forge/issues/1616) - [PERFORMANCE]: Parallelize session cleanup with asyncio.gather()

???+ info "🐛 Bugs - Remaining (9)"

    - ⏳ [**#383**](https://github.com/IBM/mcp-context-forge/issues/383) - [Bug]: Remove migration step from Helm chart (now automated, no longer needed)
    - ⏳ [**#840**](https://github.com/IBM/mcp-context-forge/issues/840) - [Bug]: For A2A Agent test not working
    - ⏳ [**#842**](https://github.com/IBM/mcp-context-forge/issues/842) - [Bug]: 401 on privileged actions after cold restart despite valid login
    - ⏳ [**#1047**](https://github.com/IBM/mcp-context-forge/issues/1047) - [Bug]: MCP Server/Federated Gateway Registration is failing
    - ⏳ [**#1108**](https://github.com/IBM/mcp-context-forge/issues/1108) - [Bug]: When using postgresql as database, high postgresql transaction rollback rate detected
    - ⏳ [**#1187**](https://github.com/IBM/mcp-context-forge/issues/1187) - [Bug]: Latest helm chart not available
    - ⏳ [**#1324**](https://github.com/IBM/mcp-context-forge/issues/1324) - [BUG]: Inconsistent UUID string format across database models
    - ⏳ [**#1325**](https://github.com/IBM/mcp-context-forge/issues/1325) - [Bug]: added keycloak sso to the mcp-context-forge
    - ⏳ [**#1357**](https://github.com/IBM/mcp-context-forge/issues/1357) - [Bug]: Claude Desktop is getting invalid type from mcp-context-forge gateway

???+ info "🔒 Security - Remaining (10)"

    - ⏳ [**#230**](https://github.com/IBM/mcp-context-forge/issues/230) - [SECURITY FEATURE]: Cryptographic Request & Response Signing
    - ⏳ [**#342**](https://github.com/IBM/mcp-context-forge/issues/342) - [SECURITY FEATURE]: Implement database-level security constraints and SQL injection prevention
    - ⏳ [**#534**](https://github.com/IBM/mcp-context-forge/issues/534) - [SECURITY FEATURE]: Add Security Configuration Validation and Startup Checks
    - ⏳ [**#535**](https://github.com/IBM/mcp-context-forge/issues/535) - [SECURITY FEATURE]: Audit Logging System
    - ⏳ [**#536**](https://github.com/IBM/mcp-context-forge/issues/536) - [SECURITY FEATURE]: Generic IP-Based Access Control (allowlist)
    - ⏳ [**#537**](https://github.com/IBM/mcp-context-forge/issues/537) - [SECURITY FEATURE]: Simple Endpoint Feature Flags (selectively enable or disable tools, resources, prompts, servers, gateways, roots)
    - ⏳ [**#538**](https://github.com/IBM/mcp-context-forge/issues/538) - [SECURITY FEATURE] Content Size & Type Security Limits for Resources & Prompts
    - ⏳ [**#539**](https://github.com/IBM/mcp-context-forge/issues/539) - [SECURITY FEATURE]: Tool Execution Limits & Resource Controls
    - ⏳ [**#541**](https://github.com/IBM/mcp-context-forge/issues/541) - [SECURITY FEATURE]: Enhanced Session Management for Admin UI
    - ⏳ [**#543**](https://github.com/IBM/mcp-context-forge/issues/543) - [SECURITY FEATURE]: CSRF Token Protection System

???+ info "🔧 Chores - Remaining (24)"

    - ⏳ [**#253**](https://github.com/IBM/mcp-context-forge/issues/253) - [CHORE]: Implement chaos engineering tests for fault tolerance validation (network partitions, service failures)
    - ⏳ [**#259**](https://github.com/IBM/mcp-context-forge/issues/259) - [CHORE]: SAST (Semgrep) and DAST (OWASP ZAP) automated security testing Makefile targets and GitHub Actions
    - ⏳ [**#260**](https://github.com/IBM/mcp-context-forge/issues/260) - [CHORE]: Manual security testing plan and template for release validation and production deployments
    - ⏳ [**#261**](https://github.com/IBM/mcp-context-forge/issues/261) - [CHORE]: Implement 90% Test Coverage Quality Gate and automatic badge and coverage html / markdown report publication
    - ⏳ [**#281**](https://github.com/IBM/mcp-context-forge/issues/281) - [CHORE]: Set up contract testing with Pact (pact-python) including Makefile and GitHub Actions targets
    - ⏳ [**#290**](https://github.com/IBM/mcp-context-forge/issues/290) - [CHORE]: Enhance Gateway Tuning Guide with PostgreSQL Deep-Dive
    - ⏳ [**#291**](https://github.com/IBM/mcp-context-forge/issues/291) - [CHORE]: Comprehensive Scalability & Soak-Test Harness (Long-term Stability & Load) - locust, pytest-benchmark, smocker mocked MCP servers
    - ⏳ [**#312**](https://github.com/IBM/mcp-context-forge/issues/312) - [CHORE]: End-to-End MCP Gateway Stack Testing Harness (mcpgateway, translate, wrapper, mcp-servers)
    - ⏳ [**#341**](https://github.com/IBM/mcp-context-forge/issues/341) - [CHORE]: Enhance UI security with DOMPurify and content sanitization
    - ⏳ [**#377**](https://github.com/IBM/mcp-context-forge/issues/377) - [CHORE]: Fix PostgreSQL Volume Name Conflicts in Helm Chart (draft)
    - ⏳ [**#391**](https://github.com/IBM/mcp-context-forge/issues/391) - [CHORE]: Setup SonarQube quality gate (draft)
    - ⏳ [**#398**](https://github.com/IBM/mcp-context-forge/issues/398) - [CHORE]: Enforce pre-commit targets for doctest coverage, pytest coverage, pylint score 10/10, flake8 pass and add badges
    - ⏳ [**#402**](https://github.com/IBM/mcp-context-forge/issues/402) - [CHORE]: Add post-deploy step to helm that configures the Time Server as a Gateway (draft)
    - ⏳ [**#407**](https://github.com/IBM/mcp-context-forge/issues/407) - [CHORE]: Improve pytest and plugins (draft)
    - ⏳ [**#408**](https://github.com/IBM/mcp-context-forge/issues/408) - [CHORE]: Add normalize script to pre-commit hooks (draft)
    - ⏳ [**#414**](https://github.com/IBM/mcp-context-forge/issues/414) - [CHORE]: Restructure Makefile targets (ex: move grype to container scanning section), or have a dedicated security scanning section
    - ⏳ [**#574**](https://github.com/IBM/mcp-context-forge/issues/574) - [CHORE]: Run pyupgrade to upgrade python syntax (draft)
    - ⏳ [**#589**](https://github.com/IBM/mcp-context-forge/issues/589) - [CHORE]: generating build provenance attestations for workflow artifacts (draft)
    - ⏳ [**#595**](https://github.com/IBM/mcp-context-forge/issues/595) - [CHORE] Investigate potential migration to UUID7 (draft)
    - ⏳ [**#674**](https://github.com/IBM/mcp-context-forge/issues/674) - [CHORE]: Automate release management process (draft)
    - ⏳ [**#1260**](https://github.com/IBM/mcp-context-forge/issues/1260) - [CHORE]: x86-64-v2 support
    - ⏳ [**#1300**](https://github.com/IBM/mcp-context-forge/issues/1300) - [chore] Transition linter execution from local venv to uvx-driven
    - ⏳ [**#1419**](https://github.com/IBM/mcp-context-forge/issues/1419) - [Test]: QA Plan for Shortlist of Plugins
    - ⏳ [**#1606**](https://github.com/IBM/mcp-context-forge/issues/1606) - refactor(plugin_template): update MCP runtime in plugins template

???+ info "📚 Documentation - Remaining (3)"

    - ⏳ [**#264**](https://github.com/IBM/mcp-context-forge/issues/264) - [DOCS]: GA Documentation Review & End-to-End Validation Audit
    - ⏳ [**#503**](https://github.com/IBM/mcp-context-forge/issues/503) - [Docs]: Tutorial: OpenWebUI with Ollama, LiteLLM, MCPO, and MCP Gateway Deployment Guide (Draft)
    - ⏳ [**#1346**](https://github.com/IBM/mcp-context-forge/issues/1346) - [Docs]: Unclear instructions to test a2a agent as mcp tool

---


## Release 1.0.0-BETA-1

!!! success "Release 1.0.0-BETA-1 - Completed (100%)"
    **Due:** 16 Dec 2025 | **Status:** Closed
    Release 1.0.0-BETA-1

???+ check "✨ Features - Completed (14)"

    - ✅ [**#80**](https://github.com/IBM/mcp-context-forge/issues/80) - [Feature Request]: Publish a multi-architecture container (including ARM64) support
    - ✅ [**#288**](https://github.com/IBM/mcp-context-forge/issues/288) - [Feature Request]: MariaDB Support Testing, Documentation, CI/CD (alongside PostgreSQL & SQLite)
    - ✅ [**#898**](https://github.com/IBM/mcp-context-forge/issues/898) - Sample MCP Server - Go (system-monitor-server)
    - ✅ [**#932**](https://github.com/IBM/mcp-context-forge/issues/932) - [Feature Request]: Air-Gapped Environment Support
    - ✅ [**#1019**](https://github.com/IBM/mcp-context-forge/issues/1019) - [Feature] Authentication Architecture through Plugin System
    - ✅ [**#1138**](https://github.com/IBM/mcp-context-forge/issues/1138) - [Feature Request]: Support for container builds for s390x
    - ✅ [**#1171**](https://github.com/IBM/mcp-context-forge/issues/1171) - [Feature]: gRPC-to-MCP Protocol Translation
    - ✅ [**#1203**](https://github.com/IBM/mcp-context-forge/issues/1203) - [Feature]: Performance Testing & Benchmarking Framework
    - ✅ [**#1219**](https://github.com/IBM/mcp-context-forge/issues/1219) - [Feature]: Benchmark MCP Server for Load Testing and Performance Analysis
    - ✅ [**#1282**](https://github.com/IBM/mcp-context-forge/issues/1282) - [Feature]🔐 Configurable Password Expiration with Forced Password Change on Login
    - ✅ [**#1387**](https://github.com/IBM/mcp-context-forge/issues/1387) - [Feature Request]: Support One-Time Authentication Mode for WXO Integration
    - ✅ [**#1392**](https://github.com/IBM/mcp-context-forge/issues/1392) - Feature Request: Allow Multiple MCP Gateway Registrations with the Same Gateway URL
    - ✅ [**#1442**](https://github.com/IBM/mcp-context-forge/issues/1442) - [Feature Request]: Modify Tool Tag Structure from Array of Strings to List of Objects
    - ✅ [**#1560**](https://github.com/IBM/mcp-context-forge/issues/1560) - [Feature Request]: Test Button for Resource

???+ check "🐛 Bugs - Completed (9)"

    - ✅ [**#464**](https://github.com/IBM/mcp-context-forge/issues/464) - [Bug]: MCP Server "Active" status not getting updated under "Gateways/MCP Servers" when the MCP Server shutdown
    - ✅ [**#1259**](https://github.com/IBM/mcp-context-forge/issues/1259) - [Bug]: MCP Resource is not getting listed
    - ✅ [**#1280**](https://github.com/IBM/mcp-context-forge/issues/1280) - [Bug] Non-standard redirect handling in _validate_gateway_url for STREAMABLEHTTP transport
    - ✅ [**#1395**](https://github.com/IBM/mcp-context-forge/issues/1395) - [Bug]: tool schema team_id not effective
    - ✅ [**#1406**](https://github.com/IBM/mcp-context-forge/issues/1406) - [Bug]: Missing Structured Content for Virtual Server in Streamable HTTP Response
    - ✅ [**#1448**](https://github.com/IBM/mcp-context-forge/issues/1448) - [Bug]: One time auth restricts addition of multiple gateways with same URL since the Auth is None
    - ✅ [**#1522**](https://github.com/IBM/mcp-context-forge/issues/1522) - [Bug]: Implement Concurrent Health Checks for gateways instead of sequential
    - ✅ [**#1523**](https://github.com/IBM/mcp-context-forge/issues/1523) - [Bug]: Severe Performance Degradation Due to N+1 Queries and Non-Batch Operations in Gateway/Tool/Server Services
    - ✅ [**#1577**](https://github.com/IBM/mcp-context-forge/issues/1577) - [Bug]: Support for Passphrase Protected SSL Keys in HTTPS Configuration for Gunicorn/Uvicorn

???+ check "🔒 Security - Completed (1)"

    - ✅ [**#221**](https://github.com/IBM/mcp-context-forge/issues/221) - [SECURITY FEATURE]: Gateway-Level Input Validation & Output Sanitization (prevent traversal)

???+ check "🔧 Chores - Completed (1)"

    - ✅ [**#806**](https://github.com/IBM/mcp-context-forge/issues/806) - [CHORE]: Bulk Import – Missing error messages and registration feedback in UI

---


## Release 0.9.0

!!! success "Release 0.9.0 - Completed (100%)"
    **Due:** 09 Nov 2025 | **Status:** Closed
    Interoperability, marketplaces & advanced connectivity

???+ check "📋 Epics - Completed (4)"

    - ✅ [**#1225**](https://github.com/IBM/mcp-context-forge/issues/1225) - Epic: Production-Scale Load Data Generator for Multi-Tenant Testing
    - ✅ [**#1249**](https://github.com/IBM/mcp-context-forge/issues/1249) - 🦀 Epic: Rust-Powered PII Filter Plugin - 5-10x Performance Improvement
    - ✅ [**#1292**](https://github.com/IBM/mcp-context-forge/issues/1292) - [Epic] 🗜️ Performance - Brotli/Zstd/GZip Response Compression
    - ✅ [**#1294**](https://github.com/IBM/mcp-context-forge/issues/1294) - [Epic] ⚡ Performance - orjson JSON Serialization

???+ check "✨ Features - Completed (16)"

    - ✅ [**#277**](https://github.com/IBM/mcp-context-forge/issues/277) - [Feature Request]: Authentication & Authorization - GitHub SSO Integration Tutorial (Depends on #220)
    - ✅ [**#835**](https://github.com/IBM/mcp-context-forge/issues/835) - [Feature Request]: Adding Custom annotation for the tools
    - ✅ [**#869**](https://github.com/IBM/mcp-context-forge/issues/869) - [Question]: 0.7.0 Release timeline
    - ✅ [**#967**](https://github.com/IBM/mcp-context-forge/issues/967) - UI Gaps in Multi-Tenancy Support - Visibility fields missing for most resource types
    - ✅ [**#969**](https://github.com/IBM/mcp-context-forge/issues/969) - Backend Multi-Tenancy Issues - Critical bugs and missing features
    - ✅ [**#1020**](https://github.com/IBM/mcp-context-forge/issues/1020) - [Feature] Edit Button Functionality - A2A
    - ✅ [**#1093**](https://github.com/IBM/mcp-context-forge/issues/1093) - [Feature Request]: Role-Based Access Control (RBAC) - support generic oAuth provider or ldap provider
    - ✅ [**#1111**](https://github.com/IBM/mcp-context-forge/issues/1111) - [Feature Request]: Support application/x-www-form-urlencoded Requests in MCP Gateway UI for OAuth2 / Keycloak Integration
    - ✅ [**#1137**](https://github.com/IBM/mcp-context-forge/issues/1137) - [Feature Request]: Add missing hooks to OPA plugin
    - ✅ [**#1197**](https://github.com/IBM/mcp-context-forge/issues/1197) - [Feature]: Support Bundle Generation - Automated Diagnostics Collection
    - ✅ [**#1200**](https://github.com/IBM/mcp-context-forge/issues/1200) - [Feature Request]: In built MCP client - LLM Chat service for virtual servers with agentic capabilities and MCP Enabled Tool Orchestration
    - ✅ [**#1209**](https://github.com/IBM/mcp-context-forge/issues/1209) - [Feature]: Finalize RBAC / ABAC implementation to Implement Ownership Checks for Public Resources
    - ✅ [**#1228**](https://github.com/IBM/mcp-context-forge/issues/1228) - [Feature] Show system statistics in metrics page
    - ✅ [**#1239**](https://github.com/IBM/mcp-context-forge/issues/1239) - LLMChat Multi-Worker: Add Documentation and Integration Tests (PR #1236 Follow-up)
    - ✅ [**#1336**](https://github.com/IBM/mcp-context-forge/issues/1336) - [Feature Request]: Add toggles to password/sensitive textboxes to mask/unmask the input value.
    - ✅ [**#1348**](https://github.com/IBM/mcp-context-forge/issues/1348) - [Feature Request]: Add support for IBM Watsonx.ai LLM provider

???+ check "🐛 Bugs - Completed (18)"

    - ✅ [**#409**](https://github.com/IBM/mcp-context-forge/issues/409) - [Bug]: Add configurable limits for data cleaning / XSS prevention in .env.example and helm
    - ✅ [**#448**](https://github.com/IBM/mcp-context-forge/issues/448) - [Bug]:MCP server with custom base path "/api" instead of "mcp" or "sse" is not working
    - ✅ [**#625**](https://github.com/IBM/mcp-context-forge/issues/625) - [Bug]: Gateway unable to register gateway or call tools on MacOS
    - ✅ [**#861**](https://github.com/IBM/mcp-context-forge/issues/861) - [Bug]: Passthrough header parameters not persisted to database
    - ✅ [**#922**](https://github.com/IBM/mcp-context-forge/issues/922) - [Bug]: In 0.6.0 Version, IFraming the admin UI is not working.
    - ✅ [**#926**](https://github.com/IBM/mcp-context-forge/issues/926) - [BUG] Bootstrap fails to assign platform_admin role due to foreign key constraint violation
    - ✅ [**#945**](https://github.com/IBM/mcp-context-forge/issues/945) - [Bug]: Unique Constraint is not allowing Users to create servers/tools/resources/prompts with Names already used by another User
    - ✅ [**#946**](https://github.com/IBM/mcp-context-forge/issues/946) - [Bug]: Alembic migrations fails in docker compose setup
    - ✅ [**#1024**](https://github.com/IBM/mcp-context-forge/issues/1024) - [Bug]: plugin that is using tool_prefetch hook cannot access PASSTHROUGH_HEADERS, tags for an MCP Server Need MCP-GW restart
    - ✅ [**#1092**](https://github.com/IBM/mcp-context-forge/issues/1092) - [Bug]: after issue 1078 change, how to add X-Upstream-Authorization header when click Authorize in admin UI
    - ✅ [**#1094**](https://github.com/IBM/mcp-context-forge/issues/1094) - [Bug]: Creating an MCP OAUTH2 server fails if using API.
    - ✅ [**#1098**](https://github.com/IBM/mcp-context-forge/issues/1098) - [Bug]:Unable to see request payload being sent
    - ✅ [**#1222**](https://github.com/IBM/mcp-context-forge/issues/1222) - [Bug]: Missing name conflict detection for private visibility resources
    - ✅ [**#1248**](https://github.com/IBM/mcp-context-forge/issues/1248) - [Bug]: RBAC Vulnerability: Unauthorized Access to Resource Status Toggling
    - ✅ [**#1254**](https://github.com/IBM/mcp-context-forge/issues/1254) - [Bug]: JWT jti mismatch between token and database record
    - ✅ [**#1258**](https://github.com/IBM/mcp-context-forge/issues/1258) - [Bug]: MCP Tool outputSchema Field is Stripped During Discovery
    - ✅ [**#1261**](https://github.com/IBM/mcp-context-forge/issues/1261) - [Bug]: API Token Expiry Issue: UI Configuration overridden by default env Variable
    - ✅ [**#1381**](https://github.com/IBM/mcp-context-forge/issues/1381) - [Bug]: Resource view error - mime type handling for resource added via mcp server

---

## Release 0.8.0 - Enterprise Security & Policy Guardrails

!!! success "Release 0.8.0 - Completed (100%)"
    **Due:** 07 Oct 2025 | **Status:** Closed
    Enterprise Security & Policy Guardrails

???+ check "✨ Completed Features (17)"

    - ✅ [**#1176**](https://github.com/IBM/mcp-context-forge/issues/1176) - [Feature Request]: Implement Team-Level Scoping for API Tokens
    - ✅ [**#1043**](https://github.com/IBM/mcp-context-forge/issues/1043) - [Feature]: Sample MCP Server - Implement Pandoc MCP server in Go
    - ✅ [**#1035**](https://github.com/IBM/mcp-context-forge/issues/1035) - [Feature Request]: Add "Team" Column to All Admin UI Tables (Tools, Gateway Server, Virtual Servers, Prompts, Resources)
    - ✅ [**#979**](https://github.com/IBM/mcp-context-forge/issues/979) - [Feature Request]: OAuth Dynamic Client Registration
    - ✅ [**#964**](https://github.com/IBM/mcp-context-forge/issues/964) - Support dynamic environment variable injection in mcpgateway.translate for STDIO MCP servers
    - ✅ [**#920**](https://github.com/IBM/mcp-context-forge/issues/920) - Sample MCP Server - Go (calculator-server)
    - ✅ [**#900**](https://github.com/IBM/mcp-context-forge/issues/900) - Sample MCP Server - Python (data-analysis-server)
    - ✅ [**#699**](https://github.com/IBM/mcp-context-forge/issues/699) - [Feature]: Metrics Enhancement (export all data, capture all metrics, fix last used timestamps, UI improvements)
    - ✅ [**#298**](https://github.com/IBM/mcp-context-forge/issues/298) - [Feature Request]: A2A Initial Support - Add A2A Servers as Tools
    - ✅ [**#243**](https://github.com/IBM/mcp-context-forge/issues/243) - [Feature Request]: a2a compatibility?
    - ✅ [**#229**](https://github.com/IBM/mcp-context-forge/issues/229) - [SECURITY FEATURE]: Guardrails - Input/Output Sanitization & PII Masking
    - ✅ [**#1045**](https://github.com/IBM/mcp-context-forge/issues/1045) - Sample MCP Server - Python (docx-server)
    - ✅ [**#1052**](https://github.com/IBM/mcp-context-forge/issues/1052) - Sample MCP Server - Python (chunker-server)
    - ✅ [**#1053**](https://github.com/IBM/mcp-context-forge/issues/1053) - Sample MCP Server - Python (code-splitter-server)
    - ✅ [**#1054**](https://github.com/IBM/mcp-context-forge/issues/1054) - Sample MCP Server - Python (xlsx-server)
    - ✅ [**#1055**](https://github.com/IBM/mcp-context-forge/issues/1055) - Sample MCP Server - Python (libreoffice-server)
    - ✅ [**#1056**](https://github.com/IBM/mcp-context-forge/issues/1056) - Sample MCP Server - Python (csv-pandas-chat-server)

???+ check "🐛 Completed Bugs (16)"

    - ✅ [**#1178**](https://github.com/IBM/mcp-context-forge/issues/1178) - [Bug]: The header in UI overlaps with all the modals
    - ✅ [**#1117**](https://github.com/IBM/mcp-context-forge/issues/1117) - [Bug]:Login not working with 0.7.0 version
    - ✅ [**#1109**](https://github.com/IBM/mcp-context-forge/issues/1109) - [Bug]:MCP Gateway UI OAuth2 Integration Fails with Keycloak Due to Missing x-www-form-urlencoded Support
    - ✅ [**#1104**](https://github.com/IBM/mcp-context-forge/issues/1104) - [Bug]: X-Upstream-Authorization Header Not Working When Auth Type is None
    - ✅ [**#1101**](https://github.com/IBM/mcp-context-forge/issues/1101) - [Bug]:login issue
    - ✅ [**#1078**](https://github.com/IBM/mcp-context-forge/issues/1078) - [Bug]: OAuth Token Multi-Tenancy Support: User-Specific Token Handling Required
    - ✅ [**#1048**](https://github.com/IBM/mcp-context-forge/issues/1048) - [Bug]: Login issue - Serving over HTTP requires SECURE_COOKIES=false (warning required)
    - ✅ [**#1046**](https://github.com/IBM/mcp-context-forge/issues/1046) - [Bug]:  pass-through headers are not functioning as expected
    - ✅ [**#1039**](https://github.com/IBM/mcp-context-forge/issues/1039) - [Bug]:Update Gateway fails
    - ✅ [**#1025**](https://github.com/IBM/mcp-context-forge/issues/1025) - [Bug]:After edit/save of an MCP Server with OAUTh2 Authentication I need to also fetch tools.
    - ✅ [**#1022**](https://github.com/IBM/mcp-context-forge/issues/1022) - [Bug] "Join Request" button shows no pending request for team membership
    - ✅ [**#959**](https://github.com/IBM/mcp-context-forge/issues/959) - [Bug]: Unable to Re-add Team Member Due to Unique Constraint on (team_id, user_email)
    - ✅ [**#949**](https://github.com/IBM/mcp-context-forge/issues/949) - [Bug]: Tool invocation for an MCP server authorized by OAUTH2 fails
    - ✅ [**#948**](https://github.com/IBM/mcp-context-forge/issues/948) - [Bug]:MCP  OAUTH2 authenticate server is shown as offline after is added
    - ✅ [**#941**](https://github.com/IBM/mcp-context-forge/issues/941) - [Bug]: Access Token scoping not working
    - ✅ [**#939**](https://github.com/IBM/mcp-context-forge/issues/939) - [Bug]: Missing Document links in SSO page for Team/RBAC management

???+ check "🔧 Completed Chores (3)"

    - ✅ [**#931**](https://github.com/IBM/mcp-context-forge/issues/931) - [Bug]: Helm install does not work when kubeVersion has vendor specific suffix
    - ✅ [**#867**](https://github.com/IBM/mcp-context-forge/issues/867) - [Bug]: update_gateway does not persist passthrough_headers field
    - ✅ [**#845**](https://github.com/IBM/mcp-context-forge/issues/845) - [Bug]:2025-08-28 05:47:06,733 - mcpgateway.services.gateway_service - ERROR - FileLock health check failed: can't start new thread

???+ check "📚 Completed Documentation (3)"

    - ✅ [**#865**](https://github.com/IBM/mcp-context-forge/issues/865) - [Bug]: Static assets return 404 when APP_ROOT_PATH is configured
    - ✅ [**#856**](https://github.com/IBM/mcp-context-forge/issues/856) - [Bug]: Admin UI: Associated tools checkboxes on Virtual Servers edit not pre-populated due to ID vs name mismatch
    - ✅ [**#810**](https://github.com/IBM/mcp-context-forge/issues/810) - [Bug]: Ensure Test Cases Use Mock Database instead of Main DB

???+ check "🔌 Completed Plugin Features (29)"

    - ✅ [**#1077**](https://github.com/IBM/mcp-context-forge/issues/1077) - [Plugin] Create ClamAV External Plugin using Plugin Framework
    - ✅ [**#1076**](https://github.com/IBM/mcp-context-forge/issues/1076) - [Plugin] Create Summarizer Plugin using Plugin Framework
    - ✅ [**#1075**](https://github.com/IBM/mcp-context-forge/issues/1075) - [Plugin] Create Watchdog Plugin using Plugin Framework
    - ✅ [**#1074**](https://github.com/IBM/mcp-context-forge/issues/1074) - [Plugin] Create Timezone Translator Plugin using Plugin Framework
    - ✅ [**#1073**](https://github.com/IBM/mcp-context-forge/issues/1073) - [Plugin] Create Privacy Notice Injector Plugin using Plugin Framework
    - ✅ [**#1072**](https://github.com/IBM/mcp-context-forge/issues/1072) - [Plugin] Create License Header Injector Plugin using Plugin Framework
    - ✅ [**#1071**](https://github.com/IBM/mcp-context-forge/issues/1071) - [Plugin] Create Response Cache by Prompt Plugin using Plugin Framework
    - ✅ [**#1070**](https://github.com/IBM/mcp-context-forge/issues/1070) - [Plugin] Create Circuit Breaker Plugin using Plugin Framework
    - ✅ [**#1069**](https://github.com/IBM/mcp-context-forge/issues/1069) - [Plugin] Create Citation Validator Plugin using Plugin Framework
    - ✅ [**#1068**](https://github.com/IBM/mcp-context-forge/issues/1068) - [Plugin] Create Code Formatter Plugin using Plugin Framework
    - ✅ [**#1067**](https://github.com/IBM/mcp-context-forge/issues/1067) - [Plugin] Create AI Artifacts Normalizer Plugin using Plugin Framework
    - ✅ [**#1066**](https://github.com/IBM/mcp-context-forge/issues/1066) - [Plugin] Create Robots License Guard Plugin using Plugin Framework
    - ✅ [**#1065**](https://github.com/IBM/mcp-context-forge/issues/1065) - [Plugin] Create SQL Sanitizer Plugin using Plugin Framework
    - ✅ [**#1064**](https://github.com/IBM/mcp-context-forge/issues/1064) - [Plugin] Create Harmful Content Detector Plugin using Plugin Framework
    - ✅ [**#1063**](https://github.com/IBM/mcp-context-forge/issues/1063) - [Plugin] Create Safe HTML Sanitizer Plugin using Plugin Framework
    - ✅ [**#1005**](https://github.com/IBM/mcp-context-forge/issues/1005) - [Plugin] Create VirusTotal Checker Plugin using Plugin Framework
    - ✅ [**#1004**](https://github.com/IBM/mcp-context-forge/issues/1004) - [Plugin] Create URL Reputation Plugin using Plugin Framework
    - ✅ [**#1003**](https://github.com/IBM/mcp-context-forge/issues/1003) - [Plugin] Create Schema Guard Plugin using Plugin Framework
    - ✅ [**#1002**](https://github.com/IBM/mcp-context-forge/issues/1002) - [Plugin] Create Retry with Backoff Plugin using Plugin Framework
    - ✅ [**#1001**](https://github.com/IBM/mcp-context-forge/issues/1001) - [Plugin] Create Rate Limiter Plugin using Plugin Framework
    - ✅ [**#1000**](https://github.com/IBM/mcp-context-forge/issues/1000) - [Plugin] Create Output Length Guard Plugin using Plugin Framework
    - ✅ [**#999**](https://github.com/IBM/mcp-context-forge/issues/999) - [Plugin] Create Markdown Cleaner Plugin using Plugin Framework
    - ✅ [**#998**](https://github.com/IBM/mcp-context-forge/issues/998) - [Plugin] Create JSON Repair Plugin using Plugin Framework
    - ✅ [**#997**](https://github.com/IBM/mcp-context-forge/issues/997) - [Plugin] Create HTML to Markdown Plugin using Plugin Framework
    - ✅ [**#996**](https://github.com/IBM/mcp-context-forge/issues/996) - [Plugin] Create File Type Allowlist Plugin using Plugin Framework
    - ✅ [**#995**](https://github.com/IBM/mcp-context-forge/issues/995) - [Plugin] Create Code Safety Linter Plugin using Plugin Framework
    - ✅ [**#994**](https://github.com/IBM/mcp-context-forge/issues/994) - [Plugin] Create Cached Tool Result Plugin using Plugin Framework
    - ✅ [**#895**](https://github.com/IBM/mcp-context-forge/issues/895) - [Plugin] Create Header Injector Plugin using Plugin Framework
    - ✅ [**#894**](https://github.com/IBM/mcp-context-forge/issues/894) - [Plugin] Create Secrets Detection Plugin using Plugin Framework
    - ✅ [**#893**](https://github.com/IBM/mcp-context-forge/issues/893) - [Plugin] Create JSON Schema Validator Plugin using Plugin Framework

???+ check "📦 Completed Sample Servers (10)"

    - ✅ [**#1062**](https://github.com/IBM/mcp-context-forge/issues/1062) - Sample MCP Server - Python (url-to-markdown-server)
    - ✅ [**#1061**](https://github.com/IBM/mcp-context-forge/issues/1061) - Sample MCP Server - Python (python-sandbox-server)
    - ✅ [**#1060**](https://github.com/IBM/mcp-context-forge/issues/1060) - Sample MCP Server - Python (latex-server)
    - ✅ [**#1059**](https://github.com/IBM/mcp-context-forge/issues/1059) - Sample MCP Server - Python (graphviz-server)
    - ✅ [**#1058**](https://github.com/IBM/mcp-context-forge/issues/1058) - Sample MCP Server - Python (mermaid-server)
    - ✅ [**#1057**](https://github.com/IBM/mcp-context-forge/issues/1057) - Sample MCP Server - Python (plotly-server)
    - ✅ [**#841**](https://github.com/IBM/mcp-context-forge/issues/841) - [Bug]: For A2A Agent, tools are not getting listed under Global Tools
    - ✅ [**#839**](https://github.com/IBM/mcp-context-forge/issues/839) - [Bug]:Getting 401 un-authorized on Testing tools in "In-Cognito" mode.
    - ✅ [**#836**](https://github.com/IBM/mcp-context-forge/issues/836) - [Bug]: Server Tags Not Propagated to Tools via /tools Endpoint

---

## Release 0.7.0 - Multitenancy and RBAC (Private/Team/Global catalogs), Extended Connectivity, Core Observability & Starter Agents (OpenAI and A2A)

!!! success "Release 0.7.0 - Completed (100%)"
    **Due:** 16 Sep 2025 | **Status:** Closed
    Multitenancy and RBAC (Private/Team/Global catalogs), Extended Connectivity, Core Observability & Starter Agents (OpenAI and A2A)

???+ check "✨ Completed Features (21)"

    - ✅ [**#989**](https://github.com/IBM/mcp-context-forge/issues/989) - [Feature Request]: Sample MCP Server - Python PowerPoint Editor (python-pptx)
    - ✅ [**#986**](https://github.com/IBM/mcp-context-forge/issues/986) - Plugin Request: Implement Argument Normalizer Plugin (Native)
    - ✅ [**#928**](https://github.com/IBM/mcp-context-forge/issues/928) - Migrate container base images from UBI9 to UBI10 and Python from 3.11 to 3.12
    - ✅ [**#925**](https://github.com/IBM/mcp-context-forge/issues/925) - Add MySQL database support to MCP Gateway
    - ✅ [**#860**](https://github.com/IBM/mcp-context-forge/issues/860) - [EPIC]: Complete Enterprise Multi-Tenancy System with Team-Based Resource Scoping
    - ✅ [**#859**](https://github.com/IBM/mcp-context-forge/issues/859) - [Feature Request]: Authentication & Authorization - IBM Security Verify Enterprise SSO Integration (Depends on #220)
    - ✅ [**#846**](https://github.com/IBM/mcp-context-forge/issues/846) - [Bug]: Editing server converts hex UUID to hyphenated UUID format, lacks error handling
    - ✅ [**#844**](https://github.com/IBM/mcp-context-forge/issues/844) - [Bug]: Creating a new virtual server with a custom UUID, removes the "-" hyphens from the UUID field.
    - ✅ [**#831**](https://github.com/IBM/mcp-context-forge/issues/831) - [Bug]: Newly added or deleted tools are not reflected in Global Tools tab after server reactivation
    - ✅ [**#822**](https://github.com/IBM/mcp-context-forge/issues/822) - [Bug]: Incorrect _sleep_with_jitter Method Call
    - ✅ [**#820**](https://github.com/IBM/mcp-context-forge/issues/820) - [Bug]: Unable to create a new server with custom UUID
    - ✅ [**#605**](https://github.com/IBM/mcp-context-forge/issues/605) - [Feature Request]: Access to remote MCP Servers/Tools via OAuth on behalf of Users
    - ✅ [**#570**](https://github.com/IBM/mcp-context-forge/issues/570) - [Feature Request]: Word wrap in codemirror
    - ✅ [**#544**](https://github.com/IBM/mcp-context-forge/issues/544) - [SECURITY FEATURE]: Database-Backed User Authentication with Argon2id (replace BASIC auth)
    - ✅ [**#491**](https://github.com/IBM/mcp-context-forge/issues/491) - [Feature Request]: UI Keyboard shortcuts
    - ✅ [**#426**](https://github.com/IBM/mcp-context-forge/issues/426) - [SECURITY FEATURE]: Configurable Password and Secret Policy Engine
    - ✅ [**#283**](https://github.com/IBM/mcp-context-forge/issues/283) - [SECURITY FEATURE]: Role-Based Access Control (RBAC) - User/Team/Global Scopes for full multi-tenancy support
    - ✅ [**#282**](https://github.com/IBM/mcp-context-forge/issues/282) - [SECURITY FEATURE]: Per-Virtual-Server API Keys with Scoped Access
    - ✅ [**#278**](https://github.com/IBM/mcp-context-forge/issues/278) - [Feature Request]: Authentication & Authorization - Google SSO Integration Tutorial (Depends on #220)
    - ✅ [**#220**](https://github.com/IBM/mcp-context-forge/issues/220) - [AUTH FEATURE]: Authentication & Authorization - SSO + Identity-Provider Integration
    - ✅ [**#87**](https://github.com/IBM/mcp-context-forge/issues/87) - [Feature Request]: Epic: Secure JWT Token Catalog with Per-User Expiry and Revocation

???+ check "🐛 Completed Bugs (5)"

    - ✅ [**#958**](https://github.com/IBM/mcp-context-forge/issues/958) - [Bug]: Incomplete Visibility Implementation
    - ✅ [**#955**](https://github.com/IBM/mcp-context-forge/issues/955) - [Bug]: Team Selection implementation not tagging or loading added servers, tools, gateways
    - ✅ [**#942**](https://github.com/IBM/mcp-context-forge/issues/942) - [Bug]: DateTime UTC Fixes Required
    - ✅ [**#587**](https://github.com/IBM/mcp-context-forge/issues/587) - [Bug]: REST Tool giving error
    - ✅ [**#232**](https://github.com/IBM/mcp-context-forge/issues/232) - [Bug]: Leaving Auth to None fails

???+ check "📚 Completed Documentation (4)"

    - ✅ [**#818**](https://github.com/IBM/mcp-context-forge/issues/818) - [Docs]: Readme ghcr.io/ibm/mcp-context-forge:0.6.0 image still building
    - ✅ [**#323**](https://github.com/IBM/mcp-context-forge/issues/323) - [Docs]: Add Developer Guide for using fast-time-server via JSON-RPC commands using curl or stdio
    - ✅ [**#19**](https://github.com/IBM/mcp-context-forge/issues/19) - [Docs]: Add Developer Guide for using MCP via the CLI (curl commands, JSON-RPC)
    - ✅ [**#834**](https://github.com/IBM/mcp-context-forge/issues/834) - [Bug]: Existing tool configurations are not updating after changes to the MCP server configuration.

---

## Release 0.6.0 - Security, Scale & Smart Automation

!!! success "Release 0.6.0 - Completed (100%)"
    **Due:** 19 Aug 2025 | **Status:** Closed
    Security, Scale & Smart Automation

???+ check "✨ Completed Features (30)"

    - ✅ [**#773**](https://github.com/IBM/mcp-context-forge/issues/773) - [Feature]: add support for external plugins
    - ✅ [**#749**](https://github.com/IBM/mcp-context-forge/issues/749) - [Feature Request]: MCP Reverse Proxy - Bridge Local Servers to Remote Gateways
    - ✅ [**#737**](https://github.com/IBM/mcp-context-forge/issues/737) - [Feature Request]: Bulk Tool Import
    - ✅ [**#735**](https://github.com/IBM/mcp-context-forge/issues/735) - [Epic]: Vendor Agnostic OpenTelemetry Observability Support
    - ✅ [**#727**](https://github.com/IBM/mcp-context-forge/issues/727) - [Feature]: Phoenix Observability Integration plugin
    - ✅ [**#720**](https://github.com/IBM/mcp-context-forge/issues/720) - [Feature]: Add CLI for authoring and packaging plugins
    - ✅ [**#708**](https://github.com/IBM/mcp-context-forge/issues/708) - [Feature Request]: MCP Elicitation (v2025-06-18)
    - ✅ [**#705**](https://github.com/IBM/mcp-context-forge/issues/705) - [Feature Request]: Option to completely remove Bearer token auth to MCP gateway
    - ✅ [**#690**](https://github.com/IBM/mcp-context-forge/issues/690) - [Feature] Make SSE Keepalive Events Configurable
    - ✅ [**#682**](https://github.com/IBM/mcp-context-forge/issues/682) - [Feature]: Add tool hooks (tool_pre_invoke / tool_post_invoke) to plugin system
    - ✅ [**#673**](https://github.com/IBM/mcp-context-forge/issues/673) - [ARCHITECTURE] Identify Next Steps for Plugin Development
    - ✅ [**#672**](https://github.com/IBM/mcp-context-forge/issues/672) - [CHORE]: Part 2: Replace Raw Errors with Friendly Messages in main.py
    - ✅ [**#668**](https://github.com/IBM/mcp-context-forge/issues/668) - [Feature Request]: Add Null Checks and Improve Error Handling in Frontend Form Handlers (admin.js)
    - ✅ [**#586**](https://github.com/IBM/mcp-context-forge/issues/586) - [Feature Request]: Tag support with editing and validation across all APIs endpoints and UI (tags)
    - ✅ [**#540**](https://github.com/IBM/mcp-context-forge/issues/540) - [SECURITY FEATURE]: Configurable Well-Known URI Handler including security.txt and robots.txt
    - ✅ [**#533**](https://github.com/IBM/mcp-context-forge/issues/533) - [SECURITY FEATURE]: Add Additional Configurable Security Headers to APIs for Admin UI
    - ✅ [**#492**](https://github.com/IBM/mcp-context-forge/issues/492) - [Feature Request]: Change UI ID field name to UUID
    - ✅ [**#452**](https://github.com/IBM/mcp-context-forge/issues/452) - [Bug]: integrationType should only support REST, not MCP (Remove Integration Type: MCP)
    - ✅ [**#405**](https://github.com/IBM/mcp-context-forge/issues/405) - [Bug]: Fix the go time server annotation (it shows as destructive)
    - ✅ [**#404**](https://github.com/IBM/mcp-context-forge/issues/404) - [Feature Request]: Add resources and prompts/prompt templates to time server
    - ✅ [**#380**](https://github.com/IBM/mcp-context-forge/issues/380) - [Feature Request]: REST Endpoints for Go fast-time-server
    - ✅ [**#368**](https://github.com/IBM/mcp-context-forge/issues/368) - [Feature Request]: Enhance Metrics Tab UI with Virtual Servers and Top 5 Performance Tables
    - ✅ [**#364**](https://github.com/IBM/mcp-context-forge/issues/364) - [Feature Request]: Add Log File Support to MCP Gateway
    - ✅ [**#344**](https://github.com/IBM/mcp-context-forge/issues/344) - [CHORE]: Implement additional security headers and CORS configuration
    - ✅ [**#320**](https://github.com/IBM/mcp-context-forge/issues/320) - [Feature Request]: Update Streamable HTTP to fully support Virtual Servers
    - ✅ [**#319**](https://github.com/IBM/mcp-context-forge/issues/319) - [Feature Request]: AI Middleware Integration / Plugin Framework for extensible gateway capabilities
    - ✅ [**#317**](https://github.com/IBM/mcp-context-forge/issues/317) - [CHORE]: Script to add relative file path header to each file and verify top level docstring
    - ✅ [**#315**](https://github.com/IBM/mcp-context-forge/issues/315) - [CHORE] Check SPDX headers Makefile and GitHub Actions target - ensure all files have File, Author(s) and SPDX headers
    - ✅ [**#313**](https://github.com/IBM/mcp-context-forge/issues/313) - [DESIGN]: Architecture Decisions and Discussions for AI Middleware and Plugin Framework (Enables #319)
    - ✅ [**#208**](https://github.com/IBM/mcp-context-forge/issues/208) - [AUTH FEATURE]: HTTP Header Passthrough (forward headers to MCP server)

???+ check "🐛 Completed Bugs (22)"

    - ✅ [**#774**](https://github.com/IBM/mcp-context-forge/issues/774) - [Bug]: Tools Annotations not working and need specificity for mentioning annotations
    - ✅ [**#765**](https://github.com/IBM/mcp-context-forge/issues/765) - [Bug]: illegal IP address string passed to inet_aton during discovery process
    - ✅ [**#753**](https://github.com/IBM/mcp-context-forge/issues/753) - [BUG] Tool invocation returns 'Invalid method' error after PR #746
    - ✅ [**#744**](https://github.com/IBM/mcp-context-forge/issues/744) - [BUG] Gateway fails to connect to services behind CDNs/load balancers due to DNS resolution
    - ✅ [**#741**](https://github.com/IBM/mcp-context-forge/issues/741) - [Bug]: Enhance Server Creation/Editing UI for Prompt and Resource Association
    - ✅ [**#728**](https://github.com/IBM/mcp-context-forge/issues/728) - [Bug]: Streamable HTTP Translation Feature: Connects but Fails to List Tools, Resources, or Support Tool Calls
    - ✅ [**#716**](https://github.com/IBM/mcp-context-forge/issues/716) - [Bug]: Resources and Prompts not displaying in Admin Dashboard while Tools are visible
    - ✅ [**#704**](https://github.com/IBM/mcp-context-forge/issues/704) - [Bug]: Virtual Servers don't actually work as advertised v0.5.0
    - ✅ [**#696**](https://github.com/IBM/mcp-context-forge/issues/696) - [Bug]: SSE Tool Invocation Fails After Integration Type Migration post PR #678
    - ✅ [**#694**](https://github.com/IBM/mcp-context-forge/issues/694) - [BUG]: Enhanced Validation Missing in GatewayCreate
    - ✅ [**#689**](https://github.com/IBM/mcp-context-forge/issues/689) - Getting "Unknown SSE event: keepalive" when trying to use virtual servers
    - ✅ [**#685**](https://github.com/IBM/mcp-context-forge/issues/685) - [Bug]: Multiple Fixes and improved security for HTTP Header Passthrough Feature
    - ✅ [**#666**](https://github.com/IBM/mcp-context-forge/issues/666) - [Bug]:Vague/Unclear Error Message "Validation Failed" When Adding a REST Tool
    - ✅ [**#661**](https://github.com/IBM/mcp-context-forge/issues/661) - [Bug]: Database migration runs during doctest execution
    - ✅ [**#649**](https://github.com/IBM/mcp-context-forge/issues/649) - [Bug]: Duplicate Gateway Registration with Equivalent URLs Bypasses Uniqueness Check
    - ✅ [**#646**](https://github.com/IBM/mcp-context-forge/issues/646) - [Bug]: MCP Server/Federated Gateway Registration is failing
    - ✅ [**#560**](https://github.com/IBM/mcp-context-forge/issues/560) - [Bug]: Can't list tools when running inside of a docker
    - ✅ [**#557**](https://github.com/IBM/mcp-context-forge/issues/557) - [BUG] Cleanup tool descriptions to remove newlines and truncate text
    - ✅ [**#526**](https://github.com/IBM/mcp-context-forge/issues/526) - [Bug]: Unable to add multiple headers when adding a gateway through UI (draft)
    - ✅ [**#520**](https://github.com/IBM/mcp-context-forge/issues/520) - [Bug]: Resource mime-type is always stored as text/plain
    - ✅ [**#518**](https://github.com/IBM/mcp-context-forge/issues/518) - [Bug]: Runtime error from Redis when multiple sessions exist
    - ✅ [**#417**](https://github.com/IBM/mcp-context-forge/issues/417) - [Bug]: Intermittent doctest failure in /mcpgateway/cache/resource_cache.py:7

???+ check "🔧 Completed Chores (8)"

    - ✅ [**#481**](https://github.com/IBM/mcp-context-forge/issues/481) - [Bug]: Intermittent test_resource_cache.py::test_expiration - AssertionError: assert 'bar' is None (draft)
    - ✅ [**#480**](https://github.com/IBM/mcp-context-forge/issues/480) - [Bug]: Alembic treated as first party dependency by isort
    - ✅ [**#479**](https://github.com/IBM/mcp-context-forge/issues/479) - [Bug]: Update make commands for alembic
    - ✅ [**#478**](https://github.com/IBM/mcp-context-forge/issues/478) - [Bug]: Alembic migration is broken
    - ✅ [**#436**](https://github.com/IBM/mcp-context-forge/issues/436) - [Bug]: Verify content length using the content itself when the content-length header is absent.
    - ✅ [**#280**](https://github.com/IBM/mcp-context-forge/issues/280) - [CHORE]: Add mutation testing with mutmut for test quality validation
    - ✅ [**#256**](https://github.com/IBM/mcp-context-forge/issues/256) - [CHORE]: Implement comprehensive fuzz testing automation and Makefile targets (hypothesis, atheris, schemathesis , RESTler)
    - ✅ [**#254**](https://github.com/IBM/mcp-context-forge/issues/254) - [CHORE]: Async Code Testing and Performance Profiling Makefile targets (flake8-async, cprofile, snakeviz, aiomonitor)

???+ check "📚 Completed Documentation (4)"

    - ✅ [**#306**](https://github.com/IBM/mcp-context-forge/issues/306) - Quick Start (manual install) gunicorn fails
    - ✅ [**#186**](https://github.com/IBM/mcp-context-forge/issues/186) - [Feature Request]: Granular Configuration Export & Import (via UI & API)
    - ✅ [**#185**](https://github.com/IBM/mcp-context-forge/issues/185) - [Feature Request]: Portable Configuration Export & Import CLI (registry, virtual servers and prompts)
    - ✅ [**#94**](https://github.com/IBM/mcp-context-forge/issues/94) - [Feature Request]: Transport-Translation Bridge (`mcpgateway.translate`)  any to any protocol conversion cli tool

???+ check "❓ Completed Questions (3)"

    - ✅ [**#510**](https://github.com/IBM/mcp-context-forge/issues/510) - [QUESTION]: Create users - User management & RBAC
    - ✅ [**#509**](https://github.com/IBM/mcp-context-forge/issues/509) - [QUESTION]: Enterprise LDAP Integration
    - ✅ [**#393**](https://github.com/IBM/mcp-context-forge/issues/393) - [BUG] Both resources and prompts not loading after adding a federated gateway

???+ check "📦 Completed Sample Servers (3)"

    - ✅ [**#138**](https://github.com/IBM/mcp-context-forge/issues/138) - [Feature Request]: View & Export Logs from Admin UI
    - ✅ [**#137**](https://github.com/IBM/mcp-context-forge/issues/137) - [Feature Request]: Track Creator & Timestamp Metadata for Servers, Tools, and Resources
    - ✅ [**#136**](https://github.com/IBM/mcp-context-forge/issues/136) - [Feature Request]: Downloadable JSON Client Config Generator from Admin UI

---

## Release 0.5.0 - Enterprise Operability, Auth, Configuration & Observability

!!! success "Release 0.5.0 - Completed (100%)"
    **Due:** 05 Aug 2025 | **Status:** Closed
    Enterprise Operability, Auth, Configuration & Observability

???+ check "✨ Completed Features (4)"

    - ✅ [**#663**](https://github.com/IBM/mcp-context-forge/issues/663) - [Feature Request]: Add basic auth support for API Docs
    - ✅ [**#623**](https://github.com/IBM/mcp-context-forge/issues/623) - [Feature Request]: Display default values from input_schema in test tool screen
    - ✅ [**#506**](https://github.com/IBM/mcp-context-forge/issues/506) - [Feature Request]:  New column for "MCP Server Name" in Global tools/resources etc
    - ✅ [**#392**](https://github.com/IBM/mcp-context-forge/issues/392) - [Feature Request]: UI checkbox selection for servers, tools, and resources

???+ check "🐛 Completed Bugs (20)"

    - ✅ [**#631**](https://github.com/IBM/mcp-context-forge/issues/631) - [Bug]: Inconsistency in acceptable length of Tool Names for tools created via UI and programmatically
    - ✅ [**#630**](https://github.com/IBM/mcp-context-forge/issues/630) - [Bug]: Gateway update fails silently in UI, backend throws ValidationInfo error
    - ✅ [**#622**](https://github.com/IBM/mcp-context-forge/issues/622) - [Bug]: Test tool UI passes boolean inputs as on/off instead of true/false
    - ✅ [**#620**](https://github.com/IBM/mcp-context-forge/issues/620) - [Bug]: Test tool UI passes array inputs as strings
    - ✅ [**#613**](https://github.com/IBM/mcp-context-forge/issues/613) - [Bug]: Fix lint-web issues in admin.js
    - ✅ [**#610**](https://github.com/IBM/mcp-context-forge/issues/610) - [Bug]: Edit tool in Admin UI sends invalid "STREAMABLE" value for Request Type
    - ✅ [**#603**](https://github.com/IBM/mcp-context-forge/issues/603) - [Bug]: Unexpected error when registering a gateway with the same name.
    - ✅ [**#601**](https://github.com/IBM/mcp-context-forge/issues/601) - [Bug]: APIs for gateways in admin and main do not mask auth values
    - ✅ [**#598**](https://github.com/IBM/mcp-context-forge/issues/598) - [Bug]: Long input names in tool creation reflected back to user in error message
    - ✅ [**#591**](https://github.com/IBM/mcp-context-forge/issues/591) - [Bug] Edit Prompt Fails When Template Field Is Empty
    - ✅ [**#584**](https://github.com/IBM/mcp-context-forge/issues/584) - [Bug]: Can't register Github MCP Server in the MCP Registry
    - ✅ [**#579**](https://github.com/IBM/mcp-context-forge/issues/579) - [Bug]: Edit tool update fail  integration_type="REST"
    - ✅ [**#578**](https://github.com/IBM/mcp-context-forge/issues/578) - [Bug]: Adding invalid gateway URL does not return an error immediately
    - ✅ [**#521**](https://github.com/IBM/mcp-context-forge/issues/521) - [Bug]: Gateway ID returned as null by Gateway Create API
    - ✅ [**#507**](https://github.com/IBM/mcp-context-forge/issues/507) - [Bug]: Makefile missing .PHONY declarations and other issues
    - ✅ [**#434**](https://github.com/IBM/mcp-context-forge/issues/434) - [Bug]: Logs show"Invalid HTTP request received"
    - ✅ [**#430**](https://github.com/IBM/mcp-context-forge/issues/430) - [Bug]: make serve doesn't check if I'm already running an instance (run-gunicorn.sh) letting me start the server multiple times
    - ✅ [**#423**](https://github.com/IBM/mcp-context-forge/issues/423) - [Bug]: Redundant Conditional Expression in Content Validation
    - ✅ [**#373**](https://github.com/IBM/mcp-context-forge/issues/373) - [Bug]: Clarify Difference Between "Reachable" and "Available" Status in Version Info
    - ✅ [**#357**](https://github.com/IBM/mcp-context-forge/issues/357) - [Bug]: Improve consistency of displaying error messages

???+ check "🔒 Completed Security (1)"

    - ✅ [**#425**](https://github.com/IBM/mcp-context-forge/issues/425) - [SECURITY FEATURE]: Make JWT Token Expiration Mandatory when REQUIRE_TOKEN_EXPIRATION=true (depends on #87)

???+ check "🔧 Completed Chores (9)"

    - ✅ [**#638**](https://github.com/IBM/mcp-context-forge/issues/638) - [CHORE]: Add Makefile and GitHub Actions support for Snyk (test, code-test, container-test, helm charts)
    - ✅ [**#615**](https://github.com/IBM/mcp-context-forge/issues/615) - [CHORE]: Add pypi package linters: check-manifest pyroma and verify target to GitHub Actions
    - ✅ [**#590**](https://github.com/IBM/mcp-context-forge/issues/590) - [CHORE]: Integrate DevSkim static analysis tool via Makefile
    - ✅ [**#410**](https://github.com/IBM/mcp-context-forge/issues/410) - [CHORE]: Add `make lint filename|dirname` target to Makefile
    - ✅ [**#403**](https://github.com/IBM/mcp-context-forge/issues/403) - [CHORE]: Add time server (and configure it post-deploy) to docker-compose.yaml
    - ✅ [**#397**](https://github.com/IBM/mcp-context-forge/issues/397) - [CHORE]: Migrate run-gunicorn-v2.sh to run-gunicorn.sh and have a single file (improved startup script with configurable flags)
    - ✅ [**#390**](https://github.com/IBM/mcp-context-forge/issues/390) - [CHORE]: Add lint-web to CI/CD and add additional linters to Makefile (jshint jscpd markuplint)
    - ✅ [**#365**](https://github.com/IBM/mcp-context-forge/issues/365) - [CHORE]: Fix Database Migration Commands in Makefile
    - ✅ [**#363**](https://github.com/IBM/mcp-context-forge/issues/363) - [CHORE]: Improve Error Messages - Replace Raw Technical Errors with User-Friendly Messages

---

## Release 0.4.0 - Bugfixes, Security, Resilience (retry with exponential backoff), code quality and technical debt (test coverage, linting, security scans, GitHub Actions, Makefile, Helm improvements)

!!! success "Release 0.4.0 - Completed (100%)"
    **Due:** 22 Jul 2025 | **Status:** Closed
    Bugfixes, Security, Resilience (retry with exponential backoff), code quality and technical debt (test coverage, linting, security scans, GitHub Actions, Makefile, Helm improvements)

???+ check "✨ Completed Features (9)"

    - ✅ [**#456**](https://github.com/IBM/mcp-context-forge/issues/456) - [Feature Request]: HTTPX Client with Smart Retry and Backoff Mechanism
    - ✅ [**#351**](https://github.com/IBM/mcp-context-forge/issues/351) - CHORE: Checklist for complete End-to-End Validation Testing for All API Endpoints, UI and Data Validation
    - ✅ [**#340**](https://github.com/IBM/mcp-context-forge/issues/340) - [Security]: Add input validation for main API endpoints (depends on #339 /admin API validation)
    - ✅ [**#339**](https://github.com/IBM/mcp-context-forge/issues/339) - [Security]: Add input validation for /admin endpoints
    - ✅ [**#338**](https://github.com/IBM/mcp-context-forge/issues/338) - [Security]: Eliminate all lint issues in web stack
    - ✅ [**#336**](https://github.com/IBM/mcp-context-forge/issues/336) - [Security]: Implement output escaping for user data in UI
    - ✅ [**#233**](https://github.com/IBM/mcp-context-forge/issues/233) - [Feature Request]: Contextual Hover-Help Tooltips in UI
    - ✅ [**#181**](https://github.com/IBM/mcp-context-forge/issues/181) - [Feature Request]: Test MCP Server Connectivity Debugging Tool
    - ✅ [**#177**](https://github.com/IBM/mcp-context-forge/issues/177) - [Feature Request]: Persistent Admin UI Filter State

???+ check "🐛 Completed Bugs (26)"

    - ✅ [**#508**](https://github.com/IBM/mcp-context-forge/issues/508) - [BUG]: "PATCH" in global tools while creating REST API integration through UI
    - ✅ [**#495**](https://github.com/IBM/mcp-context-forge/issues/495) - [Bug]: test_admin_tool_name_conflict creates record in actual db
    - ✅ [**#476**](https://github.com/IBM/mcp-context-forge/issues/476) - [Bug]:UI Does Not Show Error for Duplicate Server Name
    - ✅ [**#472**](https://github.com/IBM/mcp-context-forge/issues/472) - [Bug]: auth_username and auth_password not getting set in GET /gateways/<gateway_id> API
    - ✅ [**#471**](https://github.com/IBM/mcp-context-forge/issues/471) - [Bug]: _populate_auth not working
    - ✅ [**#424**](https://github.com/IBM/mcp-context-forge/issues/424) - [Bug]: MCP Gateway Doesn't Detect HTTPS/TLS Context or respect X-Forwarded-Proto when using Federation
    - ✅ [**#419**](https://github.com/IBM/mcp-context-forge/issues/419) - [Bug]: Remove unused lock_file_path from config.py (trips up bandit)
    - ✅ [**#416**](https://github.com/IBM/mcp-context-forge/issues/416) - [Bug]: Achieve 100% bandit lint for version.py (remove git command from version.py, tests and UI and rely on semantic version only)
    - ✅ [**#412**](https://github.com/IBM/mcp-context-forge/issues/412) - [Bug]: Replace assert statements with explicit error handling in translate.py and fix bandit lint issues
    - ✅ [**#396**](https://github.com/IBM/mcp-context-forge/issues/396) - [Bug]: Test server URL does not work correctly
    - ✅ [**#387**](https://github.com/IBM/mcp-context-forge/issues/387) - [Bug]: Respect GATEWAY_TOOL_NAME_SEPARATOR for gateway slug
    - ✅ [**#384**](https://github.com/IBM/mcp-context-forge/issues/384) - [Bug]: Push image to GHCR incorrectly runs in PR
    - ✅ [**#382**](https://github.com/IBM/mcp-context-forge/issues/382) - [Bug]: API incorrectly shows version, use semantic version from __init__
    - ✅ [**#378**](https://github.com/IBM/mcp-context-forge/issues/378) - [Bug] Fix Unit Tests to Handle UI-Disabled Mode
    - ✅ [**#374**](https://github.com/IBM/mcp-context-forge/issues/374) - [Bug]: Fix "metrics-loading" Element Not Found Console Warning
    - ✅ [**#371**](https://github.com/IBM/mcp-context-forge/issues/371) - [Bug]: Fix Makefile to let you pick docker or podman and work consistently with the right image name
    - ✅ [**#369**](https://github.com/IBM/mcp-context-forge/issues/369) - [Bug]: Fix Version Endpoint to Include Semantic Version (Not Just Git Revision)
    - ✅ [**#367**](https://github.com/IBM/mcp-context-forge/issues/367) - [Bug]: Fix "Test Server Connectivity" Feature in Admin UI
    - ✅ [**#366**](https://github.com/IBM/mcp-context-forge/issues/366) - [Bug]: Fix Dark Theme Visibility Issues in Admin UI
    - ✅ [**#361**](https://github.com/IBM/mcp-context-forge/issues/361) - [Bug]: Prompt and RPC Endpoints Accept XSS Content Without Validation Error
    - ✅ [**#359**](https://github.com/IBM/mcp-context-forge/issues/359) - [BUG]: Gateway validation accepts invalid transport types
    - ✅ [**#356**](https://github.com/IBM/mcp-context-forge/issues/356) - [Bug]: Annotations not editable
    - ✅ [**#355**](https://github.com/IBM/mcp-context-forge/issues/355) - [Bug]: Large empty space after line number in text boxes
    - ✅ [**#354**](https://github.com/IBM/mcp-context-forge/issues/354) - [Bug]: Edit screens not populating fields
    - ✅ [**#352**](https://github.com/IBM/mcp-context-forge/issues/352) - [Bug]: Resources - All data going into content
    - ✅ [**#213**](https://github.com/IBM/mcp-context-forge/issues/213) - [Bug]:Can't use `STREAMABLEHTTP`

???+ check "🔒 Completed Security (1)"

    - ✅ [**#552**](https://github.com/IBM/mcp-context-forge/issues/552) - [SECURITY CHORE]: Add comprehensive input validation security test suite

???+ check "🔧 Completed Chores (13)"

    - ✅ [**#558**](https://github.com/IBM/mcp-context-forge/issues/558) - [CHORE]: Ignore tests/security/test_input_validation.py in pre-commit for bidi-controls
    - ✅ [**#499**](https://github.com/IBM/mcp-context-forge/issues/499) - [CHORE]: Add nodejsscan security scanner
    - ✅ [**#467**](https://github.com/IBM/mcp-context-forge/issues/467) - [CHORE]: Achieve 100% docstring coverage (make interrogate) - currently at 96.3%
    - ✅ [**#433**](https://github.com/IBM/mcp-context-forge/issues/433) - [CHORE]: Fix all Makefile targets to work without pre-activated venv and check for OS depends
    - ✅ [**#421**](https://github.com/IBM/mcp-context-forge/issues/421) - [CHORE]: Achieve zero flagged Bandit issues
    - ✅ [**#415**](https://github.com/IBM/mcp-context-forge/issues/415) - [CHORE]: Additional Python Security Scanners
    - ✅ [**#399**](https://github.com/IBM/mcp-context-forge/issues/399) - [Test]: Create e2e acceptance test docs
    - ✅ [**#375**](https://github.com/IBM/mcp-context-forge/issues/375) - [CHORE]: Fix yamllint to Ignore node_modules Directory
    - ✅ [**#362**](https://github.com/IBM/mcp-context-forge/issues/362) - [CHORE]: Implement Docker HEALTHCHECK
    - ✅ [**#305**](https://github.com/IBM/mcp-context-forge/issues/305) - [CHORE]: Add vulture (dead code detect) and unimport (unused import detect) to Makefile and GitHub Actions
    - ✅ [**#279**](https://github.com/IBM/mcp-context-forge/issues/279) - [CHORE]: Implement security audit and vulnerability scanning with grype in Makefile and GitHub Actions
    - ✅ [**#249**](https://github.com/IBM/mcp-context-forge/issues/249) - [CHORE]: Achieve 60% doctest coverage and add Makefile and CI/CD targets for doctest and coverage
    - ✅ [**#210**](https://github.com/IBM/mcp-context-forge/issues/210) - [CHORE]: Raise pylint from 9.16/10 -> 10/10

???+ check "📚 Completed Documentation (3)"

    - ✅ [**#522**](https://github.com/IBM/mcp-context-forge/issues/522) - [Docs]: OpenAPI title is MCP_Gateway instead of MCP Gateway
    - ✅ [**#376**](https://github.com/IBM/mcp-context-forge/issues/376) - [Docs]: Document Security Policy in GitHub Pages and Link Roadmap on Homepage
    - ✅ [**#46**](https://github.com/IBM/mcp-context-forge/issues/46) - [Docs]: Add documentation for using mcp-cli with MCP Gateway

---

## Release 0.3.0 - Annotations and multi-server tool federations

!!! success "Release 0.3.0 - Completed (100%)"
    **Due:** 08 Jul 2025 | **Status:** Closed
    Annotations and multi-server tool federations

???+ check "✨ Completed Features (8)"

    - ✅ [**#265**](https://github.com/IBM/mcp-context-forge/issues/265) - [Feature Request]: Sample MCP Server - Go (fast-time-server)
    - ✅ [**#179**](https://github.com/IBM/mcp-context-forge/issues/179) - [Feature Request]: Configurable Connection Retries for DB and Redis
    - ✅ [**#159**](https://github.com/IBM/mcp-context-forge/issues/159) - [Feature Request]: Add auto activation of mcp-server, when it goes up back again
    - ✅ [**#154**](https://github.com/IBM/mcp-context-forge/issues/154) - [Feature Request]: Export connection strings to various clients from UI and via API
    - ✅ [**#135**](https://github.com/IBM/mcp-context-forge/issues/135) - [Feature Request]: Dynamic UI Picker for Tool, Resource, and Prompt Associations
    - ✅ [**#116**](https://github.com/IBM/mcp-context-forge/issues/116) - [Feature Request]: Namespace Composite Key & UUIDs for Tool Identity
    - ✅ [**#100**](https://github.com/IBM/mcp-context-forge/issues/100) - Add path parameter or replace value in input payload for a REST API?
    - ✅ [**#26**](https://github.com/IBM/mcp-context-forge/issues/26) - [Feature]: Add dark mode toggle to Admin UI

???+ check "🐛 Completed Bugs (9)"

    - ✅ [**#316**](https://github.com/IBM/mcp-context-forge/issues/316) - [Bug]: Correctly create filelock_path: str = "tmp/gateway_service_leader.lock" in /tmp not current directory
    - ✅ [**#303**](https://github.com/IBM/mcp-context-forge/issues/303) - [Bug]: Update manager.py and admin.js removed `is_active` field - replace with separate `enabled` and `reachable` fields from migration
    - ✅ [**#302**](https://github.com/IBM/mcp-context-forge/issues/302) - [Bug]: Alembic configuration not packaged with pip wheel, `pip install . && mcpgateway` fails on db migration
    - ✅ [**#197**](https://github.com/IBM/mcp-context-forge/issues/197) - [Bug]: Pytest run exposes warnings from outdated Pydantic patterns, deprecated stdlib functions
    - ✅ [**#189**](https://github.com/IBM/mcp-context-forge/issues/189) - [Bug]: Close button for parameter input scheme does not work
    - ✅ [**#152**](https://github.com/IBM/mcp-context-forge/issues/152) - [Bug]: not able to add Github Remote Server
    - ✅ [**#132**](https://github.com/IBM/mcp-context-forge/issues/132) - [Bug]: SBOM Generation Failure
    - ✅ [**#131**](https://github.com/IBM/mcp-context-forge/issues/131) - [Bug]: Documentation Generation fails due to error in Makefile's image target
    - ✅ [**#28**](https://github.com/IBM/mcp-context-forge/issues/28) - [Bug]: Reactivating a gateway logs warning due to 'dict' object used as Pydantic model

???+ check "📚 Completed Documentation (1)"

    - ✅ [**#18**](https://github.com/IBM/mcp-context-forge/issues/18) - [Docs]: Add Developer Workstation Setup Guide for Mac (Intel/ARM), Linux, and Windows

---

## Release 0.2.0 - Streamable HTTP, Infra-as-Code, Dark Mode

!!! success "Release 0.2.0 - Completed (100%)"
    **Due:** 24 Jun 2025 | **Status:** Closed
    Streamable HTTP, Infra-as-Code, Dark Mode

???+ check "✨ Completed Features (3)"

    - ✅ [**#125**](https://github.com/IBM/mcp-context-forge/issues/125) - [Feature Request]: Add Streamable HTTP MCP servers to Gateway
    - ✅ [**#109**](https://github.com/IBM/mcp-context-forge/issues/109) - [Feature Request]: Implement Streamable HTTP Transport for Client Connections to MCP Gateway
    - ✅ [**#25**](https://github.com/IBM/mcp-context-forge/issues/25) - [Feature]: Add "Version and Environment Info" tab to Admin UI

???+ check "🐛 Completed Bugs (2)"

    - ✅ [**#85**](https://github.com/IBM/mcp-context-forge/issues/85) - [Bug]: internal server error comes if there is any error while adding an entry or even any crud operation is happening
    - ✅ [**#51**](https://github.com/IBM/mcp-context-forge/issues/51) - [Bug]: Internal server running when running gunicorn after install

???+ check "📚 Completed Documentation (3)"

    - ✅ [**#98**](https://github.com/IBM/mcp-context-forge/issues/98) - [Docs]: Add additional information for using the mcpgateway with Claude desktop
    - ✅ [**#71**](https://github.com/IBM/mcp-context-forge/issues/71) - [Docs]:Documentation Over Whelming Cannot figure out the basic task of adding an MCP server
    - ✅ [**#21**](https://github.com/IBM/mcp-context-forge/issues/21) - [Docs]: Deploying to Fly.io

---

## Release 0.1.0 - Initial release

!!! success "Release 0.1.0 - Completed (100%)"
    **Due:** 05 Jun 2025 | **Status:** Closed
    Initial release

???+ check "✨ Completed Features (3)"

    - ✅ [**#27**](https://github.com/IBM/mcp-context-forge/issues/27) - [Feature]: Add /ready endpoint for readiness probe
    - ✅ [**#24**](https://github.com/IBM/mcp-context-forge/issues/24) - [Feature]: Publish Helm chart for Kubernetes deployment
    - ✅ [**#23**](https://github.com/IBM/mcp-context-forge/issues/23) - [Feature]: Add VS Code Devcontainer support for instant onboarding

???+ check "🐛 Completed Bugs (3)"

    - ✅ [**#49**](https://github.com/IBM/mcp-context-forge/issues/49) - [Bug]:make venv install serve fails with "./run-gunicorn.sh: line 40: python: command not found"
    - ✅ [**#37**](https://github.com/IBM/mcp-context-forge/issues/37) - [Bug]: Issues  with the  gateway Container Image
    - ✅ [**#35**](https://github.com/IBM/mcp-context-forge/issues/35) - [Bug]: Error when running in Docker Desktop for Windows

???+ check "📚 Completed Documentation (2)"

    - ✅ [**#50**](https://github.com/IBM/mcp-context-forge/issues/50) - [Docs]: virtual env location is incorrect
    - ✅ [**#30**](https://github.com/IBM/mcp-context-forge/issues/30) - [Docs]: Deploying to Google Cloud Run

---

## Legend

- ✨ **Feature Request** - New functionality or enhancement
- 🐛 **Bug** - Issues that need to be fixed
- 🔒 **Security** - Security features and improvements
- ⚡ **Performance** - Performance optimizations
- 🔧 **Chore** - Maintenance, tooling, or infrastructure work
- 📚 **Documentation** - Documentation improvements or additions
- 🔌 **Plugin Features** - Plugin framework and plugin implementations
- 📦 **Sample Servers** - Sample MCP server implementations
- ❓ **Question** - User questions (typically closed after resolution)
- ✅ **Completed** - Issue has been resolved and closed

!!! tip "Contributing"
    Want to contribute to any of these features? Check out the individual GitHub issues for more details and discussion!
