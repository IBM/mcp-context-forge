# ContextForge Roadmap

!!! info "Release Overview"
    This roadmap outlines the planned development milestones for ContextForge, organized by release version with completion status and due dates.


## Release Status Summary

| Release | Due Date    | Completion | Status       | Description |
| ------- | ----------- | ---------- | ------------ | ----------- |
| 1.6.0         | 31 Aug 2026 |   0 %      | Open         | Collaboration, Workflow Management, Security Posture |
| 1.5.0         | 31 Jul 2026 |   0 %      | Open         | Ecosystem Integrations, Advanced Observability, Plugin Marketplace |
| 1.4.0         | 30 Jun 2026 |   0 %      | Open         | Enterprise Features, Federation Enhancements, Performance |
| 1.3.0         | 31 May 2026 |   0 %      | Open         | New MCP Servers and Agents |
| 1.2.0         | 30 Apr 2026 |   0 %      | Open         | Documentation, Technical Debt, Bugfixes |
| 1.1.0         | 31 Mar 2026 |   0 %      | Open         | Technical Debt and Quality |
| 1.0.0         | 28 Apr 2026 |   0 %      | Open         | General Availability - Technical Debt, Security Hardening, Catalog Improvements, A2A Improvements, MCP Standard Review and Sync |
| 1.0.0-RC3     | 14 Apr 2026 | 100 %      | **Closed**   | Release Candidate 3 - Auth Hardening, Plugin Multi-Tenancy, Rust Runtime & Multi-Arch |
| 1.0.0-RC2     | 09 Mar 2026 | 100 %      | **Closed**   | Release Candidate 2 - Hardening, Admin UI Polish, Plugin Framework & Quality |
| 1.0.0-RC1     | 17 Feb 2026 | 100 %      | **Closed**   | Release Candidate 1 - Security, Linting, Catalog Enhancements, Ratings, experience and UI |

---

## Release 1.6.0

!!! warning "Release 1.6.0 - In Progress (0%)"
    **Due:** 31 Aug 2026 | **Status:** Open
    Collaboration, Workflow Management, Security Posture

???+ info "📋 Epics - Remaining (10)"

    - ⏳ [**#2274**](https://github.com/IBM/mcp-context-forge/issues/2274) - [EPIC][A11Y]: Accessibility (WCAG 2.1 AA compliance)
    - ⏳ [**#2275**](https://github.com/IBM/mcp-context-forge/issues/2275) - [EPIC][A11Y]: Keyboard navigation and shortcuts
    - ⏳ [**#2306**](https://github.com/IBM/mcp-context-forge/issues/2306) - [EPIC][COLLAB]: Multi-user collaboration and presence
    - ⏳ [**#2307**](https://github.com/IBM/mcp-context-forge/issues/2307) - [EPIC][UI]: Comments and annotations
    - ⏳ [**#2308**](https://github.com/IBM/mcp-context-forge/issues/2308) - [EPIC][WORKFLOW]: Workflow approvals and change management
    - ⏳ [**#2309**](https://github.com/IBM/mcp-context-forge/issues/2309) - [EPIC][SECURITY]: Security posture dashboard
    - ⏳ [**#2347**](https://github.com/IBM/mcp-context-forge/issues/2347) - [EPIC][TESTING]: Automated MCP server compatibility regression suite - Top 100+ server testing
    - ⏳ [**#2349**](https://github.com/IBM/mcp-context-forge/issues/2349) - [EPIC][K8S]: Kubernetes Operator integration for production-grade infrastructure
    - ⏳ [**#2350**](https://github.com/IBM/mcp-context-forge/issues/2350) - [EPIC][K8S]: ContextForge Kubernetes Operator - Helm-based Operator SDK implementation
    - ⏳ [**#2957**](https://github.com/IBM/mcp-context-forge/issues/2957) - [EPIC][ANSIBLE]: Ansible collection for ContextForge Gateway CI/CD configuration

???+ info "🧪 Testing - Remaining (1)"

    - ⏳ [**#407**](https://github.com/IBM/mcp-context-forge/issues/407) - [CHORE][TESTING]: Improve pytest configuration and plugins

???+ info "⚡ Performance - Remaining (5)"

    - ⏳ [**#902**](https://github.com/IBM/mcp-context-forge/issues/902) - [FEATURE][MCP-SERVER]: Rust sample - performance-benchmark-server
    - ⏳ [**#1620**](https://github.com/IBM/mcp-context-forge/issues/1620) - [RUST]: Implement performance-sensitive plugins in Rust/PyO3
    - ⏳ [**#1638**](https://github.com/IBM/mcp-context-forge/issues/1638) - [PERFORMANCE]: Migrate to Python 3.14 with Free-Threading (No GIL)
    - ⏳ [**#1640**](https://github.com/IBM/mcp-context-forge/issues/1640) - [PERFORMANCE]: Add asyncpg Driver Support (Alternative to psycopg2)
    - ⏳ [**#1761**](https://github.com/IBM/mcp-context-forge/issues/1761) - [PERFORMANCE]: Reduce importlib lookups at runtime

???+ info "📚 Documentation - Remaining (28)"

    - ⏳ [**#22**](https://github.com/IBM/mcp-context-forge/issues/22) - [DOCS]: Add BeeAI framework client integration (Python and TypeScript)
    - ⏳ [**#565**](https://github.com/IBM/mcp-context-forge/issues/565) - [DOCS]: Documentation for Goose integration
    - ⏳ [**#871**](https://github.com/IBM/mcp-context-forge/issues/871) - [DOCS]: Langflow integration
    - ⏳ [**#872**](https://github.com/IBM/mcp-context-forge/issues/872) - [DOCS]: watsonx.ai integration
    - ⏳ [**#873**](https://github.com/IBM/mcp-context-forge/issues/873) - [DOCS]: watsonx Orchestrate integration
    - ⏳ [**#874**](https://github.com/IBM/mcp-context-forge/issues/874) - [DOCS]: IBM Decision Intelligence MCP server integration
    - ⏳ [**#875**](https://github.com/IBM/mcp-context-forge/issues/875) - [DOCS]: IBM MQ server MCP integration
    - ⏳ [**#876**](https://github.com/IBM/mcp-context-forge/issues/876) - [DOCS]: IBM ODM MCP server integration
    - ⏳ [**#877**](https://github.com/IBM/mcp-context-forge/issues/877) - [DOCS]: IBM watsonx.data Document Retrieval MCP server integration
    - ⏳ [**#878**](https://github.com/IBM/mcp-context-forge/issues/878) - [DOCS]: IBM Cloud MCP server integration
    - ⏳ [**#879**](https://github.com/IBM/mcp-context-forge/issues/879) - [DOCS]: IBM Cloud Code Engine MCP server integration
    - ⏳ [**#880**](https://github.com/IBM/mcp-context-forge/issues/880) - [DOCS]: IBM Cloud VPC MCP server integration
    - ⏳ [**#881**](https://github.com/IBM/mcp-context-forge/issues/881) - [DOCS]: IBM Instana MCP server integration
    - ⏳ [**#882**](https://github.com/IBM/mcp-context-forge/issues/882) - [DOCS]: IBM Storage Insights MCP server integration
    - ⏳ [**#883**](https://github.com/IBM/mcp-context-forge/issues/883) - [DOCS]: IBM API Connect for GraphQL MCP integration
    - ⏳ [**#884**](https://github.com/IBM/mcp-context-forge/issues/884) - [DOCS]: WxMCPServer (webMethods) integration
    - ⏳ [**#885**](https://github.com/IBM/mcp-context-forge/issues/885) - [DOCS]: Terraform MCP server integration
    - ⏳ [**#886**](https://github.com/IBM/mcp-context-forge/issues/886) - [DOCS]: Vault Radar MCP server integration
    - ⏳ [**#887**](https://github.com/IBM/mcp-context-forge/issues/887) - [DOCS]: DataStax Astra DB MCP server integration
    - ⏳ [**#888**](https://github.com/IBM/mcp-context-forge/issues/888) - [DOCS]: Docling MCP server integration
    - ⏳ [**#889**](https://github.com/IBM/mcp-context-forge/issues/889) - [DOCS]: MCP Composer integration
    - ✅ [**#890**](https://github.com/IBM/mcp-context-forge/issues/890) - [DOCS]: Langflow MCP server integration
    - ⏳ [**#891**](https://github.com/IBM/mcp-context-forge/issues/891) - [DOCS]: BeeAI framework integration
    - ⏳ [**#913**](https://github.com/IBM/mcp-context-forge/issues/913) - [DOCS]: Atlassian MCP server integration
    - ⏳ [**#914**](https://github.com/IBM/mcp-context-forge/issues/914) - [DOCS]: Box MCP server integration
    - ⏳ [**#915**](https://github.com/IBM/mcp-context-forge/issues/915) - [DOCS]: GitHub MCP server integration
    - ⏳ [**#917**](https://github.com/IBM/mcp-context-forge/issues/917) - [DOCS]: Hugging Face MCP server integration
    - ⏳ [**#918**](https://github.com/IBM/mcp-context-forge/issues/918) - [DOCS]: Javadocs.dev MCP server integration

???+ info "🔧 Chores - Remaining (5)"

    - ⏳ [**#292**](https://github.com/IBM/mcp-context-forge/issues/292) - [CHORE]: Enable AI Alliance Analytics Stack Integration
    - ⏳ [**#318**](https://github.com/IBM/mcp-context-forge/issues/318) - [CHORE]: Publish Agents and Tools that leverage codebase and templates
    - ⏳ [**#408**](https://github.com/IBM/mcp-context-forge/issues/408) - [CHORE][CICD]: Add normalize script to pre-commit hooks
    - ⏳ [**#414**](https://github.com/IBM/mcp-context-forge/issues/414) - [CHORE]: Restructure container scanning targets into a dedicated section
    - ⏳ [**#574**](https://github.com/IBM/mcp-context-forge/issues/574) - [CHORE][PYTHON]: Run pyupgrade to modernize Python syntax

???+ info "✨ Features - Remaining (27)"

    - ⏳ [**#267**](https://github.com/IBM/mcp-context-forge/issues/267) - [FEATURE][MCP-SERVER]: Java implementation - plantuml-server
    - ⏳ [**#268**](https://github.com/IBM/mcp-context-forge/issues/268) - [FEATURE][MCP-SERVER]: Haskell implementation - pandoc-server
    - ⏳ [**#269**](https://github.com/IBM/mcp-context-forge/issues/269) - [FEATURE][MCP-SERVER]: Go implementation - LaTeX service
    - ⏳ [**#270**](https://github.com/IBM/mcp-context-forge/issues/270) - [FEATURE][MCP-SERVER]: Go implementation - libreoffice-server
    - ⏳ [**#273**](https://github.com/IBM/mcp-context-forge/issues/273) - [FEATURE][TERRAFORM]: mcp-gateway-aws module (EKS, ECS Fargate)
    - ⏳ [**#274**](https://github.com/IBM/mcp-context-forge/issues/274) - [FEATURE][TERRAFORM]: mcp-gateway-azure module (AKS, ACA)
    - ⏳ [**#275**](https://github.com/IBM/mcp-context-forge/issues/275) - [FEATURE][TERRAFORM]: mcp-gateway-gcp module (GKE, Cloud Run)
    - ⏳ [**#276**](https://github.com/IBM/mcp-context-forge/issues/276) - [FEATURE][TERRAFORM]: mcp-gateway-ibm-cloud module (IKS, ROKS, Code Engine)
    - ⏳ [**#896**](https://github.com/IBM/mcp-context-forge/issues/896) - [FEATURE]: Add prompt authoring tools category to MCP eval server
    - ⏳ [**#897**](https://github.com/IBM/mcp-context-forge/issues/897) - [FEATURE][MCP-SERVER]: Go sample - database-query-server
    - ⏳ [**#899**](https://github.com/IBM/mcp-context-forge/issues/899) - [FEATURE][MCP-SERVER]: Python sample - ml-inference-server
    - ⏳ [**#901**](https://github.com/IBM/mcp-context-forge/issues/901) - [FEATURE][MCP-SERVER]: Rust sample - crypto-tools-server
    - ⏳ [**#903**](https://github.com/IBM/mcp-context-forge/issues/903) - [FEATURE][MCP-SERVER]: TypeScript sample - web-automation-server
    - ⏳ [**#904**](https://github.com/IBM/mcp-context-forge/issues/904) - [FEATURE][MCP-SERVER]: TypeScript sample - real-time-collaboration-server
    - ⏳ [**#905**](https://github.com/IBM/mcp-context-forge/issues/905) - [FEATURE][MCP-SERVER]: IBM Granite language models MCP server
    - ⏳ [**#906**](https://github.com/IBM/mcp-context-forge/issues/906) - [FEATURE][MCP-SERVER]: IBM Granite vision models MCP server
    - ⏳ [**#907**](https://github.com/IBM/mcp-context-forge/issues/907) - [FEATURE][MCP-SERVER]: IBM Granite speech models MCP server
    - ⏳ [**#908**](https://github.com/IBM/mcp-context-forge/issues/908) - [FEATURE][MCP-SERVER]: IBM Granite time series models MCP server
    - ⏳ [**#909**](https://github.com/IBM/mcp-context-forge/issues/909) - [FEATURE][MCP-SERVER]: IBM Granite Guardian safety models MCP server
    - ⏳ [**#910**](https://github.com/IBM/mcp-context-forge/issues/910) - [FEATURE][MCP-SERVER]: IBM Granite geospatial models MCP server
    - ⏳ [**#911**](https://github.com/IBM/mcp-context-forge/issues/911) - [FEATURE][MCP-SERVER]: IBM Granite embedding models MCP server
    - ⏳ [**#921**](https://github.com/IBM/mcp-context-forge/issues/921) - [FEATURE][MCP-SERVER]: Python sample - weather-data-server
    - ⏳ [**#1617**](https://github.com/IBM/mcp-context-forge/issues/1617) - [RUST]: Rewrite translate module in Rust
    - ⏳ [**#1621**](https://github.com/IBM/mcp-context-forge/issues/1621) - [RUST]: Rewrite transport layer in Rust
    - ⏳ [**#2358**](https://github.com/IBM/mcp-context-forge/issues/2358) - [FEATURE]: Granian feature requests - max-requests, jitter, and worker lifecycle improvements
    - ⏳ [**#2886**](https://github.com/IBM/mcp-context-forge/issues/2886) - [FEATURE][PLUGINS]: Architectural policy for deprecating Python plugins when other languages versions are superior
    - ⏳ [**#2907**](https://github.com/IBM/mcp-context-forge/issues/2907) - [FEATURE]: Rust implementation of url reputation plugin

---

## Release 1.5.0

!!! warning "Release 1.5.0 - In Progress (0%)"
    **Due:** 31 Jul 2026 | **Status:** Open
    Ecosystem Integrations, Advanced Observability, Plugin Marketplace

???+ info "📋 Epics - Remaining (11)"

    - ⏳ [**#2282**](https://github.com/IBM/mcp-context-forge/issues/2282) - [EPIC][WEBSOCKET]: Real-time updates via WebSocket
    - ⏳ [**#2283**](https://github.com/IBM/mcp-context-forge/issues/2283) - [EPIC][MOBILE]: Mobile-first responsive redesign
    - ⏳ [**#2284**](https://github.com/IBM/mcp-context-forge/issues/2284) - [EPIC][UI]: Customizable dashboard builder
    - ⏳ [**#2285**](https://github.com/IBM/mcp-context-forge/issues/2285) - [EPIC][PLUGIN]: Plugin UI extension framework
    - ⏳ [**#2289**](https://github.com/IBM/mcp-context-forge/issues/2289) - [EPIC][DESKTOP]: ContextForge Desktop (React + Electron)
    - ⏳ [**#2290**](https://github.com/IBM/mcp-context-forge/issues/2290) - [EPIC][PLUGIN]: Plugin marketplace UI
    - ⏳ [**#2291**](https://github.com/IBM/mcp-context-forge/issues/2291) - [EPIC][AI]: AI-assisted operations (natural language interface)
    - ⏳ [**#2292**](https://github.com/IBM/mcp-context-forge/issues/2292) - [EPIC][ANALYTICS]: Advanced analytics and trends dashboard
    - ⏳ [**#2299**](https://github.com/IBM/mcp-context-forge/issues/2299) - [EPIC][UI]: Integrated monitoring and observability UI
    - ⏳ [**#2302**](https://github.com/IBM/mcp-context-forge/issues/2302) - [EPIC][UI]: Integrated help center
    - ⏳ [**#2303**](https://github.com/IBM/mcp-context-forge/issues/2303) - [EPIC][COMPLIANCE]: Compliance reporting dashboard

???+ info "🐛 Bugs - Remaining (1)"

    - ⏳ [**#2550**](https://github.com/IBM/mcp-context-forge/issues/2550) - [BUG][PERFORMANCE]: Idle transaction timeout under high load (4000+ users)

???+ info "⚡ Performance - Remaining (6)"

    - ⏳ [**#251**](https://github.com/IBM/mcp-context-forge/issues/251) - [PERFORMANCE]: Automatic performance testing and tracking for every build (hey) including SQLite and Postgres / Redis configurations
    - ⏳ [**#1293**](https://github.com/IBM/mcp-context-forge/issues/1293) - [PERFORMANCE]: HTTP/2 and keep-alive transport
    - ⏳ [**#1295**](https://github.com/IBM/mcp-context-forge/issues/1295) - [PERFORMANCE]: Static asset caching and CDN
    - ⏳ [**#1681**](https://github.com/IBM/mcp-context-forge/issues/1681) - [PERFORMANCE]: Implement Lazy Service Initialization
    - ⏳ [**#1682**](https://github.com/IBM/mcp-context-forge/issues/1682) - [PERFORMANCE]: Implement SSE Backpressure and Slow Client Handling
    - ⏳ [**#1780**](https://github.com/IBM/mcp-context-forge/issues/1780) - [PERFORMANCE]: Add random jitter to scheduled tasks to prevent thundering herd

???+ info "🔧 Chores - Remaining (2)"

    - ⏳ [**#2145**](https://github.com/IBM/mcp-context-forge/issues/2145) - [CHORE]: Refactor APIRouters from main.py into separate router modules
    - ⏳ [**#2612**](https://github.com/IBM/mcp-context-forge/issues/2612) - [CHORE]: Deprecate SQLite Support - Focus Exclusively on PostgreSQL 18+

???+ info "✨ Features - Remaining (6)"

    - ⏳ [**#756**](https://github.com/IBM/mcp-context-forge/issues/756) - [FEATURE][API]: REST passthrough APIs with pre/post plugins (JSONPath and filters)
    - ⏳ [**#1338**](https://github.com/IBM/mcp-context-forge/issues/1338) - [FEATURE][API]: Enhance REST API gateway to support form data, path parameters, and dynamic path variables
    - ⏳ [**#1559**](https://github.com/IBM/mcp-context-forge/issues/1559) - [FEATURE]: Package with other MCP server in stdio mode
    - ⏳ [**#1660**](https://github.com/IBM/mcp-context-forge/issues/1660) - [FEATURE]: Centralized Redis configuration
    - ⏳ [**#2074**](https://github.com/IBM/mcp-context-forge/issues/2074) - [FEATURE]: Convert prompts and resources to tools in virtual servers
    - ⏳ [**#2313**](https://github.com/IBM/mcp-context-forge/issues/2313) - [FEATURE]: Implement vendor-specific adapters for A2A Agent Types (OpenAI, Anthropic) with UI interactive help

---

## Release 1.4.0

!!! warning "Release 1.4.0 - In Progress (0%)"
    **Due:** 30 Jun 2026 | **Status:** Open
    Enterprise Features, Federation Enhancements, Performance

???+ info "📋 Epics - Remaining (12)"

    - ⏳ [**#1285**](https://github.com/IBM/mcp-context-forge/issues/1285) - [EPIC][COMPLIANCE]: Fully implement MCP 2025-06-18 compliance across all endpoints
    - ⏳ [**#2287**](https://github.com/IBM/mcp-context-forge/issues/2287) - [EPIC][MOBILE]: Mobile layout testing and optimization
    - ⏳ [**#2288**](https://github.com/IBM/mcp-context-forge/issues/2288) - [EPIC][SDK]: TypeScript SDK auto-generation (@hey-api/openapi-ts)
    - ⏳ [**#2293**](https://github.com/IBM/mcp-context-forge/issues/2293) - [EPIC][FEDERATION]: Federation dashboard and cross-gateway visibility
    - ⏳ [**#2294**](https://github.com/IBM/mcp-context-forge/issues/2294) - [EPIC][COMPLIANCE]: Audit log viewer and compliance reports
    - ⏳ [**#2295**](https://github.com/IBM/mcp-context-forge/issues/2295) - [EPIC][PERFORMANCE]: Performance profiling dashboard
    - ⏳ [**#2296**](https://github.com/IBM/mcp-context-forge/issues/2296) - [EPIC][AUTH]: Advanced RBAC and permissions UI
    - ⏳ [**#2297**](https://github.com/IBM/mcp-context-forge/issues/2297) - [EPIC][UI]: Notification center and alert management
    - ⏳ [**#2298**](https://github.com/IBM/mcp-context-forge/issues/2298) - [EPIC][CONFIG]: Configuration versioning and rollback
    - ⏳ [**#2304**](https://github.com/IBM/mcp-context-forge/issues/2304) - [EPIC][UI]: Interactive tutorials and guided tours
    - ⏳ [**#2310**](https://github.com/IBM/mcp-context-forge/issues/2310) - [EPIC][UI]: Backup and restore UI
    - ⏳ [**#2311**](https://github.com/IBM/mcp-context-forge/issues/2311) - [EPIC][ADMIN]: Admin alerting and alert management

???+ info "🧪 Testing - Remaining (2)"

    - ⏳ [**#751**](https://github.com/IBM/mcp-context-forge/issues/751) - [FEATURE][TESTING]: MCP server - Implement MCP evaluation benchmarks suite
    - ⏳ [**#1971**](https://github.com/IBM/mcp-context-forge/issues/1971) - [TESTING]: Optimize test and lint pipeline (doctest, test, flake8, pylint, lint-web, verify)

???+ info "🔒 Security - Remaining (1)"

    - ⏳ [**#542**](https://github.com/IBM/mcp-context-forge/issues/542) - [FEATURE][SECURITY]: Helm chart - Enterprise secrets management integration (Vault)

???+ info "⚡ Performance - Remaining (4)"

    - ⏳ [**#1856**](https://github.com/IBM/mcp-context-forge/issues/1856) - [PERFORMANCE]: Connection Pool Health Monitoring and Readiness Integration
    - ⏳ [**#1858**](https://github.com/IBM/mcp-context-forge/issues/1858) - [PERFORMANCE]: Request Priority and Quality of Service (QoS)
    - ⏳ [**#1863**](https://github.com/IBM/mcp-context-forge/issues/1863) - [PERFORMANCE]: Add Envoy Proxy with Optional Caching for Docker Compose
    - ⏳ [**#1864**](https://github.com/IBM/mcp-context-forge/issues/1864) - [PERFORMANCE]: Add Envoy Gateway with Optional Caching for Helm Chart

???+ info "📚 Documentation - Remaining (1)"

    - ⏳ [**#1346**](https://github.com/IBM/mcp-context-forge/issues/1346) - [DOCS]: Unclear instructions to test A2A agent as MCP tool

???+ info "🔧 Chores - Remaining (4)"

    - ⏳ [**#211**](https://github.com/IBM/mcp-context-forge/issues/211) - [CHORE]: Achieve Zero Static-Type Errors Across All Checkers (mypy, ty, pyright, pyrefly)
    - ⏳ [**#253**](https://github.com/IBM/mcp-context-forge/issues/253) - [CHORE]: Implement chaos engineering tests for fault tolerance validation (network partitions, service failures)
    - ⏳ [**#398**](https://github.com/IBM/mcp-context-forge/issues/398) - [CHORE]: Enforce pre-commit targets for doctest coverage, pytest coverage, pylint score 10/10, flake8 pass and add badges
    - ⏳ [**#595**](https://github.com/IBM/mcp-context-forge/issues/595) - [CHORE][DATABASE]: Investigate potential migration to UUID7

???+ info "✨ Features - Remaining (26)"

    - ⏳ [**#114**](https://github.com/IBM/mcp-context-forge/issues/114) - [FEATURE][DOCKER]: Connect to dockerized MCP servers via STDIO
    - ⏳ [**#175**](https://github.com/IBM/mcp-context-forge/issues/175) - [FEATURE][OBSERVABILITY]: Add OpenLLMetry integration
    - ⏳ [**#209**](https://github.com/IBM/mcp-context-forge/issues/209) - [FEATURE]: Anthropic Desktop Extensions DTX directory/marketplace
    - ⏳ [**#218**](https://github.com/IBM/mcp-context-forge/issues/218) - [FEATURE][OBSERVABILITY]: Prometheus metrics instrumentation
    - ⏳ [**#258**](https://github.com/IBM/mcp-context-forge/issues/258) - [FEATURE]: Universal client retry mechanisms with exponential backoff and jitter
    - ⏳ [**#262**](https://github.com/IBM/mcp-context-forge/issues/262) - [FEATURE][AGENT]: LangChain integration sample (OpenAI and A2A endpoints)
    - ⏳ [**#263**](https://github.com/IBM/mcp-context-forge/issues/263) - [FEATURE][AGENT]: CrewAI integration sample (OpenAI and A2A endpoints)
    - ⏳ [**#272**](https://github.com/IBM/mcp-context-forge/issues/272) - [FEATURE][OBSERVABILITY]: Pre-built Grafana dashboards and Loki log export
    - ⏳ [**#286**](https://github.com/IBM/mcp-context-forge/issues/286) - [FEATURE][CONFIG]: Dynamic configuration UI and admin API
    - ⏳ [**#293**](https://github.com/IBM/mcp-context-forge/issues/293) - [FEATURE]: Intelligent load balancing for redundant MCP servers
    - ⏳ [**#296**](https://github.com/IBM/mcp-context-forge/issues/296) - [FEATURE]: MCP server rating and review system
    - ⏳ [**#299**](https://github.com/IBM/mcp-context-forge/issues/299) - [FEATURE][A2A]: A2A ecosystem integration and marketplace
    - ⏳ [**#300**](https://github.com/IBM/mcp-context-forge/issues/300) - [FEATURE][LOGGING]: Structured JSON logging with correlation IDs
    - ⏳ [**#301**](https://github.com/IBM/mcp-context-forge/issues/301) - [FEATURE]: Full circuit breakers for unstable MCP server backends
    - ⏳ [**#505**](https://github.com/IBM/mcp-context-forge/issues/505) - [FEATURE]: Add ENV token forwarding management per tool
    - ⏳ [**#545**](https://github.com/IBM/mcp-context-forge/issues/545) - [FEATURE][CONFIG]: Hot-reload configuration without restart
    - ⏳ [**#546**](https://github.com/IBM/mcp-context-forge/issues/546) - [FEATURE]: Protocol version negotiation and backward compatibility
    - ⏳ [**#547**](https://github.com/IBM/mcp-context-forge/issues/547) - [FEATURE][UI]: Built-in MCP server health dashboard
    - ⏳ [**#636**](https://github.com/IBM/mcp-context-forge/issues/636) - [FEATURE][BUILD]: Add PyInstaller support for standalone binaries
    - ⏳ [**#1135**](https://github.com/IBM/mcp-context-forge/issues/1135) - [FEATURE][POLICY]: Support OPA bundling for external policy downloads
    - ⏳ [**#1266**](https://github.com/IBM/mcp-context-forge/issues/1266) - [FEATURE]: Share visibility with specific teams or users
    - ⏳ [**#1267**](https://github.com/IBM/mcp-context-forge/issues/1267) - [FEATURE]: Approval-based promotion of MCP server to MCP registry
    - ⏳ [**#1673**](https://github.com/IBM/mcp-context-forge/issues/1673) - [FEATURE]: OS service management - systemd, launchd, and Windows service support
    - ⏳ [**#2095**](https://github.com/IBM/mcp-context-forge/issues/2095) - [FEATURE][CONFIG]: Support secrets-from-file and configurable .env loading
    - ⏳ [**#2118**](https://github.com/IBM/mcp-context-forge/issues/2118) - [FEATURE]: Export MCP session pool metrics to Prometheus
    - ⏳ [**#2199**](https://github.com/IBM/mcp-context-forge/issues/2199) - [FEATURE] Add LangChain-based MCP Agent

---

## Release 1.3.0

!!! warning "Release 1.3.0 - In Progress (0%)"
    **Due:** 31 May 2026 | **Status:** Open
    New MCP Servers and Agents

???+ info "📋 Epics - Remaining (9)"

    - ⏳ [**#2279**](https://github.com/IBM/mcp-context-forge/issues/2279) - [EPIC][I18N]: Internationalization (i18n) framework
    - ⏳ [**#2280**](https://github.com/IBM/mcp-context-forge/issues/2280) - [EPIC][UI]: Theming and white-label support
    - ⏳ [**#2281**](https://github.com/IBM/mcp-context-forge/issues/2281) - [EPIC][UI]: Bulk operations and multi-select
    - ⏳ [**#2286**](https://github.com/IBM/mcp-context-forge/issues/2286) - [EPIC][UI]: Visual polish and UI consistency
    - ⏳ [**#2300**](https://github.com/IBM/mcp-context-forge/issues/2300) - [EPIC][PERFORMANCE]: UI caching strategy and CDN
    - ⏳ [**#2312**](https://github.com/IBM/mcp-context-forge/issues/2312) - [EPIC][UI]: Notification bell and real-time alerts UI
    - ⏳ [**#2527**](https://github.com/IBM/mcp-context-forge/issues/2527) - [EPIC][MCP-APPS]: MCP Apps Support for ContextForge
    - ⏳ [**#2603**](https://github.com/IBM/mcp-context-forge/issues/2603) - [EPIC][SECURITY]: ML-Based Behavioral Fingerprinting for Issue #257
    - ⏳ [**#2823**](https://github.com/IBM/mcp-context-forge/issues/2823) - [EPIC][WEBMCP]: WebMCP Integration — Browser-Native Tool Registration and Gateway Bridge

???+ info "🧪 Testing - Remaining (3)"

    - ⏳ [**#2480**](https://github.com/IBM/mcp-context-forge/issues/2480) - [TESTING][ACCESSIBILITY]: Admin UI WCAG Compliance, Keyboard Navigation, Screen Reader Support
    - ⏳ [**#2482**](https://github.com/IBM/mcp-context-forge/issues/2482) - [TESTING][CHAOS]: Chaos Engineering, Random Fault Injection, and Game Day Scenarios
    - ⏳ [**#2484**](https://github.com/IBM/mcp-context-forge/issues/2484) - [TESTING][LOCALIZATION]: Timezone Handling, Unicode/UTF-8, and International Character Support

???+ info "🐛 Bugs - Remaining (1)"

    - ⏳ [**#683**](https://github.com/IBM/mcp-context-forge/issues/683) - [FEATURE]: Debug headers and passthrough headers support

???+ info "🔒 Security - Remaining (1)"

    - ⏳ [**#1789**](https://github.com/IBM/mcp-context-forge/issues/1789) - [FEATURE][SECURITY]: Separate /rpc endpoints per tool/MCP server

???+ info "⚡ Performance - Remaining (4)"

    - ⏳ [**#290**](https://github.com/IBM/mcp-context-forge/issues/290) - [PERFORMANCE]: Enhance Gateway Tuning Guide with PostgreSQL Deep-Dive
    - ⏳ [**#1639**](https://github.com/IBM/mcp-context-forge/issues/1639) - [PERFORMANCE]: Migrate to PostgreSQL 18 (Experimental)
    - ⏳ [**#1745**](https://github.com/IBM/mcp-context-forge/issues/1745) - [PERFORMANCE]: Audit Trail Performance & Configuration Enhancements
    - ⏳ [**#2161**](https://github.com/IBM/mcp-context-forge/issues/2161) - [PERFORMANCE]: Evaluate async SQLAlchemy migration for high-concurrency scenarios

???+ info "📚 Documentation - Remaining (1)"

    - ⏳ [**#503**](https://github.com/IBM/mcp-context-forge/issues/503) - [DOCS]: Tutorial - OpenWebUI with Ollama, LiteLLM, MCPO, and ContextForge deployment

???+ info "🔧 Chores - Remaining (8)"

    - ⏳ [**#250**](https://github.com/IBM/mcp-context-forge/issues/250) - [CHORE]: Implement automatic API documentation generation using mkdocstrings and update Makefile
    - ✅ [**#255**](https://github.com/IBM/mcp-context-forge/issues/255) - [CHORE]: Implement comprehensive Playwright test automation for the entire ContextForge Admin UI with Makefile targets and GitHub Actions
    - ⏳ [**#307**](https://github.com/IBM/mcp-context-forge/issues/307) - [CHORE]: GitHub Actions to build docs, with diagrams and test report, and deploy to GitHub Pages using MkDocs on every push to main
    - ⏳ [**#402**](https://github.com/IBM/mcp-context-forge/issues/402) - [CHORE][HELM]: Add post-deploy hook to register Time Server as Gateway
    - ⏳ [**#1340**](https://github.com/IBM/mcp-context-forge/issues/1340) - [CHORE] Proposal: Split Monorepo into Separate Repositories in contextforge-org
    - ✅ [**#1688**](https://github.com/IBM/mcp-context-forge/issues/1688) - [CHORE]: Deprecate MySQL/MariaDB support - Focus on SQLite and PostgreSQL
    - ⏳ [**#2139**](https://github.com/IBM/mcp-context-forge/issues/2139) - [CHORE]: Documentation rationalization and Diataxis framework adoption
    - ⏳ [**#2383**](https://github.com/IBM/mcp-context-forge/issues/2383) - [CHORE] Evaluate and select additional CI/CD quality tools

???+ info "✨ Features - Remaining (11)"

    - ⏳ [**#285**](https://github.com/IBM/mcp-context-forge/issues/285) - [FEATURE][CONFIG]: Configuration validation and schema enforcement
    - ⏳ [**#537**](https://github.com/IBM/mcp-context-forge/issues/537) - [FEATURE][CONFIG]: Simple endpoint feature flags
    - ⏳ [**#738**](https://github.com/IBM/mcp-context-forge/issues/738) - [FEATURE][CONFIG]: Configuration database for dynamic settings management
    - ⏳ [**#912**](https://github.com/IBM/mcp-context-forge/issues/912) - [FEATURE][AGENT]: IBM BeeAI framework integration sample
    - ⏳ [**#1042**](https://github.com/IBM/mcp-context-forge/issues/1042) - [FEATURE]: Implementation plan for root directory
    - ⏳ [**#1535**](https://github.com/IBM/mcp-context-forge/issues/1535) - [FEATURE][DB]: PostgreSQL schema configuration support
    - ⏳ [**#1568**](https://github.com/IBM/mcp-context-forge/issues/1568) - [FEATURE][BUILD]: Future directions for configurable builds
    - ⏳ [**#1619**](https://github.com/IBM/mcp-context-forge/issues/1619) - [RUST]: Rewrite reverse-proxy module in Rust
    - ⏳ [**#1671**](https://github.com/IBM/mcp-context-forge/issues/1671) - [FEATURE][DB]: Consider wait-and-retry fallback for advisory lock timeout
    - ⏳ [**#1952**](https://github.com/IBM/mcp-context-forge/issues/1952) - [FEATURE][DB]: Implement 4-database architecture for scaling and separation of metrics, logs, and observability data
    - ⏳ [**#2339**](https://github.com/IBM/mcp-context-forge/issues/2339) - [PROPOSAL]: Plugin Framework Evolution

---

## Release 1.2.0

!!! warning "Release 1.2.0 - In Progress (0%)"
    **Due:** 30 Apr 2026 | **Status:** Open
    Documentation, Technical Debt, Bugfixes

???+ info "📋 Epics - Remaining (27)"

    - ⏳ [**#287**](https://github.com/IBM/mcp-context-forge/issues/287) - [EPIC][API]: API Path Versioning - Unified /api/v1 prefix with /api/experimental namespace
    - ⏳ [**#1245**](https://github.com/IBM/mcp-context-forge/issues/1245) - [EPIC][SECURITY]: Security clearance levels plugin - Bell-LaPadula MAC implementation
    - ⏳ [**#1286**](https://github.com/IBM/mcp-context-forge/issues/1286) - [EPIC][TESTING]: MCP compliance checker - Automated specification testing tool
    - ⏳ [**#1305**](https://github.com/IBM/mcp-context-forge/issues/1305) - [EPIC][AI]: AI service discovery and gateway proxy
    - ⏳ [**#1359**](https://github.com/IBM/mcp-context-forge/issues/1359) - [EPIC]: Custom metadata fields - Rich extensible metadata system
    - ⏳ [**#1374**](https://github.com/IBM/mcp-context-forge/issues/1374) - [EPIC][AUTH]: Two-factor authentication (2FA) - TOTP/Google Authenticator support
    - ⏳ [**#1377**](https://github.com/IBM/mcp-context-forge/issues/1377) - [EPIC][SECURITY]: A2AS framework - Runtime security and self-defense for MCP and A2A
    - ⏳ [**#1422**](https://github.com/IBM/mcp-context-forge/issues/1422) - [EPIC][AUTH]: Agent and tool authentication and authorization plugin
    - ⏳ [**#1472**](https://github.com/IBM/mcp-context-forge/issues/1472) - [EPIC][PLUGIN]: Configurable plugins via admin UI
    - ⏳ [**#2110**](https://github.com/IBM/mcp-context-forge/issues/2110) - [EPIC][RUNTIME]: Secure MCP runtime - Remote server deployment and catalog integration (Docker, Code Engine)
    - ⏳ [**#2215**](https://github.com/IBM/mcp-context-forge/issues/2215) - [EPIC][SECURITY]: MCP server security posture assessment - Pre-deployment scanning and validation
    - ⏳ [**#2222**](https://github.com/IBM/mcp-context-forge/issues/2222) - [EPIC][SECURITY]: Policy-as-code security and compliance automation platform
    - ⏳ [**#2228**](https://github.com/IBM/mcp-context-forge/issues/2228) - [EPIC][AI]: AI-powered conversational gateway and semantic discovery platform
    - ⏳ [**#2305**](https://github.com/IBM/mcp-context-forge/issues/2305) - [EPIC][UI]: Contextual help and tooltips
    - ⏳ [**#2556**](https://github.com/IBM/mcp-context-forge/issues/2556) - [EPIC][AUTH]: Authentication Rate Controls & Plugin Support
    - ⏳ [**#2560**](https://github.com/IBM/mcp-context-forge/issues/2560) - [EPIC][UI]: Client-side rate limiting and request management
    - ⏳ [**#2561**](https://github.com/IBM/mcp-context-forge/issues/2561) - [EPIC][UI]: Session timeout and idle detection for Admin UI
    - ⏳ [**#2564**](https://github.com/IBM/mcp-context-forge/issues/2564) - [EPIC][SECURITY][UI]: Click-to-Reveal UI Components (UX Improvements)
    - ✅ [**#2575**](https://github.com/IBM/mcp-context-forge/issues/2575) - [EPIC][PLUGIN]: Decouple plugin framework from mcpgateway dependencies
    - ⏳ [**#2578**](https://github.com/IBM/mcp-context-forge/issues/2578) - [EPIC][SECURITY]: Interface-Level Access Control (ILAC) - Restrict Users to MCP/A2A/API/UI via RBAC
    - ⏳ [**#2599**](https://github.com/IBM/mcp-context-forge/issues/2599) - [EPIC][SECURITY]: Canary Tokens and Honeypot Resources
    - ⏳ [**#2600**](https://github.com/IBM/mcp-context-forge/issues/2600) - [EPIC][SECURITY]: Tool Payload Encryption (Gateway-Terminating and Passthrough Modes)
    - ⏳ [**#2602**](https://github.com/IBM/mcp-context-forge/issues/2602) - [EPIC][SECURITY]: Interactive Compliance Gap Checker and Self-Assessment Tool
    - ⏳ [**#2755**](https://github.com/IBM/mcp-context-forge/issues/2755) - [EPIC][SECURITY]: Admin IP allowlist - CIDR-based network access control for administrative endpoints
    - ⏳ [**#2756**](https://github.com/IBM/mcp-context-forge/issues/2756) - [EPIC][SECURITY]: Gateway IP allowlist/denylist - CIDR-based network access control for MCP, A2A, and REST endpoints
    - ⏳ [**#2809**](https://github.com/IBM/mcp-context-forge/issues/2809) - [EPIC][INTEGRATION]: Backstage integration - MCP/A2A federation, catalog sync, and developer portal experience
    - ⏳ [**#2984**](https://github.com/IBM/mcp-context-forge/issues/2984) - [EPIC][PROTOCOL]: GraphQL-to-MCP translation module - automatic schema introspection and tool generation

???+ info "🧪 Testing - Remaining (3)"

    - ⏳ [**#2003**](https://github.com/IBM/mcp-context-forge/issues/2003) - [TESTING]: Load test toggle tasks fail under database saturation
    - ⏳ [**#2479**](https://github.com/IBM/mcp-context-forge/issues/2479) - [TESTING][COMPATIBILITY]: Python Versions, Database Versions, and Browser Compatibility
    - ⏳ [**#2481**](https://github.com/IBM/mcp-context-forge/issues/2481) - [TESTING][CLI]: Command-Line Interface, Help Text, and Error Messages

???+ info "🔒 Security - Remaining (9)"

    - ⏳ [**#536**](https://github.com/IBM/mcp-context-forge/issues/536) - [FEATURE][SECURITY]: Generic IP-based access control (allowlist)
    - ⏳ [**#2216**](https://github.com/IBM/mcp-context-forge/issues/2216) - [FEATURE][SECURITY]: Container vulnerability scanner integration
    - ⏳ [**#2217**](https://github.com/IBM/mcp-context-forge/issues/2217) - [FEATURE][SECURITY]: MCP server source code scanner - Semgrep/Bandit integration
    - ⏳ [**#2218**](https://github.com/IBM/mcp-context-forge/issues/2218) - [FEATURE][SECURITY]: SBOM generator - CycloneDX/SPDX for MCP servers
    - ⏳ [**#2219**](https://github.com/IBM/mcp-context-forge/issues/2219) - [FEATURE][SECURITY]: MCP server security policy engine - Configurable compliance gates
    - ⏳ [**#2234**](https://github.com/IBM/mcp-context-forge/issues/2234) - [FEATURE][SECURITY]: Supply chain attack detection - Typosquatting and dependency confusion
    - ⏳ [**#2235**](https://github.com/IBM/mcp-context-forge/issues/2235) - [FEATURE][SECURITY]: Container image signing and verification - Sigstore/Cosign integration
    - ⏳ [**#2236**](https://github.com/IBM/mcp-context-forge/issues/2236) - [FEATURE][SECURITY]: Security posture drift alerting - Continuous CVE monitoring
    - ⏳ [**#2237**](https://github.com/IBM/mcp-context-forge/issues/2237) - [FEATURE][SECURITY]: MCP-specific security rules - Custom Semgrep/CodeQL for MCP patterns

???+ info "⚡ Performance - Remaining (23)"

    - ⏳ [**#289**](https://github.com/IBM/mcp-context-forge/issues/289) - [PERFORMANCE]: Multi-Layer Caching System (Memory + Redis)
    - ⏳ [**#291**](https://github.com/IBM/mcp-context-forge/issues/291) - [PERFORMANCE]: Comprehensive Scalability & Soak-Test Harness (Long-term Stability & Load) - locust, pytest-benchmark, smocker mocked MCP servers
    - ⏳ [**#432**](https://github.com/IBM/mcp-context-forge/issues/432) - [PERFORMANCE]: Performance Optimization Implementation and Guide for ContextForge (baseline)
    - ⏳ [**#1354**](https://github.com/IBM/mcp-context-forge/issues/1354) - [PERFORMANCE][DB]: PostgreSQL database tuning and optimization
    - ⏳ [**#1612**](https://github.com/IBM/mcp-context-forge/issues/1612) - [PERFORMANCE]: Reduce SQLite busy_timeout from 30s to 5s (configurable)
    - ⏳ [**#1825**](https://github.com/IBM/mcp-context-forge/issues/1825) - [PERFORMANCE]: Reduce wrapper CPU overhead (stdin read + task churn)
    - ⏳ [**#1853**](https://github.com/IBM/mcp-context-forge/issues/1853) - [PERFORMANCE]: Database Retry Mechanism for High-Concurrency Resilience
    - ⏳ [**#1854**](https://github.com/IBM/mcp-context-forge/issues/1854) - [PERFORMANCE]: Global Rate Limiting for Gateway Protection
    - ⏳ [**#1857**](https://github.com/IBM/mcp-context-forge/issues/1857) - [PERFORMANCE]: Async Database Logging to Prevent Feedback Loop Under Load
    - ⏳ [**#1862**](https://github.com/IBM/mcp-context-forge/issues/1862) - [PERFORMANCE]: Fix PostgreSQL 'Idle in Transaction' Connection Issue
    - ⏳ [**#1894**](https://github.com/IBM/mcp-context-forge/issues/1894) - [PERFORMANCE]: Admin UI endpoints have high tail latency (5-10s p95)
    - ⏳ [**#1906**](https://github.com/IBM/mcp-context-forge/issues/1906) - [PERFORMANCE]: Metrics aggregation queries cause full table scans under load
    - ✅ [**#1907**](https://github.com/IBM/mcp-context-forge/issues/1907) - [PERFORMANCE]: Admin UI endpoint /admin/ has high latency under load
    - ⏳ [**#1919**](https://github.com/IBM/mcp-context-forge/issues/1919) - [PERFORMANCE]: Upstream rmcp returns SSE-only responses, no JSON option
    - ⏳ [**#1963**](https://github.com/IBM/mcp-context-forge/issues/1963) - [PERFORMANCE]: Plugin framework performance optimization
    - ⏳ [**#1995**](https://github.com/IBM/mcp-context-forge/issues/1995) - [PERFORMANCE]: Optimize SQLAlchemy pool configuration for PgBouncer deployments
    - ⏳ [**#2004**](https://github.com/IBM/mcp-context-forge/issues/2004) - [PERFORMANCE]: Increase default registry cache TTLs for core tables
    - ⏳ [**#2005**](https://github.com/IBM/mcp-context-forge/issues/2005) - [PERFORMANCE]: Add Redis caching for association table queries
    - ⏳ [**#2006**](https://github.com/IBM/mcp-context-forge/issues/2006) - [PERFORMANCE]: Optimize linear O(N) condition matching in plugin framework
    - ⏳ [**#2007**](https://github.com/IBM/mcp-context-forge/issues/2007) - [PERFORMANCE]: Compile user patterns to regex in plugin condition matching
    - ⏳ [**#2114**](https://github.com/IBM/mcp-context-forge/issues/2114) - [PERFORMANCE]: Database lock contention in toggle operations under high concurrency
    - ⏳ [**#2181**](https://github.com/IBM/mcp-context-forge/issues/2181) - [PERFORMANCE]: Distributed MCP Session State for Multi-Node Deployments
    - ⏳ [**#2356**](https://github.com/IBM/mcp-context-forge/issues/2356) - [PERFORMANCE]: Add database resilience hardening (connection monitoring, optimistic locking, circuit breaker)

???+ info "🔧 Chores - Remaining (6)"

    - ⏳ [**#589**](https://github.com/IBM/mcp-context-forge/issues/589) - [CHORE][CICD]: Generate build provenance attestations for workflow artifacts
    - ⏳ [**#674**](https://github.com/IBM/mcp-context-forge/issues/674) - [CHORE][DEVOPS]: Automate release management process
    - ⏳ [**#1260**](https://github.com/IBM/mcp-context-forge/issues/1260) - [CHORE]: x86-64-v2 support
    - ⏳ [**#2100**](https://github.com/IBM/mcp-context-forge/issues/2100) - [CHORE]: Setup Plugin Framework Repository
    - ⏳ [**#2138**](https://github.com/IBM/mcp-context-forge/issues/2138) - [CHORE]: Rationalize Full Pipeline Build workflow against other GitHub Actions workflows
    - ⏳ [**#2568**](https://github.com/IBM/mcp-context-forge/issues/2568) - [REFACTOR][UI]: Consolidate innerHTML patterns with auto-escaping helpers

???+ info "✨ Features - Remaining (47)"

    - ⏳ [**#123**](https://github.com/IBM/mcp-context-forge/issues/123) - [FEATURE][AI]: Dynamic server catalog via rule, regexp, tags, or LLM-based selection
    - ⏳ [**#182**](https://github.com/IBM/mcp-context-forge/issues/182) - [FEATURE]: Semantic tool auto-filtering
    - ⏳ [**#295**](https://github.com/IBM/mcp-context-forge/issues/295) - [FEATURE]: MCP server marketplace and registry
    - ⏳ [**#548**](https://github.com/IBM/mcp-context-forge/issues/548) - [FEATURE][API]: GraphQL API support for tool discovery
    - ⏳ [**#706**](https://github.com/IBM/mcp-context-forge/issues/706) - [FEATURE][AUTH]: ABAC virtual server support
    - ⏳ [**#782**](https://github.com/IBM/mcp-context-forge/issues/782) - [FEATURE][AUTH]: OAuth enhancement following PR 768
    - ⏳ [**#848**](https://github.com/IBM/mcp-context-forge/issues/848) - [FEATURE]: Allow same prompt name across different MCP servers
    - ⏳ [**#1136**](https://github.com/IBM/mcp-context-forge/issues/1136) - [FEATURE][PLUGIN]: Add depends_on key in plugin configurations
    - ⏳ [**#1265**](https://github.com/IBM/mcp-context-forge/issues/1265) - [FEATURE][AUTH]: Map teams to roles and permissions
    - ⏳ [**#1356**](https://github.com/IBM/mcp-context-forge/issues/1356) - [FEATURE]: Headers passthrough from MCP server configuration
    - ⏳ [**#1428**](https://github.com/IBM/mcp-context-forge/issues/1428) - [FEATURE]: CRT-based semantic tool router for dynamic MCP servers
    - ⏳ [**#1435**](https://github.com/IBM/mcp-context-forge/issues/1435) - [FEATURE][AUTH]: Infer identity provider info for onboarded MCP servers
    - ⏳ [**#1438**](https://github.com/IBM/mcp-context-forge/issues/1438) - [FEATURE][PLUGIN]: Enhance the IAM pre-tool plugin
    - ⏳ [**#1456**](https://github.com/IBM/mcp-context-forge/issues/1456) - [FEATURE][AUTH]: Migrate from JWT tokens to short opaque API tokens
    - ⏳ [**#1473**](https://github.com/IBM/mcp-context-forge/issues/1473) - [FEATURE][HELM]: Adding extra values to values.yaml
    - ⏳ [**#1911**](https://github.com/IBM/mcp-context-forge/issues/1911) - [FEATURE][HELM]: Support nodeSelector, tolerations, affinity, and anti-affinity
    - ⏳ [**#1917**](https://github.com/IBM/mcp-context-forge/issues/1917) - [FEATURE][HELM]: Allow passing extra env variables via secret
    - ⏳ [**#2019**](https://github.com/IBM/mcp-context-forge/issues/2019) - [FEATURE]: Centralized configurable RBAC/ABAC policy engine
    - ⏳ [**#2120**](https://github.com/IBM/mcp-context-forge/issues/2120) - [FEATURE][AUTH]: Generic OIDC group to team mapping for SSO
    - ⏳ [**#2148**](https://github.com/IBM/mcp-context-forge/issues/2148) - [FEATURE][AUTH]: DCR proxy for MCP services with non-DCR OAuth providers
    - ✅ [**#2221**](https://github.com/IBM/mcp-context-forge/issues/2221) - [FEATURE][CATALOG]: Curated secure MCP server catalog with trust tiers
    - ⏳ [**#2224**](https://github.com/IBM/mcp-context-forge/issues/2224) - [FEATURE][COMPLIANCE]: Compliance report generator - FedRAMP/HIPAA/SOC2 automation
    - ⏳ [**#2225**](https://github.com/IBM/mcp-context-forge/issues/2225) - [FEATURE][POLICY]: Policy audit trail and decision logging
    - ⏳ [**#2226**](https://github.com/IBM/mcp-context-forge/issues/2226) - [FEATURE][POLICY]: Policy testing and simulation sandbox
    - ⏳ [**#2227**](https://github.com/IBM/mcp-context-forge/issues/2227) - [FEATURE][AUTH]: Just-in-time (JIT) access and temporary privilege elevation
    - ⏳ [**#2229**](https://github.com/IBM/mcp-context-forge/issues/2229) - [FEATURE][SEARCH]: Tool embedding index and semantic search service
    - ⏳ [**#2230**](https://github.com/IBM/mcp-context-forge/issues/2230) - [FEATURE]: Virtual meta-server - Comprehensive tool discovery and execution layer
    - ⏳ [**#2231**](https://github.com/IBM/mcp-context-forge/issues/2231) - [FEATURE][AI]: Conversational tool discovery interface
    - ⏳ [**#2232**](https://github.com/IBM/mcp-context-forge/issues/2232) - [FEATURE][A2A]: A2A agent semantic discovery and orchestration
    - ⏳ [**#2238**](https://github.com/IBM/mcp-context-forge/issues/2238) - [FEATURE][POLICY]: Policy GitOps and version control
    - ⏳ [**#2239**](https://github.com/IBM/mcp-context-forge/issues/2239) - [FEATURE][POLICY]: Policy conflict detection and resolution
    - ⏳ [**#2240**](https://github.com/IBM/mcp-context-forge/issues/2240) - [FEATURE][POLICY]: Policy impact analysis and what-if simulation
    - ⏳ [**#2241**](https://github.com/IBM/mcp-context-forge/issues/2241) - [FEATURE][POLICY]: Separation of duties (SoD) enforcement plugin
    - ⏳ [**#2242**](https://github.com/IBM/mcp-context-forge/issues/2242) - [FEATURE][POLICY]: Policy templates library
    - ⏳ [**#2244**](https://github.com/IBM/mcp-context-forge/issues/2244) - [FEATURE][AI]: Tool recommendation engine
    - ⏳ [**#2245**](https://github.com/IBM/mcp-context-forge/issues/2245) - [FEATURE][ANALYTICS]: Tool usage analytics for search ranking
    - ⏳ [**#2246**](https://github.com/IBM/mcp-context-forge/issues/2246) - [FEATURE][TOOLS]: Tool chain templates and workflow automation
    - ⏳ [**#2247**](https://github.com/IBM/mcp-context-forge/issues/2247) - [FEATURE][TOOLS]: Semantic tool deprecation and migration assistant
    - ⏳ [**#2248**](https://github.com/IBM/mcp-context-forge/issues/2248) - [FEATURE][AI]: Natural language direct tool execution
    - ⏳ [**#2385**](https://github.com/IBM/mcp-context-forge/issues/2385) - [FEATURE]: Multi-Platform CI/CD Testing Matrix (Windows, Linux, macOS)
    - ⏳ [**#2653**](https://github.com/IBM/mcp-context-forge/issues/2653) - [ENHANCEMENT][DATABASE]: Add retry logic for row lock contention in service layer
    - ⏳ [**#2748**](https://github.com/IBM/mcp-context-forge/issues/2748) - [FEATURE][PLUGINS]: gRPC/Unix socket transport hardening and observability
    - ⏳ [**#2754**](https://github.com/IBM/mcp-context-forge/issues/2754) - [FEATURE][API]: Add PATCH endpoint for user updates, deprecate PUT partial-update semantics
    - ✅ [**#2828**](https://github.com/IBM/mcp-context-forge/issues/2828) - [FEATURE]: Remove observability service dependency from plugin framework
    - ✅ [**#2831**](https://github.com/IBM/mcp-context-forge/issues/2831) - [FEATURE]: Create plugin framework settings
    - ✅ [**#2859**](https://github.com/IBM/mcp-context-forge/issues/2859) - [FEATURE]: Decouple plugin framework data models from gateway core types
    - ⏳ [**#2903**](https://github.com/IBM/mcp-context-forge/issues/2903) - [ENHANCEMENT][PLUGINS]: Proactive secrets management integration for secrets detection plugin

---

## Release 1.1.0

!!! warning "Release 1.1.0 - In Progress (0%)"
    **Due:** 31 Mar 2026 | **Status:** Open
    Technical Debt and Quality

???+ info "📋 Epics - Remaining (22)"

    - ⏳ [**#1304**](https://github.com/IBM/mcp-context-forge/issues/1304) - [EPIC]: Implement SEP-1649 MCP server cards discovery
    - ✅ [**#1306**](https://github.com/IBM/mcp-context-forge/issues/1306) - [EPIC][PLUGIN]: Billing and metering plugin with guaranteed message delivery
    - ⏳ [**#1315**](https://github.com/IBM/mcp-context-forge/issues/1315) - [EPIC][UI]: UI field documentation - Context-sensitive help
    - ⏳ [**#1358**](https://github.com/IBM/mcp-context-forge/issues/1358) - [EPIC]: Configurable tag restrictions - Whitelist enforcement
    - ⏳ [**#1417**](https://github.com/IBM/mcp-context-forge/issues/1417) - [EPIC][PLUGIN]: Improve plugins hygiene
    - ⏳ [**#1471**](https://github.com/IBM/mcp-context-forge/issues/1471) - [EPIC][UI]: Alerting system with UI notification center
    - ⏳ [**#2276**](https://github.com/IBM/mcp-context-forge/issues/2276) - [EPIC][SDK]: OpenAPI SDK generation and UI migration
    - ⏳ [**#2277**](https://github.com/IBM/mcp-context-forge/issues/2277) - [EPIC][UI]: UI component library and design system
    - ⏳ [**#2278**](https://github.com/IBM/mcp-context-forge/issues/2278) - [EPIC][UI]: Unified search and command palette
    - ⏳ [**#2301**](https://github.com/IBM/mcp-context-forge/issues/2301) - [EPIC][UI]: Server and tool ratings and feedback
    - ⏳ [**#2546**](https://github.com/IBM/mcp-context-forge/issues/2546) - [EPIC][CATALOG]: Database-Backed MCP Server Catalog - Workflow, Governance, and Trust Tiers
    - ⏳ [**#2547**](https://github.com/IBM/mcp-context-forge/issues/2547) - [EPIC][A2A]: A2A Protocol v0.3.0 Full Compliance Implementation
    - ⏳ [**#2552**](https://github.com/IBM/mcp-context-forge/issues/2552) - [EPIC][COMPLIANCE]: Extensible Compliance Metadata Framework for MCP Servers and A2A Agents
    - ⏳ [**#2557**](https://github.com/IBM/mcp-context-forge/issues/2557) - [EPIC][BUILD]: Frontend asset minification and optimization
    - ⏳ [**#2597**](https://github.com/IBM/mcp-context-forge/issues/2597) - [EPIC][SECURITY]: SIEM Integration and Security Event Export
    - ⏳ [**#2598**](https://github.com/IBM/mcp-context-forge/issues/2598) - [EPIC][SECURITY]: API Key Lifecycle Management System
    - ⏳ [**#2601**](https://github.com/IBM/mcp-context-forge/issues/2601) - [EPIC][SECURITY]: Internal Secret Rotation with Zero-Downtime
    - ⏳ [**#2652**](https://github.com/IBM/mcp-context-forge/issues/2652) - [EPIC][CICD]: Auto-generate requirements.txt from pyproject.toml
    - ⏳ [**#2792**](https://github.com/IBM/mcp-context-forge/issues/2792) - [EPIC][TESTING][DOCS]: Comprehensive testing strategy documentation overhaul
    - ⏳ [**#2861**](https://github.com/IBM/mcp-context-forge/issues/2861) - [EPIC][UI][SECURITY]: OAuth Gateway Authorization UX Overhaul — Guided Flows, Validation, and Error Recovery
    - ⏳ [**#2952**](https://github.com/IBM/mcp-context-forge/issues/2952) - [EPIC][CORE]: Secure Code Execution & Virtual Tool Filesystem (MCP Code Mode)
    - ⏳ [**#2991**](https://github.com/IBM/mcp-context-forge/issues/2991) - [EPIC][UI][OBSERVABILITY]: Admin Overview redesign with actionable topology and health signals

???+ info "🧪 Testing - Remaining (18)"

    - ⏳ [**#294**](https://github.com/IBM/mcp-context-forge/issues/294) - [FEATURE][TESTING]: Automated MCP server testing and certification
    - ⏳ [**#2425**](https://github.com/IBM/mcp-context-forge/issues/2425) - [TESTING][FUNCTIONALITY]: WebSocket transport manual test plan (connection, bidirectional, multiplexing)
    - ⏳ [**#2427**](https://github.com/IBM/mcp-context-forge/issues/2427) - [TESTING][FUNCTIONALITY]: stdio transport manual test plan (local servers, translation, process management)
    - ⏳ [**#2430**](https://github.com/IBM/mcp-context-forge/issues/2430) - [TESTING][FUNCTIONALITY]: Federation manual test plan (peer discovery, cross-gateway calls, sync)
    - ⏳ [**#2435**](https://github.com/IBM/mcp-context-forge/issues/2435) - [TESTING][FUNCTIONALITY]: Observability manual test plan (metrics, logging, tracing, health)
    - ⏳ [**#2445**](https://github.com/IBM/mcp-context-forge/issues/2445) - [TESTING][FUNCTIONALITY]: gRPC translation manual test plan (service discovery, method invocation, streaming)
    - ⏳ [**#2447**](https://github.com/IBM/mcp-context-forge/issues/2447) - [TESTING][FUNCTIONALITY]: Completion/Autocomplete manual test plan (tool completion, resource completion, prompt completion)
    - ⏳ [**#2449**](https://github.com/IBM/mcp-context-forge/issues/2449) - [TESTING][FUNCTIONALITY]: Roots catalog manual test plan (CRUD, change tracking, notifications)
    - ⏳ [**#2450**](https://github.com/IBM/mcp-context-forge/issues/2450) - [TESTING][FUNCTIONALITY]: Metrics system manual test plan (buffering, rollup, cleanup, queries)
    - ✅ [**#2453**](https://github.com/IBM/mcp-context-forge/issues/2453) - [TESTING][E2E]: User journey - Multi-gateway aggregation end-to-end test (virtual server, tool routing)
    - ⏳ [**#2454**](https://github.com/IBM/mcp-context-forge/issues/2454) - [TESTING][E2E]: User journey - Federation end-to-end test (peer discovery, cross-gateway invocation)
    - ⏳ [**#2460**](https://github.com/IBM/mcp-context-forge/issues/2460) - [TESTING][OPERATIONS]: Metrics Maintenance Manual Test Plan (Rollup, Cleanup, Retention)
    - ⏳ [**#2476**](https://github.com/IBM/mcp-context-forge/issues/2476) - [TESTING][OBSERVABILITY]: Metrics Accuracy, Tracing Completeness, and Dashboard Validation
    - ⏳ [**#2477**](https://github.com/IBM/mcp-context-forge/issues/2477) - [TESTING][INTEGRATION]: OAuth/OIDC Providers, SSO, and External Identity Integration
    - ✅ [**#2478**](https://github.com/IBM/mcp-context-forge/issues/2478) - [TESTING][CONFIGURATION]: Environment Variables, Validation, and Default Values
    - ⏳ [**#2483**](https://github.com/IBM/mcp-context-forge/issues/2483) - [TESTING][DOCUMENTATION]: API Documentation Accuracy, Code Examples, and Tutorial Validation
    - ⏳ [**#2488**](https://github.com/IBM/mcp-context-forge/issues/2488) - [TESTING][MULTI-INSTANCE]: Leader Election, Redis Coordination, and Horizontal Scaling
    - ⏳ [**#2489**](https://github.com/IBM/mcp-context-forge/issues/2489) - [TESTING][WEBHOOK]: Webhook Plugin Event Delivery, Retry Logic, HMAC Signatures

???+ info "🐛 Bugs - Remaining (24)"

    - ⏳ [**#1187**](https://github.com/IBM/mcp-context-forge/issues/1187) - [BUG][HELM]: Latest helm chart not available
    - ⏳ [**#1324**](https://github.com/IBM/mcp-context-forge/issues/1324) - [BUG]: Inconsistent UUID string format across database models
    - ⏳ [**#1405**](https://github.com/IBM/mcp-context-forge/issues/1405) - [BUG]: Incomplete implementation of REST passthrough configuration
    - ⏳ [**#1411**](https://github.com/IBM/mcp-context-forge/issues/1411) - [BUG][OBSERVABILITY]: Prometheus unable to scrape the metrics
    - ⏳ [**#1670**](https://github.com/IBM/mcp-context-forge/issues/1670) - [BUG][DB]: Advisory lock IDs should be namespaced by database name
    - ⏳ [**#1704**](https://github.com/IBM/mcp-context-forge/issues/1704) - [BUG][API]: prompts/get RPC incorrectly looks up by ID instead of name per MCP spec
    - ⏳ [**#1961**](https://github.com/IBM/mcp-context-forge/issues/1961) - [BUG][PERFORMANCE]: Fix minor performance issues in llm-guard plugin
    - ⏳ [**#2119**](https://github.com/IBM/mcp-context-forge/issues/2119) - [BUG]: Server toggle returns 400 errors under load
    - ✅ [**#2159**](https://github.com/IBM/mcp-context-forge/issues/2159) - [BUG][UI]: Search filter on the tools tab only filters for the current page
    - ⏳ [**#2162**](https://github.com/IBM/mcp-context-forge/issues/2162) - [BUG]: Prevent asyncio tasks from being garbage collected (S7502)
    - ⏳ [**#2334**](https://github.com/IBM/mcp-context-forge/issues/2334) - [BUG]: Apply fresh_db_session() to remaining 271 endpoints using Depends(get_db)
    - ⏳ [**#2335**](https://github.com/IBM/mcp-context-forge/issues/2335) - [BUG]: Apply fresh_db_session() to admin.py endpoints (135 usages)
    - ⏳ [**#2336**](https://github.com/IBM/mcp-context-forge/issues/2336) - [BUG]: Apply fresh_db_session() to remaining 52 REST endpoints in main.py
    - ✅ [**#2522**](https://github.com/IBM/mcp-context-forge/issues/2522) - [BUG][MINOR]: Migration silent exception handling may mask schema failures
    - ⏳ [**#2621**](https://github.com/IBM/mcp-context-forge/issues/2621) - [BUG][PLUGINS]: Race conditions in plugin global state dictionaries under concurrent load
    - ⏳ [**#2643**](https://github.com/IBM/mcp-context-forge/issues/2643) - [BUG][UI]: Total Executions metric fluctuates randomly on page refresh
    - ⏳ [**#2669**](https://github.com/IBM/mcp-context-forge/issues/2669) - [BUG][PERFORMANCE]: Remove unnecessary SERVER_RESET_QUERY=DISCARD ALL from PgBouncer config
    - ⏳ [**#2691**](https://github.com/IBM/mcp-context-forge/issues/2691) - [BUG]: Teams - Team visibility updates are not reflected until the page is refreshed
    - ⏳ [**#2692**](https://github.com/IBM/mcp-context-forge/issues/2692) - [BUG][PERFORMANCE]: auth hot-path DB queries dominate request latency under load
    - ✅ [**#2796**](https://github.com/IBM/mcp-context-forge/issues/2796) - [BUG][PLUGINS]: External MCP plugin session not recovered after plugin restart
    - ⏳ [**#2854**](https://github.com/IBM/mcp-context-forge/issues/2854) - [BUG][API]: gRPC service registration unusable - multiple failures
    - ✅ [**#2864**](https://github.com/IBM/mcp-context-forge/issues/2864) - [BUG][UI]: Race condition in deleteTeamSafe causes stale team list after deletion
    - ✅ [**#2968**](https://github.com/IBM/mcp-context-forge/issues/2968) - [BUG]: MCP Servers - Edit - Admin role - The Admin can no longer see the token
    - ⏳ [**#3005**](https://github.com/IBM/mcp-context-forge/issues/3005) - [BUG][PERFORMANCE]: Extend get_user_teams cache to store full team objects instead of just IDs

???+ info "🔒 Security - Remaining (6)"

    - ⏳ [**#230**](https://github.com/IBM/mcp-context-forge/issues/230) - [FEATURE][SECURITY]: Cryptographic request and response signing
    - ⏳ [**#257**](https://github.com/IBM/mcp-context-forge/issues/257) - [FEATURE][SECURITY]: Gateway-level rate limiting, DDoS protection, and abuse detection
    - ⏳ [**#541**](https://github.com/IBM/mcp-context-forge/issues/541) - [FEATURE][SECURITY]: Enhanced session management for admin UI
    - ✅ [**#568**](https://github.com/IBM/mcp-context-forge/issues/568) - [FEATURE][SECURITY]: mTLS support for gateway, plugins, and MCP servers
    - ✅ [**#654**](https://github.com/IBM/mcp-context-forge/issues/654) - [FEATURE][SECURITY]: Pre-register checks (MCP server scan)
    - ⏳ [**#2712**](https://github.com/IBM/mcp-context-forge/issues/2712) - [ENHANCEMENT][SECURITY]: Virtual Server token enforcement - require scoped tokens for access

???+ info "⚡ Performance - Remaining (37)"

    - ⏳ [**#1296**](https://github.com/IBM/mcp-context-forge/issues/1296) - [PERFORMANCE][REDIS]: Redis endpoint response caching
    - ⏳ [**#1297**](https://github.com/IBM/mcp-context-forge/issues/1297) - [PERFORMANCE]: Production server tuning
    - ⏳ [**#1625**](https://github.com/IBM/mcp-context-forge/issues/1625) - [RUST]: Implement high-performance metrics aggregation in Rust
    - ⏳ [**#1679**](https://github.com/IBM/mcp-context-forge/issues/1679) - [PERFORMANCE]: Make Query Logging Non-Blocking with Async I/O
    - ⏳ [**#1685**](https://github.com/IBM/mcp-context-forge/issues/1685) - [PERFORMANCE]: Optimize Database Session Creation and Management
    - ⏳ [**#1689**](https://github.com/IBM/mcp-context-forge/issues/1689) - [PERFORMANCE]: Improve Instrumentation Span Queue Handling
    - ⏳ [**#1690**](https://github.com/IBM/mcp-context-forge/issues/1690) - [PERFORMANCE]: Optimize Response Streaming for Large Payloads
    - ⏳ [**#1693**](https://github.com/IBM/mcp-context-forge/issues/1693) - [PERFORMANCE]: Optimize Background Task Execution
    - ⏳ [**#1694**](https://github.com/IBM/mcp-context-forge/issues/1694) - [PERFORMANCE]: Optimize Database Migration Performance
    - ⏳ [**#1751**](https://github.com/IBM/mcp-context-forge/issues/1751) - [PERFORMANCE]: Phase 2 Caching - Auth Batching & Low-Risk Endpoint Caching
    - ⏳ [**#1759**](https://github.com/IBM/mcp-context-forge/issues/1759) - [PERFORMANCE]: Optimize in-memory log storage queries
    - ⏳ [**#1769**](https://github.com/IBM/mcp-context-forge/issues/1769) - [PERFORMANCE]: PostgreSQL SQL optimization opportunities
    - ⏳ [**#1807**](https://github.com/IBM/mcp-context-forge/issues/1807) - [PERFORMANCE]: Reduce CPU cost of validation middleware full-body traversal
    - ⏳ [**#1823**](https://github.com/IBM/mcp-context-forge/issues/1823) - [PERFORMANCE]: Reduce CPU hotspots in translate.py (stdio/SSE/streamable HTTP)
    - ⏳ [**#1824**](https://github.com/IBM/mcp-context-forge/issues/1824) - [PERFORMANCE]: Cache gRPC schema generation and make default-field expansion optional
    - ⏳ [**#1833**](https://github.com/IBM/mcp-context-forge/issues/1833) - [PERFORMANCE]: Optimize SQLite tag filter SQL/bind generation
    - ⏳ [**#1860**](https://github.com/IBM/mcp-context-forge/issues/1860) - [PERFORMANCE]: Gunicorn Server Backpressure with Concurrency Limit Middleware
    - ⏳ [**#1895**](https://github.com/IBM/mcp-context-forge/issues/1895) - [PERFORMANCE]: Pydantic model_validate() overhead in hot paths
    - ⏳ [**#1930**](https://github.com/IBM/mcp-context-forge/issues/1930) - [PERFORMANCE]: Optimize httpx - Replace per-request AsyncClient with shared client
    - ⏳ [**#1958**](https://github.com/IBM/mcp-context-forge/issues/1958) - [PERFORMANCE]: Optimize llm-guard plugin
    - ⏳ [**#1993**](https://github.com/IBM/mcp-context-forge/issues/1993) - [PERFORMANCE]: Add DB_POOL_USE_LIFO configuration for SQLAlchemy QueuePool
    - ⏳ [**#1997**](https://github.com/IBM/mcp-context-forge/issues/1997) - [PERFORMANCE]: Audit and fix SELECT-only endpoints missing explicit commit for PgBouncer compatibility
    - ⏳ [**#2000**](https://github.com/IBM/mcp-context-forge/issues/2000) - [PERFORMANCE]: Add missing indexes on association tables
    - ⏳ [**#2008**](https://github.com/IBM/mcp-context-forge/issues/2008) - [PERFORMANCE]: audit_trails table has 18 indexes causing severe write amplification
    - ⏳ [**#2009**](https://github.com/IBM/mcp-context-forge/issues/2009) - [PERFORMANCE]: security_events table has 16 indexes causing write overhead
    - ⏳ [**#2012**](https://github.com/IBM/mcp-context-forge/issues/2012) - [PERFORMANCE]: Observability feature causes major performance regression
    - ⏳ [**#2013**](https://github.com/IBM/mcp-context-forge/issues/2013) - [PERFORMANCE]: Remove 16 unused indexes on structured_log_entries table
    - ⏳ [**#2014**](https://github.com/IBM/mcp-context-forge/issues/2014) - [PERFORMANCE]: Optimize tool_metrics table - 1B+ sequential tuple reads
    - ⏳ [**#2032**](https://github.com/IBM/mcp-context-forge/issues/2032) - [PERFORMANCE]: Cache full EmailTeam objects instead of IDs in auth_cache
    - ⏳ [**#2034**](https://github.com/IBM/mcp-context-forge/issues/2034) - [PERFORMANCE]: Add fast-path middleware bypass for /rpc endpoints
    - ⏳ [**#2035**](https://github.com/IBM/mcp-context-forge/issues/2035) - [PERFORMANCE]: Cache negative token revocation results longer
    - ⏳ [**#2036**](https://github.com/IBM/mcp-context-forge/issues/2036) - [PERFORMANCE]: Consolidate tool query variants to improve query plan caching
    - ⏳ [**#2037**](https://github.com/IBM/mcp-context-forge/issues/2037) - [PERFORMANCE]: Add load_only() to list view queries to reduce data transfer
    - ⏳ [**#2115**](https://github.com/IBM/mcp-context-forge/issues/2115) - [PERFORMANCE]: Pre-compute CSP header string at startup
    - ⏳ [**#2116**](https://github.com/IBM/mcp-context-forge/issues/2116) - [PERFORMANCE]: Parallelize admin dashboard service calls with asyncio.gather()
    - ⏳ [**#2117**](https://github.com/IBM/mcp-context-forge/issues/2117) - [PERFORMANCE]: Move /admin/export/configuration to async job queue
    - ⏳ [**#2993**](https://github.com/IBM/mcp-context-forge/issues/2993) - [UI][PERFORMANCE]: Lazy-load admin tab partials and reduce initial request fan-out

???+ info "📚 Documentation - Remaining (1)"

    - ⏳ [**#892**](https://github.com/IBM/mcp-context-forge/issues/892) - [DOCS]: Update and test IBM Cloud deployment documentation

???+ info "🔧 Chores - Remaining (27)"

    - ⏳ [**#216**](https://github.com/IBM/mcp-context-forge/issues/216) - [CHORE]: Add spec-validation targets and make the OpenAPI build go green
    - ⏳ [**#383**](https://github.com/IBM/mcp-context-forge/issues/383) - [CHORE][HELM]: Remove migration step from Helm chart
    - ⏳ [**#1290**](https://github.com/IBM/mcp-context-forge/issues/1290) - [CHORE] Remove redundant import checkers: importchecker and unimport
    - ⏳ [**#1300**](https://github.com/IBM/mcp-context-forge/issues/1300) - [CHORE]: Transition linter execution from local venv to uvx-driven
    - ⏳ [**#1420**](https://github.com/IBM/mcp-context-forge/issues/1420) - [CHORE]: Naming discussion - Gateways vs MCP Servers terminology
    - ⏳ [**#1588**](https://github.com/IBM/mcp-context-forge/issues/1588) - [CHORE][REFACTOR]: Standardize root_path access pattern across codebase
    - ⏳ [**#1591**](https://github.com/IBM/mcp-context-forge/issues/1591) - [CHORE][REFACTOR]: Preserve specific exceptions in service error handlers
    - ⏳ [**#1901**](https://github.com/IBM/mcp-context-forge/issues/1901) - [CHORE]: cleanup dead code in mcpgateway/common/ and related modules
    - ⏳ [**#1974**](https://github.com/IBM/mcp-context-forge/issues/1974) - [CHORE][REFACTOR]: Simplify convert_server_to_read using Pydantic from_attributes
    - ⏳ [**#2091**](https://github.com/IBM/mcp-context-forge/issues/2091) - [CHORE][REFACTOR]: Reduce code duplication in team management UI and cursor pagination
    - ⏳ [**#2133**](https://github.com/IBM/mcp-context-forge/issues/2133) - [CHORE]: Refine AGENTS.md for code assistant behavior guidelines
    - ⏳ [**#2147**](https://github.com/IBM/mcp-context-forge/issues/2147) - [CHORE]: Consolidate redundant get_db definitions to single source
    - ⏳ [**#2165**](https://github.com/IBM/mcp-context-forge/issues/2165) - [CHORE]: Remove duplicate if/else branches and exception handlers (S3923, S1045)
    - ⏳ [**#2175**](https://github.com/IBM/mcp-context-forge/issues/2175) - [CHORE]: Align VirusTotal upload retry logic with ResilientHttpClient semantics
    - ✅ [**#2369**](https://github.com/IBM/mcp-context-forge/issues/2369) - [CLEANUP][SONAR][LOW]: Dead code - if/else branches identical in admin.py
    - ⏳ [**#2373**](https://github.com/IBM/mcp-context-forge/issues/2373) - [CLEANUP][SONAR][LOW]: Code duplication - tools/list vs list_tools endpoints in main.py
    - ⏳ [**#2374**](https://github.com/IBM/mcp-context-forge/issues/2374) - [CLEANUP][SONAR][LOW]: Redundant exception handling - ValidationError already caught by ValueError
    - ⏳ [**#2376**](https://github.com/IBM/mcp-context-forge/issues/2376) - [CLEANUP][SONAR][LOW]: Identical if/elif branches in path_template normalization in schemas.py
    - ⏳ [**#2379**](https://github.com/IBM/mcp-context-forge/issues/2379) - [CLEANUP][SONAR][LOW]: Dead code - identical if/else with commented-out logic in translate.py
    - ⏳ [**#2380**](https://github.com/IBM/mcp-context-forge/issues/2380) - [CLEANUP][SONAR][LOW]: Identical if/else branches in error handling in wrapper.py
    - ⏳ [**#2381**](https://github.com/IBM/mcp-context-forge/issues/2381) - [CLEANUP][SONAR][LOW]: Identical if/elif branches in catalog_service.py auth handling
    - ⏳ [**#2505**](https://github.com/IBM/mcp-context-forge/issues/2505) - [CHORE]: Standardize user context parameter naming (_user vs current_user_ctx)
    - ⏳ [**#2577**](https://github.com/IBM/mcp-context-forge/issues/2577) - [REFACTOR][API]: Standardize error response formatting with ErrorFormatter
    - ⏳ [**#2613**](https://github.com/IBM/mcp-context-forge/issues/2613) - [CHORE][BUILD]: Consolidate Container Images - Single Containerfile
    - ⏳ [**#2872**](https://github.com/IBM/mcp-context-forge/issues/2872) - [TASK][PLUGINS]: Add unit tests for secrets detection plugins
    - ⏳ [**#2969**](https://github.com/IBM/mcp-context-forge/issues/2969) - [CHORE][RUST]: enforce code coverage to 90% for rust plugins
    - ✅ [**#3027**](https://github.com/IBM/mcp-context-forge/issues/3027) - [CHORE]: setup rust mcpgateway for internal components

???+ info "✨ Features - Remaining (34)"

    - ⏳ [**#130**](https://github.com/IBM/mcp-context-forge/issues/130) - [FEATURE][AI]: Dynamic LLM-powered tool generation via prompt
    - ⏳ [**#172**](https://github.com/IBM/mcp-context-forge/issues/172) - [FEATURE]: Enable auto refresh and reconnection for MCP servers
    - ⏳ [**#217**](https://github.com/IBM/mcp-context-forge/issues/217) - [FEATURE]: Graceful-shutdown hooks for API and worker containers
    - ⏳ [**#284**](https://github.com/IBM/mcp-context-forge/issues/284) - [FEATURE][AUTH]: LDAP / Active Directory integration
    - ⏳ [**#386**](https://github.com/IBM/mcp-context-forge/issues/386) - [FEATURE][UI]: Gateways/MCP servers page refresh
    - ⏳ [**#566**](https://github.com/IBM/mcp-context-forge/issues/566) - [FEATURE]: Add support for limiting specific fields to user-defined values
    - ⏳ [**#647**](https://github.com/IBM/mcp-context-forge/issues/647) - [FEATURE]: Configurable caching for tools
    - ⏳ [**#707**](https://github.com/IBM/mcp-context-forge/issues/707) - [FEATURE][UI]: Customizable admin panel
    - ⏳ [**#732**](https://github.com/IBM/mcp-context-forge/issues/732) - [FEATURE][UI]: Enhance handling of long tool descriptions
    - ✅ [**#743**](https://github.com/IBM/mcp-context-forge/issues/743) - [FEATURE][UI]: Enhance server creation/editing UI for prompt and resource association
    - ⏳ [**#758**](https://github.com/IBM/mcp-context-forge/issues/758) - [FEATURE][PROTOCOL]: Implement missing MCP protocol methods
    - ⏳ [**#1122**](https://github.com/IBM/mcp-context-forge/issues/1122) - [FEATURE][AUTH]: Investigate bearer token validation with Keycloak JWT
    - ⏳ [**#1140**](https://github.com/IBM/mcp-context-forge/issues/1140) - [FEATURE][PLUGIN]: Reduce complexity in plugin configuration framework
    - ⏳ [**#1160**](https://github.com/IBM/mcp-context-forge/issues/1160) - [FEATURE]: Add Roundtable external MCP server for enterprise AI assistant orchestration
    - ⏳ [**#1191**](https://github.com/IBM/mcp-context-forge/issues/1191) - [FEATURE][PLUGIN]: Content limit plugin - Resource exhaustion protection
    - ⏳ [**#1264**](https://github.com/IBM/mcp-context-forge/issues/1264) - [FEATURE][AUTH]: Support for LDAP integration with multiple domains
    - ⏳ [**#1361**](https://github.com/IBM/mcp-context-forge/issues/1361) - [FEATURE]: OpenAPI to REST protocol conversion tool
    - ⏳ [**#1413**](https://github.com/IBM/mcp-context-forge/issues/1413) - [FEATURE][PLUGIN]: Add maturity levels to plugins
    - ⏳ [**#1421**](https://github.com/IBM/mcp-context-forge/issues/1421) - [FEATURE][CONFIG]: Unified config surface
    - ✅ [**#1429**](https://github.com/IBM/mcp-context-forge/issues/1429) - [FEATURE][PLUGIN]: RBAC plugin using Cedar
    - ⏳ [**#1434**](https://github.com/IBM/mcp-context-forge/issues/1434) - [FEATURE][AUTH]: Comprehensive OAuth2 base library with helper functions
    - ⏳ [**#1437**](https://github.com/IBM/mcp-context-forge/issues/1437) - [FEATURE][PLUGIN]: Create IAM pre-tool plugin
    - ⏳ [**#1622**](https://github.com/IBM/mcp-context-forge/issues/1622) - [RUST]: Implement translate-grpc module in Rust
    - ⏳ [**#1623**](https://github.com/IBM/mcp-context-forge/issues/1623) - [RUST]: Build translate-graphql module in Rust
    - ⏳ [**#1624**](https://github.com/IBM/mcp-context-forge/issues/1624) - [RUST]: Rewrite A2A invocation core in Rust
    - ⏳ [**#1796**](https://github.com/IBM/mcp-context-forge/issues/1796) - [FEATURE][OBSERVABILITY]: Allow timezone configuration for built-in observability and metrics
    - ⏳ [**#2027**](https://github.com/IBM/mcp-context-forge/issues/2027) - [FEATURE]: Fail fast on non-transient connection errors during startup
    - ✅ [**#2049**](https://github.com/IBM/mcp-context-forge/issues/2049) - [FEATURE][BUILD]: Support for container builds for ppc64le
    - ⏳ [**#2063**](https://github.com/IBM/mcp-context-forge/issues/2063) - [FEATURE][I18N]: Add internationalization support for Chinese (zh-CN)
    - ⏳ [**#2101**](https://github.com/IBM/mcp-context-forge/issues/2101) - [FEATURE]: Make public teams discovery limit configurable via environment variable
    - ⏳ [**#2135**](https://github.com/IBM/mcp-context-forge/issues/2135) - [FEATURE][DEPLOYMENT]: Ansible playbook for AWS deployment of demo and test environments
    - ⏳ [**#2503**](https://github.com/IBM/mcp-context-forge/issues/2503) - [QUICK-START]: 5-Minute Setup & First Steps
    - ⏳ [**#2504**](https://github.com/IBM/mcp-context-forge/issues/2504) - [SUPPORT]: Getting Help & Support Options
    - ⏳ [**#2551**](https://github.com/IBM/mcp-context-forge/issues/2551) - [FEATURE][COMPLIANCE]: Hosting Location Metadata for MCP Servers and A2A Agents

---

## Release 1.0.0-RC3

!!! success "Release 1.0.0-RC3 - Complete (100%)"
    **Due:** 14 Apr 2026 | **Status:** **Closed**
    Release Candidate 3 - Auth Hardening, Plugin Multi-Tenancy, Rust Runtime & Multi-Arch

    Final pre-1.0 candidate consolidating **242 commits** and **294 closed issues**. Highlights: token-teams narrowing across Layer 2 RBAC, plugin framework multi-tenancy with hybrid AND/OR condition evaluation, experimental Rust MCP runtime, s390x / ppc64le multi-arch support, Langfuse LLM observability. MySQL/MariaDB/MongoDB support removed. See [CHANGELOG.md](https://github.com/IBM/mcp-context-forge/blob/main/CHANGELOG.md#100-rc3---2026-04-14---auth-hardening-plugin-multi-tenancy-rust-runtime--multi-arch) for full details.

???+ check "📋 Epics - Completed (9)"

    - ✅ [**#2547**](https://github.com/IBM/mcp-context-forge/issues/2547) - [EPIC][A2A]: A2A Protocol v0.3.0 Full Compliance Implementation
    - ✅ [**#2659**](https://github.com/IBM/mcp-context-forge/issues/2659) - [EPIC][SSO][SECURITY]: OIDC Token Verification - Enterprise Claims Extraction
    - ✅ [**#2660**](https://github.com/IBM/mcp-context-forge/issues/2660) - [EPIC][PERFORMANCE]: Database Session Management - Eliminate Transaction Leaks Under Load
    - ✅ [**#2668**](https://github.com/IBM/mcp-context-forge/issues/2668) - [BUG]: Follow-up: Rate limiter — incorrect HTTP status, missing headers, and feature gaps (refs #2397)
    - ✅ [**#3538**](https://github.com/IBM/mcp-context-forge/issues/3538) - [EPIC][SECURITY]: Auth context consolidation — eliminate duplicated auth logic
    - ✅ [**#3638**](https://github.com/IBM/mcp-context-forge/issues/3638) - [EPIC][API]: Add gateway_id filtering to prompts and resources listing endpoints
    - ✅ [**#3665**](https://github.com/IBM/mcp-context-forge/issues/3665) - feat: Added gateway_id filtering to prompts and resources listing endpoints and corresponding unit and integration tests.
    - ✅ [**#3801**](https://github.com/IBM/mcp-context-forge/issues/3801) - [EPIC][PLUGINS]: Support for Plugins Multi-tenancy and dynamic loading
    - ✅ [**#3901**](https://github.com/IBM/mcp-context-forge/issues/3901) - [EPIC][OBSERVABILITY]: Full Langfuse LLM observability integration — rich traces, user context, and A2A coverage

???+ check "✨ Features - Completed (47)"

    - ✅ [**#1191**](https://github.com/IBM/mcp-context-forge/issues/1191) - [FEATURE][PLUGIN]: Content limit plugin - Resource exhaustion protection
    - ✅ [**#1985**](https://github.com/IBM/mcp-context-forge/issues/1985) - [FEATURE]: Elicitation pass-through and logging
    - ✅ [**#2730**](https://github.com/IBM/mcp-context-forge/issues/2730) - [RUST] Plugin Architecture Options
    - ✅ [**#2810**](https://github.com/IBM/mcp-context-forge/issues/2810) - [FEATURE][A2A]: Ability to register and use non-A2A Agents (HTTP based Agents)
    - ✅ [**#3137**](https://github.com/IBM/mcp-context-forge/issues/3137) - feat(ui): modularize admin scope into independent modules
    - ✅ [**#3204**](https://github.com/IBM/mcp-context-forge/issues/3204) - feat(ui): persist admin table filters across HTMX pagination and part…
    - ✅ [**#3217**](https://github.com/IBM/mcp-context-forge/issues/3217) - feat(auth): add team scope support for session tokens
    - ✅ [**#3454**](https://github.com/IBM/mcp-context-forge/issues/3454) - feat(ci): add Helm chart lint and OCI publish workflow
    - ✅ [**#3479**](https://github.com/IBM/mcp-context-forge/issues/3479) - [FEAT][UI]: Role based Admin UI visibility gating
    - ✅ [**#3537**](https://github.com/IBM/mcp-context-forge/issues/3537) - Standardize user context parameter naming (_user vs current_user_ctx)…
    - ✅ [**#3552**](https://github.com/IBM/mcp-context-forge/issues/3552) - fix(charts): fix TRANSPORT_TYPE validation and enable minikube testing profile
    - ✅ [**#3602**](https://github.com/IBM/mcp-context-forge/issues/3602) - fix(ui): show federated prompt arguments in Admin UI instead of empty list
    - ✅ [**#3603**](https://github.com/IBM/mcp-context-forge/issues/3603) - test-clear-filters-htmx-race-condition
    - ✅ [**#3604**](https://github.com/IBM/mcp-context-forge/issues/3604) - Logging Hardening and Sanitization
    - ✅ [**#3647**](https://github.com/IBM/mcp-context-forge/issues/3647) - feat(ui): persist admin table filters across HTMX pagination and partial refresh
    - ✅ [**#3663**](https://github.com/IBM/mcp-context-forge/issues/3663) - feat: Add PLUGINS_CAN_OVERRIDE_AUTH_HEADERS feature flag for WXO auth
    - ✅ [**#3675**](https://github.com/IBM/mcp-context-forge/issues/3675) - fix(transports): forward passthrough headers in SSE/WebSocket loopback calls
    - ✅ [**#3676**](https://github.com/IBM/mcp-context-forge/issues/3676) - feat(api): Add gateway_id filtering to prompts and resources listing endpoints
    - ✅ [**#3677**](https://github.com/IBM/mcp-context-forge/issues/3677) - fix(mcp): Direct proxy paths use shared passthrough header utility
    - ✅ [**#3728**](https://github.com/IBM/mcp-context-forge/issues/3728) - feat(plugins): add Rust url_reputation plugin
    - ✅ [**#3739**](https://github.com/IBM/mcp-context-forge/issues/3739) - fix(session-pool): isolate cancel scopes via background task ownership
    - ✅ [**#3747**](https://github.com/IBM/mcp-context-forge/issues/3747) - [FEAT][PLUGINS]: Output Length Guard Plugin v1.0.0 - Major Feature Release
    - ✅ [**#3759**](https://github.com/IBM/mcp-context-forge/issues/3759) - chore: standardize cargo-deny coverage for rust projects
    - ✅ [**#3765**](https://github.com/IBM/mcp-context-forge/issues/3765) - [FEATURE][UI]: MCP tool refresh button
    - ✅ [**#3774**](https://github.com/IBM/mcp-context-forge/issues/3774) - feat: add retry-with-exponential-backoff plugin
    - ✅ [**#3775**](https://github.com/IBM/mcp-context-forge/issues/3775) - ci: use native GitHub runners for s390x and ppc64le Docker builds
    - ✅ [**#3802**](https://github.com/IBM/mcp-context-forge/issues/3802) - feat(ui): MCP tool refresh button
    - ✅ [**#3812**](https://github.com/IBM/mcp-context-forge/issues/3812) - fix(auth): close auth bypass on /mcp/{server_id} virtual server endpoints
    - ✅ [**#3839**](https://github.com/IBM/mcp-context-forge/issues/3839) - feat(discovery): add automatic tool discovery with hot/cold classification
    - ✅ [**#3841**](https://github.com/IBM/mcp-context-forge/issues/3841) - feat(plugin): output length guard plugin
    - ✅ [**#3858**](https://github.com/IBM/mcp-context-forge/issues/3858) - [TASK][OBSERVABILITY]: Add end-to-end OTEL trace trees and W3C propagation for gateway to MCP servers
    - ✅ [**#3860**](https://github.com/IBM/mcp-context-forge/issues/3860) - Bh/detect secrets
    - ✅ [**#3872**](https://github.com/IBM/mcp-context-forge/issues/3872) - feat(observability): add OTEL root and client spans for MCP flows
    - ✅ [**#3900**](https://github.com/IBM/mcp-context-forge/issues/3900) - feat: integrate Langfuse LLM observability via OTEL
    - ✅ [**#3916**](https://github.com/IBM/mcp-context-forge/issues/3916) - fix(tools): remove semicolon from tool description forbidden patterns
    - ✅ [**#3930**](https://github.com/IBM/mcp-context-forge/issues/3930) - [FEATURE]: Hierarchical Plugin Condition Evaluation (Breaking Change)
    - ✅ [**#3931**](https://github.com/IBM/mcp-context-forge/issues/3931) - test: add secrets detection hook regressions
    - ✅ [**#3941**](https://github.com/IBM/mcp-context-forge/issues/3941) - Add OAuth token claim validation before MCP server forwarding
    - ✅ [**#3952**](https://github.com/IBM/mcp-context-forge/issues/3952) - fix: session pool resource exhaustion
    - ✅ [**#3976**](https://github.com/IBM/mcp-context-forge/issues/3976) - [FEATURE]: OpenTelemetry Baggage Propagation with Configurable Header Validation
    - ✅ [**#3987**](https://github.com/IBM/mcp-context-forge/issues/3987) - fix(bootstrap): rename orphaned resources to fix team and name assignment conflict
    - ✅ [**#3996**](https://github.com/IBM/mcp-context-forge/issues/3996) - [FEATURE][PLUGINS]: Phase2 -  Plugin-Tool Policy Config CRUD API
    - ✅ [**#4008**](https://github.com/IBM/mcp-context-forge/issues/4008) - feat: Add OpenTelemetry W3C Baggage support for distributed tracing
    - ✅ [**#4029**](https://github.com/IBM/mcp-context-forge/issues/4029) - fix(mcp): resolve MCP session pool memory leak, dead-worker locks and polling inefficiency
    - ✅ [**#4034**](https://github.com/IBM/mcp-context-forge/issues/4034) - fix: honor fail_on_plugin_error during plugin init
    - ✅ [**#4039**](https://github.com/IBM/mcp-context-forge/issues/4039) - Updates to pre-commit for cyclical secret detection issue
    - ✅ [**#4081**](https://github.com/IBM/mcp-context-forge/issues/4081) - fix(permissions): add missing TOOLS_MANAGE_PLUGINS permission constant

???+ check "🔒 Security - Completed (60)"

    - ✅ [**#230**](https://github.com/IBM/mcp-context-forge/issues/230) - [FEATURE][SECURITY]: Cryptographic request and response signing
    - ✅ [**#341**](https://github.com/IBM/mcp-context-forge/issues/341) - [CHORE]: Enhance UI security with DOMPurify and content sanitization
    - ✅ [**#342**](https://github.com/IBM/mcp-context-forge/issues/342) - [FEATURE][SECURITY]: Implement database-level security constraints and SQL injection prevention
    - ✅ [**#534**](https://github.com/IBM/mcp-context-forge/issues/534) - [FEATURE][SECURITY]: Add security configuration validation and startup checks
    - ✅ [**#538**](https://github.com/IBM/mcp-context-forge/issues/538) - [FEATURE][SECURITY]: Content size and type security limits for resources and prompts
    - ✅ [**#539**](https://github.com/IBM/mcp-context-forge/issues/539) - [FEATURE][SECURITY]: Tool execution limits and resource controls
    - ✅ [**#1122**](https://github.com/IBM/mcp-context-forge/issues/1122) - [FEATURE][AUTH]: Investigate bearer token validation with Keycloak JWT
    - ✅ [**#1436**](https://github.com/IBM/mcp-context-forge/issues/1436) - [FEATURE][AUTH]: Propagate end user identity and context through the CF workflow
    - ✅ [**#2330**](https://github.com/IBM/mcp-context-forge/issues/2330) - [BUG][PERFORMANCE]: TokenScopingMiddleware causes connection pool exhaustion under load
    - ✅ [**#2389**](https://github.com/IBM/mcp-context-forge/issues/2389) - [FEATURE][AUTH]: Add A2A agent RBAC enforcement to token scoping middleware
    - ✅ [**#2395**](https://github.com/IBM/mcp-context-forge/issues/2395) - [TESTING][SECURITY]: MCP authentication modes manual test plan (permissive, strict, transport auth)
    - ✅ [**#2407**](https://github.com/IBM/mcp-context-forge/issues/2407) - [TESTING][SECURITY]: Federation security manual test plan (cross-gateway auth, peer validation)
    - ✅ [**#3068**](https://github.com/IBM/mcp-context-forge/issues/3068) - [BUG][AUTH]: OAuth OBO flow missing token audience validation and legacy state format failure
    - ✅ [**#3201**](https://github.com/IBM/mcp-context-forge/issues/3201) - fix(ui): admin UI "Show" toggle for gateway tokens, passwords, and header values
    - ✅ [**#3228**](https://github.com/IBM/mcp-context-forge/issues/3228) - fix(oauth): harden legacy state handling and document token audience gap
    - ✅ [**#3253**](https://github.com/IBM/mcp-context-forge/issues/3253) - [BUG][AUTH]: Microsoft Entra SSO — first-time user creation fails due to missing email_verified claim
    - ✅ [**#3365**](https://github.com/IBM/mcp-context-forge/issues/3365) - [BUG][API]: Forwarded RPC non-2xx responses masked as success — affinity tests non-hermetic
    - ✅ [**#3381**](https://github.com/IBM/mcp-context-forge/issues/3381) - [BUG]: _execute_forwarded_request silently swallows HTTP errors as successful empty results
    - ✅ [**#3416**](https://github.com/IBM/mcp-context-forge/issues/3416) - [BUG][UI]: Create Team button shown to users without teams.create permission
    - ✅ [**#3474**](https://github.com/IBM/mcp-context-forge/issues/3474) - fix(deps): dependency security hardening updates
    - ✅ [**#3523**](https://github.com/IBM/mcp-context-forge/issues/3523) - [BUG][API]: _create_db_tool() hardcodes visibility="public" instead of inheriting gateway visibility
    - ✅ [**#3524**](https://github.com/IBM/mcp-context-forge/issues/3524) - [BUG]: Resource visibility semantics inconsistent between register_gateway() and _update_or_create_resources()
    - ✅ [**#3525**](https://github.com/IBM/mcp-context-forge/issues/3525) - [BUG]: GatewayUpdate.visibility accepts arbitrary strings — no enum validation
    - ✅ [**#3531**](https://github.com/IBM/mcp-context-forge/issues/3531) - [BUG][API]: Naive vs aware datetime crashes on SQLite in PasswordResetToken, UserRole, and EmailApiToken
    - ✅ [**#3532**](https://github.com/IBM/mcp-context-forge/issues/3532) - [BUG][UI]: ADFS SSO login page shows duplicate provider buttons (ADFS + Auth0)
    - ✅ [**#3535**](https://github.com/IBM/mcp-context-forge/issues/3535) - [BUG][AUTH]: OAuth RFC 9728 protected resource metadata not working with Cursor IDE
    - ✅ [**#3543**](https://github.com/IBM/mcp-context-forge/issues/3543) - [CHORE][PYTHON]: Consolidate internal loopback RPC calls into a shared helper
    - ✅ [**#3554**](https://github.com/IBM/mcp-context-forge/issues/3554) - [BUG][UI]: Non-admin users see menu items they lack permissions for
    - ✅ [**#3563**](https://github.com/IBM/mcp-context-forge/issues/3563) - [BUG][AUTH]: OAuth OBO flow missing token audience and scope validation before MCP server call
    - ✅ [**#3566**](https://github.com/IBM/mcp-context-forge/issues/3566) - fix: implement permission-based menu hiding in admin UI
    - ✅ [**#3597**](https://github.com/IBM/mcp-context-forge/issues/3597) - fix: extract groups from id_token for generic OIDC providers
    - ✅ [**#3635**](https://github.com/IBM/mcp-context-forge/issues/3635) - fix(auth): SSO login blocked for providers that omit email_verified claim
    - ✅ [**#3640**](https://github.com/IBM/mcp-context-forge/issues/3640) - [BUG]: SSE and WebSocket transports drop client passthrough headers (X-Upstream-Authorization) in loopback /rpc calls
    - ✅ [**#3643**](https://github.com/IBM/mcp-context-forge/issues/3643) - [BUG]: Direct proxy paths in Streamable HTTP skip X-Upstream-Authorization rename
    - ✅ [**#3654**](https://github.com/IBM/mcp-context-forge/issues/3654) - [BUG][AUTH]: Admin API tokens created with 'All Teams' get teams=[] instead of teams=null
    - ✅ [**#3678**](https://github.com/IBM/mcp-context-forge/issues/3678) - fix(gateway): preserve per-resource visibility on gateway refresh
    - ✅ [**#3686**](https://github.com/IBM/mcp-context-forge/issues/3686) - fix(auth): set teams=None instead of [] for All Teams API tokens
    - ✅ [**#3701**](https://github.com/IBM/mcp-context-forge/issues/3701) - fix(schemas): enforce visibility literals across entity schemas
    - ✅ [**#3707**](https://github.com/IBM/mcp-context-forge/issues/3707) - fix(auth): include provider_metadata in SSO provider detail endpoint
    - ✅ [**#3710**](https://github.com/IBM/mcp-context-forge/issues/3710) - test(auth): add provider_metadata to SSO detail endpoint with test
    - ✅ [**#3715**](https://github.com/IBM/mcp-context-forge/issues/3715) - feat(auth): verify OAuth access tokens via JWKS for virtual server MCP
    - ✅ [**#3732**](https://github.com/IBM/mcp-context-forge/issues/3732) - fix(llm): align Bedrock GatewayProvider config keys with DB schema
    - ✅ [**#3741**](https://github.com/IBM/mcp-context-forge/issues/3741) - [TESTING][PLUGINS]: Validate and harden secrets detection plugin
    - ✅ [**#3750**](https://github.com/IBM/mcp-context-forge/issues/3750) - fix(rate-limiter): shared state, eviction, thread safety, config validation
    - ✅ [**#3752**](https://github.com/IBM/mcp-context-forge/issues/3752) - [BUG][AUTH]: Virtual Server OAuth enforcement returns 200 instead of 401 with WWW-Authenticate header
    - ✅ [**#3756**](https://github.com/IBM/mcp-context-forge/issues/3756) - fix(ui): populate issuer field when editing OAuth gateway
    - ✅ [**#3758**](https://github.com/IBM/mcp-context-forge/issues/3758) - fix(ssl): enhance SSL context cache for mTLS+rotation and bypass HTTP
    - ✅ [**#3764**](https://github.com/IBM/mcp-context-forge/issues/3764) - fix: tighten secrets detection coverage and add focused benchmarking
    - ✅ [**#3777**](https://github.com/IBM/mcp-context-forge/issues/3777) - [BUG][PERFORMANCE]: Session pool resource exhaustion — no global cap, high per-bucket limit, and rotating JWT identity explosion
    - ✅ [**#3798**](https://github.com/IBM/mcp-context-forge/issues/3798) - feat(auth): add ADFS SSO authorization provider
    - ✅ [**#3799**](https://github.com/IBM/mcp-context-forge/issues/3799) - [FEATURE]: Narrow RBAC Layer 2 permission checks to match session-token team scope
    - ✅ [**#3807**](https://github.com/IBM/mcp-context-forge/issues/3807) - [TESTING][PLUGINS]: Test, harden and document encoded exfil detection plugin
    - ✅ [**#3821**](https://github.com/IBM/mcp-context-forge/issues/3821) - [BUG]: SSO team mapping is additive-only — stale team memberships never revoked on group removal
    - ✅ [**#3847**](https://github.com/IBM/mcp-context-forge/issues/3847) - feat(security): add MIME type restrictions for resources (US-2)
    - ✅ [**#3881**](https://github.com/IBM/mcp-context-forge/issues/3881) - [FEATURE][AUTH]: Add tools.execute to team-scoped viewer role
    - ✅ [**#3882**](https://github.com/IBM/mcp-context-forge/issues/3882) - feat(rbac): add tools.execute permission to team-scoped viewer role
    - ✅ [**#3891**](https://github.com/IBM/mcp-context-forge/issues/3891) - [BUG]: [Security] Invalid Virtual MCP Server URL provides access to all the MCP components (tools, prompts, resources, agents) available on ContextForge
    - ✅ [**#3897**](https://github.com/IBM/mcp-context-forge/issues/3897) - [BUG][SECURITY]: /servers/{id}/message endpoint does not validate server_id against database
    - ✅ [**#3902**](https://github.com/IBM/mcp-context-forge/issues/3902) - [CHORE][CI]: Add uv exclude-newer dependency age guardrail
    - ✅ [**#3906**](https://github.com/IBM/mcp-context-forge/issues/3906) - feat(encoded-exfil): test, harden, and document encoded exfiltration detection plugin

???+ check "🐛 Bugs - Completed (107)"

    - ✅ [**#1187**](https://github.com/IBM/mcp-context-forge/issues/1187) - [BUG][HELM]: Latest helm chart not available
    - ✅ [**#1704**](https://github.com/IBM/mcp-context-forge/issues/1704) - [BUG][API]: prompts/get RPC incorrectly looks up by ID instead of name per MCP spec
    - ✅ [**#2689**](https://github.com/IBM/mcp-context-forge/issues/2689) - [BUG]: MCP Servers/Virtual Servers/Tools - Double loading spinner on refresh
    - ✅ [**#2784**](https://github.com/IBM/mcp-context-forge/issues/2784) - [BUG][API]: No tools listed via MCP after adding tool from REST API
    - ✅ [**#2796**](https://github.com/IBM/mcp-context-forge/issues/2796) - [BUG][PLUGINS]: External MCP plugin session not recovered after plugin restart
    - ✅ [**#2848**](https://github.com/IBM/mcp-context-forge/issues/2848) - [BUG][API]: GET /tools should not require a request body
    - ✅ [**#2960**](https://github.com/IBM/mcp-context-forge/issues/2960) - [BUG][API]: Import endpoint silently ignores CLI parameters and rejects raw export data
    - ✅ [**#2968**](https://github.com/IBM/mcp-context-forge/issues/2968) - [BUG][UI]: Remove non-functional "Show" button for auth tokens after security hardening
    - ✅ [**#2997**](https://github.com/IBM/mcp-context-forge/issues/2997) - [BUG][UI]: Inactive A2A agents still visible in Tools and Virtual Servers panels
    - ✅ [**#3039**](https://github.com/IBM/mcp-context-forge/issues/3039) - [BUG][UI]: Pagination controls break when search/filter returns results with query parameters
    - ✅ [**#3050**](https://github.com/IBM/mcp-context-forge/issues/3050) - [BUG][MCP]: Tool title field (BaseMetadata) dropped during ToolCreate validation
    - ✅ [**#3051**](https://github.com/IBM/mcp-context-forge/issues/3051) - [BUG][API]: MIME type validation rejects valid parameterized types (text/html;profile=mcp-app)
    - ✅ [**#3082**](https://github.com/IBM/mcp-context-forge/issues/3082) - [BUG][UI]: Fetch Tools button broken due to Jinja tojson quote escaping in gateways_partial.html
    - ✅ [**#3119**](https://github.com/IBM/mcp-context-forge/issues/3119) - [BUG][UI]: Plugin Management filter not showing enforced plugins
    - ✅ [**#3122**](https://github.com/IBM/mcp-context-forge/issues/3122) - [BUG][API]: A2A_Agents.auth_value is stored in the postgres database with extra surrounding double quotes
    - ✅ [**#3128**](https://github.com/IBM/mcp-context-forge/issues/3128) - [BUG][UI]:  The items in tables are filtered on a single pagination page and not across all records
    - ✅ [**#3155**](https://github.com/IBM/mcp-context-forge/issues/3155) - fix(ui): move pagination data into script tag
    - ✅ [**#3166**](https://github.com/IBM/mcp-context-forge/issues/3166) - [FIX][API]: Fix import endpoint JSON parameter handling
    - ✅ [**#3173**](https://github.com/IBM/mcp-context-forge/issues/3173) - fix(a2a): cascade agent state changes to associated MCP tools
    - ✅ [**#3179**](https://github.com/IBM/mcp-context-forge/issues/3179) - fix(ui): replace tojson with single-quoted literals in Fetch Tools onclick
    - ✅ [**#3182**](https://github.com/IBM/mcp-context-forge/issues/3182) - fix(mcp): propagate title field for tools, resources, and prompts
    - ✅ [**#3184**](https://github.com/IBM/mcp-context-forge/issues/3184) - fix(plugins): add session reconnection logic to MCP external plugin client (#2796)
    - ✅ [**#3205**](https://github.com/IBM/mcp-context-forge/issues/3205) - fix(ui): show toast notification when user deletion returns an error
    - ✅ [**#3206**](https://github.com/IBM/mcp-context-forge/issues/3206) - fix(ui): reinit Alpine.js on OOB-swapped pagination controls after fi…
    - ✅ [**#3233**](https://github.com/IBM/mcp-context-forge/issues/3233) - [BUG][MCP]: Unable to connect to public virtual MCP server using LLM Chat — missing langgraph dependency check
    - ✅ [**#3247**](https://github.com/IBM/mcp-context-forge/issues/3247) - fix(auth): allow removing non-last admin users
    - ✅ [**#3256**](https://github.com/IBM/mcp-context-forge/issues/3256) - [FIX][A2A]: Fix auth_value stored with extra surrounding double quotes in PostgreSQL (#3122)
    - ✅ [**#3263**](https://github.com/IBM/mcp-context-forge/issues/3263) - [FEATURE][API]: Make tool description forbidden patterns configurable + fix auth_value encoding bug
    - ✅ [**#3298**](https://github.com/IBM/mcp-context-forge/issues/3298) - [BUG][API]: Root path resolution missing settings fallback outside admin.py
    - ✅ [**#3320**](https://github.com/IBM/mcp-context-forge/issues/3320) - fix(infra): disable IPv6 listener in nginx config
    - ✅ [**#3329**](https://github.com/IBM/mcp-context-forge/issues/3329) - [BUG][RBAC]: Non-admin users cannot access Overview page and have inconsistent Test/View privileges
    - ✅ [**#3334**](https://github.com/IBM/mcp-context-forge/issues/3334) - [FIX][MCP]: add guard check for missing deps in MCPChatService
    - ✅ [**#3368**](https://github.com/IBM/mcp-context-forge/issues/3368) - [BUG][UI]: Tool creation returns 500 error for invalid JSON in query/header mapping fields
    - ✅ [**#3369**](https://github.com/IBM/mcp-context-forge/issues/3369) - fix(api): apply query and header mappings on tool invocation (#1405)
    - ✅ [**#3371**](https://github.com/IBM/mcp-context-forge/issues/3371) - fix(mcp): forwarded RPC non-2xx responses masked as success (#3365)
    - ✅ [**#3390**](https://github.com/IBM/mcp-context-forge/issues/3390) - fix(rbac): backfill admin.overview and servers.use permissions to viewer roles
    - ✅ [**#3425**](https://github.com/IBM/mcp-context-forge/issues/3425) - [BUG][API]: Deactivated prompts, tools, resources, A2A Agent can be seen in Admin UI and API
    - ✅ [**#3433**](https://github.com/IBM/mcp-context-forge/issues/3433) - [BUG][UI]:  Unable to create a tool without a display name
    - ✅ [**#3446**](https://github.com/IBM/mcp-context-forge/issues/3446) - [BUG][API]: Public MCP server tools not included when added to team-owned virtual server
    - ✅ [**#3447**](https://github.com/IBM/mcp-context-forge/issues/3447) - [BUG][UI]: Prompts show empty argument list in Admin UI
    - ✅ [**#3449**](https://github.com/IBM/mcp-context-forge/issues/3449) - fix(plugins): rate limiter returns proper HTTP status codes and headers (#2668)
    - ✅ [**#3459**](https://github.com/IBM/mcp-context-forge/issues/3459) - [BUG][RBAC]: Max team members limit not enforced when adding members
    - ✅ [**#3461**](https://github.com/IBM/mcp-context-forge/issues/3461) - fix(ui): redirect authenticated users from login page to dashboard
    - ✅ [**#3462**](https://github.com/IBM/mcp-context-forge/issues/3462) - fix(ui): hide deactivated entities in admin UI catalog and API
    - ✅ [**#3464**](https://github.com/IBM/mcp-context-forge/issues/3464) - fix(ui): exclude display name from required-field validation in tool form
    - ✅ [**#3469**](https://github.com/IBM/mcp-context-forge/issues/3469) - [BUG][UI]: Pagination per_page options 200/500 exceed API limit of 100
    - ✅ [**#3477**](https://github.com/IBM/mcp-context-forge/issues/3477) - fix(ui): add JSON validation with 422 error for tool form fields
    - ✅ [**#3487**](https://github.com/IBM/mcp-context-forge/issues/3487) - fix(ui): pass max_members from admin UI team create/edit forms
    - ✅ [**#3492**](https://github.com/IBM/mcp-context-forge/issues/3492) - fix: preserve search filters across pagination pages
    - ✅ [**#3501**](https://github.com/IBM/mcp-context-forge/issues/3501) - [BUG][RBAC]: Admin UI 'administrator' checkbox does not reliably assign platform_admin RBAC role
    - ✅ [**#3505**](https://github.com/IBM/mcp-context-forge/issues/3505) - [BUG][RBAC]: MultipleResultsFound in get_user_role_assignment after role revoke/re-assign cycle
    - ✅ [**#3513**](https://github.com/IBM/mcp-context-forge/issues/3513) - [BUG][RBAC]: Team join/limit tests failing — permission, UI and message issues with team feature flags
    - ✅ [**#3514**](https://github.com/IBM/mcp-context-forge/issues/3514) - [FIX][UI]: Include public MCP objects in team-scoped server associations
    - ✅ [**#3529**](https://github.com/IBM/mcp-context-forge/issues/3529) - [BUG][API]: Tool test endpoint fails for private-visibility tools
    - ✅ [**#3530**](https://github.com/IBM/mcp-context-forge/issues/3530) - [BUG]: AUTO_REFRESH_SERVERS Changes Tool Visibility From Private to Public
    - ✅ [**#3540**](https://github.com/IBM/mcp-context-forge/issues/3540) - [BUG][API]: _prepare_gateway_for_read mutates ORM object, causing auth_value dict→string writeback
    - ✅ [**#3541**](https://github.com/IBM/mcp-context-forge/issues/3541) - fix(gateway): avoid mutating ORM gateway auth_value during read conversion
    - ✅ [**#3555**](https://github.com/IBM/mcp-context-forge/issues/3555) - [BUG][UI]:  Redirect manually accessed admin/logout to admin/login page
    - ✅ [**#3559**](https://github.com/IBM/mcp-context-forge/issues/3559) - [BUG][MCP]: POST /mcp returns 405 after v0.9 to v1.0 migration — TRANSPORT_TYPE config mismatch
    - ✅ [**#3560**](https://github.com/IBM/mcp-context-forge/issues/3560) - [BUG]: Bug Report: HTTP 429 Status Code Not Returned for Rate-Limited Requests
    - ✅ [**#3562**](https://github.com/IBM/mcp-context-forge/issues/3562) - Fixes naive vs aware datetime comparison crashes on SQLite
    - ✅ [**#3570**](https://github.com/IBM/mcp-context-forge/issues/3570) - fix: _prepare_gateway_for_read mutates ORM object
    - ✅ [**#3574**](https://github.com/IBM/mcp-context-forge/issues/3574) - fix(visibility): prevent auto-refresh from overriding tool/prompt/resource visibility
    - ✅ [**#3577**](https://github.com/IBM/mcp-context-forge/issues/3577) - [BUG]: Gateway creation ignores passthroughHeaders (camelCase) field
    - ✅ [**#3578**](https://github.com/IBM/mcp-context-forge/issues/3578) - fix: accept camelCase passthroughHeaders in gateway creation
    - ✅ [**#3588**](https://github.com/IBM/mcp-context-forge/issues/3588) - [BUG]: MAX_MEMBERS_PER_TEAM cannot be overriden.
    - ✅ [**#3589**](https://github.com/IBM/mcp-context-forge/issues/3589) - [BUG]: `MAX_MEMBERS_PER_TEAM` setting is ignored by the UI
    - ✅ [**#3606**](https://github.com/IBM/mcp-context-forge/issues/3606) - [BUG][UI]: copying or downloading resource causes the whole resource page reloading
    - ✅ [**#3607**](https://github.com/IBM/mcp-context-forge/issues/3607) - [BUG]: Unable to add  Virtual Server via mcp inspector
    - ✅ [**#3608**](https://github.com/IBM/mcp-context-forge/issues/3608) - fix: Synchronize is_admin flag when platform_admin role is assigned during bootstrap
    - ✅ [**#3610**](https://github.com/IBM/mcp-context-forge/issues/3610) - fix(ui): filter team members modal to show only non-members
    - ✅ [**#3616**](https://github.com/IBM/mcp-context-forge/issues/3616) - fix(ui): replace tojson with single-quoted literals in Fetch Tools onclick
    - ✅ [**#3623**](https://github.com/IBM/mcp-context-forge/issues/3623) - fix: team join validation and error handling
    - ✅ [**#3633**](https://github.com/IBM/mcp-context-forge/issues/3633) - fix(ui): clear stale test results when reopening tool/prompt/gateway test modals
    - ✅ [**#3636**](https://github.com/IBM/mcp-context-forge/issues/3636) - fix(mcp): Restore MCP handshake for public tokens by adjusting appropriate permission for mcp servers RBAC
    - ✅ [**#3637**](https://github.com/IBM/mcp-context-forge/issues/3637) - [BUG][UI]: Custom headers (auth_headers) not saved or displayed in A2A agent admin UI edit form
    - ✅ [**#3641**](https://github.com/IBM/mcp-context-forge/issues/3641) - ui-pagination-422-response
    - ✅ [**#3644**](https://github.com/IBM/mcp-context-forge/issues/3644) - [BUG]: visibility query parameter ignored for admin tokens on listing endpoints
    - ✅ [**#3650**](https://github.com/IBM/mcp-context-forge/issues/3650) - fix(ui): set MAX_MEMBERS_PER_TEAM in team forms
    - ✅ [**#3651**](https://github.com/IBM/mcp-context-forge/issues/3651) - fix(prompts): prioritize name-based lookup per MCP spec (#1704)
    - ✅ [**#3666**](https://github.com/IBM/mcp-context-forge/issues/3666) - fix(ui): persist and display custom auth_headers in A2A agent admin edit form
    - ✅ [**#3682**](https://github.com/IBM/mcp-context-forge/issues/3682) - fix: resolve MAX_MEMBERS_PER_TEAM not applying to existing teams
    - ✅ [**#3685**](https://github.com/IBM/mcp-context-forge/issues/3685) - fix(schemas): accept camelCase fields on gateway creation
    - ✅ [**#3696**](https://github.com/IBM/mcp-context-forge/issues/3696) - fix(api): consolidate loopback RPC URLs and TLS verification into shared helper (#3543)
    - ✅ [**#3711**](https://github.com/IBM/mcp-context-forge/issues/3711) - [BUG][API]: Tool description validation ignores VALIDATION_STRICT env var — blocks MCP server registration
    - ✅ [**#3720**](https://github.com/IBM/mcp-context-forge/issues/3720) - fix(api): separate query params from body payload in REST tool POST requests
    - ✅ [**#3724**](https://github.com/IBM/mcp-context-forge/issues/3724) - [BUG][PLUGINS]: PIIFilterPlugin ignores default_mask_strategy config — built-in PII types always use hardcoded masking strategies
    - ✅ [**#3725**](https://github.com/IBM/mcp-context-forge/issues/3725) - fix(a2a): A2A agent test endpoint returns 500 for admin users
    - ✅ [**#3733**](https://github.com/IBM/mcp-context-forge/issues/3733) - fix(llmchat): mark tool/parsing errors as recoverable in streaming
    - ✅ [**#3738**](https://github.com/IBM/mcp-context-forge/issues/3738) - [BUG][RUST]: Rust PII filter — correctness issues, false positives, and broken redaction config
    - ✅ [**#3745**](https://github.com/IBM/mcp-context-forge/issues/3745) - [BUG][MCP]: Automatic and notification-driven tool rediscovery not reflecting updated tool list from MCP servers
    - ✅ [**#3749**](https://github.com/IBM/mcp-context-forge/issues/3749) - fix(api): MCP Tool Validation Fix
    - ✅ [**#3755**](https://github.com/IBM/mcp-context-forge/issues/3755) - [BUG][UI]: OAuth issuer URL not populated when editing gateway — silently dropped on save
    - ✅ [**#3794**](https://github.com/IBM/mcp-context-forge/issues/3794) - fix(observability): fix top performers data loss, dead guards, display bugs, and response time unit conversion
    - ✅ [**#3833**](https://github.com/IBM/mcp-context-forge/issues/3833) - [BUG][FE]: Virtual Servers - Associated Tools - Select All is not showing the correct count of the tools selected
    - ✅ [**#3834**](https://github.com/IBM/mcp-context-forge/issues/3834) - [BUG][MULTI-INSTANCE]: Critical Stall in Leader Re-election Mechanism
    - ✅ [**#3861**](https://github.com/IBM/mcp-context-forge/issues/3861) - [BUG][UI]: infinite /partial request loop triggered by search input
    - ✅ [**#3863**](https://github.com/IBM/mcp-context-forge/issues/3863) - fix: infinite /partial request loop triggered by search input
    - ✅ [**#3885**](https://github.com/IBM/mcp-context-forge/issues/3885) - fix(ui): remove duplicate disabled badge and tag/hook truncation on plugin cards
    - ✅ [**#3921**](https://github.com/IBM/mcp-context-forge/issues/3921) -  fix(admin): reset scroll position on tab navigation
    - ✅ [**#3925**](https://github.com/IBM/mcp-context-forge/issues/3925) - [BUG]: PluginCondition.content_types field is defined but not implemented
    - ✅ [**#3955**](https://github.com/IBM/mcp-context-forge/issues/3955) - [BUG]: Plugin Condition Evaluation System Requires Comprehensive Overhaul
    - ✅ [**#4002**](https://github.com/IBM/mcp-context-forge/issues/4002) - [BUG]: Session Pool Reliability & Resource Management Issues
    - ✅ [**#4050**](https://github.com/IBM/mcp-context-forge/issues/4050) - fix: observability data incorrectly rolled back with failed transactions
    - ✅ [**#4077**](https://github.com/IBM/mcp-context-forge/issues/4077) - [BUG]: Pod crash-loop on startup — `tools.manage_plugins` not registered in `Permissions` class
    - ✅ [**#4082**](https://github.com/IBM/mcp-context-forge/issues/4082) - [BUG]: Refresh tool buttons are broken
    - ✅ [**#4090**](https://github.com/IBM/mcp-context-forge/issues/4090) - fix(ui): remove duplicate onclick handler causing double-click for CA cert upload

???+ check "⚡ Performance - Completed (23)"

    - ✅ [**#1618**](https://github.com/IBM/mcp-context-forge/issues/1618) - [RUST]: Rewrite wrapper module in Rust
    - ✅ [**#1874**](https://github.com/IBM/mcp-context-forge/issues/1874) - [PERFORMANCE]: Establish performance baselines for MCP Gateway
    - ✅ [**#2012**](https://github.com/IBM/mcp-context-forge/issues/2012) - [PERFORMANCE]: Observability feature causes major performance regression
    - ✅ [**#2014**](https://github.com/IBM/mcp-context-forge/issues/2014) - [PERFORMANCE]: Optimize tool_metrics table - 1B+ sequential tuple reads
    - ✅ [**#2323**](https://github.com/IBM/mcp-context-forge/issues/2323) - [BUG][PERFORMANCE][DB]: Endpoint handlers hold DB sessions during slow MCP backend calls
    - ✅ [**#2344**](https://github.com/IBM/mcp-context-forge/issues/2344) - [FEATURE]: Bypass DB/cache lookup option for gateways
    - ✅ [**#3085**](https://github.com/IBM/mcp-context-forge/issues/3085) - [BUG][PERFORMANCE][UI]: The team members and non-members should not load in one go in Manage members modal.
    - ✅ [**#3209**](https://github.com/IBM/mcp-context-forge/issues/3209) - fix(ui): search-only non-members in Manage Members modal
    - ✅ [**#3403**](https://github.com/IBM/mcp-context-forge/issues/3403) - test: add and document CONC-02 gateway read-during-write manual runner
    - ✅ [**#3443**](https://github.com/IBM/mcp-context-forge/issues/3443) - [BUG][UI]: Team switcher dropdown remains in loading state after repeated switches
    - ✅ [**#3467**](https://github.com/IBM/mcp-context-forge/issues/3467) - [BUG][PERFORMANCE]: Observability middleware opens duplicate DB session per request
    - ✅ [**#3520**](https://github.com/IBM/mcp-context-forge/issues/3520) - [BUG][PERFORMANCE]: MCP session pool recycles broken sessions, causing cascading ClosedResourceError failures under load
    - ✅ [**#3605**](https://github.com/IBM/mcp-context-forge/issues/3605) - fix(session-pool): prevent broken session recycling in MCPSessionPool
    - ✅ [**#3617**](https://github.com/IBM/mcp-context-forge/issues/3617) - feat: add experimental Rust MCP runtime and session core
    - ✅ [**#3622**](https://github.com/IBM/mcp-context-forge/issues/3622) - [BUG][PERFORMANCE]: Auth and RBAC middleware create duplicate DB sessions alongside observability middleware
    - ✅ [**#3714**](https://github.com/IBM/mcp-context-forge/issues/3714) - feat: service-account support and pre-invoke security hardening
    - ✅ [**#3731**](https://github.com/IBM/mcp-context-forge/issues/3731) - [BUG][DB]: Transaction management violation in PR 3600 — get_db() loses control over commits
    - ✅ [**#3783**](https://github.com/IBM/mcp-context-forge/issues/3783) - feat(rate-limiter): pluggable algorithms, tenant isolation fix, and scale load test
    - ✅ [**#3784**](https://github.com/IBM/mcp-context-forge/issues/3784) - [FEATURE][PLUGINS]: Rate limiter — pluggable algorithm strategy (sliding_window, token_bucket, Redis backend for all algorithms)
    - ✅ [**#3809**](https://github.com/IBM/mcp-context-forge/issues/3809) - feat(rate-limiter): pluggable algorithms with Rust-backed execution engine, benchmarks, and validation
    - ✅ [**#3864**](https://github.com/IBM/mcp-context-forge/issues/3864) - [FEATURE][PLUGINS]: Rust-backed rate limiter execution engine for hot-path acceleration
    - ✅ [**#3884**](https://github.com/IBM/mcp-context-forge/issues/3884) - [BUG][PERFORMANCE]: High error rate under load — ExceptionGroup in concurrent MCP tool execution (wxo integration)
    - ✅ [**#3886**](https://github.com/IBM/mcp-context-forge/issues/3886) - fix(auth): eliminate duplicate DB sessions in auth and RBAC middleware

???+ check "🧪 Testing - Completed (31)"

    - ✅ [**#252**](https://github.com/IBM/mcp-context-forge/issues/252) - [CHORE]: Establish database migration testing pipeline with rollback validation across SQLite, Postgres, and Redis
    - ✅ [**#2418**](https://github.com/IBM/mcp-context-forge/issues/2418) - [TESTING][FUNCTIONALITY]: MCP Tools manual test plan (discovery, invocation, streaming, error handling)
    - ✅ [**#2419**](https://github.com/IBM/mcp-context-forge/issues/2419) - [TESTING][FUNCTIONALITY]: MCP Resources manual test plan (discovery, fetch, templates, subscriptions)
    - ✅ [**#2423**](https://github.com/IBM/mcp-context-forge/issues/2423) - [TESTING][FUNCTIONALITY]: Virtual servers manual test plan (aggregation, routing, tool merging)
    - ✅ [**#2432**](https://github.com/IBM/mcp-context-forge/issues/2432) - [TESTING][FUNCTIONALITY]: Caching manual test plan (response cache, Redis, invalidation)
    - ✅ [**#2451**](https://github.com/IBM/mcp-context-forge/issues/2451) - [TESTING][E2E]: User journey - New user onboarding end-to-end test (registration, team creation, first server)
    - ✅ [**#2452**](https://github.com/IBM/mcp-context-forge/issues/2452) - [TESTING][E2E]: User journey - Team collaboration end-to-end test (team setup, sharing, permissions)
    - ✅ [**#2453**](https://github.com/IBM/mcp-context-forge/issues/2453) - [TESTING][E2E]: User journey - Multi-gateway aggregation end-to-end test (virtual server, tool routing)
    - ✅ [**#2456**](https://github.com/IBM/mcp-context-forge/issues/2456) - [TESTING][E2E]: User journey - SSO authentication end-to-end test (OAuth flow, token exchange, session management)
    - ✅ [**#2457**](https://github.com/IBM/mcp-context-forge/issues/2457) - [TESTING][E2E]: User journey - A2A agent orchestration end-to-end test (agent discovery, multi-agent workflow)
    - ✅ [**#2469**](https://github.com/IBM/mcp-context-forge/issues/2469) - [TESTING][RESILIENCE]: MCP Server Resilience Manual Test Plan (Crash Recovery, Timeout Handling, Retry Logic)
    - ✅ [**#2476**](https://github.com/IBM/mcp-context-forge/issues/2476) - [TESTING][OBSERVABILITY]: Metrics Accuracy, Tracing Completeness, and Dashboard Validation
    - ✅ [**#2478**](https://github.com/IBM/mcp-context-forge/issues/2478) - [TESTING][CONFIGURATION]: Environment Variables, Validation, and Default Values
    - ✅ [**#2485**](https://github.com/IBM/mcp-context-forge/issues/2485) - [TESTING][NETWORK]: TLS Configuration, Proxy Support, Certificate Handling, and mTLS
    - ✅ [**#2488**](https://github.com/IBM/mcp-context-forge/issues/2488) - [TESTING][MULTI-INSTANCE]: Leader Election, Redis Coordination, and Horizontal Scaling
    - ✅ [**#2496**](https://github.com/IBM/mcp-context-forge/issues/2496) - [TESTING][CONFIG]: Airgapped Mode Test Plan
    - ✅ [**#2906**](https://github.com/IBM/mcp-context-forge/issues/2906) - [CHORE]: Fix CI rust env and apply same corrections to `pii_filter` plugin
    - ✅ [**#3208**](https://github.com/IBM/mcp-context-forge/issues/3208) - test(api): add regression coverage for prompt original_name during federation (#3087)
    - ✅ [**#3333**](https://github.com/IBM/mcp-context-forge/issues/3333) - [BUG][TESTING]: Playwright agents modal test flakes due to selector race with hidden legacy table
    - ✅ [**#3370**](https://github.com/IBM/mcp-context-forge/issues/3370) - fix(testing): eliminate Playwright agents modal test flake (#3333)
    - ✅ [**#3465**](https://github.com/IBM/mcp-context-forge/issues/3465) - fix(tests): fix 5 failing Playwright regression test selectors
    - ✅ [**#3533**](https://github.com/IBM/mcp-context-forge/issues/3533) - [TESTING]: Order-dependent /metrics unit failures caused by leaked metrics_cache singleton mocks
    - ✅ [**#3536**](https://github.com/IBM/mcp-context-forge/issues/3536) - [BUG]: test_admin_catalog_htmx.py triggers full gateway lifespan in parallel test runs, causing hangs
    - ✅ [**#3601**](https://github.com/IBM/mcp-context-forge/issues/3601) - fix: resolve order-dependent test failures from leaked metrics_cache …
    - ✅ [**#3740**](https://github.com/IBM/mcp-context-forge/issues/3740) - [TESTING][PLUGINS]: Test, harden, and document the Rate Limiter plugin
    - ✅ [**#3746**](https://github.com/IBM/mcp-context-forge/issues/3746) - [TESTING][PLUGINS]: Test, harden and document retry with exponential backoff plugin
    - ✅ [**#3808**](https://github.com/IBM/mcp-context-forge/issues/3808) - [TESTING][PLUGINS]: Test, harden and document Cedar policy plugin
    - ✅ [**#3815**](https://github.com/IBM/mcp-context-forge/issues/3815) - [BUG][TESTING]: Fix 6 deterministic Playwright test failures and stabilize 5 flaky tests in admin UI
    - ✅ [**#3816**](https://github.com/IBM/mcp-context-forge/issues/3816) - fix(tests): fix 6 broken Playwright tests, stabilize flaky ones, eliminate private key false positives
    - ✅ [**#3889**](https://github.com/IBM/mcp-context-forge/issues/3889) - [BUG]: JWT secret default mismatch after #3716 — E2E tests, docker-compose variants, and scripts still use old key
    - ✅ [**#4020**](https://github.com/IBM/mcp-context-forge/issues/4020) - [BUG][TESTING]: 6 Playwright E2E tests failing on feat/security-restrict-content-types branch

???+ check "📚 Documentation - Completed (5)"

    - ✅ [**#2500**](https://github.com/IBM/mcp-context-forge/issues/2500) - [TESTING] README.md Complete Test Plan
    - ✅ [**#3688**](https://github.com/IBM/mcp-context-forge/issues/3688) - docs: fix inaccurate claims in README.md
    - ✅ [**#3709**](https://github.com/IBM/mcp-context-forge/issues/3709) - [DOCS][A2A]: Demo A2A agent quick-start is missing required prerequisites
    - ✅ [**#3770**](https://github.com/IBM/mcp-context-forge/issues/3770) - [BUG]: Tool validation rejects legitimate documentation text containing semicolons and marks tools as unavailable
    - ✅ [**#3853**](https://github.com/IBM/mcp-context-forge/issues/3853) - fix(docs): improve demo a2a agent docs

???+ check "🔧 Chores - Completed (12)"

    - ✅ [**#3027**](https://github.com/IBM/mcp-context-forge/issues/3027) - [CHORE][RUST]: Set up Rust workspace and PyO3 bindings for performance-critical components
    - ✅ [**#3147**](https://github.com/IBM/mcp-context-forge/issues/3147) - chore(rust): restructure Rust plugins as independent crates
    - ✅ [**#3156**](https://github.com/IBM/mcp-context-forge/issues/3156) - chore(ui): rename admin references to UI across codebase
    - ✅ [**#3281**](https://github.com/IBM/mcp-context-forge/issues/3281) - [CHORE][CONFIG]: Network access required to IBM DST endpoints for AgentStudio integration
    - ✅ [**#3440**](https://github.com/IBM/mcp-context-forge/issues/3440) - chore(devops): add nginx cache management Makefile targets
    - ✅ [**#3684**](https://github.com/IBM/mcp-context-forge/issues/3684) - chore: remove MySQL/MariaDB/MongoDB support - PostgreSQL and SQLite only
    - ✅ [**#3734**](https://github.com/IBM/mcp-context-forge/issues/3734) - [CHORE][NOTIFICATIONS]: Investigate and test support for notifications/tools/list_changed signal for dynamic tool discovery
    - ✅ [**#3742**](https://github.com/IBM/mcp-context-forge/issues/3742) - [CHORE][CI]: Ensure all Rust workflows run clippy consistently
    - ✅ [**#3743**](https://github.com/IBM/mcp-context-forge/issues/3743) - [CHORE][CI]: Add cargo-deny coverage to all Rust workflows
    - ✅ [**#3859**](https://github.com/IBM/mcp-context-forge/issues/3859) - [CHORE]: Add detect-secrets baseline workflow and documentation
    - ✅ [**#3874**](https://github.com/IBM/mcp-context-forge/issues/3874) - chore(ci): remove unused linting-security-trufflehog make target
    - ✅ [**#3903**](https://github.com/IBM/mcp-context-forge/issues/3903) - chore: add uv exclude-newer policy

---

## Release 1.0.0

!!! warning "Release 1.0.0 - In Progress"
    **Due:** 28 Apr 2026 | **Status:** Open
    Technical Debt, Security Hardening, Catalog Improvements, A2A Improvements, MCP Standard Review and Sync

    Final General Availability release. Remaining work consolidates items carried over from RC3 plus dedicated GA milestone items.

???+ info "📋 Epics - Remaining (4)"

    - ⏳ [**#1247**](https://github.com/IBM/mcp-context-forge/issues/1247) - [EPIC][PLUGIN]: Per-virtual-server plugin selection with multi-level RBAC
    - ⏳ [**#1355**](https://github.com/IBM/mcp-context-forge/issues/1355) - [EPIC]: Document backup and restore - Data protection strategy
    - ⏳ [**#1417**](https://github.com/IBM/mcp-context-forge/issues/1417) - [EPIC][PLUGIN]: Improve plugins hygiene
    - ⏳ [**#3751**](https://github.com/IBM/mcp-context-forge/issues/3751) - [FEATURE][PLUGINS]: Plugin multi-tenancy support — per-team plugin configurations

???+ info "✨ Features - Remaining (18)"

    - ⏳ [**#758**](https://github.com/IBM/mcp-context-forge/issues/758) - [FEATURE][PROTOCOL]: Implement missing MCP protocol methods
    - ⏳ [**#1140**](https://github.com/IBM/mcp-context-forge/issues/1140) - [FEATURE][PLUGIN]: Reduce complexity in plugin configuration framework
    - ⏳ [**#2101**](https://github.com/IBM/mcp-context-forge/issues/2101) - [FEATURE]: Make public teams discovery limit configurable via environment variable
    - ⏳ [**#2332**](https://github.com/IBM/mcp-context-forge/issues/2332) - [FEATURE][API]: Support _meta for all RPC methods
    - ⏳ [**#3148**](https://github.com/IBM/mcp-context-forge/issues/3148) - feat(auth): add LDAP / Active Directory authentication support
    - ⏳ [**#3200**](https://github.com/IBM/mcp-context-forge/issues/3200) - feat(plugins): add json_prune plugin to strip unnecessary fields from tool output
    - ⏳ [**#3576**](https://github.com/IBM/mcp-context-forge/issues/3576) - [FEATURE][PLUGINS]: Propagate PluginResult.http_headers to HTTP responses
    - ⏳ [**#3754**](https://github.com/IBM/mcp-context-forge/issues/3754) - feat: replace the internal plugin framework with CPEX
    - ⏳ [**#3818**](https://github.com/IBM/mcp-context-forge/issues/3818) - [FEATURE][PLUGINS]: Phase 2 - Database Schema and Models for Multi-Tenant Plugins
    - ⏳ [**#3823**](https://github.com/IBM/mcp-context-forge/issues/3823) - [FEATURE][PLUGINS]: Phase 3 - Startup and Service Integration for Multi-Tenant Plugins
    - ⏳ [**#3827**](https://github.com/IBM/mcp-context-forge/issues/3827) - [FEATURE][PLUGINS]: Phase 4 - Admin API for Multi-Tenant Plugin Management
    - ⏳ [**#3828**](https://github.com/IBM/mcp-context-forge/issues/3828) - [FEATURE][PLUGINS]: Phase 5 - Admin UI and Change Notification for Multi-Tenant Plugins
    - ⏳ [**#4048**](https://github.com/IBM/mcp-context-forge/issues/4048) - fix(OAuth): OAuth flows now use gateway CA certificates for self-signed servers
    - ⏳ [**#4061**](https://github.com/IBM/mcp-context-forge/issues/4061) - [FEATURE]: Expose advanced tool configuration fields in Admin UI edit form
    - ⏳ [**#4080**](https://github.com/IBM/mcp-context-forge/issues/4080) - fix(sso): SSO users with platform_admin role can now access teams in admin UI
    - ⏳ [**#4091**](https://github.com/IBM/mcp-context-forge/issues/4091) - feat(tools): Elicitation pass-through implementation with session routing and observability
    - ⏳ [**#4107**](https://github.com/IBM/mcp-context-forge/issues/4107) - fix(rbac): add database-backed admin bypass for visibility filtering
    - ⏳ [**#4143**](https://github.com/IBM/mcp-context-forge/issues/4143) - feat: add binding_reference_id to tool plugin bindings and expand plugin config schemas

???+ info "🔒 Security - Remaining (38)"

    - ⏳ [**#212**](https://github.com/IBM/mcp-context-forge/issues/212) - [CHORE]: Achieve zero flagged SonarQube issues
    - ⏳ [**#259**](https://github.com/IBM/mcp-context-forge/issues/259) - [CHORE]: SAST (Semgrep) and DAST (OWASP ZAP) automated security testing Makefile targets and GitHub Actions
    - ⏳ [**#260**](https://github.com/IBM/mcp-context-forge/issues/260) - [CHORE]: Manual security testing plan and template for release validation and production deployments
    - ⏳ [**#1325**](https://github.com/IBM/mcp-context-forge/issues/1325) - [BUG][AUTH]: Keycloak SSO integration issue
    - ⏳ [**#1500**](https://github.com/IBM/mcp-context-forge/issues/1500) - [BUG][AUTH]: OAuth callback failed for provider keycloak - MetaData AttributeError
    - ⏳ [**#1672**](https://github.com/IBM/mcp-context-forge/issues/1672) - [BUG][AUTH]: Permission system inconsistencies - Undefined permissions in use
    - ⏳ [**#2388**](https://github.com/IBM/mcp-context-forge/issues/2388) - [TESTING][SECURITY]: RBAC manual test plan (visibility, teams, token scope)
    - ⏳ [**#2390**](https://github.com/IBM/mcp-context-forge/issues/2390) - [TESTING][SECURITY]: Core authentication manual test plan (JWT, Basic Auth, API tokens, email/password)
    - ⏳ [**#2391**](https://github.com/IBM/mcp-context-forge/issues/2391) - [TESTING][SECURITY]: SSO and OAuth manual test plan (Keycloak, EntraID, OIDC, PKCE, token exchange)
    - ⏳ [**#2393**](https://github.com/IBM/mcp-context-forge/issues/2393) - [TESTING][SECURITY]: Token scoping middleware manual test plan (server ID, IP, time, permissions)
    - ⏳ [**#2400**](https://github.com/IBM/mcp-context-forge/issues/2400) - [TESTING][SECURITY]: PII filter plugin manual test plan (SSN, credit cards, emails, medical)
    - ⏳ [**#2403**](https://github.com/IBM/mcp-context-forge/issues/2403) - [TESTING][SECURITY]: Audit trail manual test plan (CRUD logging, compliance, data classification)
    - ⏳ [**#2406**](https://github.com/IBM/mcp-context-forge/issues/2406) - [TESTING][SECURITY]: A2A agent security manual test plan (agent auth, permissions, boundaries)
    - ⏳ [**#2408**](https://github.com/IBM/mcp-context-forge/issues/2408) - [TESTING][SECURITY]: SSRF prevention manual test plan (URL validation, allowlists, internal network protection)
    - ⏳ [**#2410**](https://github.com/IBM/mcp-context-forge/issues/2410) - [TESTING][SECURITY]: Session management manual test plan (fixation, hijacking, timeout, concurrent sessions)
    - ⏳ [**#2411**](https://github.com/IBM/mcp-context-forge/issues/2411) - [TESTING][SECURITY]: Error handling manual test plan (stack traces, debug info, verbose errors, information disclosure)
    - ⏳ [**#2412**](https://github.com/IBM/mcp-context-forge/issues/2412) - [TESTING][SECURITY]: API security manual test plan (mass assignment, BOLA, parameter pollution, OpenAPI validation)
    - ⏳ [**#2413**](https://github.com/IBM/mcp-context-forge/issues/2413) - [TESTING][SECURITY]: Resource exhaustion / DoS prevention manual test plan (memory bombs, connection exhaustion, slowloris, CPU exhaustion)
    - ⏳ [**#2414**](https://github.com/IBM/mcp-context-forge/issues/2414) - [TESTING][SECURITY]: Protocol-level security manual test plan (WebSocket/SSE abuse, connection management, HTTP smuggling)
    - ⏳ [**#2415**](https://github.com/IBM/mcp-context-forge/issues/2415) - [TESTING][SECURITY]: Serialization security manual test plan (XML bombs, YAML deserialization, recursive JSON)
    - ⏳ [**#2416**](https://github.com/IBM/mcp-context-forge/issues/2416) - [TESTING][SECURITY]: Encoding/Unicode security manual test plan (homograph attacks, null byte injection, normalization bypass)
    - ⏳ [**#2417**](https://github.com/IBM/mcp-context-forge/issues/2417) - [TESTING][SECURITY]: File upload security manual test plan (malicious files, size limits, MIME validation, zip bombs)
    - ⏳ [**#2769**](https://github.com/IBM/mcp-context-forge/issues/2769) - [TESTING][RBAC]: Add unit tests for RBAC Tier 1/2/3 team derivation and session token permission paths
    - ⏳ [**#3094**](https://github.com/IBM/mcp-context-forge/issues/3094) - [BUG][AUTH]: Misleading BASIC_AUTH comments, startup warning, validator naming, and dead code
    - ⏳ [**#3152**](https://github.com/IBM/mcp-context-forge/issues/3152) - feat(auth): propagate end-user identity to upstream MCP servers
    - ⏳ [**#3181**](https://github.com/IBM/mcp-context-forge/issues/3181) - feat(security): move Tailwind CSS from CDN to local compiled build
    - ⏳ [**#3197**](https://github.com/IBM/mcp-context-forge/issues/3197) - feat(security): implement environment-aware defaults and fail-closed secrets
    - ⏳ [**#3213**](https://github.com/IBM/mcp-context-forge/issues/3213) - feat(auth): add IAM pre-tool plugin for MCP server authentication
    - ⏳ [**#3344**](https://github.com/IBM/mcp-context-forge/issues/3344) - fix(transport): protocol and transport hardening for auth and lifecycle consistency
    - ⏳ [**#3542**](https://github.com/IBM/mcp-context-forge/issues/3542) - feat(oauth): add client_credentials M2M config support (US2 of #3386)
    - ⏳ [**#3687**](https://github.com/IBM/mcp-context-forge/issues/3687) - fix(rbac): use check_any_team for API tokens in MCP transports
    - ⏳ [**#3695**](https://github.com/IBM/mcp-context-forge/issues/3695) - feat(auth): add Generic OIDC group-to-team mapping for SSO (#2120)
    - ⏳ [**#3735**](https://github.com/IBM/mcp-context-forge/issues/3735) - [CHORE][PLUGINS]: Test, load test, document, and harden security and resilience plugins
    - ⏳ [**#3846**](https://github.com/IBM/mcp-context-forge/issues/3846) - feat(plugin): add tool call anomaly detection plugin
    - ✅ [**#3924**](https://github.com/IBM/mcp-context-forge/issues/3924) - [BUG][SECURITY]: token_teams narrowing not enforced consistently across Layer 2 permission paths
    - ✅ [**#3932**](https://github.com/IBM/mcp-context-forge/issues/3932) - fix(security): enforce token_teams narrowing across all Layer 2 RBAC paths
    - ⏳ [**#4059**](https://github.com/IBM/mcp-context-forge/issues/4059) - [BUG]: Rust MCP runtime proxy bypasses server ID validation for non-hex server IDs
    - ⏳ [**#4066**](https://github.com/IBM/mcp-context-forge/issues/4066) - fix(security): Validate server ID in Rust MCP runtime proxy to prevent unauthorized access

???+ info "🐛 Bugs - Remaining (21)"

    - ⏳ [**#1411**](https://github.com/IBM/mcp-context-forge/issues/1411) - [BUG][OBSERVABILITY]: Prometheus unable to scrape the metrics
    - ⏳ [**#2249**](https://github.com/IBM/mcp-context-forge/issues/2249) - [BUG]: Self-hosted local service is not actually local nor self-hosted
    - ⏳ [**#2671**](https://github.com/IBM/mcp-context-forge/issues/2671) - [BUG]: ASGI protocol violation in streamable_http: response emitted after completion causing ClosedResourceError
    - ⏳ [**#2935**](https://github.com/IBM/mcp-context-forge/issues/2935) - [BUG]:  Plugin manager not using plugins_dir config
    - ⏳ [**#3138**](https://github.com/IBM/mcp-context-forge/issues/3138) - fix(middleware): add client disconnect middleware to prevent CLOSE_WAIT accumulation
    - ⏳ [**#3172**](https://github.com/IBM/mcp-context-forge/issues/3172) - fix(rpc): use configurable internal RPC URL for self-calls in hybrid mesh deployments
    - ⏳ [**#3178**](https://github.com/IBM/mcp-context-forge/issues/3178) - fix(api): remove shared db session from audit trail calls to prevent inactive transaction errors
    - ⏳ [**#3211**](https://github.com/IBM/mcp-context-forge/issues/3211) - fix(plugins): update external plugin Containerfiles and test configs
    - ⏳ [**#3215**](https://github.com/IBM/mcp-context-forge/issues/3215) - fix(plugins): use plugin_dirs config to resolve external plugins
    - ⏳ [**#3512**](https://github.com/IBM/mcp-context-forge/issues/3512) - [BUG][DB]: bootstrap_db crashes on alembic version mismatch when pgdata volume persists across image rebuilds
    - ⏳ [**#3528**](https://github.com/IBM/mcp-context-forge/issues/3528) - [BUG][API]: Tool update conflict checks have pre-existing gaps in name resolution and scope validation
    - ⏳ [**#3659**](https://github.com/IBM/mcp-context-forge/issues/3659) - fix: use compute_passthrough_headers_cached in direct proxy paths to …
    - ⏳ [**#3832**](https://github.com/IBM/mcp-context-forge/issues/3832) - [BUG][UI]: Virtual Servers — Associated Tools not always loaded
    - ⏳ [**#3850**](https://github.com/IBM/mcp-context-forge/issues/3850) - [BUG][UI]: OAuth Authorize button remains active after successful authorization, Fetch Tools non-functional
    - ⏳ [**#3851**](https://github.com/IBM/mcp-context-forge/issues/3851) - [BUG][UI]: OAuth Fetch Tools fails with cookie authentication error after successful authorization
    - ⏳ [**#3857**](https://github.com/IBM/mcp-context-forge/issues/3857) - [BUG][API]: REST POST tools strip query parameters from URL, breaking signed URLs and query-based auth
    - ⏳ [**#3873**](https://github.com/IBM/mcp-context-forge/issues/3873) - fix[bug]: handle non-JSON responses and query params in REST tools (#3855, #3857)
    - ⏳ [**#3913**](https://github.com/IBM/mcp-context-forge/issues/3913) - [BUG]: Langchain and langgraph missing ghcr.io/ibm/mcp-context-forge:latest
    - ⏳ [**#4051**](https://github.com/IBM/mcp-context-forge/issues/4051) - [BUG]: Alembic migration advisory lock hangs when multiple gateway pods start through PgBouncer (transaction pooling mode)
    - ⏳ [**#4070**](https://github.com/IBM/mcp-context-forge/issues/4070) - SSO (Entra ID) users cannot edit gateways/servers in admin UI — 'invalid team name' error despite ["*"] effective permissions
    - ⏳ [**#4085**](https://github.com/IBM/mcp-context-forge/issues/4085) - [BUG]: team_admin role fails to bootstrap — tools.manage_plugins not in Permissions class

???+ info "⚡ Performance - Remaining (11)"

    - ⏳ [**#2027**](https://github.com/IBM/mcp-context-forge/issues/2027) - [FEATURE]: Fail fast on non-transient connection errors during startup
    - ⏳ [**#2034**](https://github.com/IBM/mcp-context-forge/issues/2034) - [PERFORMANCE]: Add fast-path middleware bypass for /rpc endpoints
    - ⏳ [**#2119**](https://github.com/IBM/mcp-context-forge/issues/2119) - [BUG]: Server toggle returns 400 errors under load
    - ⏳ [**#2621**](https://github.com/IBM/mcp-context-forge/issues/2621) - [BUG][PLUGINS]: Race conditions in plugin global state dictionaries under concurrent load
    - ⏳ [**#2669**](https://github.com/IBM/mcp-context-forge/issues/2669) - [BUG][PERFORMANCE]: Remove unnecessary SERVER_RESET_QUERY=DISCARD ALL from PgBouncer config
    - ⏳ [**#2692**](https://github.com/IBM/mcp-context-forge/issues/2692) - [BUG][PERFORMANCE]: auth hot-path DB queries dominate request latency under load
    - ⏳ [**#3177**](https://github.com/IBM/mcp-context-forge/issues/3177) - feat(auth): add service-level caching for get_user_by_email
    - ⏳ [**#3188**](https://github.com/IBM/mcp-context-forge/issues/3188) - perf(api): optimize metrics aggregation to prevent performance degradation
    - ⏳ [**#3587**](https://github.com/IBM/mcp-context-forge/issues/3587) - [BUG][CACHE]: API hangs on Redis connectivity failure — no graceful fallback
    - ⏳ [**#3689**](https://github.com/IBM/mcp-context-forge/issues/3689) - fix(gateway-service): invalidate tools/resources/prompts caches on update and delete
    - ⏳ [**#3890**](https://github.com/IBM/mcp-context-forge/issues/3890) - feat: add Redis Cluster support via REDIS_CLUSTER_MODE setting

???+ info "🧪 Testing - Remaining (4)"

    - ⏳ [**#2433**](https://github.com/IBM/mcp-context-forge/issues/2433) - [TESTING][FUNCTIONALITY]: Database manual test plan (SQLite, PostgreSQL, migrations, connections)
    - ⏳ [**#2474**](https://github.com/IBM/mcp-context-forge/issues/2474) - [TESTING][UPGRADE]: Version Upgrades, Database Migrations, and Rollback Procedures
    - ⏳ [**#2872**](https://github.com/IBM/mcp-context-forge/issues/2872) - [TASK][PLUGINS]: Add unit tests for secrets detection plugins
    - ⏳ [**#3830**](https://github.com/IBM/mcp-context-forge/issues/3830) - [TESTING][PLUGINS]: Phase 6 - Testing Strategy for Multi-Tenant Plugin Management

???+ info "📚 Documentation - Remaining (5)"

    - ⏳ [**#264**](https://github.com/IBM/mcp-context-forge/issues/264) - [DOCS]: GA Documentation Review & End-to-End Validation Audit
    - ⏳ [**#1413**](https://github.com/IBM/mcp-context-forge/issues/1413) - [FEATURE][PLUGIN]: Add maturity levels to plugins
    - ⏳ [**#2502**](https://github.com/IBM/mcp-context-forge/issues/2502) - [README-FIRST]: Project Backlog & Issue Guide
    - ⏳ [**#2503**](https://github.com/IBM/mcp-context-forge/issues/2503) - [QUICK-START]: 5-Minute Setup & First Steps
    - ⏳ [**#3835**](https://github.com/IBM/mcp-context-forge/issues/3835) - [DOCS][PLUGINS]: Phase 7 - Documentation for Multi-Tenant Plugin Management

???+ info "🔧 Chores - Remaining (3)"

    - ⏳ [**#3736**](https://github.com/IBM/mcp-context-forge/issues/3736) - [CHORE][OBSERVABILITY]: Investigate, test, and harden observability — plugin telemetry, tenant context, and OTel integration gaps
    - ⏳ [**#3836**](https://github.com/IBM/mcp-context-forge/issues/3836) - [CHORE][PLUGINS]: Phase 8 - Migration and Rollout for Multi-Tenant Plugin Management
    - ⏳ [**#3837**](https://github.com/IBM/mcp-context-forge/issues/3837) - [CHORE][PLUGINS]: Phase 9 - Monitoring and Observability for Multi-Tenant Plugin Management

---

## Release 1.0.0-RC2

!!! success "Release 1.0.0-RC2 - Complete (100%)"
    **Due:** 09 Mar 2026 | **Status:** **Closed**
    Release Candidate 2 - Hardening, Admin UI Polish, Plugin Framework & Quality

148 issues resolved. See [CHANGELOG](https://github.com/IBM/mcp-context-forge/blob/main/CHANGELOG.md#100-rc2---2026-03-09---hardening-admin-ui-polish-plugin-framework--quality) for the full list organized by category (Breaking Changes, Added, Fixed, Hardening, Removed, Chores, Testing, Documentation).

---

## Release 1.0.0-RC1

!!! success "Release 1.0.0-RC1 - Complete (100%)"
    **Due:** 17 Feb 2026 | **Status:** **Closed**
    Release Candidate 1 - Security, Linting, Catalog Enhancements, Ratings, experience and UI

???+ check "📋 Epics - Completed (11)"

    - ✅ [**#2109**](https://github.com/IBM/mcp-context-forge/issues/2109) - [EPIC][UI]: Unified search experience for ContextForge admin UI
    - ✅ [**#2387**](https://github.com/IBM/mcp-context-forge/issues/2387) - [EPIC][TESTING][SECURITY]: RBAC automated regression suite (visibility, teams, token scope)
    - ✅ [**#2525**](https://github.com/IBM/mcp-context-forge/issues/2525) - [EPIC][TESTING][PROTOCOL]: MCP 2025-11-25 Protocol Compliance Test Suite
    - ✅ [**#2535**](https://github.com/IBM/mcp-context-forge/issues/2535) - [EPIC][PLUGINS]: External plugin STDIO launch options (cmd/env/cwd)
    - ✅ [**#2555**](https://github.com/IBM/mcp-context-forge/issues/2555) - [EPIC][AUTH]: Streamlined Authentication Model & Secure Defaults
    - ✅ [**#2625**](https://github.com/IBM/mcp-context-forge/issues/2625) - [EPIC][TESTING]: Achieve 80%+ Code Coverage with CI/CD Enforcement
    - ✅ [**#2663**](https://github.com/IBM/mcp-context-forge/issues/2663) - [EPIC][SECURITY]: Enterprise Security Controls - Credential Protection, SSRF Prevention, Multi-Tenant Isolation & Granular RBAC
    - ✅ [**#2783**](https://github.com/IBM/mcp-context-forge/issues/2783) - [EPIC][TESTING]: Slow Time Server - configurable-latency MCP server for timeout, resilience, and load testing
    - ✅ [**#2875**](https://github.com/IBM/mcp-context-forge/issues/2875) - [EPIC][SSO]: Add Keycloak to docker-compose and enable SSO by default for development testing
    - ✅ [**#2939**](https://github.com/IBM/mcp-context-forge/issues/2939) - [EPIC][CI/CD]: Automated license compliance checker with full SBOM scanning across all sub-projects
    - ✅ [**#2953**](https://github.com/IBM/mcp-context-forge/issues/2953) - [EPIC][PLUGINS]: Encoded exfiltration detector plugin - suspicious encoded payload leak prevention

???+ check "🧪 Testing - Completed (17)"

    - ✅ [**#2136**](https://github.com/IBM/mcp-context-forge/issues/2136) - [BUG][TESTING]: Playwright tests not updated to use admin email/password login credentials
    - ✅ [**#2396**](https://github.com/IBM/mcp-context-forge/issues/2396) - [TESTING][SECURITY]: Security headers manual test plan (CSP, HSTS, CORS, clickjacking)
    - ✅ [**#2404**](https://github.com/IBM/mcp-context-forge/issues/2404) - [TESTING][SECURITY]: Security logger manual test plan (brute force, threat scoring, anomaly detection)
    - ✅ [**#2405**](https://github.com/IBM/mcp-context-forge/issues/2405) - [TESTING][SECURITY]: Encryption and secrets manual test plan (Argon2, Fernet, key derivation)
    - ✅ [**#2443**](https://github.com/IBM/mcp-context-forge/issues/2443) - [TESTING][FUNCTIONALITY]: Tags manual test plan (CRUD, entity association, filtering, statistics)
    - ✅ [**#2487**](https://github.com/IBM/mcp-context-forge/issues/2487) - [TESTING][EDGE-CASES]: Boundary Conditions, Empty States, Maximum Limits, and Null Handling
    - ✅ [**#2492**](https://github.com/IBM/mcp-context-forge/issues/2492) - [TESTING][CONFIG]: iFrame Mode (X-Frame-Options) Test Plan
    - ✅ [**#2499**](https://github.com/IBM/mcp-context-forge/issues/2499) - [TESTING] Documentation Site Test Plan
    - ✅ [**#2520**](https://github.com/IBM/mcp-context-forge/issues/2520) - [TESTING][REGRESSION]: Add regression tests for gateway namespacing constraints
    - ✅ [**#2521**](https://github.com/IBM/mcp-context-forge/issues/2521) - [BUG][TESTING]: Flaky tests: TTL expiration and tool listing error handling
    - ✅ [**#2541**](https://github.com/IBM/mcp-context-forge/issues/2541) - [TESTING][PERFORMANCE]: JMeter Performance Load Testing Baseline
    - ✅ [**#2566**](https://github.com/IBM/mcp-context-forge/issues/2566) - [TESTING]: Locust load test reports false failures for 409 Conflict on state change endpoints
    - ✅ [**#2632**](https://github.com/IBM/mcp-context-forge/issues/2632) - [ENHANCEMENT][TESTING][UI]: Improve Playwright test resilience and developer experience
    - ✅ [**#2759**](https://github.com/IBM/mcp-context-forge/issues/2759) - [TESTING][PERFORMANCE]: REST API Data Population Framework (tests/populate)
    - ✅ [**#2788**](https://github.com/IBM/mcp-context-forge/issues/2788) - [TESTING]: Add Jest or Vitest to `package.json`
    - ✅ [**#2789**](https://github.com/IBM/mcp-context-forge/issues/2789) - [TESTING]: Configure test runner in `jest.config.js` or `vitest.config.js`
    - ✅ [**#2815**](https://github.com/IBM/mcp-context-forge/issues/2815) - [TESTING]: Lightweight Local Load Testing and Monitoring Setup

???+ check "🐛 Bugs - Completed (105)"

    - ✅ [**#1430**](https://github.com/IBM/mcp-context-forge/issues/1430) - [BUG][UI]: Tools - Add Tool from REST API with incorrect input schema breaks GET tools
    - ✅ [**#1528**](https://github.com/IBM/mcp-context-forge/issues/1528) - [BUG]: Ignores proxy-based authentication configuration and still requires token
    - ✅ [**#1595**](https://github.com/IBM/mcp-context-forge/issues/1595) - [BUG][SSE]: SSE transport incorrect endpoint and data parsing
    - ✅ [**#1960**](https://github.com/IBM/mcp-context-forge/issues/1960) - [BUG][PERFORMANCE]: Fix high-impact performance issues in llm-guard plugin
    - ✅ [**#2163**](https://github.com/IBM/mcp-context-forge/issues/2163) - [BUG]: Re-raise asyncio.CancelledError after cleanup (S7497)
    - ✅ [**#2185**](https://github.com/IBM/mcp-context-forge/issues/2185) - [BUG][AUTH]: Non-admin user unable to list public gateways
    - ✅ [**#2189**](https://github.com/IBM/mcp-context-forge/issues/2189) - [BUG][AUTH]: Multi-team users denied access to non-primary teams and cannot see public resources from other teams
    - ✅ [**#2192**](https://github.com/IBM/mcp-context-forge/issues/2192) - [BUG]: Token scoping
    - ✅ [**#2261**](https://github.com/IBM/mcp-context-forge/issues/2261) - [BUG]: JWT token creation divergence between CLI and API
    - ✅ [**#2272**](https://github.com/IBM/mcp-context-forge/issues/2272) - [BUG]: Virtual server using an MCP Gateway authenticated with OAUTH2 is loosing tools
    - ✅ [**#2273**](https://github.com/IBM/mcp-context-forge/issues/2273) - [BUG][UI]: Saving a virtual server configuration after edit fails
    - ✅ [**#2324**](https://github.com/IBM/mcp-context-forge/issues/2324) - [BUG]: Observability Dark Mode
    - ✅ [**#2329**](https://github.com/IBM/mcp-context-forge/issues/2329) - [BUG]: Tag filter returns 500 Exception for list tools api
    - ✅ [**#2331**](https://github.com/IBM/mcp-context-forge/issues/2331) - [BUG]: Security: SSO admin role not revoked when user removed from identity provider admin group
    - ✅ [**#2340**](https://github.com/IBM/mcp-context-forge/issues/2340) - [BUG]: RBAC middleware holds database sessions for entire request duration
    - ✅ [**#2346**](https://github.com/IBM/mcp-context-forge/issues/2346) - [BUG]: Root actions are (mostly) all broken
    - ✅ [**#2348**](https://github.com/IBM/mcp-context-forge/issues/2348) - [BUG]: Schema validation behavior change may cause runtime errors
    - ✅ [**#2357**](https://github.com/IBM/mcp-context-forge/issues/2357) - [BUG]: (sse): Granian CPU spikes to 800% after load stops, recovers when load resumes
    - ✅ [**#2360**](https://github.com/IBM/mcp-context-forge/issues/2360) - [BUG]: anyio cancel scope spin loop causes 100% CPU after load test stops
    - ✅ [**#2378**](https://github.com/IBM/mcp-context-forge/issues/2378) - [BUG][SONAR][LOW]: Missing expires_at calculation in DCR client registration
    - ✅ [**#2386**](https://github.com/IBM/mcp-context-forge/issues/2386) - [BUG][AUTH]: SSO admin tokens include teams key, preventing unrestricted admin bypass
    - ✅ [**#2512**](https://github.com/IBM/mcp-context-forge/issues/2512) - [BUG]: Tool invocation fails with Pydantic validation errors
    - ✅ [**#2518**](https://github.com/IBM/mcp-context-forge/issues/2518) - [BUG][PERFORMANCE][DATABASE]: DB sessions held during external HTTP calls cause connection pool exhaustion
    - ✅ [**#2523**](https://github.com/IBM/mcp-context-forge/issues/2523) - [BUG]: API Call - Users - Can not create/edit users with password_change_required:true
    - ✅ [**#2524**](https://github.com/IBM/mcp-context-forge/issues/2524) - [BUG]: API Call - Users - Can not create inactive users
    - ✅ [**#2526**](https://github.com/IBM/mcp-context-forge/issues/2526) - [BUG]: Gateway Container Stuck at "Waiting" with SSL Enabled
    - ✅ [**#2528**](https://github.com/IBM/mcp-context-forge/issues/2528) - [BUG]: MCP Servers with tool name starts with "_" is failing to add to gateway
    - ✅ [**#2539**](https://github.com/IBM/mcp-context-forge/issues/2539) - [BUG][AUTH]: Login loop when SECURE_COOKIES=true with HTTP access
    - ✅ [**#2544**](https://github.com/IBM/mcp-context-forge/issues/2544) - [BUG]: A2A Agent "Test Agent" returns HTTP 500 error message
    - ✅ [**#2545**](https://github.com/IBM/mcp-context-forge/issues/2545) - [BUG]: UI/ API - Edit user is not working
    - ✅ [**#2562**](https://github.com/IBM/mcp-context-forge/issues/2562) - [BUG]: JSON parse error when adding MCP server - missing response validation in admin.js
    - ✅ [**#2563**](https://github.com/IBM/mcp-context-forge/issues/2563) - [BUG]: Gateway tags return empty due to type mismatch between schema and validation layer
    - ✅ [**#2570**](https://github.com/IBM/mcp-context-forge/issues/2570) - [BUG]: Error message not propogated in /mcp endpoint responses
    - ✅ [**#2572**](https://github.com/IBM/mcp-context-forge/issues/2572) - [BUG]: UI - API Tokens - Last Used and Usage Stats not showing any data
    - ✅ [**#2573**](https://github.com/IBM/mcp-context-forge/issues/2573) - [BUG]: API Calls - API Tokens- Create / Update API calls are not saving the correct data
    - ✅ [**#2576**](https://github.com/IBM/mcp-context-forge/issues/2576) - [BUG]: Gateway Rejects Loki Query Tools Due to Backtick Validation
    - ✅ [**#2590**](https://github.com/IBM/mcp-context-forge/issues/2590) - [BUG][AUTH]: UI/API Users with no admin privileges can no longer login
    - ✅ [**#2591**](https://github.com/IBM/mcp-context-forge/issues/2591) - [BUG]: LimitOverrunError with `translate` for stdio server
    - ✅ [**#2607**](https://github.com/IBM/mcp-context-forge/issues/2607) - [BUG][TAGS]: get_entities_by_tag fails on PostgreSQL - uses SQLite json_extract function
    - ✅ [**#2608**](https://github.com/IBM/mcp-context-forge/issues/2608) - [BUG][TEAMS]: list_teams uses current_user_ctx["db"] which is always None
    - ✅ [**#2626**](https://github.com/IBM/mcp-context-forge/issues/2626) - [BUG][UI]: Browser autocomplete incorrectly fills fields with saved credentials (UX issue)
    - ✅ [**#2628**](https://github.com/IBM/mcp-context-forge/issues/2628) - [BUG][AUTH]: Account lockout issues - counter persists after expiry, no user notification, no admin unlock capability
    - ✅ [**#2648**](https://github.com/IBM/mcp-context-forge/issues/2648) - [BUG][PLUGINS]: RESOURCE_POST_FETCH plugins are executed before invoke_resource() resolves resource templates
    - ✅ [**#2656**](https://github.com/IBM/mcp-context-forge/issues/2656) - [BUG]: prompt_id not visible in UI
    - ✅ [**#2658**](https://github.com/IBM/mcp-context-forge/issues/2658) - [BUG]: Admin User Update Endpoint Overwrites Fields with None
    - ✅ [**#2673**](https://github.com/IBM/mcp-context-forge/issues/2673) - [BUG]: Admin can no longer see all teams
    - ✅ [**#2675**](https://github.com/IBM/mcp-context-forge/issues/2675) - [BUG]: User with no Administrator privileges should not see all menu entries as Admin does
    - ✅ [**#2676**](https://github.com/IBM/mcp-context-forge/issues/2676) - [BUG]: Teams - Manage Members - Add New Member - Add Member button don't work for user role
    - ✅ [**#2677**](https://github.com/IBM/mcp-context-forge/issues/2677) - [BUG]: Teams - Manage Members - User role - Owner of the team can not switch member to owners or owner to members
    - ✅ [**#2679**](https://github.com/IBM/mcp-context-forge/issues/2679) - [BUG]: TLS profile doesn't support passphrase-protected certificates
    - ✅ [**#2681**](https://github.com/IBM/mcp-context-forge/issues/2681) - [BUG]: The texts of Authorize and Fetch tool overlap on the MCP Servers page
    - ✅ [**#2690**](https://github.com/IBM/mcp-context-forge/issues/2690) - [BUG]: Teams - Newly created team is not displayed until the page is refreshed
    - ✅ [**#2693**](https://github.com/IBM/mcp-context-forge/issues/2693) - [BUG]:  Unable to Update User via Admin UI & API Requires Mandatory Fields Causing Full Name Loss
    - ✅ [**#2694**](https://github.com/IBM/mcp-context-forge/issues/2694) - [BUG][AUTH]: Users Cannot Access Admin UI - Missing Default Role Assignment
    - ✅ [**#2695**](https://github.com/IBM/mcp-context-forge/issues/2695) - [BUG]: Redundant database queries in PermissionService.check_permission()
    - ✅ [**#2697**](https://github.com/IBM/mcp-context-forge/issues/2697) - [BUG][SECURITY]: Virtual MCP Server incorrectly requires servers.create permission
    - ✅ [**#2700**](https://github.com/IBM/mcp-context-forge/issues/2700) - [BUG]: API Call - /auth/email/me - 422 Error is shown
    - ✅ [**#2702**](https://github.com/IBM/mcp-context-forge/issues/2702) - [BUG]: Password requirements checker not working on user edit
    - ✅ [**#2706**](https://github.com/IBM/mcp-context-forge/issues/2706) - [BUG]: [AUTH] OAuth Protected Resource Metadata endpoint not RFC 9728 compliant
    - ✅ [**#2710**](https://github.com/IBM/mcp-context-forge/issues/2710) - [BUG]: Tools - Edit - Description - Showing special characters instead of the correct text
    - ✅ [**#2731**](https://github.com/IBM/mcp-context-forge/issues/2731) - [BUG]: make pre-commit fails on check-executables-have-shebangs for tests/client/init.py
    - ✅ [**#2732**](https://github.com/IBM/mcp-context-forge/issues/2732) - [BUG]: make pre-commit fails on check-shebang-scripts-are-executable for multiple files
    - ✅ [**#2733**](https://github.com/IBM/mcp-context-forge/issues/2733) - [BUG]: detect-private-key hook fails on test fixtures containing private keys
    - ✅ [**#2734**](https://github.com/IBM/mcp-context-forge/issues/2734) - [BUG]: check-yaml hook fails on multi-document YAML files
    - ✅ [**#2735**](https://github.com/IBM/mcp-context-forge/issues/2735) - [BUG]: pre-commit name-tests-test hook fails on test utility files
    - ✅ [**#2741**](https://github.com/IBM/mcp-context-forge/issues/2741) - [BUG]: New administrator user not assigned correct privileges and hence cannot access UI
    - ✅ [**#2757**](https://github.com/IBM/mcp-context-forge/issues/2757) - [BUG][SCALE]: JWT cookie exceeds browser 4KB limit when user has many team memberships
    - ✅ [**#2760**](https://github.com/IBM/mcp-context-forge/issues/2760) - [BUG]: UI - Delete and Update button should be hidden for public mcp servers created by other users and teams
    - ✅ [**#2763**](https://github.com/IBM/mcp-context-forge/issues/2763) - [BUG][LOCKOUT]: Admin accounts can be locked out via failed login attempts despite protect_all_admins
    - ✅ [**#2764**](https://github.com/IBM/mcp-context-forge/issues/2764) - [BUG][UI]: API Tokens page missing pagination and team filter not updating
    - ✅ [**#2777**](https://github.com/IBM/mcp-context-forge/issues/2777) - [BUG]: Admin UI breaks when embedded in an iframe
    - ✅ [**#2794**](https://github.com/IBM/mcp-context-forge/issues/2794) - [BUG][UI]: Admin users should not have option to remove administration privileges by themselves.
    - ✅ [**#2799**](https://github.com/IBM/mcp-context-forge/issues/2799) - [BUG][UI]: Teams list resets to page 1 after any team CRUD action
    - ✅ [**#2800**](https://github.com/IBM/mcp-context-forge/issues/2800) - [BUG][UI]: Redundant HX-Retarget headers in team creation error handlers after #2780
    - ✅ [**#2803**](https://github.com/IBM/mcp-context-forge/issues/2803) - [BUG][AUTH]: OCP2 QA — new admin user lacks admin.dashboard permission (duplicate of #2741)
    - ✅ [**#2805**](https://github.com/IBM/mcp-context-forge/issues/2805) - [BUG][UI]: The error message from API on updating a user is not displayed
    - ✅ [**#2806**](https://github.com/IBM/mcp-context-forge/issues/2806) - [BUG][AUTH]: Admin login redirect loop behind reverse proxy without path rewriting
    - ✅ [**#2811**](https://github.com/IBM/mcp-context-forge/issues/2811) - [BUG]: Teams - Add / Remove members - The updates are shown only after a refresh
    - ✅ [**#2821**](https://github.com/IBM/mcp-context-forge/issues/2821) - [BUG]: RBAC middleware crashes on token creation
    - ✅ [**#2836**](https://github.com/IBM/mcp-context-forge/issues/2836) - [BUG][AUTH]: Token created with no expiration returns 401
    - ✅ [**#2837**](https://github.com/IBM/mcp-context-forge/issues/2837) - [BUG]: gunicorn workers crash with SIGSEGV on macOS when running `make serve`
    - ✅ [**#2845**](https://github.com/IBM/mcp-context-forge/issues/2845) - [BUG]: Admin UI pagination breaks behind reverse proxies and shows incorrect counts
    - ✅ [**#2863**](https://github.com/IBM/mcp-context-forge/issues/2863) - [BUG]: MultipleResultsFound when invoking MCP tools due to name-only lookup in DbTool
    - ✅ [**#2870**](https://github.com/IBM/mcp-context-forge/issues/2870) - [BUG]: API Call - Tokens - Can no longer create tokens - 403 error
    - ✅ [**#2873**](https://github.com/IBM/mcp-context-forge/issues/2873) - [BUG]: Critical: SSO authentication blocked - AttributeError on app_domain breaks Azure Entra ID
    - ✅ [**#2874**](https://github.com/IBM/mcp-context-forge/issues/2874) - [BUG][UI]: Login page appears inside active module tab despite valid session
    - ✅ [**#2881**](https://github.com/IBM/mcp-context-forge/issues/2881) - [BUG][AUTH]: OAuth2 with Microsoft Entra v2 fails with resource+scope conflict (AADSTS9010010)
    - ✅ [**#2882**](https://github.com/IBM/mcp-context-forge/issues/2882) - [BUG][AUTH]: Unable to create team token using APIs
    - ✅ [**#2883**](https://github.com/IBM/mcp-context-forge/issues/2883) - [BUG][RBAC]: Getting 403 when adding MCP server or virtual server from team
    - ✅ [**#2887**](https://github.com/IBM/mcp-context-forge/issues/2887) - [BUG][UI]: Agents page has double loading spinner on refresh
    - ✅ [**#2891**](https://github.com/IBM/mcp-context-forge/issues/2891) - [BUG][RBAC]: Platform admin blocked by RBAC on gateway delete (allow_admin_bypass=False)
    - ✅ [**#2908**](https://github.com/IBM/mcp-context-forge/issues/2908) - [BUG]: Allow teams to deploy Gateway with developer as default role for team members
    - ✅ [**#2916**](https://github.com/IBM/mcp-context-forge/issues/2916) - [BUG][API]: Selective export crashes with AttributeError on Tool.rate_limit
    - ✅ [**#2917**](https://github.com/IBM/mcp-context-forge/issues/2917) - [BUG][API]: RBAC role DELETE returns 500 due to incorrect SQLAlchemy query
    - ✅ [**#2920**](https://github.com/IBM/mcp-context-forge/issues/2920) - [BUG]: Select team visibility as default when creating resources in team scope
    - ✅ [**#2923**](https://github.com/IBM/mcp-context-forge/issues/2923) - [BUG]: HTML new line tags appearing in server listing team column
    - ✅ [**#2926**](https://github.com/IBM/mcp-context-forge/issues/2926) - [BUG]: Gunicorn worker crashes on macOS due to Objective-C fork safety
    - ✅ [**#2930**](https://github.com/IBM/mcp-context-forge/issues/2930) - [BUG][UI]: Hight automatically expands modal in the Team Manage Members modal blocking to save changes
    - ✅ [**#2932**](https://github.com/IBM/mcp-context-forge/issues/2932) - [BUG]: Team Filter Lost During Pagination
    - ✅ [**#2946**](https://github.com/IBM/mcp-context-forge/issues/2946) - [BUG][UI]: The loading messages are not consistent on all pages while waiting for the API response
    - ✅ [**#2955**](https://github.com/IBM/mcp-context-forge/issues/2955) - [BUG][ALEMBIC]: migration compatibility issues in a31c6ffc2239 and ba202ac1665f
    - ✅ [**#2965**](https://github.com/IBM/mcp-context-forge/issues/2965) - [BUG][UI]: Admin UI shows raw JSON error instead of redirecting to login when user is deleted
    - ✅ [**#2973**](https://github.com/IBM/mcp-context-forge/issues/2973) - [BUG]: Server ID Context Dropped During Stateful Session/ Session Affinity Processing
    - ✅ [**#2987**](https://github.com/IBM/mcp-context-forge/issues/2987) - [BUG]: When a toolkit import fails for any reason, subsequent attempts to import a toolkit with the same tool name are blocked
    - ✅ [**#3010**](https://github.com/IBM/mcp-context-forge/issues/3010) - [BUG]: Failed to bootstrap SSO providers: 'jwks_uri' is an invalid keyword argument for SSOProvider

???+ check "🔒 Security - Completed (3)"

    - ✅ [**#2366**](https://github.com/IBM/mcp-context-forge/issues/2366) - [SECURITY][SONAR][MEDIUM]: ReDoS vulnerability in SSTI validation patterns in validators.py
    - ✅ [**#2370**](https://github.com/IBM/mcp-context-forge/issues/2370) - [SECURITY][SONAR][LOW]: ReDoS vulnerability in plugin regex patterns
    - ✅ [**#2375**](https://github.com/IBM/mcp-context-forge/issues/2375) - [SECURITY][SONAR][MEDIUM]: Missing token validation in reverse_proxy WebSocket endpoint

???+ check "⚡ Performance - Completed (7)"

    - ✅ [**#1834**](https://github.com/IBM/mcp-context-forge/issues/1834) - [PERFORMANCE]: Precompile regex patterns across plugins
    - ✅ [**#1835**](https://github.com/IBM/mcp-context-forge/issues/1835) - [PERFORMANCE]: Response-cache-by-prompt algorithmic optimization
    - ✅ [**#1836**](https://github.com/IBM/mcp-context-forge/issues/1836) - [PERFORMANCE]: Offload CPU-bound crypto (Argon2/Fernet) to threadpool
    - ✅ [**#1938**](https://github.com/IBM/mcp-context-forge/issues/1938) - [PERFORMANCE]: Admin metrics rollups empty during benchmark window (raw scans only)
    - ✅ [**#1959**](https://github.com/IBM/mcp-context-forge/issues/1959) - [PERFORMANCE]: Fix critical performance issues in llm-guard plugin
    - ✅ [**#1999**](https://github.com/IBM/mcp-context-forge/issues/1999) - [PERFORMANCE]: Add ulimits to PgBouncer container to prevent file descriptor exhaustion
    - ✅ [**#2082**](https://github.com/IBM/mcp-context-forge/issues/2082) - [PERFORMANCE][PLUGIN]: Optimize Cedar plugin - Replace synchronous requests with async

???+ check "📚 Documentation - Completed (3)"

    - ✅ [**#2365**](https://github.com/IBM/mcp-context-forge/issues/2365) - [DOCS]: README rationalization
    - ✅ [**#2543**](https://github.com/IBM/mcp-context-forge/issues/2543) - [DOCS][AUTH]: Administrator Password Reset & Recovery Guide
    - ✅ [**#2817**](https://github.com/IBM/mcp-context-forge/issues/2817) - [DOCS]: CONTRIBUTING.md link for file header management is broken

???+ check "🔧 Chores - Completed (21)"

    - ✅ [**#222**](https://github.com/IBM/mcp-context-forge/issues/222) - [CHORE]: Helm chart build Makefile with lint and values.schema.json validation + CODEOWNERS, CHANGELOG.md, .helmignore and CONTRIBUTING.md
    - ✅ [**#261**](https://github.com/IBM/mcp-context-forge/issues/261) - [CHORE]: Implement 90% Test Coverage Quality Gate and automatic badge and coverage html / markdown report publication
    - ✅ [**#377**](https://github.com/IBM/mcp-context-forge/issues/377) - [CHORE][HELM]: Fix PostgreSQL volume name conflicts in Helm chart
    - ✅ [**#2154**](https://github.com/IBM/mcp-context-forge/issues/2154) - [CHORE]: Add CI/CD validation for Alembic migration status
    - ✅ [**#2193**](https://github.com/IBM/mcp-context-forge/issues/2193) - [CHORE]: Add Rocky Linux setup script variant
    - ✅ [**#2207**](https://github.com/IBM/mcp-context-forge/issues/2207) - [CHORE] workflow_dispatch platforms input is unused in docker-multiplatform.yml
    - ✅ [**#2233**](https://github.com/IBM/mcp-context-forge/issues/2233) - [CHORE][AUTH]: Align SSO service teams claim format with /tokens and /auth/login
    - ✅ [**#2256**](https://github.com/IBM/mcp-context-forge/issues/2256) - [CHORE]: GatewayService creates uninitialized service instances (ToolService, PromptService, ResourceService)
    - ✅ [**#2265**](https://github.com/IBM/mcp-context-forge/issues/2265) - [CHORE][AUTH]: Add sso_entra_admin_groups to _parse_list_from_env validator
    - ✅ [**#2337**](https://github.com/IBM/mcp-context-forge/issues/2337) - [CHORE]: Clean up .gitignore redundant patterns and organization
    - ✅ [**#2361**](https://github.com/IBM/mcp-context-forge/issues/2361) - [CHORE]: Replace copier with cookiecutter for template scaffolding
    - ✅ [**#2367**](https://github.com/IBM/mcp-context-forge/issues/2367) - [CLEANUP][SONAR][LOW]: Redundant ternary - both branches identical in log_aggregator.py
    - ✅ [**#2368**](https://github.com/IBM/mcp-context-forge/issues/2368) - [CLEANUP][SONAR][LOW]: Dead code - if/else branches identical in oauth_manager.py
    - ✅ [**#2371**](https://github.com/IBM/mcp-context-forge/issues/2371) - [CLEANUP][SONAR][LOW]: Dead code - unused variable max_duration in admin.py
    - ✅ [**#2372**](https://github.com/IBM/mcp-context-forge/issues/2372) - [CLEANUP][SONAR][LOW]: Dead code - unused function json_default in llmchat_router.py
    - ✅ [**#2377**](https://github.com/IBM/mcp-context-forge/issues/2377) - [CLEANUP][SONAR][LOW]: Deprecated datetime.utcnow() usage in main.py
    - ✅ [**#2382**](https://github.com/IBM/mcp-context-forge/issues/2382) - [CHORE][TESTS]: Remove unused PromptNotFoundError import
    - ✅ [**#2630**](https://github.com/IBM/mcp-context-forge/issues/2630) - [CHORE][MCP-SERVERS]: Update dependencies across Python, Go, and Rust servers
    - ✅ [**#2651**](https://github.com/IBM/mcp-context-forge/issues/2651) - [CHORE]: Remove unused runtime dependencies from pyproject.toml
    - ✅ [**#2665**](https://github.com/IBM/mcp-context-forge/issues/2665) - [CHORE][PYTEST]: Add verbose test output option for real-time test name visibility
    - ✅ [**#2981**](https://github.com/IBM/mcp-context-forge/issues/2981) - [CHORE][SONAR]: Fix all must-fix SonarQube findings - type safety, async tasks, dead code

???+ check "❓ Questions - Completed (3)"

    - ✅ [**#2644**](https://github.com/IBM/mcp-context-forge/issues/2644) - [QUESTION][ICA]: Unable to register most MCP servers from catalog
    - ✅ [**#2725**](https://github.com/IBM/mcp-context-forge/issues/2725) - [QUESTION][ICA]: Error creating API token in ICA
    - ✅ [**#2781**](https://github.com/IBM/mcp-context-forge/issues/2781) - [QUESTION][CONFIGURATION]: MCP toolkit tool invocation returns an error Tool invocation failed

???+ check "✨ Features - Completed (19)"

    - ✅ [**#234**](https://github.com/IBM/mcp-context-forge/issues/234) - [FEATURE][PROTOCOL]: Elicitation support (MCP 2025-06-18)
    - ✅ [**#266**](https://github.com/IBM/mcp-context-forge/issues/266) - [Feature Request]: Sample MCP Server - Rust Implementation ("filesystem-server")
    - ✅ [**#1308**](https://github.com/IBM/mcp-context-forge/issues/1308) - [FEATURE][HELM]: Add optional persistence support for PostgreSQL and Redis
    - ✅ [**#1439**](https://github.com/IBM/mcp-context-forge/issues/1439) - [FEATURE][PLUGIN]: Create JWT claims and metadata extraction plugin
    - ✅ [**#1986**](https://github.com/IBM/mcp-context-forge/issues/1986) - [FEATURE]: Session affinity for stateful MCP workflows (REQ-005)
    - ✅ [**#2075**](https://github.com/IBM/mcp-context-forge/issues/2075) - [FEATURE][UI]: Flexible UI sections for embedded contexts
    - ✅ [**#2076**](https://github.com/IBM/mcp-context-forge/issues/2076) - [FEATURE][UI]: Add search capabilities for tools in admin UI
    - ✅ [**#2078**](https://github.com/IBM/mcp-context-forge/issues/2078) - [FEATURE]: Tool invocation timeouts and circuit breaker
    - ✅ [**#2167**](https://github.com/IBM/mcp-context-forge/issues/2167) - [FEATURE]: Add keyboard handlers to interactive elements
    - ✅ [**#2171**](https://github.com/IBM/mcp-context-forge/issues/2171) - [FEATURE]: Dynamic tools/resources based on user context and server-side signals
    - ✅ [**#2187**](https://github.com/IBM/mcp-context-forge/issues/2187) - [FEATURE][AUTH]: Extend default_roles to add additional roles during bootstrap
    - ✅ [**#2198**](https://github.com/IBM/mcp-context-forge/issues/2198) - [FEATURE] Add MCP Client (MCP Inspector) to docker-compose
    - ✅ [**#2223**](https://github.com/IBM/mcp-context-forge/issues/2223) - [FEATURE][POLICY]: Unified policy decision point (PDP) - Cedar/OPA/native abstraction
    - ✅ [**#2542**](https://github.com/IBM/mcp-context-forge/issues/2542) - [FEATURE][AUTH]: Self-Service Password Reset Workflow (Forgot Password)
    - ✅ [**#2571**](https://github.com/IBM/mcp-context-forge/issues/2571) - [FEATURE][INFRA]: Zero-config TLS for Nginx via Docker Compose profile
    - ✅ [**#2729**](https://github.com/IBM/mcp-context-forge/issues/2729) - [RUST]: Rust Implementation for Secrets Detection Plugin
    - ✅ [**#2776**](https://github.com/IBM/mcp-context-forge/issues/2776) - [RUST] Rust Plugins CI/CD workflow fails to start due to disallowed actions
    - ✅ [**#2893**](https://github.com/IBM/mcp-context-forge/issues/2893) - [FEATURE]: Maintain custom and original description for tools
    - ✅ [**#2905**](https://github.com/IBM/mcp-context-forge/issues/2905) - [FEATURE]: Add new backend api to add a team member

---
---

## Release 1.0.0-BETA-2

!!! success "Release 1.0.0-BETA-2 - Completed (100%)"
    **Due:** 20 Jan 2026 | **Status:** Closed
    Testing, Bugfixing, Documentation, Performance and Scale

???+ check "✨ Features - Completed (26)"

    - ✅ [**#919**](https://github.com/IBM/mcp-context-forge/issues/919) - Sample MCP Server - Python (qr-code-server)
    - ✅ [**#950**](https://github.com/IBM/mcp-context-forge/issues/950) - Session Management & Tool Invocation with Gateway vs Direct MCP Client–Server
    - ✅ [**#974**](https://github.com/IBM/mcp-context-forge/issues/974) - [Feature Request]: Make users change default admin passwords and secrets for production deployments.
    - ✅ [**#1148**](https://github.com/IBM/mcp-context-forge/issues/1148) - [Feature]: Full Stack CICD build and deployment of MCP CF through single configuration
    - ✅ [**#1318**](https://github.com/IBM/mcp-context-forge/issues/1318) - [Feature Request]: While creating Virtual Server can we have tool list in <server_name>_<tool_name> format
    - ✅ [**#1414**](https://github.com/IBM/mcp-context-forge/issues/1414) - [Feature Request]: Client CLI
    - ✅ [**#1580**](https://github.com/IBM/mcp-context-forge/issues/1580) - [Feature Request]: API Key Auth support through queryparams
    - ✅ [**#1722**](https://github.com/IBM/mcp-context-forge/issues/1722) - [Feature Request]: Support External Database host/url
    - ✅ [**#1735**](https://github.com/IBM/mcp-context-forge/issues/1735) - [ENHANCEMENT]: Add metrics cleanup and rollup for long-term performance
    - ✅ [**#1753**](https://github.com/IBM/mcp-context-forge/issues/1753) - [HELM]: Add optional PgBouncer connection pooling support
    - ✅ [**#1766**](https://github.com/IBM/mcp-context-forge/issues/1766) - [FEATURE] Add resilient database session handling for connection pool exhaustion recovery
    - ✅ [**#1804**](https://github.com/IBM/mcp-context-forge/issues/1804) - [FEATURE]: Add DB_METRICS_RECORDING_ENABLED switch to disable execution metrics
    - ✅ [**#1843**](https://github.com/IBM/mcp-context-forge/issues/1843) - Feature: Add configurable password change enforcement settings
    - ✅ [**#1910**](https://github.com/IBM/mcp-context-forge/issues/1910) - [Feature Request]: Support re-discovery / refresh of tools for already registered MCP gateways
    - ✅ [**#1977**](https://github.com/IBM/mcp-context-forge/issues/1977) - [FEATURE]: Optimize Tools, Prompts, and Resources tables to reduce horizontal scrolling
    - ✅ [**#1978**](https://github.com/IBM/mcp-context-forge/issues/1978) - [FEATURE]: Add Overview tab to Admin UI with architecture visualization
    - ✅ [**#1983**](https://github.com/IBM/mcp-context-forge/issues/1983) - [FEATURE REQUEST]: Support cancellation of long-running tool executions
    - ✅ [**#1984**](https://github.com/IBM/mcp-context-forge/issues/1984) - [FEATURE REQUEST]: Full tool list/spec refresh (polling + API + list_changed)
    - ✅ [**#2022**](https://github.com/IBM/mcp-context-forge/issues/2022) - [Feature Request] OAuth 2.0 authentication for MCP clients with browser-based SSO (RFC 9728)
    - ✅ [**#2025**](https://github.com/IBM/mcp-context-forge/issues/2025) - [FEATURE]: Add exponential backoff with jitter for database and Redis startup resilience
    - ✅ [**#2047**](https://github.com/IBM/mcp-context-forge/issues/2047) - feat(chart): Add support for extraEnvFrom in mcp-stack-mcpgateway
    - ✅ [**#2052**](https://github.com/IBM/mcp-context-forge/issues/2052) - feat(chart): Support External PostgreSQL (CloudNativePG compatible)
    - ✅ [**#2054**](https://github.com/IBM/mcp-context-forge/issues/2054) - [Feature Request]: Microsoft EntraID Role and Group Claim Mapping for SSO
    - ✅ [**#2195**](https://github.com/IBM/mcp-context-forge/issues/2195) - [FEATURE]: Add query parameter authentication support for A2A agents
    - ✅ [**#2205**](https://github.com/IBM/mcp-context-forge/issues/2205) - [FEATURE]: Add ppc64le (IBM POWER) architecture support for container builds
    - ✅ [**#2364**](https://github.com/IBM/mcp-context-forge/pull/2364) - Default plugins setup in docker-compose

???+ check "⚡ Performance - Completed (107)"

    - ✅ [**#975**](https://github.com/IBM/mcp-context-forge/issues/975) - [PERFORMANCE]: Implement Session Persistence & Pooling for Improved Performance and State Continuity
    - ✅ [**#1224**](https://github.com/IBM/mcp-context-forge/issues/1224) - [PERFORMANCE]: REST API and UI Pagination for Large-Scale Multi-Tenant Deployments
    - ✅ [**#1353**](https://github.com/IBM/mcp-context-forge/issues/1353) - [PERFORMANCE] 💾 Database Indexing Optimization
    - ✅ [**#1608**](https://github.com/IBM/mcp-context-forge/issues/1608) - [PERFORMANCE]: Plugin Framework Memory Optimization: Copy-on-Write for Context State
    - ✅ [**#1609**](https://github.com/IBM/mcp-context-forge/issues/1609) - [PERFORMANCE]: Fix N+1 and Redundant Query Patterns
    - ✅ [**#1610**](https://github.com/IBM/mcp-context-forge/issues/1610) - [PERFORMANCE]: Optimize Performance Tracker Buffer Management (O(n) → O(1))
    - ✅ [**#1611**](https://github.com/IBM/mcp-context-forge/issues/1611) - [PERFORMANCE]: Optimize Startup Slug Refresh with Batch Processing
    - ✅ [**#1613**](https://github.com/IBM/mcp-context-forge/issues/1613) - [PERFORMANCE]: Optimize stream parser buffer management (O(n²) → O(n))
    - ✅ [**#1614**](https://github.com/IBM/mcp-context-forge/issues/1614) - [PERFORMANCE]: Optimize LRU cache eviction (O(n) → O(1))
    - ✅ [**#1615**](https://github.com/IBM/mcp-context-forge/issues/1615) - [PERFORMANCE]: Eliminate redundant JSON encoding in session registry
    - ✅ [**#1616**](https://github.com/IBM/mcp-context-forge/issues/1616) - [PERFORMANCE]: Parallelize session cleanup with asyncio.gather()
    - ✅ [**#1641**](https://github.com/IBM/mcp-context-forge/issues/1641) - [PERFORMANCE]: Add SELECT FOR UPDATE to prevent race conditions under high concurrency
    - ✅ [**#1657**](https://github.com/IBM/mcp-context-forge/issues/1657) - [PERFORMANCE]: Logging consistency and performance improvements
    - ✅ [**#1661**](https://github.com/IBM/mcp-context-forge/issues/1661) - [REFACTOR]: Shared async Redis client factory, async, configurable, with atomic lock release + migrate all services
    - ✅ [**#1674**](https://github.com/IBM/mcp-context-forge/issues/1674) - [PERFORMANCE]: Implement Bulk Insert Operations for Import Service
    - ✅ [**#1675**](https://github.com/IBM/mcp-context-forge/issues/1675) - [PERFORMANCE]: Reduce Session Registry Database Polling Overhead
    - ✅ [**#1676**](https://github.com/IBM/mcp-context-forge/issues/1676) - [PERFORMANCE]: Configure HTTP Client Connection Pool Limits
    - ✅ [**#1677**](https://github.com/IBM/mcp-context-forge/issues/1677) - [PERFORMANCE]: Cache JWT Token Verification Results
    - ✅ [**#1678**](https://github.com/IBM/mcp-context-forge/issues/1678) - [PERFORMANCE]: Optimize Plugin Hook Execution Path
    - ✅ [**#1680**](https://github.com/IBM/mcp-context-forge/issues/1680) - [PERFORMANCE]: Implement Distributed Registry & Admin Cache
    - ✅ [**#1683**](https://github.com/IBM/mcp-context-forge/issues/1683) - [PERFORMANCE]: Optimize Middleware Chain Execution
    - ✅ [**#1684**](https://github.com/IBM/mcp-context-forge/issues/1684) - [PERFORMANCE]: Optimize Duplicate and Inefficient COUNT Queries
    - ✅ [**#1686**](https://github.com/IBM/mcp-context-forge/issues/1686) - [PERFORMANCE]: Batch Team Membership Queries
    - ✅ [**#1687**](https://github.com/IBM/mcp-context-forge/issues/1687) - [PERFORMANCE]: Optimize Admin UI Dashboard Queries
    - ✅ [**#1691**](https://github.com/IBM/mcp-context-forge/issues/1691) - [PERFORMANCE]: Optimize Gateway Health Check Timeout
    - ✅ [**#1692**](https://github.com/IBM/mcp-context-forge/issues/1692) - [PERFORMANCE]: Replace Explicit JSONResponse with ORJSONResponse
    - ✅ [**#1695**](https://github.com/IBM/mcp-context-forge/issues/1695) - [PERFORMANCE]: Migrate from Gunicorn to Granian HTTP Server
    - ✅ [**#1696**](https://github.com/IBM/mcp-context-forge/issues/1696) - [PERFORMANCE]: Replace stdlib json with orjson throughout codebase for less frequently used json.loads and json.dumps
    - ✅ [**#1699**](https://github.com/IBM/mcp-context-forge/issues/1699) - [PERFORMANCE]: Adopt uvicorn[standard] for Enhanced Server Performance
    - ✅ [**#1702**](https://github.com/IBM/mcp-context-forge/issues/1702) - [PERFORMANCE]: Add Hiredis as Default Redis Parser with Fallback Option
    - ✅ [**#1714**](https://github.com/IBM/mcp-context-forge/issues/1714) - [PERFORMANCE]: Buffered Metrics Writes and Skip Metrics on List Endpoints
    - ✅ [**#1715**](https://github.com/IBM/mcp-context-forge/issues/1715) - [PERFORMANCE]: In-Memory Cache for GlobalConfig Lookups
    - ✅ [**#1727**](https://github.com/IBM/mcp-context-forge/issues/1727) - [PERFORMANCE]: Optimize Export Service with Batch Queries
    - ✅ [**#1731**](https://github.com/IBM/mcp-context-forge/issues/1731) - [PERFORMANCE]: High httpx client churn causes memory pressure under load
    - ✅ [**#1732**](https://github.com/IBM/mcp-context-forge/issues/1732) - [PERFORMANCE]: Database session issues causing high rollback rate and connection growth
    - ✅ [**#1734**](https://github.com/IBM/mcp-context-forge/issues/1734) - [PERFORMANCE]: Optimize metrics aggregation to prevent performance degradation under load
    - ✅ [**#1737**](https://github.com/IBM/mcp-context-forge/issues/1737) - [PERFORMANCE]: Cache get_top_* methods to prevent full metrics table scans
    - ✅ [**#1740**](https://github.com/IBM/mcp-context-forge/issues/1740) - [PERFORMANCE]: Migrate from psycopg2 to psycopg3 (Psycopg 3)
    - ✅ [**#1750**](https://github.com/IBM/mcp-context-forge/issues/1750) - [PERFORMANCE]: Add PgBouncer Connection Pooling to Docker Compose
    - ✅ [**#1756**](https://github.com/IBM/mcp-context-forge/issues/1756) - [PERFORMANCE]: Move log aggregation percentile computation to SQL
    - ✅ [**#1757**](https://github.com/IBM/mcp-context-forge/issues/1757) - [PERFORMANCE]: Optimize PerformanceTracker percentile calculation
    - ✅ [**#1758**](https://github.com/IBM/mcp-context-forge/issues/1758) - [PERFORMANCE]: Skip auth decoding on tool list endpoints
    - ✅ [**#1760**](https://github.com/IBM/mcp-context-forge/issues/1760) - [PERFORMANCE]: Use bulk UPDATE for token cleanup
    - ✅ [**#1764**](https://github.com/IBM/mcp-context-forge/issues/1764) - [PERFORMANCE]: Move observability and metrics aggregations to SQL
    - ✅ [**#1768**](https://github.com/IBM/mcp-context-forge/issues/1768) - [PERFORMANCE]: Optimize nginx reverse proxy for high-concurrency load testing and move to ubi 10.x
    - ✅ [**#1770**](https://github.com/IBM/mcp-context-forge/issues/1770) - [PERFORMANCE]: Fix db.close() without commit causing unnecessary rollbacks
    - ✅ [**#1773**](https://github.com/IBM/mcp-context-forge/issues/1773) - [PERFORMANCE] Cache get_user_teams() to reduce idle-in-transaction connections
    - ✅ [**#1777**](https://github.com/IBM/mcp-context-forge/issues/1777) - [PERFORMANCE]: Complete has_hooks_for optimization in HTTP middleware
    - ✅ [**#1778**](https://github.com/IBM/mcp-context-forge/issues/1778) - [PERFORMANCE]: Add has_hooks_for optimization to auth and RBAC hook invocations
    - ✅ [**#1799**](https://github.com/IBM/mcp-context-forge/issues/1799) - [PERFORMANCE]: Fix metrics table growth causing performance degradation under sustained load
    - ✅ [**#1806**](https://github.com/IBM/mcp-context-forge/issues/1806) - [PERFORMANCE]: Improve Locust load test client performance for 4000+ concurrent users
    - ✅ [**#1808**](https://github.com/IBM/mcp-context-forge/issues/1808) - [PERFORMANCE]: Reduce CPU cost of detailed request logging
    - ✅ [**#1809**](https://github.com/IBM/mcp-context-forge/issues/1809) - [PERFORMANCE]: Cache JSON Schema validators for tool output validation
    - ✅ [**#1810**](https://github.com/IBM/mcp-context-forge/issues/1810) - [PERFORMANCE]: Move metrics rollup percentiles to SQL (PostgreSQL)
    - ✅ [**#1811**](https://github.com/IBM/mcp-context-forge/issues/1811) - [PERFORMANCE]: Cache compiled regex/parse for resource URI templates
    - ✅ [**#1812**](https://github.com/IBM/mcp-context-forge/issues/1812) - [PERFORMANCE]: Cache JSONPath parsing for jsonpath_modifier and mappings
    - ✅ [**#1813**](https://github.com/IBM/mcp-context-forge/issues/1813) - [PERFORMANCE]: Cache jq filter compilation in extract_using_jq
    - ✅ [**#1814**](https://github.com/IBM/mcp-context-forge/issues/1814) - [PERFORMANCE]: Cache compiled Jinja templates for prompt rendering
    - ✅ [**#1815**](https://github.com/IBM/mcp-context-forge/issues/1815) - [PERFORMANCE]: Avoid double JWT decode and per-request config validation
    - ✅ [**#1816**](https://github.com/IBM/mcp-context-forge/issues/1816) - [PERFORMANCE]: Precompile token scoping regex patterns and permission maps
    - ✅ [**#1817**](https://github.com/IBM/mcp-context-forge/issues/1817) - [PERFORMANCE]: Move admin tool/prompt/resource percentiles to SQL
    - ✅ [**#1818**](https://github.com/IBM/mcp-context-forge/issues/1818) - [PERFORMANCE]: Avoid full scan in ResourceCache cleanup loop
    - ✅ [**#1819**](https://github.com/IBM/mcp-context-forge/issues/1819) - [PERFORMANCE]: Precompile regexes for DB query logging normalization
    - ✅ [**#1820**](https://github.com/IBM/mcp-context-forge/issues/1820) - [PERFORMANCE]: Throttle psutil.net_connections in system metrics
    - ✅ [**#1826**](https://github.com/IBM/mcp-context-forge/issues/1826) - [PERFORMANCE]: Avoid per-window recomputation in log search custom windows
    - ✅ [**#1827**](https://github.com/IBM/mcp-context-forge/issues/1827) - [PERFORMANCE]: Optimize streamable HTTP replay to avoid full deque scans
    - ✅ [**#1828**](https://github.com/IBM/mcp-context-forge/issues/1828) - [PERFORMANCE]: Avoid TimeoutError control flow for SSE keepalives
    - ✅ [**#1829**](https://github.com/IBM/mcp-context-forge/issues/1829) - [PERFORMANCE]: Optimize header mapping extraction to avoid nested scans
    - ✅ [**#1830**](https://github.com/IBM/mcp-context-forge/issues/1830) - [PERFORMANCE]: Precompile regex validators across core validation paths
    - ✅ [**#1831**](https://github.com/IBM/mcp-context-forge/issues/1831) - [PERFORMANCE]: Cache auth/crypto key material and derived objects
    - ✅ [**#1832**](https://github.com/IBM/mcp-context-forge/issues/1832) - [PERFORMANCE]: Transport micro-optimizations (streamable regex + stdio send)
    - ✅ [**#1837**](https://github.com/IBM/mcp-context-forge/issues/1837) - [PERFORMANCE]: Avoid eager f-string logging in hot paths
    - ✅ [**#1838**](https://github.com/IBM/mcp-context-forge/issues/1838) - [PERFORMANCE]: Avoid bytes→str decode in SSE transport serialization
    - ✅ [**#1844**](https://github.com/IBM/mcp-context-forge/issues/1844) - [PERFORMANCE]: Add optional monitoring profile for load testing (Prometheus + Grafana + exporters)
    - ✅ [**#1859**](https://github.com/IBM/mcp-context-forge/issues/1859) - Enable Granian Server Backpressure for Overload Protection
    - ✅ [**#1861**](https://github.com/IBM/mcp-context-forge/issues/1861) - [PERFORMANCE]: PostgreSQL Read Replicas for Horizontal Scaling
    - ✅ [**#1879**](https://github.com/IBM/mcp-context-forge/issues/1879) - [PERFORMANCE]: Fix N+1 Query in list_tools - Missing joinedload for gateway
    - ✅ [**#1880**](https://github.com/IBM/mcp-context-forge/issues/1880) - [PERFORMANCE]: Fix N+1 Query in list_prompts - Missing joinedload for gateway
    - ✅ [**#1881**](https://github.com/IBM/mcp-context-forge/issues/1881) - [PERFORMANCE]: Auth Cache should check L1 (in-memory) before L2 (Redis)
    - ✅ [**#1883**](https://github.com/IBM/mcp-context-forge/issues/1883) - [PERFORMANCE]: Fix remaining N+1 queries in list_servers, list_agents, and gateway sync
    - ✅ [**#1887**](https://github.com/IBM/mcp-context-forge/issues/1887) - [PERFORMANCE]: Combine double DB sessions in token_scoping middleware
    - ✅ [**#1888**](https://github.com/IBM/mcp-context-forge/issues/1888) - [PERFORMANCE]: Cache team membership validation in token_scoping middleware
    - ✅ [**#1891**](https://github.com/IBM/mcp-context-forge/issues/1891) - [PERFORMANCE]: execution_count property causes N+1 by loading all metrics into memory
    - ✅ [**#1892**](https://github.com/IBM/mcp-context-forge/issues/1892) - [PERFORMANCE]: N+1 query pattern in EmailTeam.get_member_count()
    - ✅ [**#1893**](https://github.com/IBM/mcp-context-forge/issues/1893) - [PERFORMANCE]: Add partial index for team member count queries
    - ✅ [**#1897**](https://github.com/IBM/mcp-context-forge/issues/1897) - [PERFORMANCE]: MCP client connection exhaustion under high concurrency - configurable httpx limits
    - ✅ [**#1908**](https://github.com/IBM/mcp-context-forge/issues/1908) - [PERFORMANCE]: Add Rust MCP Test Server for Performance Testing
    - ✅ [**#1918**](https://github.com/IBM/mcp-context-forge/issues/1918) - [Performance] Implement MCP client session pooling to reduce per-request overhead (optional)
    - ✅ [**#1940**](https://github.com/IBM/mcp-context-forge/issues/1940) - [PERFORMANCE]: Cache tool lookups by name (L1 memory + L2 Redis)
    - ✅ [**#1944**](https://github.com/IBM/mcp-context-forge/issues/1944) - [PERFORMANCE]: Add TEMPLATES_AUTO_RELOAD setting
    - ✅ [**#1946**](https://github.com/IBM/mcp-context-forge/issues/1946) - [PERFORMANCE]: Add nginx caching for admin pages with multi-tenant isolation
    - ✅ [**#1962**](https://github.com/IBM/mcp-context-forge/issues/1962) - [PERFORMANCE]: Fix N+1 queries in single-entity retrieval functions (get_server, get_gateway, etc.)
    - ✅ [**#1964**](https://github.com/IBM/mcp-context-forge/issues/1964) - [PERFORMANCE]: Fix N+1 queries for team name lookups in tool_service
    - ✅ [**#1994**](https://github.com/IBM/mcp-context-forge/issues/1994) - [PERFORMANCE]: Fix N+1 queries in Gateway single-entity retrieval functions
    - ✅ [**#1996**](https://github.com/IBM/mcp-context-forge/issues/1996) - [PERFORMANCE]: Health check endpoints should explicitly commit to release PgBouncer connections
    - ✅ [**#2010**](https://github.com/IBM/mcp-context-forge/issues/2010) - [PERFORMANCE]: Plugin manager re-initialized on every request instead of once per worker
    - ✅ [**#2030**](https://github.com/IBM/mcp-context-forge/issues/2030) - [PERFORMANCE]: Migrate remaining stdlib json usage to orjson
    - ✅ [**#2033**](https://github.com/IBM/mcp-context-forge/issues/2033) - [PERFORMANCE]: Replace blocking MCP session health check with lightweight ping or remove
    - ✅ [**#2061**](https://github.com/IBM/mcp-context-forge/issues/2061) - [PERFORMANCE]: Add performance test profiling and guideline for plugins
    - ✅ [**#2064**](https://github.com/IBM/mcp-context-forge/issues/2064) - [PERFORMANCE]: Remove exc_info=True from Plugin Manager critical path
    - ✅ [**#2084**](https://github.com/IBM/mcp-context-forge/issues/2084) - [PERFORMANCE]: Logging overhead in plugin manager
    - ✅ [**#2113**](https://github.com/IBM/mcp-context-forge/issues/2113) - [PERFORMANCE]: Replace stdlib json with orjson for consistency and performance
    - ✅ [**#2160**](https://github.com/IBM/mcp-context-forge/issues/2160) - [PERFORMANCE]: Double token scoping for /mcp requests when email_auth_enabled=True
    - ✅ [**#2164**](https://github.com/IBM/mcp-context-forge/issues/2164) - [PERFORMANCE]: Use async I/O instead of blocking calls in async functions (S7493, S7487)
    - ✅ [**#1865**](https://github.com/IBM/mcp-context-forge/issues/1865) - [PERFORMANCE]: Logging CPU optimization
    - ✅ [**#2318**](https://github.com/IBM/mcp-context-forge/issues/2318) - [PERFORMANCE]: RBAC middleware holds DB sessions for entire request lifecycle causing pool exhaustion
    - ✅ [**#2355**](https://github.com/IBM/mcp-context-forge/issues/2355) - [PERFORMANCE]: Fix FOR UPDATE lock contention and CPU spin loops under high load

???+ check "🐛 Bugs - Completed (95)"

    - ✅ [**#840**](https://github.com/IBM/mcp-context-forge/issues/840) - [Bug]: For A2A Agent test not working
    - ✅ [**#1047**](https://github.com/IBM/mcp-context-forge/issues/1047) - [Bug]: MCP Server/Federated Gateway Registration is failing
    - ✅ [**#1108**](https://github.com/IBM/mcp-context-forge/issues/1108) - [Bug]: When using postgresql as database, high postgresql transaction rollback rate detected
    - ✅ [**#1357**](https://github.com/IBM/mcp-context-forge/issues/1357) - [Bug]: Claude Desktop is getting invalid type from mcp-context-forge gateway
    - ✅ [**#1415**](https://github.com/IBM/mcp-context-forge/issues/1415) - [Bug]: SettingsError raised when parsing environment variable observability_exclude_paths in Pydantic settings
    - ✅ [**#1423**](https://github.com/IBM/mcp-context-forge/issues/1423) - [Bug]: The Helm deployment encounters an error, causing the pod to restart.
    - ✅ [**#1440**](https://github.com/IBM/mcp-context-forge/issues/1440) - [Bug]: Trying to register ZGithub Remote MCP server but tools are not discoverable
    - ✅ [**#1463**](https://github.com/IBM/mcp-context-forge/issues/1463) - [Bug]: No cursors are displayed at the selected input text fields on UI
    - ✅ [**#1465**](https://github.com/IBM/mcp-context-forge/issues/1465) - [Bug]: Not able to build Gateway with existing Postgres DB
    - ✅ [**#1486**](https://github.com/IBM/mcp-context-forge/issues/1486) - [Bug]: team_id from token can be a dict
    - ✅ [**#1497**](https://github.com/IBM/mcp-context-forge/issues/1497) - [Bug]: Toggling a resource makes it invisible
    - ✅ [**#1501**](https://github.com/IBM/mcp-context-forge/issues/1501) - Non-admin cannot create a api token.
    - ✅ [**#1508**](https://github.com/IBM/mcp-context-forge/issues/1508) - [Bug]: Cannot invoke Virtual Server tools using LangChain
    - ✅ [**#1526**](https://github.com/IBM/mcp-context-forge/issues/1526) - [Bug]: start in docker, get error
    - ✅ [**#1530**](https://github.com/IBM/mcp-context-forge/issues/1530) - [Bug]: PassThrough Header configuration seems to be broken through environment variables.
    - ✅ [**#1533**](https://github.com/IBM/mcp-context-forge/issues/1533) - [Bug]: Encoded DATABASE_URL causes configparser interpolation error
    - ✅ [**#1539**](https://github.com/IBM/mcp-context-forge/issues/1539) - [Bug]: HTTPS MCP Servers with Self signed certificate not working
    - ✅ [**#1549**](https://github.com/IBM/mcp-context-forge/issues/1549) - Spring MCP Server connecting to MCP gateway 0.9.0 facing JVM OutOfMemoryError despite limited number of requests
    - ✅ [**#1576**](https://github.com/IBM/mcp-context-forge/issues/1576) - [Bug]: Rest API with text based response not working
    - ✅ [**#1581**](https://github.com/IBM/mcp-context-forge/issues/1581) - [Bug]: AMD64-v3 Compatibility Issue on Apple Silicon
    - ✅ [**#1582**](https://github.com/IBM/mcp-context-forge/issues/1582) - [Bug]: Tool Visibility Not Honoring Gateway Visibility
    - ✅ [**#1583**](https://github.com/IBM/mcp-context-forge/issues/1583) - [Bug]: Non-expiring password (or ability to change password via API)
    - ✅ [**#1633**](https://github.com/IBM/mcp-context-forge/issues/1633) - [Bug]: External plugin does not start from docker automatically
    - ✅ [**#1643**](https://github.com/IBM/mcp-context-forge/issues/1643) - [Bug]: POST /admin/users not using is_admin flag and creating users as non admin by default
    - ✅ [**#1644**](https://github.com/IBM/mcp-context-forge/issues/1644) - [Bug]: POST /admin/teams/{team_id}/add-member requires teams.write permission eventhough I am owner of team
    - ✅ [**#1653**](https://github.com/IBM/mcp-context-forge/issues/1653) - [Bug]: Login returns 500 and no token when password change is required (ContextForge 1.0.0-BETA-1)
    - ✅ [**#1663**](https://github.com/IBM/mcp-context-forge/issues/1663) - [Bug]: PostgreSQL: User deletion fails with foreign key constraint violation on email_team_member_history
    - ✅ [**#1664**](https://github.com/IBM/mcp-context-forge/issues/1664) - [Bug]: Cannot retrieve tools by gateway_id when total tools exceed 50
    - ✅ [**#1706**](https://github.com/IBM/mcp-context-forge/issues/1706) - DB connection pool exhaustion: sessions held during upstream HTTP calls
    - ✅ [**#1707**](https://github.com/IBM/mcp-context-forge/issues/1707) - [Bug]: All servers in LLM Chat are tagged as inactive even if active
    - ✅ [**#1719**](https://github.com/IBM/mcp-context-forge/issues/1719) - Fix HTTP error codes and improve nginx performance for high-concurrency load tests
    - ✅ [**#1725**](https://github.com/IBM/mcp-context-forge/issues/1725) - [Bug]: LLM Settings does not support provider-specific configuration parameters
    - ✅ [**#1742**](https://github.com/IBM/mcp-context-forge/issues/1742) - [Bug]: When creating a token in the UI page, regardless of the number of days selected for validity, it defaults to 7 days.
    - ✅ [**#1762**](https://github.com/IBM/mcp-context-forge/issues/1762) - [BUG]: Prompt Namespacing + Name/ID Resolution (Tool-Parity)
    - ✅ [**#1787**](https://github.com/IBM/mcp-context-forge/issues/1787) - [Bug]: Fullscreen mode in resource test quickly vanishes back to resource table on first attempt
    - ✅ [**#1788**](https://github.com/IBM/mcp-context-forge/issues/1788) - Observability / Advanced Metrics graphs disappear with Chart.js canvas reuse error
    - ✅ [**#1792**](https://github.com/IBM/mcp-context-forge/issues/1792) - [Bug]: JWT_AUDIENCE_VERIFICATION=false does not disable issuer validation
    - ✅ [**#1841**](https://github.com/IBM/mcp-context-forge/issues/1841) - [BUG]: email_auth router swallows HTTPException and returns 500 for all errors
    - ✅ [**#1842**](https://github.com/IBM/mcp-context-forge/issues/1842) - Bug: API password change endpoint does not clear password_change_required flag
    - ✅ [**#1850**](https://github.com/IBM/mcp-context-forge/issues/1850) - Inconsistent component names in request_logging_middleware structured logs
    - ✅ [**#1875**](https://github.com/IBM/mcp-context-forge/issues/1875) - [Bug]: Tool import fails for deeply nested schemas; VALIDATION_MAX_JSON_DEPTH environment variable ineffective
    - ✅ [**#1877**](https://github.com/IBM/mcp-context-forge/issues/1877) - PgBouncer client_idle_timeout errors not recognized as disconnects
    - ✅ [**#1885**](https://github.com/IBM/mcp-context-forge/issues/1885) - [BUG]: Database connections stuck in 'idle in transaction' under load
    - ✅ [**#1896**](https://github.com/IBM/mcp-context-forge/issues/1896) - [BUG]: Locust load tests miss JSON-RPC errors - reports false success rate
    - ✅ [**#1902**](https://github.com/IBM/mcp-context-forge/issues/1902) - Unwrap ExceptionGroup in tool invocation errors to show root cause
    - ✅ [**#1912**](https://github.com/IBM/mcp-context-forge/issues/1912) - [Bug]: Cleanup unused Federation module and duplicate Forwarding logic
    - ✅ [**#1913**](https://github.com/IBM/mcp-context-forge/issues/1913) - [Bug]: ARM64 Support is broken with the latest release
    - ✅ [**#1914**](https://github.com/IBM/mcp-context-forge/issues/1914) - [Bug]: Platform admin is forced to change password on every login (Password Change Required never clears)
    - ✅ [**#1915**](https://github.com/IBM/mcp-context-forge/issues/1915) - [Bug]: SSE and /mcp list paths ignore visibility filters for MCP resources
    - ✅ [**#1916**](https://github.com/IBM/mcp-context-forge/issues/1916) - [Bug]: Required form fields trap focus and block navigation on blur
    - ✅ [**#1925**](https://github.com/IBM/mcp-context-forge/issues/1925) - Implement MCP Session Pool Isolation Verification Tests
    - ✅ [**#1929**](https://github.com/IBM/mcp-context-forge/issues/1929) - Optimize aiohttp: Replace per-request ClientSession with shared singleton in DCR and OAuth services
    - ✅ [**#1931**](https://github.com/IBM/mcp-context-forge/issues/1931) - Optimize OPA plugin: Replace synchronous requests with async httpx client
    - ✅ [**#1934**](https://github.com/IBM/mcp-context-forge/issues/1934) - Admin UI: close read transactions before rendering to avoid idle-in-transaction timeouts
    - ✅ [**#1937**](https://github.com/IBM/mcp-context-forge/issues/1937) - [Bug]: MCP tools/list returns only ~50 tools instead of all registered tools
    - ✅ [**#1948**](https://github.com/IBM/mcp-context-forge/issues/1948) - Admin UI /admin/events SSE stream times out when idle
    - ✅ [**#1956**](https://github.com/IBM/mcp-context-forge/issues/1956) - [Bug]: New A2A Agent Tools Missing Team ID
    - ✅ [**#1966**](https://github.com/IBM/mcp-context-forge/issues/1966) - HTMX partial endpoints ignore team_id filters for tools/resources/prompts
    - ✅ [**#1987**](https://github.com/IBM/mcp-context-forge/issues/1987) - OAuth/DCR services: Connection pooling not fully effective due to per-request instantiation
    - ✅ [**#2002**](https://github.com/IBM/mcp-context-forge/issues/2002) - [Bug]: Unable to authenticate and use Basic Auth and X-API-Key A2A agents
    - ✅ [**#2018**](https://github.com/IBM/mcp-context-forge/issues/2018) - [BUG]: REST /tools list endpoint returns stale visibility data after tool update
    - ✅ [**#2031**](https://github.com/IBM/mcp-context-forge/issues/2031) - [Bug]: Token Usage Statistics in Admin UI Always Null / Zero
    - ✅ [**#2044**](https://github.com/IBM/mcp-context-forge/issues/2044) - [Bug]: Low contrast on Plugin management card in dark mode
    - ✅ [**#2055**](https://github.com/IBM/mcp-context-forge/issues/2055) - [Bug]: MCP session pool allows state leakage between Gateway users
    - ✅ [**#2058**](https://github.com/IBM/mcp-context-forge/issues/2058) - [Bug]: Advanced metrics tables have low readability.
    - ✅ [**#2068**](https://github.com/IBM/mcp-context-forge/issues/2068) - Observability: restrict tracing to MCP/A2A endpoints and honor observability_exclude_paths
    - ✅ [**#2072**](https://github.com/IBM/mcp-context-forge/issues/2072) - [Bug]: MCP Registry "Add Server" button behaviour is inconsistent
    - ✅ [**#2073**](https://github.com/IBM/mcp-context-forge/issues/2073) - [Bug]: Buttons are cluttered on the MCP Servers table's Action column
    - ✅ [**#2077**](https://github.com/IBM/mcp-context-forge/issues/2077) - [Bug]: Action buttons hidden by horizontal scroll in server tables
    - ✅ [**#2080**](https://github.com/IBM/mcp-context-forge/issues/2080) - [Bug]: Clicking the Show Inactive toggle won't update the table
    - ✅ [**#2094**](https://github.com/IBM/mcp-context-forge/issues/2094) - feat: Support _meta field propagation in MCP tool calls
    - ✅ [**#2096**](https://github.com/IBM/mcp-context-forge/issues/2096) - [Bug]: Incorrect Alembic migration placement and history: a8f3b2c1d4e5 & c96c11c111b4
    - ✅ [**#2103**](https://github.com/IBM/mcp-context-forge/issues/2103) - [Bug]: Issues identified in several native plugins
    - ✅ [**#2108**](https://github.com/IBM/mcp-context-forge/issues/2108) - [Bug]: Pagination is broken on Admin UI tables
    - ✅ [**#2111**](https://github.com/IBM/mcp-context-forge/issues/2111) - [Bug]: Clicking the Show Inactive toggle won't update the table - Remaining tables
    - ✅ [**#2121**](https://github.com/IBM/mcp-context-forge/issues/2121) - [Bug]: On table views, initializeSearchInputs() is called recurrently
    - ✅ [**#2134**](https://github.com/IBM/mcp-context-forge/issues/2134) - [Bug]: docker-compose.yaml nginx_cache volume mount conflicts with Dockerfile COPY
    - ✅ [**#2137**](https://github.com/IBM/mcp-context-forge/issues/2137) - [Bug]: Alembic versions file in wrong location
    - ✅ [**#2142**](https://github.com/IBM/mcp-context-forge/issues/2142) - [QUESTION]: Missing psycopg2 module in latest Docker image -> migrated to psycopg3
    - ✅ [**#2149**](https://github.com/IBM/mcp-context-forge/issues/2149) - OAuth providers return opaque tokens instead of JWT tokens, causing verification failures
    - ✅ [**#2152**](https://github.com/IBM/mcp-context-forge/issues/2152) - [Bug]: CORS preflight OPTIONS requests return 401 on /mcp endpoints
    - ✅ [**#2172**](https://github.com/IBM/mcp-context-forge/issues/2172) - [Bug]: Single entity parsing failure stops entire listing operation
    - ✅ [**#2182**](https://github.com/IBM/mcp-context-forge/issues/2182) - [Bug]: Metrics flickering on
    - ✅ [**#2183**](https://github.com/IBM/mcp-context-forge/issues/2183) - [Bug]: team_id is none in rbac.py when a non-admin makes an API call to list gateways
    - ✅ [**#2203**](https://github.com/IBM/mcp-context-forge/issues/2203) - [Bug]: Tags for MCP servers not saved
    - ✅ [**#2212**](https://github.com/IBM/mcp-context-forge/issues/2212) - [Bug]: Gateway activation/deactivation does not update prompts and resources
    - ✅ [**#2213**](https://github.com/IBM/mcp-context-forge/issues/2213) - [Bug]: Pagination controls mix up query params across different tables
    - ✅ [**#2251**](https://github.com/IBM/mcp-context-forge/issues/2251) - [Bug]: Cannot deactivate virtual server
    - ✅ [**#2254**](https://github.com/IBM/mcp-context-forge/issues/2254) - [Bug]: HTTP export config gives wrong type value
    - ✅ [**#2262**](https://github.com/IBM/mcp-context-forge/issues/2262) - [Bug]: A2A agent GET /a2a returns 422 due to tags field type mismatch
    - ✅ [**#2267**](https://github.com/IBM/mcp-context-forge/issues/2267) - [Bug]: Incorrect tag rendering in admin views
    - ✅ [**#2322**](https://github.com/IBM/mcp-context-forge/issues/2322) - [Bug]: Few MCP servers are not supported due to tool schema validation
    - ✅ [**#2341**](https://github.com/IBM/mcp-context-forge/issues/2341) - [Bug]: MCP CF crashes while listing tools from moody's mcp server
    - ✅ [**#2352**](https://github.com/IBM/mcp-context-forge/issues/2352) - [Bug]: Multiple gateway import failing with inactive transaction during async cleanup
    - ✅ [**#2362**](https://github.com/IBM/mcp-context-forge/issues/2362) - [Bug]: Export Config button missing from Virtual Servers table

???+ check "🔒 Security - Completed (6)"

    - ✅ [**#2106**](https://github.com/IBM/mcp-context-forge/issues/2106) - [SECURITY]: Admin UI endpoints missing @require_permission checks
    - ✅ [**#2125**](https://github.com/IBM/mcp-context-forge/issues/2125) - [SECURITY]: MCP authentication controls and team membership validation
    - ✅ [**#2127**](https://github.com/IBM/mcp-context-forge/issues/2127) - [SECURITY]: Enhanced JWT Token Lifecycle Management
    - ✅ [**#2128**](https://github.com/IBM/mcp-context-forge/issues/2128) - [SECURITY]: Add REQUIRE_USER_IN_DB Configuration Option
    - ✅ [**#2141**](https://github.com/IBM/mcp-context-forge/issues/2141) - [SECURITY]: Add environment isolation warnings and optional environment claim validation
    - ✅ [**#2156**](https://github.com/IBM/mcp-context-forge/issues/2156) - [SECURITY]: LLM Guard - Replace unsafe code execution with safe AST evaluator and switch to orjson serialization

???+ check "🔧 Chores - Completed (6)"

    - ✅ [**#1606**](https://github.com/IBM/mcp-context-forge/issues/1606) - refactor(plugin_template): update MCP runtime in plugins template
    - ✅ [**#1743**](https://github.com/IBM/mcp-context-forge/issues/1743) - Add AUDIT_TRAIL_ENABLED flag to disable audit trail logging for performance
    - ✅ [**#1933**](https://github.com/IBM/mcp-context-forge/issues/1933) - [CHORE]: Add field focus out validation to forms
    - ✅ [**#2166**](https://github.com/IBM/mcp-context-forge/issues/2166) - [CHORE]: Fix regex empty match and clean up docstring examples (S5842, S6739)
    - ✅ [**#2190**](https://github.com/IBM/mcp-context-forge/issues/2190) - [CHORE]: Replace echo /etc/passwd with useradd in Containerfile.lite
    - ✅ [**#2209**](https://github.com/IBM/mcp-context-forge/issues/2209) - [CHORE] Only build non-amd64 architectures on main branch, not PRs

???+ check "📚 Documentation - Completed (1)"

    - ✅ [**#916**](https://github.com/IBM/mcp-context-forge/issues/916) - Document monday.com MCP Server integration with ContextForge

---


## Release 1.0.0-BETA-1

!!! success "Release 1.0.0-BETA-1 - Completed (100%)"
    **Due:** 16 Dec 2025 | **Status:** Closed
    Release 1.0.0-BETA-1

???+ check "📋 Epics - Completed (1)"

    - ✅ [**#1401**](https://github.com/IBM/mcp-context-forge/issues/1401) - 📊 Epic: Internal Observability System - Performance Monitoring & Trace Analytics

???+ check "✨ Features - Completed (25)"

    - ✅ [**#80**](https://github.com/IBM/mcp-context-forge/issues/80) - [Feature Request]: Publish a multi-architecture container (including ARM64) support
    - ✅ [**#288**](https://github.com/IBM/mcp-context-forge/issues/288) - [Feature Request]: MariaDB Support Testing, Documentation, CI/CD (alongside PostgreSQL & SQLite) *(deprecated — MySQL/MariaDB support removed)*
    - ✅ [**#898**](https://github.com/IBM/mcp-context-forge/issues/898) - Sample MCP Server - Go (system-monitor-server)
    - ✅ [**#932**](https://github.com/IBM/mcp-context-forge/issues/932) - [Feature Request]: Air-Gapped Environment Support
    - ✅ [**#1019**](https://github.com/IBM/mcp-context-forge/issues/1019) - [Feature] Authentication Architecture through Plugin System
    - ✅ [**#1138**](https://github.com/IBM/mcp-context-forge/issues/1138) - [Feature Request]: Support for container builds for s390x
    - ✅ [**#1161**](https://github.com/IBM/mcp-context-forge/issues/1161) - [FEATURE REQUEST]: Add Roundtable External MCP Server for Enterprise AI Assistant Orchestration
    - ✅ [**#1171**](https://github.com/IBM/mcp-context-forge/issues/1171) - [Feature]: gRPC-to-MCP Protocol Translation
    - ✅ [**#1188**](https://github.com/IBM/mcp-context-forge/issues/1188) - [Feature Request]: Allow multiple StreamableHTTP content
    - ✅ [**#1203**](https://github.com/IBM/mcp-context-forge/issues/1203) - [Feature]: Performance Testing & Benchmarking Framework
    - ✅ [**#1211**](https://github.com/IBM/mcp-context-forge/issues/1211) - [Feature Request]: Authentication & Authorization - Microsoft Entra ID Integration Support and Tutorial (Depends on #220)
    - ✅ [**#1213**](https://github.com/IBM/mcp-context-forge/issues/1213) - Generic OIDC Provider Support via Environment Variables
    - ✅ [**#1216**](https://github.com/IBM/mcp-context-forge/issues/1216) - Keycloak Integration Support with Environment Variables
    - ✅ [**#1219**](https://github.com/IBM/mcp-context-forge/issues/1219) - [Feature]: Benchmark MCP Server for Load Testing and Performance Analysis
    - ✅ [**#1227**](https://github.com/IBM/mcp-context-forge/issues/1227) - [Feature Request]: Run in production environments with stricter security policies.
    - ✅ [**#1253**](https://github.com/IBM/mcp-context-forge/issues/1253) - Add CI/CD Verification for Complete Build Pipeline
    - ✅ [**#1282**](https://github.com/IBM/mcp-context-forge/issues/1282) - [Feature]🔐 Configurable Password Expiration with Forced Password Change on Login
    - ✅ [**#1364**](https://github.com/IBM/mcp-context-forge/issues/1364) - [Feature Request]: Add Support for Self-Signed Certificates in ContextForge
    - ✅ [**#1387**](https://github.com/IBM/mcp-context-forge/issues/1387) - [Feature Request]: Support One-Time Authentication Mode for WXO Integration
    - ✅ [**#1392**](https://github.com/IBM/mcp-context-forge/issues/1392) - Feature Request: Allow Multiple ContextForge Registrations with the Same Gateway URL
    - ✅ [**#1399**](https://github.com/IBM/mcp-context-forge/issues/1399) - Coolify Deployment Certificate Issues - Analysis & Resolution
    - ✅ [**#1409**](https://github.com/IBM/mcp-context-forge/issues/1409) - [Feature Request]: Filtering by gateway ID in the List Tools API
    - ✅ [**#1442**](https://github.com/IBM/mcp-context-forge/issues/1442) - [Feature Request]: Modify Tool Tag Structure from Array of Strings to List of Objects
    - ✅ [**#1503**](https://github.com/IBM/mcp-context-forge/issues/1503) - [Feature Request]: Add additional uv examples to README (Windows Powershell example)
    - ✅ [**#1560**](https://github.com/IBM/mcp-context-forge/issues/1560) - [Feature Request]: Test Button for Resource

???+ check "🐛 Bugs - Completed (45)"

    - ✅ [**#464**](https://github.com/IBM/mcp-context-forge/issues/464) - [Bug]: MCP Server "Active" status not getting updated under "Gateways/MCP Servers" when the MCP Server shutdown
    - ✅ [**#1143**](https://github.com/IBM/mcp-context-forge/issues/1143) - [Bug]: Adding any server in MCP Registry fails.
    - ✅ [**#1180**](https://github.com/IBM/mcp-context-forge/issues/1180) - [Bug]: Edit prompt does not send team_id in form data
    - ✅ [**#1184**](https://github.com/IBM/mcp-context-forge/issues/1184) - [Bug]: Update Prompt and Resource endpoints to use unique IDs instead of name or uri
    - ✅ [**#1190**](https://github.com/IBM/mcp-context-forge/issues/1190) - [Bug]: In 0.7.0 Accessing Virtual MCP server requires OAUTH, earlier it worked with JWT
    - ✅ [**#1193**](https://github.com/IBM/mcp-context-forge/issues/1193) - [Bug]: Auth-REQUIRED=false does not work
    - ✅ [**#1230**](https://github.com/IBM/mcp-context-forge/issues/1230) - [Bug]: Current pyproject.toml configuration of optional project components contains conflicting components that need to be resolved for uv.
    - ✅ [**#1259**](https://github.com/IBM/mcp-context-forge/issues/1259) - [Bug]: MCP Resource is not getting listed
    - ✅ [**#1278**](https://github.com/IBM/mcp-context-forge/issues/1278) - [Bug]: https mcp servers with self signed certificate not able to add
    - ✅ [**#1280**](https://github.com/IBM/mcp-context-forge/issues/1280) - [Bug] Non-standard redirect handling in _validate_gateway_url for STREAMABLEHTTP transport
    - ✅ [**#1287**](https://github.com/IBM/mcp-context-forge/issues/1287) - [Bug]: Unable to use sso service with corporate CA
    - ✅ [**#1317**](https://github.com/IBM/mcp-context-forge/issues/1317) - [Bug]: API Token Expiries at 7 days even if we select expiry at 365 days
    - ✅ [**#1319**](https://github.com/IBM/mcp-context-forge/issues/1319) - [Bug]: Export virtual server configuration URL not respecting APP_ROOT_PATH
    - ✅ [**#1321**](https://github.com/IBM/mcp-context-forge/issues/1321) - [Bug]: Created date shows as Invalid Date in API Tokens list
    - ✅ [**#1327**](https://github.com/IBM/mcp-context-forge/issues/1327) - [Bug]: iFrame context-forge giving error "ancestor violates Content Security Policy directive"
    - ✅ [**#1328**](https://github.com/IBM/mcp-context-forge/issues/1328) - [Bug]: Output validation error: outputSchema defined but no structured output returned when not setting any output schema.
    - ✅ [**#1351**](https://github.com/IBM/mcp-context-forge/issues/1351) - __init__ in root directory - Huh?
    - ✅ [**#1370**](https://github.com/IBM/mcp-context-forge/issues/1370) - [Bug]: Configured Custom Headers do not show up when editing MCP servers
    - ✅ [**#1395**](https://github.com/IBM/mcp-context-forge/issues/1395) - [Bug]: tool schema team_id not effective
    - ✅ [**#1406**](https://github.com/IBM/mcp-context-forge/issues/1406) - [Bug]: Missing Structured Content for Virtual Server in Streamable HTTP Response
    - ✅ [**#1447**](https://github.com/IBM/mcp-context-forge/issues/1447) - [Bug]: UI bug in the Metrics Tab, The Navigate page for Tools tab bottom starts from page 66 instead of 1
    - ✅ [**#1448**](https://github.com/IBM/mcp-context-forge/issues/1448) - [Bug]: One time auth restricts addition of multiple gateways with same URL since the Auth is None
    - ✅ [**#1451**](https://github.com/IBM/mcp-context-forge/issues/1451) - [Bug]: Bug in Plugin Tab of ContextForge - Gateway Administration, PIIFilterPlugin is Enabled but doesn't mask email id and Phone number
    - ✅ [**#1452**](https://github.com/IBM/mcp-context-forge/issues/1452) - [Bug]: Issues Identified in MCP Server Admin UI
    - ✅ [**#1453**](https://github.com/IBM/mcp-context-forge/issues/1453) - [Bug]: Gateway creation under team scope returns team id as Null
    - ✅ [**#1462**](https://github.com/IBM/mcp-context-forge/issues/1462) - [Bug]: TARGETPLATFORM argument not always populated depending on container runtime during build
    - ✅ [**#1464**](https://github.com/IBM/mcp-context-forge/issues/1464) - [Bug]: no cursor is displayed at the text input fields
    - ✅ [**#1467**](https://github.com/IBM/mcp-context-forge/issues/1467) - [Bug]: Resource cache not invalidated when gateway deleted
    - ✅ [**#1485**](https://github.com/IBM/mcp-context-forge/issues/1485) - [Bug]: Tool name update silently fails
    - ✅ [**#1495**](https://github.com/IBM/mcp-context-forge/issues/1495) - [Bug]: Context set from one hook is not available in another hook
    - ✅ [**#1506**](https://github.com/IBM/mcp-context-forge/issues/1506) - [Bug]: Centralized Event Service for Multi-Worker Environments for all services
    - ✅ [**#1517**](https://github.com/IBM/mcp-context-forge/issues/1517) - [Bug]: SQLite-specific json_extract() breaks PostgreSQL observability queries
    - ✅ [**#1522**](https://github.com/IBM/mcp-context-forge/issues/1522) - [Bug]: Implement Concurrent Health Checks for gateways instead of sequential
    - ✅ [**#1523**](https://github.com/IBM/mcp-context-forge/issues/1523) - [Bug]: Severe Performance Degradation Due to N+1 Queries and Non-Batch Operations in Gateway/Tool/Server Services
    - ✅ [**#1540**](https://github.com/IBM/mcp-context-forge/issues/1540) - [Bug]: Adding MCP Servers failing in 0.9.0
    - ✅ [**#1542**](https://github.com/IBM/mcp-context-forge/issues/1542) - [Bug]: Fetching Tools From MCP lacks logs
    - ✅ [**#1544**](https://github.com/IBM/mcp-context-forge/issues/1544) - [Bug]: "Show Inactive" toggle missing in Virtual Servers tab in Admin UI
    - ✅ [**#1545**](https://github.com/IBM/mcp-context-forge/issues/1545) - [Bug]: HTTP 404 When Editing Inactive Resource from Admin UI
    - ✅ [**#1550**](https://github.com/IBM/mcp-context-forge/issues/1550) - [Bug]: app_user_email not propagated to plugin global context if a context already exists
    - ✅ [**#1553**](https://github.com/IBM/mcp-context-forge/issues/1553) - [Bug]: When I define a tag on an MCP Server tool invocation fails
    - ✅ [**#1566**](https://github.com/IBM/mcp-context-forge/issues/1566) - [Bug]: Admin Search Lacks Gateway-Based Filtering & Virtual Server Selection Does Not Persist
    - ✅ [**#1572**](https://github.com/IBM/mcp-context-forge/issues/1572) - [Bug]: When attempting to delete a virtual server that is not found - it returns wrong status code
    - ✅ [**#1577**](https://github.com/IBM/mcp-context-forge/issues/1577) - [Bug]: Support for Passphrase Protected SSL Keys in HTTPS Configuration for Gunicorn/Uvicorn
    - ✅ [**#1596**](https://github.com/IBM/mcp-context-forge/issues/1596) - [Bug]: Users api should use get_current_user_with_permissions
    - ✅ [**#1602**](https://github.com/IBM/mcp-context-forge/issues/1602) - [Bug]: Get Call to /version api resulting in 500 Internal error

???+ check "🔒 Security - Completed (1)"

    - ✅ [**#221**](https://github.com/IBM/mcp-context-forge/issues/221) - [SECURITY FEATURE]: Gateway-Level Input Validation & Output Sanitization (prevent traversal)

???+ check "🔧 Chores - Completed (3)"

    - ✅ [**#806**](https://github.com/IBM/mcp-context-forge/issues/806) - [CHORE]: Bulk Import – Missing error messages and registration feedback in UI
    - ✅ [**#1461**](https://github.com/IBM/mcp-context-forge/issues/1461) - [CHORE]: Multiple virtual environments created mean certain make tasks do not work as expected locally and potentially in cicd flows
    - ✅ [**#1505**](https://github.com/IBM/mcp-context-forge/issues/1505) - [CHORE]: Standardize Active-State Field Names and Add UUID Support for Prompts & Resources

???+ check "📚 Documentation - Completed (2)"

    - ✅ [**#1159**](https://github.com/IBM/mcp-context-forge/issues/1159) - [Docs]: Several minor quirks in main README.md
    - ✅ [**#1512**](https://github.com/IBM/mcp-context-forge/issues/1512) - [Docs]: "end-to-end" demo instructions outdated in README

???+ check "🧪 Tests - Completed (1)"

    - ✅ [**#1418**](https://github.com/IBM/mcp-context-forge/issues/1418) - [Test]: QA Plan for Shortlist of Plugins

---


## Release 0.9.0

!!! success "Release 0.9.0 - Completed (100%)"
    **Due:** 04 Nov 2025 | **Status:** Closed
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
    - ✅ [**#1111**](https://github.com/IBM/mcp-context-forge/issues/1111) - [Feature Request]: Support application/x-www-form-urlencoded Requests in ContextForge UI for OAuth2 / Keycloak Integration
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
    - ✅ [**#1109**](https://github.com/IBM/mcp-context-forge/issues/1109) - [Bug]:ContextForge UI OAuth2 Integration Fails with Keycloak Due to Missing x-www-form-urlencoded Support
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
    - ✅ [**#925**](https://github.com/IBM/mcp-context-forge/issues/925) - Add MySQL database support to ContextForge *(deprecated — MySQL/MariaDB support removed)*
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
    - ✅ [**#364**](https://github.com/IBM/mcp-context-forge/issues/364) - [Feature Request]: Add Log File Support to ContextForge
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
    - ✅ [**#424**](https://github.com/IBM/mcp-context-forge/issues/424) - [Bug]: ContextForge Doesn't Detect HTTPS/TLS Context or respect X-Forwarded-Proto when using Federation
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
    - ✅ [**#279**](https://github.com/IBM/mcp-context-forge/issues/279) - [CHORE]: Implement container vulnerability review in Makefile and GitHub Actions
    - ✅ [**#249**](https://github.com/IBM/mcp-context-forge/issues/249) - [CHORE]: Achieve 60% doctest coverage and add Makefile and CI/CD targets for doctest and coverage
    - ✅ [**#210**](https://github.com/IBM/mcp-context-forge/issues/210) - [CHORE]: Raise pylint from 9.16/10 -> 10/10

???+ check "📚 Completed Documentation (3)"

    - ✅ [**#522**](https://github.com/IBM/mcp-context-forge/issues/522) - [Docs]: Fix OpenAPI title to use ContextForge
    - ✅ [**#376**](https://github.com/IBM/mcp-context-forge/issues/376) - [Docs]: Document Security Policy in GitHub Pages and Link Roadmap on Homepage
    - ✅ [**#46**](https://github.com/IBM/mcp-context-forge/issues/46) - [Docs]: Add documentation for using mcp-cli with ContextForge

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
    - ✅ [**#109**](https://github.com/IBM/mcp-context-forge/issues/109) - [Feature Request]: Implement Streamable HTTP Transport for Client Connections to ContextForge
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
