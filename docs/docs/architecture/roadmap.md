# MCP Gateway Roadmap

!!! info "Release Overview"
    This roadmap outlines the planned development milestones for MCP Gateway, organized by release version with completion status and due dates.

## Release Status Summary

| Release | Due Date    | Completion | Status     | Description |
| ------- | ----------- | ---------- | ---------- | ----------- |
| 1.6.0   | 06 Jan 2026 | 0  %        | Open       | New MCP Servers and Agents |
| 1.3.0   | 25 Nov 2025 | 0  %        | Open       | Catalog Improvements, A2A Improvements, MCP Standard Review and Sync, Technical Debt |
| 1.2.0   | 11 Nov 2025 | 0  %        | Open       | Catalog Enhancements, Ratings, experience and UI |
| 1.1.0   | 28 Oct 2025 | 0  %        | Open       | Post-GA Testing, Bugfixing, Documentation, Performance and Scale |
| 1.0.0   | 14 Oct 2025 | 0  %        | Open       | General Availability & Release Candidate Hardening - stable & audited |
| 0.9.0   | 30 Sep 2025 | 6  %        | Open       | Interoperability, marketplaces & advanced connectivity |
| 0.8.0   | 16 Sep 2025 | 6  %        | Open       | Enterprise Security & Policy Guardrails |
| 0.7.0   | 02 Sep 2025 | 1  %        | Open       | Multitenancy and RBAC (Private/Team/Global catalogs), Extended Connectivity, Core Observability & Starter Agents (OpenAI and A2A) |
| 0.6.0   | 19 Aug 2025 | 32 %        | Open       | Security, Scale & Smart Automation |
| 0.5.0   | 05 Aug 2025 | 100 %        | **Closed** | Enterprise Operability, Auth, Configuration & Observability |
| 0.4.0   | 22 Jul 2025 | 100 %        | **Closed** | Bugfixes, Security, Resilience (retry with exponential backoff), code quality and technical debt |
| 0.3.0   | 08 Jul 2025 | 100 %        | **Closed** | Annotations and multi-server tool federations |
| 0.2.0   | 24 Jun 2025 | 100 %        | **Closed** | Streamable HTTP, Infra-as-Code, Dark Mode |
| 0.1.0   | 05 Jun 2025 | 100 %        | **Closed** | Initial release |

---

## Release 0.1.0 - Initial release

!!! success "Release 0.1.0 - Completed (100%)"
    **Due:** 05 Jun 2025 | **Status:** Closed
    Initial release

???+ check "✨ Completed Features (3)"
    - ✅ [**#27**](https://github.com/IBM/mcp-context-forge/issues/27) - Add /ready endpoint for readiness probe
    - ✅ [**#24**](https://github.com/IBM/mcp-context-forge/issues/24) - Publish Helm chart for Kubernetes deployment
    - ✅ [**#23**](https://github.com/IBM/mcp-context-forge/issues/23) - Add VS Code Devcontainer support for instant onboarding

???+ check "🐛 Completed Bugs (3)"
    - ✅ [**#49**](https://github.com/IBM/mcp-context-forge/issues/49) - [Bug]:make venv install serve fails with "./run-gunicorn.sh: line 40: python: command not found"
    - ✅ [**#37**](https://github.com/IBM/mcp-context-forge/issues/37) - Issues  with the  gateway Container Image
    - ✅ [**#35**](https://github.com/IBM/mcp-context-forge/issues/35) - Error when running in Docker Desktop for Windows

???+ check "📚 Completed Documentation (2)"
    - ✅ [**#50**](https://github.com/IBM/mcp-context-forge/issues/50) - virtual env location is incorrect
    - ✅ [**#30**](https://github.com/IBM/mcp-context-forge/issues/30) - Deploying to Google Cloud Run

---

## Release 0.2.0 - Streamable HTTP, Infra-as-Code, Dark Mode

!!! success "Release 0.2.0 - Completed (100%)"
    **Due:** 24 Jun 2025 | **Status:** Closed
    Streamable HTTP, Infra-as-Code, Dark Mode

???+ check "✨ Completed Features (3)"
    - ✅ [**#125**](https://github.com/IBM/mcp-context-forge/issues/125) - Add Streamable HTTP MCP servers to Gateway
    - ✅ [**#109**](https://github.com/IBM/mcp-context-forge/issues/109) - Implement Streamable HTTP Transport for Client Connections to MCP Gateway
    - ✅ [**#25**](https://github.com/IBM/mcp-context-forge/issues/25) - Add "Version and Environment Info" tab to Admin UI

???+ check "🐛 Completed Bugs (2)"
    - ✅ [**#85**](https://github.com/IBM/mcp-context-forge/issues/85) - internal server error comes if there is any error while adding an entry or even any crud operation is happening
    - ✅ [**#51**](https://github.com/IBM/mcp-context-forge/issues/51) - Internal server running when running gunicorn after install

???+ check "📚 Completed Documentation (3)"
    - ✅ [**#98**](https://github.com/IBM/mcp-context-forge/issues/98) - Add additional information for using the mcpgateway with Claude desktop
    - ✅ [**#71**](https://github.com/IBM/mcp-context-forge/issues/71) - [Docs]:Documentation Over Whelming Cannot figure out the basic task of adding an MCP server
    - ✅ [**#21**](https://github.com/IBM/mcp-context-forge/issues/21) - Deploying to Fly.io

---

## Release 0.3.0 - Annotations and multi-server tool federations

!!! success "Release 0.3.0 - Completed (100%)"
    **Due:** 08 Jul 2025 | **Status:** Closed
    Annotations and multi-server tool federations

???+ check "✨ Completed Features (8)"
    - ✅ [**#265**](https://github.com/IBM/mcp-context-forge/issues/265) - Sample MCP Server - Go (fast-time-server)
    - ✅ [**#179**](https://github.com/IBM/mcp-context-forge/issues/179) - Configurable Connection Retries for DB and Redis
    - ✅ [**#159**](https://github.com/IBM/mcp-context-forge/issues/159) - Add auto activation of mcp-server, when it goes up back again
    - ✅ [**#154**](https://github.com/IBM/mcp-context-forge/issues/154) - Export connection strings to various clients from UI and via API
    - ✅ [**#135**](https://github.com/IBM/mcp-context-forge/issues/135) - Dynamic UI Picker for Tool, Resource, and Prompt Associations
    - ✅ [**#116**](https://github.com/IBM/mcp-context-forge/issues/116) - Namespace Composite Key & UUIDs for Tool Identity
    - ✅ [**#100**](https://github.com/IBM/mcp-context-forge/issues/100) - Add path parameter or replace value in input payload for a REST API?
    - ✅ [**#26**](https://github.com/IBM/mcp-context-forge/issues/26) - Add dark mode toggle to Admin UI

???+ check "🐛 Completed Bugs (9)"
    - ✅ [**#316**](https://github.com/IBM/mcp-context-forge/issues/316) - Correctly create filelock_path: str = "tmp/gateway_service_leader.lock" in /tmp not current directory
    - ✅ [**#303**](https://github.com/IBM/mcp-context-forge/issues/303) - Update manager.py and admin.js removed `is_active` field - replace with separate `enabled` and `reachable` fields from migration
    - ✅ [**#302**](https://github.com/IBM/mcp-context-forge/issues/302) - Alembic configuration not packaged with pip wheel, `pip install . && mcpgateway` fails on db migration
    - ✅ [**#197**](https://github.com/IBM/mcp-context-forge/issues/197) - Pytest run exposes warnings from outdated Pydantic patterns, deprecated stdlib functions
    - ✅ [**#189**](https://github.com/IBM/mcp-context-forge/issues/189) - Close button for parameter input scheme does not work
    - ✅ [**#152**](https://github.com/IBM/mcp-context-forge/issues/152) - not able to add Github Remote Server
    - ✅ [**#132**](https://github.com/IBM/mcp-context-forge/issues/132) - SBOM Generation Failure
    - ✅ [**#131**](https://github.com/IBM/mcp-context-forge/issues/131) - Documentation Generation fails due to error in Makefile's image target
    - ✅ [**#28**](https://github.com/IBM/mcp-context-forge/issues/28) - Reactivating a gateway logs warning due to 'dict' object used as Pydantic model

???+ check "📚 Completed Documentation (1)"
    - ✅ [**#18**](https://github.com/IBM/mcp-context-forge/issues/18) - Add Developer Workstation Setup Guide for Mac (Intel/ARM), Linux, and Windows

---

## Release 0.4.0 - Bugfixes, Security, Resilience (retry with exponential backoff), code quality and technical debt

!!! success "Release 0.4.0 - Completed (100%)"
    **Due:** 22 Jul 2025 | **Status:** Closed
    Bugfixes, Security, Resilience (retry with exponential backoff), code quality and technical debt

???+ check "✨ Completed Features (9)"
    - ✅ [**#456**](https://github.com/IBM/mcp-context-forge/issues/456) - HTTPX Client with Smart Retry and Backoff Mechanism
    - ✅ [**#351**](https://github.com/IBM/mcp-context-forge/issues/351) - CHORE: Checklist for complete End-to-End Validation Testing for All API Endpoints, UI and Data Validation
    - ✅ [**#340**](https://github.com/IBM/mcp-context-forge/issues/340) - [Security]: Add input validation for main API endpoints (depends on #339 /admin API validation)
    - ✅ [**#339**](https://github.com/IBM/mcp-context-forge/issues/339) - [Security]: Add input validation for /admin endpoints
    - ✅ [**#338**](https://github.com/IBM/mcp-context-forge/issues/338) - [Security]: Eliminate all lint issues in web stack
    - ✅ [**#336**](https://github.com/IBM/mcp-context-forge/issues/336) - [Security]: Implement output escaping for user data in UI
    - ✅ [**#233**](https://github.com/IBM/mcp-context-forge/issues/233) - Contextual Hover-Help Tooltips in UI
    - ✅ [**#181**](https://github.com/IBM/mcp-context-forge/issues/181) - Test MCP Server Connectivity Debugging Tool
    - ✅ [**#177**](https://github.com/IBM/mcp-context-forge/issues/177) - Persistent Admin UI Filter State

???+ check "🐛 Completed Bugs (26)"
    - ✅ [**#508**](https://github.com/IBM/mcp-context-forge/issues/508) - "PATCH" in global tools while creating REST API integration through UI
    - ✅ [**#495**](https://github.com/IBM/mcp-context-forge/issues/495) - test_admin_tool_name_conflict creates record in actual db
    - ✅ [**#476**](https://github.com/IBM/mcp-context-forge/issues/476) - [Bug]:UI Does Not Show Error for Duplicate Server Name
    - ✅ [**#472**](https://github.com/IBM/mcp-context-forge/issues/472) - auth_username and auth_password not getting set in GET /gateways/<gateway_id> API
    - ✅ [**#471**](https://github.com/IBM/mcp-context-forge/issues/471) - _populate_auth not working
    - ✅ [**#424**](https://github.com/IBM/mcp-context-forge/issues/424) - MCP Gateway Doesn't Detect HTTPS/TLS Context or respect X-Forwarded-Proto when using Federation
    - ✅ [**#419**](https://github.com/IBM/mcp-context-forge/issues/419) - Remove unused lock_file_path from config.py (trips up bandit)
    - ✅ [**#416**](https://github.com/IBM/mcp-context-forge/issues/416) - Achieve 100% bandit lint for version.py (remove git command from version.py, tests and UI and rely on semantic version only)
    - ✅ [**#412**](https://github.com/IBM/mcp-context-forge/issues/412) - Replace assert statements with explicit error handling in translate.py and fix bandit lint issues
    - ✅ [**#396**](https://github.com/IBM/mcp-context-forge/issues/396) - Test server URL does not work correctly
    - ✅ [**#387**](https://github.com/IBM/mcp-context-forge/issues/387) - Respect GATEWAY_TOOL_NAME_SEPARATOR for gateway slug
    - ✅ [**#384**](https://github.com/IBM/mcp-context-forge/issues/384) - Push image to GHCR incorrectly runs in PR
    - ✅ [**#382**](https://github.com/IBM/mcp-context-forge/issues/382) - API incorrectly shows version, use semantic version from __init__
    - ✅ [**#378**](https://github.com/IBM/mcp-context-forge/issues/378) - [Bug] Fix Unit Tests to Handle UI-Disabled Mode
    - ✅ [**#374**](https://github.com/IBM/mcp-context-forge/issues/374) - Fix "metrics-loading" Element Not Found Console Warning
    - ✅ [**#371**](https://github.com/IBM/mcp-context-forge/issues/371) - Fix Makefile to let you pick docker or podman and work consistently with the right image name
    - ✅ [**#369**](https://github.com/IBM/mcp-context-forge/issues/369) - Fix Version Endpoint to Include Semantic Version (Not Just Git Revision)
    - ✅ [**#367**](https://github.com/IBM/mcp-context-forge/issues/367) - Fix "Test Server Connectivity" Feature in Admin UI
    - ✅ [**#366**](https://github.com/IBM/mcp-context-forge/issues/366) - Fix Dark Theme Visibility Issues in Admin UI
    - ✅ [**#361**](https://github.com/IBM/mcp-context-forge/issues/361) - Prompt and RPC Endpoints Accept XSS Content Without Validation Error
    - ✅ [**#359**](https://github.com/IBM/mcp-context-forge/issues/359) - Gateway validation accepts invalid transport types
    - ✅ [**#356**](https://github.com/IBM/mcp-context-forge/issues/356) - Annotations not editable
    - ✅ [**#355**](https://github.com/IBM/mcp-context-forge/issues/355) - Large empty space after line number in text boxes
    - ✅ [**#354**](https://github.com/IBM/mcp-context-forge/issues/354) - Edit screens not populating fields
    - ✅ [**#352**](https://github.com/IBM/mcp-context-forge/issues/352) - Resources - All data going into content
    - ✅ [**#213**](https://github.com/IBM/mcp-context-forge/issues/213) - [Bug]:Can't use `STREAMABLEHTTP`

???+ check "🔒 Completed Security (1)"
    - ✅ [**#552**](https://github.com/IBM/mcp-context-forge/issues/552) - Add comprehensive input validation security test suite

???+ check "🔧 Completed Chores (13)"
    - ✅ [**#558**](https://github.com/IBM/mcp-context-forge/issues/558) - Ignore tests/security/test_input_validation.py in pre-commit for bidi-controls
    - ✅ [**#499**](https://github.com/IBM/mcp-context-forge/issues/499) - Add nodejsscan security scanner
    - ✅ [**#467**](https://github.com/IBM/mcp-context-forge/issues/467) - Achieve 100% docstring coverage (make interrogate) - currently at 96.3%
    - ✅ [**#433**](https://github.com/IBM/mcp-context-forge/issues/433) - Fix all Makefile targets to work without pre-activated venv and check for OS depends
    - ✅ [**#421**](https://github.com/IBM/mcp-context-forge/issues/421) - Achieve zero flagged Bandit issues
    - ✅ [**#415**](https://github.com/IBM/mcp-context-forge/issues/415) - Additional Python Security Scanners
    - ✅ [**#399**](https://github.com/IBM/mcp-context-forge/issues/399) - Create e2e acceptance test docs
    - ✅ [**#375**](https://github.com/IBM/mcp-context-forge/issues/375) - Fix yamllint to Ignore node_modules Directory
    - ✅ [**#362**](https://github.com/IBM/mcp-context-forge/issues/362) - Implement Docker HEALTHCHECK
    - ✅ [**#305**](https://github.com/IBM/mcp-context-forge/issues/305) - Add vulture (dead code detect) and unimport (unused import detect) to Makefile and GitHub Actions
    - ✅ [**#279**](https://github.com/IBM/mcp-context-forge/issues/279) - Implement security audit and vulnerability scanning with grype in Makefile and GitHub Actions
    - ✅ [**#249**](https://github.com/IBM/mcp-context-forge/issues/249) - Achieve 60% doctest coverage and add Makefile and CI/CD targets for doctest and coverage
    - ✅ [**#210**](https://github.com/IBM/mcp-context-forge/issues/210) - Raise pylint from 9.16/10 -> 10/10

???+ check "📚 Completed Documentation (3)"
    - ✅ [**#522**](https://github.com/IBM/mcp-context-forge/issues/522) - OpenAPI title is MCP_Gateway instead of MCP Gateway
    - ✅ [**#376**](https://github.com/IBM/mcp-context-forge/issues/376) - Document Security Policy in GitHub Pages and Link Roadmap on Homepage
    - ✅ [**#46**](https://github.com/IBM/mcp-context-forge/issues/46) - Add documentation for using mcp-cli with MCP Gateway

---

## Release 0.5.0 - Enterprise Operability, Auth, Configuration & Observability

!!! success "Release 0.5.0 - Completed (100%)"
    **Due:** 05 Aug 2025 | **Status:** Closed
    Enterprise Operability, Auth, Configuration & Observability

???+ check "✨ Completed Features (4)"
    - ✅ [**#663**](https://github.com/IBM/mcp-context-forge/issues/663) - Add basic auth support for API Docs
    - ✅ [**#623**](https://github.com/IBM/mcp-context-forge/issues/623) - Display default values from input_schema in test tool screen
    - ✅ [**#506**](https://github.com/IBM/mcp-context-forge/issues/506) -  New column for "MCP Server Name" in Global tools/resources etc
    - ✅ [**#392**](https://github.com/IBM/mcp-context-forge/issues/392) - UI checkbox selection for servers, tools, and resources

???+ check "🐛 Completed Bugs (20)"
    - ✅ [**#631**](https://github.com/IBM/mcp-context-forge/issues/631) - Inconsistency in acceptable length of Tool Names for tools created via UI and programmatically
    - ✅ [**#630**](https://github.com/IBM/mcp-context-forge/issues/630) - Gateway update fails silently in UI, backend throws ValidationInfo error
    - ✅ [**#622**](https://github.com/IBM/mcp-context-forge/issues/622) - Test tool UI passes boolean inputs as on/off instead of true/false
    - ✅ [**#620**](https://github.com/IBM/mcp-context-forge/issues/620) - Test tool UI passes array inputs as strings
    - ✅ [**#613**](https://github.com/IBM/mcp-context-forge/issues/613) - Fix lint-web issues in admin.js
    - ✅ [**#610**](https://github.com/IBM/mcp-context-forge/issues/610) - Edit tool in Admin UI sends invalid "STREAMABLE" value for Request Type
    - ✅ [**#603**](https://github.com/IBM/mcp-context-forge/issues/603) - Unexpected error when registering a gateway with the same name.
    - ✅ [**#601**](https://github.com/IBM/mcp-context-forge/issues/601) - APIs for gateways in admin and main do not mask auth values
    - ✅ [**#598**](https://github.com/IBM/mcp-context-forge/issues/598) - Long input names in tool creation reflected back to user in error message
    - ✅ [**#591**](https://github.com/IBM/mcp-context-forge/issues/591) - [Bug] Edit Prompt Fails When Template Field Is Empty
    - ✅ [**#584**](https://github.com/IBM/mcp-context-forge/issues/584) - Can't register Github MCP Server in the MCP Registry
    - ✅ [**#579**](https://github.com/IBM/mcp-context-forge/issues/579) - Edit tool update fail  integration_type="REST"
    - ✅ [**#578**](https://github.com/IBM/mcp-context-forge/issues/578) - Adding invalid gateway URL does not return an error immediately
    - ✅ [**#521**](https://github.com/IBM/mcp-context-forge/issues/521) - Gateway ID returned as null by Gateway Create API
    - ✅ [**#507**](https://github.com/IBM/mcp-context-forge/issues/507) - Makefile missing .PHONY declarations and other issues
    - ✅ [**#434**](https://github.com/IBM/mcp-context-forge/issues/434) - Logs show"Invalid HTTP request received"
    - ✅ [**#430**](https://github.com/IBM/mcp-context-forge/issues/430) - make serve doesn't check if I'm already running an instance (run-gunicorn.sh) letting me start the server multiple times
    - ✅ [**#423**](https://github.com/IBM/mcp-context-forge/issues/423) - Redundant Conditional Expression in Content Validation
    - ✅ [**#373**](https://github.com/IBM/mcp-context-forge/issues/373) - Clarify Difference Between "Reachable" and "Available" Status in Version Info
    - ✅ [**#357**](https://github.com/IBM/mcp-context-forge/issues/357) - Improve consistency of displaying error messages

???+ check "🔒 Completed Security (1)"
    - ✅ [**#425**](https://github.com/IBM/mcp-context-forge/issues/425) - Make JWT Token Expiration Mandatory when REQUIRE_TOKEN_EXPIRATION=true (depends on #87)

???+ check "🔧 Completed Chores (9)"
    - ✅ [**#638**](https://github.com/IBM/mcp-context-forge/issues/638) - Add Makefile and GitHub Actions support for Snyk (test, code-test, container-test, helm charts)
    - ✅ [**#615**](https://github.com/IBM/mcp-context-forge/issues/615) - Add pypi package linters: check-manifest pyroma and verify target to GitHub Actions
    - ✅ [**#590**](https://github.com/IBM/mcp-context-forge/issues/590) - Integrate DevSkim static analysis tool via Makefile
    - ✅ [**#410**](https://github.com/IBM/mcp-context-forge/issues/410) - Add `make lint filename|dirname` target to Makefile
    - ✅ [**#403**](https://github.com/IBM/mcp-context-forge/issues/403) - Add time server (and configure it post-deploy) to docker-compose.yaml
    - ✅ [**#397**](https://github.com/IBM/mcp-context-forge/issues/397) - Migrate run-gunicorn-v2.sh to run-gunicorn.sh and have a single file (improved startup script with configurable flags)
    - ✅ [**#390**](https://github.com/IBM/mcp-context-forge/issues/390) - Add lint-web to CI/CD and add additional linters to Makefile (jshint jscpd markuplint)
    - ✅ [**#365**](https://github.com/IBM/mcp-context-forge/issues/365) - Fix Database Migration Commands in Makefile
    - ✅ [**#363**](https://github.com/IBM/mcp-context-forge/issues/363) - Improve Error Messages - Replace Raw Technical Errors with User-Friendly Messages

---

## Release 0.6.0 - Security, Scale & Smart Automation

!!! danger "Release 0.6.0 - In Progress (32%)"
    **Due:** 19 Aug 2025 | **Status:** Open
    Security, Scale & Smart Automation

??? abstract "✨ Features (9 completed, 31 remaining)"
    - [**#720**](https://github.com/IBM/mcp-context-forge/issues/720) - Add CLI for authoring and packaging plugins
    - ✅ [**#705**](https://github.com/IBM/mcp-context-forge/issues/705) - Option to completely remove Bearer token auth to MCP gateway
    - [**#699**](https://github.com/IBM/mcp-context-forge/issues/699) - Metrics Enhancement (export all data, capture all metrics, fix last used timestamps, UI improvements)
    - ✅ [**#690**](https://github.com/IBM/mcp-context-forge/issues/690) - [Feature] Make SSE Keepalive Events Configurable
    - ✅ [**#682**](https://github.com/IBM/mcp-context-forge/issues/682) - Add tool hooks (tool_pre_invoke / tool_post_invoke) to plugin system
    - [**#673**](https://github.com/IBM/mcp-context-forge/issues/673) - Identify Next Steps for Plugin Development
    - [**#668**](https://github.com/IBM/mcp-context-forge/issues/668) - Add Null Checks and Improve Error Handling in Frontend Form Handlers (admin.js)
    - [**#654**](https://github.com/IBM/mcp-context-forge/issues/654) - Pre-register checks (mcp server scan) (draft)
    - [**#647**](https://github.com/IBM/mcp-context-forge/issues/647) - Configurable caching for tools (draft)
    - [**#605**](https://github.com/IBM/mcp-context-forge/issues/605) - Access to remote MCP Servers/Tools via OAuth on behalf of Users
    - ✅ [**#586**](https://github.com/IBM/mcp-context-forge/issues/586) - Tag support with editing and validation across all APIs endpoints and UI (tags)
    - [**#568**](https://github.com/IBM/mcp-context-forge/issues/568) - Configurable client require TLS cert, and certificate setup for MCP Servers with private CA (draft)
    - [**#566**](https://github.com/IBM/mcp-context-forge/issues/566) - Add support for limiting specific fields to user defined values (draft)
    - [**#565**](https://github.com/IBM/mcp-context-forge/issues/565) - Docs for https://github.com/block/goose (draft)
    - [**#505**](https://github.com/IBM/mcp-context-forge/issues/505) - Add ENV token forwarding management per tool (draft)
    - [**#492**](https://github.com/IBM/mcp-context-forge/issues/492) - Change UI ID field name to UUID
    - ✅ [**#404**](https://github.com/IBM/mcp-context-forge/issues/404) - Add resources and prompts/prompt templates to time server
    - [**#386**](https://github.com/IBM/mcp-context-forge/issues/386) - Gateways/MCP Servers Page Refresh
    - ✅ [**#380**](https://github.com/IBM/mcp-context-forge/issues/380) - REST Endpoints for Go fast-time-server
    - ✅ [**#368**](https://github.com/IBM/mcp-context-forge/issues/368) - Enhance Metrics Tab UI with Virtual Servers and Top 5 Performance Tables
    - ✅ [**#364**](https://github.com/IBM/mcp-context-forge/issues/364) - Add Log File Support to MCP Gateway
    - [**#320**](https://github.com/IBM/mcp-context-forge/issues/320) - Update Streamable HTTP to fully support Virtual Servers
    - [**#313**](https://github.com/IBM/mcp-context-forge/issues/313) - Architecture Decisions and Discussions for AI Middleware and Plugin Framework (Enables #319)
    - [**#301**](https://github.com/IBM/mcp-context-forge/issues/301) - Full Circuit Breakers for Unstable MCP Server Backends support (extend existing healthchecks with half-open state)
    - [**#289**](https://github.com/IBM/mcp-context-forge/issues/289) - Multi-Layer Caching System (Memory + Redis)
    - [**#287**](https://github.com/IBM/mcp-context-forge/issues/287) - API Path Versioning /v1 and /experimental prefix
    - [**#286**](https://github.com/IBM/mcp-context-forge/issues/286) - Dynamic Configuration UI & Admin API (store config in database after db init)
    - [**#278**](https://github.com/IBM/mcp-context-forge/issues/278) - Authentication & Authorization - Google SSO Integration Tutorial (Depends on #220)
    - [**#277**](https://github.com/IBM/mcp-context-forge/issues/277) - Authentication & Authorization - GitHub SSO Integration Tutorial (Depends on #220)
    - [**#276**](https://github.com/IBM/mcp-context-forge/issues/276) - Terraform Module – "mcp-gateway-ibm-cloud" supporting IKS, ROKS, Code Engine targets
    - [**#275**](https://github.com/IBM/mcp-context-forge/issues/275) - Terraform Module - "mcp-gateway-gcp" supporting GKE and Cloud Run
    - [**#274**](https://github.com/IBM/mcp-context-forge/issues/274) - Terraform Module - "mcp-gateway-azure" supporting AKS and ACA
    - [**#273**](https://github.com/IBM/mcp-context-forge/issues/273) - Terraform Module - "mcp-gateway-aws" supporting both EKS and ECS Fargate targets
    - [**#258**](https://github.com/IBM/mcp-context-forge/issues/258) - Universal Client Retry Mechanisms with Exponential Backoff & Random Jitter
    - [**#234**](https://github.com/IBM/mcp-context-forge/issues/234) - 🧠 Protocol Feature – Elicitation Support (MCP 2025-06-18)
    - [**#217**](https://github.com/IBM/mcp-context-forge/issues/217) - Graceful-Shutdown Hooks for API & Worker Containers (SIGTERM-safe rollouts, DB-pool cleanup, zero-drop traffic)
    - [**#172**](https://github.com/IBM/mcp-context-forge/issues/172) - Enable Auto Refresh and Reconnection for MCP Servers in Gateways
    - ✅ [**#94**](https://github.com/IBM/mcp-context-forge/issues/94) - Transport-Translation Bridge (`mcpgateway.translate`)  any to any protocol conversion cli tool
    - [**#87**](https://github.com/IBM/mcp-context-forge/issues/87) - Epic: Secure JWT Token Catalog with Per-User Expiry and Revocation
    - [**#80**](https://github.com/IBM/mcp-context-forge/issues/80) - Publish a multi-architecture container (including ARM64) support

??? abstract "🐛 Bugs (14 completed, 8 remaining)"
    - ✅ [**#716**](https://github.com/IBM/mcp-context-forge/issues/716) - Resources and Prompts not displaying in Admin Dashboard while Tools are visible
    - ✅ [**#696**](https://github.com/IBM/mcp-context-forge/issues/696) - SSE Tool Invocation Fails After Integration Type Migration post PR #678
    - ✅ [**#694**](https://github.com/IBM/mcp-context-forge/issues/694) - Enhanced Validation Missing in GatewayCreate
    - ✅ [**#685**](https://github.com/IBM/mcp-context-forge/issues/685) - Multiple Fixes and improved security for HTTP Header Passthrough Feature
    - ✅ [**#666**](https://github.com/IBM/mcp-context-forge/issues/666) - [Bug]:Vague/Unclear Error Message "Validation Failed" When Adding a REST Tool
    - ✅ [**#661**](https://github.com/IBM/mcp-context-forge/issues/661) - Database migration runs during doctest execution
    - ✅ [**#649**](https://github.com/IBM/mcp-context-forge/issues/649) - Duplicate Gateway Registration with Equivalent URLs Bypasses Uniqueness Check
    - ✅ [**#646**](https://github.com/IBM/mcp-context-forge/issues/646) - MCP Server/Federated Gateway Registration is failing
    - [**#625**](https://github.com/IBM/mcp-context-forge/issues/625) - Gateway unable to register gateway or call tools on MacOS
    - [**#587**](https://github.com/IBM/mcp-context-forge/issues/587) - REST Tool giving error
    - ✅ [**#557**](https://github.com/IBM/mcp-context-forge/issues/557) - [BUG] Cleanup tool descriptions to remove newlines and truncate text
    - ✅ [**#526**](https://github.com/IBM/mcp-context-forge/issues/526) - Unable to add multiple headers when adding a gateway through UI (draft)
    - ✅ [**#520**](https://github.com/IBM/mcp-context-forge/issues/520) - Resource mime-type is always stored as text/plain
    - [**#481**](https://github.com/IBM/mcp-context-forge/issues/481) - Intermittent test_resource_cache.py::test_expiration - AssertionError: assert 'bar' is None (draft)
    - [**#464**](https://github.com/IBM/mcp-context-forge/issues/464) - MCP Server "Active" status not getting updated under "Gateways/MCP Servers" when the MCP Server shutdown.
    - ✅ [**#452**](https://github.com/IBM/mcp-context-forge/issues/452) - integrationType should only support REST, not MCP (Remove Integration Type: MCP) (draft)
    - [**#448**](https://github.com/IBM/mcp-context-forge/issues/448) - [Bug]:MCP server with custom base path "/api" instead of "mcp" or "sse" is not working
    - ✅ [**#417**](https://github.com/IBM/mcp-context-forge/issues/417) - Intermittent doctest failure in /mcpgateway/cache/resource_cache.py:7
    - [**#409**](https://github.com/IBM/mcp-context-forge/issues/409) - Add configurable limits for data cleaning / XSS prevention in .env.example and helm (draft)
    - ✅ [**#405**](https://github.com/IBM/mcp-context-forge/issues/405) - Fix the go time server annotation (it shows as destructive)
    - [**#393**](https://github.com/IBM/mcp-context-forge/issues/393) - [BUG] Both resources and prompts not loading after adding a federated gateway
    - [**#232**](https://github.com/IBM/mcp-context-forge/issues/232) - Leaving Auth to None fails

???+ danger "🔒 Open Security (11)"
    - [**#544**](https://github.com/IBM/mcp-context-forge/issues/544) - Database-Backed User Authentication with Argon2id (replace BASIC auth)
    - [**#540**](https://github.com/IBM/mcp-context-forge/issues/540) - Configurable Well-Known URI Handler including security.txt and robots.txt
    - [**#538**](https://github.com/IBM/mcp-context-forge/issues/538) - [SECURITY FEATURE] Content Size & Type Security Limits for Resources & Prompts
    - [**#537**](https://github.com/IBM/mcp-context-forge/issues/537) - Simple Endpoint Feature Flags (selectively enable or disable tools, resources, prompts, servers, gateways, roots)
    - [**#534**](https://github.com/IBM/mcp-context-forge/issues/534) - Add Security Configuration Validation and Startup Checks
    - [**#533**](https://github.com/IBM/mcp-context-forge/issues/533) - Add Additional Configurable Security Headers to APIs for Admin UI
    - [**#342**](https://github.com/IBM/mcp-context-forge/issues/342) - Implement database-level security constraints and SQL injection prevention
    - [**#284**](https://github.com/IBM/mcp-context-forge/issues/284) - LDAP / Active-Directory Integration
    - [**#282**](https://github.com/IBM/mcp-context-forge/issues/282) - Per-Virtual-Server API Keys with Scoped Access
    - [**#220**](https://github.com/IBM/mcp-context-forge/issues/220) - Authentication & Authorization - SSO + Identity-Provider Integration
    - [**#208**](https://github.com/IBM/mcp-context-forge/issues/208) - HTTP Header Passthrough (forward headers to MCP server)

??? abstract "🔧 Chores (4 completed, 5 remaining)"
    - ✅ [**#672**](https://github.com/IBM/mcp-context-forge/issues/672) - Part 2: Replace Raw Errors with Friendly Messages in main.py
    - [**#589**](https://github.com/IBM/mcp-context-forge/issues/589) - generating build provenance attestations for workflow artifacts (draft)
    - [**#341**](https://github.com/IBM/mcp-context-forge/issues/341) - Enhance UI security with DOMPurify and content sanitization
    - ✅ [**#317**](https://github.com/IBM/mcp-context-forge/issues/317) - Script to add relative file path header to each file and verify top level docstring
    - ✅ [**#315**](https://github.com/IBM/mcp-context-forge/issues/315) - [CHORE] Check SPDX headers Makefile and GitHub Actions target - ensure all files have File, Author(s) and SPDX headers
    - [**#307**](https://github.com/IBM/mcp-context-forge/issues/307) - GitHub Actions to build docs, with diagrams and test report, and deploy to GitHub Pages using MkDocs on every push to main
    - [**#292**](https://github.com/IBM/mcp-context-forge/issues/292) - Enable AI Alliance Analytics Stack Integration
    - ✅ [**#254**](https://github.com/IBM/mcp-context-forge/issues/254) - Async Code Testing and Performance Profiling Makefile targets (flake8-async, cprofile, snakeviz, aiomonitor)
    - [**#211**](https://github.com/IBM/mcp-context-forge/issues/211) - Achieve Zero Static-Type Errors Across All Checkers (mypy, ty, pyright, pyrefly)

???+ danger "📚 Open Documentation (1)"
    - [**#503**](https://github.com/IBM/mcp-context-forge/issues/503) - Tutorial: OpenWebUI with Ollama, LiteLLM, MCPO, and MCP Gateway Deployment Guide (Draft)

---

## Release 0.7.0 - Multitenancy and RBAC (Private/Team/Global catalogs), Extended Connectivity, Core Observability & Starter Agents (OpenAI and A2A)

!!! danger "Release 0.7.0 - In Progress (1%)"
    **Due:** 02 Sep 2025 | **Status:** Open
    Multitenancy and RBAC (Private/Team/Global catalogs), Extended Connectivity, Core Observability & Starter Agents (OpenAI and A2A)

???+ danger "✨ Open Features (18)"
    - [**#727**](https://github.com/IBM/mcp-context-forge/issues/727) - Phoenix Observability Integration plugin
    - [**#706**](https://github.com/IBM/mcp-context-forge/issues/706) - ABAC Virtual Server Support
    - [**#636**](https://github.com/IBM/mcp-context-forge/issues/636) - Add PyInstaller support for building standalone binaries for all platforms
    - [**#570**](https://github.com/IBM/mcp-context-forge/issues/570) - Word wrap in codemirror (draft)
    - [**#491**](https://github.com/IBM/mcp-context-forge/issues/491) - UI Keyboard shortcuts (esc to exit Test tool for example) (draft)
    - [**#300**](https://github.com/IBM/mcp-context-forge/issues/300) - Structured JSON Logging with Correlation IDs
    - [**#272**](https://github.com/IBM/mcp-context-forge/issues/272) - Observability - Pre-built Grafana Dashboards & Loki Log Export
    - [**#270**](https://github.com/IBM/mcp-context-forge/issues/270) - MCP Server – Go Implementation ("libreoffice-server")
    - [**#269**](https://github.com/IBM/mcp-context-forge/issues/269) - MCP Server - Go Implementation (LaTeX Service)
    - [**#263**](https://github.com/IBM/mcp-context-forge/issues/263) - Sample Agent - CrewAI Integration (OpenAI & A2A Endpoints)
    - [**#262**](https://github.com/IBM/mcp-context-forge/issues/262) - Sample Agent - LangChain Integration (OpenAI & A2A Endpoints)
    - [**#218**](https://github.com/IBM/mcp-context-forge/issues/218) - Prometheus Metrics Instrumentation using prometheus-fastapi-instrumentator
    - [**#186**](https://github.com/IBM/mcp-context-forge/issues/186) - Granular Configuration Export & Import (via UI & API)
    - [**#185**](https://github.com/IBM/mcp-context-forge/issues/185) - Portable Configuration Export & Import CLI (registry, virtual servers and prompts)
    - [**#175**](https://github.com/IBM/mcp-context-forge/issues/175) - Add OpenLLMetry Integration for Observability
    - [**#138**](https://github.com/IBM/mcp-context-forge/issues/138) - View & Export Logs from Admin UI
    - [**#137**](https://github.com/IBM/mcp-context-forge/issues/137) - Track Creator & Timestamp Metadata for Servers, Tools, and Resources
    - [**#136**](https://github.com/IBM/mcp-context-forge/issues/136) - Downloadable JSON Client Config Generator from Admin UI

???+ danger "🐛 Open Bugs (1)"
    - [**#383**](https://github.com/IBM/mcp-context-forge/issues/383) - Remove migration step from Helm chart (now automated, no longer needed)

???+ danger "🔒 Open Security (1)"
    - [**#283**](https://github.com/IBM/mcp-context-forge/issues/283) - Role-Based Access Control (RBAC) - User/Team/Global Scopes for full multi-tenancy support

???+ danger "⚡ Open Performance (1)"
    - [**#432**](https://github.com/IBM/mcp-context-forge/issues/432) - Performance Optimization Implementation and Guide for MCP Gateway (baseline)

??? abstract "🔧 Chores (1 completed, 27 remaining)"
    - [**#674**](https://github.com/IBM/mcp-context-forge/issues/674) - Automate release management process (draft)
    - [**#595**](https://github.com/IBM/mcp-context-forge/issues/595) - [CHORE] Investigate potential migration to UUID7 (draft)
    - [**#574**](https://github.com/IBM/mcp-context-forge/issues/574) - Run pyupgrade to upgrade python syntax (draft)
    - [**#414**](https://github.com/IBM/mcp-context-forge/issues/414) - Restructure Makefile targets (ex: move grype to container scanning section), or have a dedicated security scanning section
    - [**#408**](https://github.com/IBM/mcp-context-forge/issues/408) - Add normalize script to pre-commit hooks (draft)
    - [**#407**](https://github.com/IBM/mcp-context-forge/issues/407) - Improve pytest and plugins (draft)
    - [**#402**](https://github.com/IBM/mcp-context-forge/issues/402) - Add post-deploy step to helm that configures the Time Server as a Gateway (draft)
    - [**#398**](https://github.com/IBM/mcp-context-forge/issues/398) - Enforce pre-commit targets for doctest coverage, pytest coverage, pylint score 10/10, flake8 pass and add badges
    - [**#391**](https://github.com/IBM/mcp-context-forge/issues/391) - Setup SonarQube quality gate (draft)
    - [**#377**](https://github.com/IBM/mcp-context-forge/issues/377) - Fix PostgreSQL Volume Name Conflicts in Helm Chart (draft)
    - [**#344**](https://github.com/IBM/mcp-context-forge/issues/344) - Implement additional security headers and CORS configuration
    - [**#318**](https://github.com/IBM/mcp-context-forge/issues/318) - Publish Agents and Tools that leverage codebase and templates (draft)
    - [**#312**](https://github.com/IBM/mcp-context-forge/issues/312) - End-to-End MCP Gateway Stack Testing Harness (mcpgateway, translate, wrapper, mcp-servers)
    - [**#281**](https://github.com/IBM/mcp-context-forge/issues/281) - Set up contract testing with Pact (pact-python) including Makefile and GitHub Actions targets
    - ✅ [**#280**](https://github.com/IBM/mcp-context-forge/issues/280) - Add mutation testing with mutmut for test quality validation
    - [**#261**](https://github.com/IBM/mcp-context-forge/issues/261) - Implement 90% Test Coverage Quality Gate and automatic badge and coverage html / markdown report publication
    - [**#260**](https://github.com/IBM/mcp-context-forge/issues/260) - Manual security testing plan and template for release validation and production deployments
    - [**#259**](https://github.com/IBM/mcp-context-forge/issues/259) - SAST (Semgrep) and DAST (OWASP ZAP) automated security testing Makefile targets and GitHub Actions
    - [**#256**](https://github.com/IBM/mcp-context-forge/issues/256) - Implement comprehensive fuzz testing automation and Makefile targets (hypothesis, atheris, schemathesis , RESTler)
    - [**#255**](https://github.com/IBM/mcp-context-forge/issues/255) - Implement comprehensive Playwright test automation for the entire MCP Gateway Admin UI with Makefile targets and GitHub Actions
    - [**#253**](https://github.com/IBM/mcp-context-forge/issues/253) - Implement chaos engineering tests for fault tolerance validation (network partitions, service failures)
    - [**#252**](https://github.com/IBM/mcp-context-forge/issues/252) - Establish database migration testing pipeline with rollback validation across SQLite, Postgres, and Redis
    - [**#251**](https://github.com/IBM/mcp-context-forge/issues/251) - Automatic performance testing and tracking for every build (hey) including SQLite and Postgres / Redis configurations
    - [**#250**](https://github.com/IBM/mcp-context-forge/issues/250) - Implement automatic API documentation generation using mkdocstrings and update Makefile
    - [**#223**](https://github.com/IBM/mcp-context-forge/issues/223) - Helm Chart Test Harness & Red Hat chart-verifier
    - [**#222**](https://github.com/IBM/mcp-context-forge/issues/222) - Helm chart build Makefile with lint and values.schema.json validation + CODEOWNERS, CHANGELOG.md, .helmignore and CONTRIBUTING.md
    - [**#216**](https://github.com/IBM/mcp-context-forge/issues/216) - Add spec-validation targets and make the OpenAPI build go green
    - [**#212**](https://github.com/IBM/mcp-context-forge/issues/212) - Achieve zero flagged SonarQube issues

???+ danger "📚 Open Documentation (3)"
    - [**#323**](https://github.com/IBM/mcp-context-forge/issues/323) - Add Developer Guide for using fast-time-server via JSON-RPC commands using curl or stdio
    - [**#22**](https://github.com/IBM/mcp-context-forge/issues/22) - Add BeeAI Framework client integration (Python & TypeScript)
    - [**#19**](https://github.com/IBM/mcp-context-forge/issues/19) - Add Developer Guide for using MCP via the CLI (curl commands, JSON-RPC)

---

## Release 0.8.0 - Enterprise Security & Policy Guardrails

!!! danger "Release 0.8.0 - In Progress (6%)"
    **Due:** 16 Sep 2025 | **Status:** Open
    Enterprise Security & Policy Guardrails

??? abstract "✨ Features (1 completed, 2 remaining)"
    - ✅ [**#319**](https://github.com/IBM/mcp-context-forge/issues/319) - AI Middleware Integration / Plugin Framework for extensible gateway capabilities
    - [**#285**](https://github.com/IBM/mcp-context-forge/issues/285) - Configuration Validation & Schema Enforcement using Pydantic V2 models, config validator cli flag
    - [**#182**](https://github.com/IBM/mcp-context-forge/issues/182) - Semantic tool auto-filtering

???+ danger "🔒 Open Security (11)"
    - [**#543**](https://github.com/IBM/mcp-context-forge/issues/543) - CSRF Token Protection System
    - [**#542**](https://github.com/IBM/mcp-context-forge/issues/542) - Helm Chart - Enterprise Secrets Management Integration (Vault)
    - [**#541**](https://github.com/IBM/mcp-context-forge/issues/541) - Enhanced Session Management for Admin UI
    - [**#539**](https://github.com/IBM/mcp-context-forge/issues/539) - Tool Execution Limits & Resource Controls
    - [**#536**](https://github.com/IBM/mcp-context-forge/issues/536) - Generic IP-Based Access Control (allowlist)
    - [**#535**](https://github.com/IBM/mcp-context-forge/issues/535) - Audit Logging System
    - [**#271**](https://github.com/IBM/mcp-context-forge/issues/271) - Policy-as-Code Engine - Rego Prototype
    - [**#257**](https://github.com/IBM/mcp-context-forge/issues/257) - Gateway-Level Rate Limiting, DDoS Protection & Abuse Detection
    - [**#230**](https://github.com/IBM/mcp-context-forge/issues/230) - Cryptographic Request & Response Signing
    - [**#229**](https://github.com/IBM/mcp-context-forge/issues/229) - Guardrails - Input/Output Sanitization & PII Masking
    - [**#221**](https://github.com/IBM/mcp-context-forge/issues/221) - Gateway-Level Input Validation & Output Sanitization (prevent traversal)

???+ danger "🔧 Open Chores (1)"
    - [**#291**](https://github.com/IBM/mcp-context-forge/issues/291) - Comprehensive Scalability & Soak-Test Harness (Long-term Stability & Load) - locust, pytest-benchmark, smocker mocked MCP servers

---

## Release 0.9.0 - Interoperability, marketplaces & advanced connectivity

!!! danger "Release 0.9.0 - In Progress (6%)"
    **Due:** 30 Sep 2025 | **Status:** Open
    Interoperability, marketplaces & advanced connectivity

??? abstract "✨ Features (1 completed, 13 remaining)"
    - [**#546**](https://github.com/IBM/mcp-context-forge/issues/546) - Protocol Version Negotiation & Backward Compatibility
    - [**#545**](https://github.com/IBM/mcp-context-forge/issues/545) - Hot-Reload Configuration Without Restart (move from .env to configuration database table) (draft)
    - [**#298**](https://github.com/IBM/mcp-context-forge/issues/298) - A2A Initial Support - Add A2A Servers as Tools
    - [**#295**](https://github.com/IBM/mcp-context-forge/issues/295) - MCP Server Marketplace
    - [**#294**](https://github.com/IBM/mcp-context-forge/issues/294) - Automated MCP Server Testing and Certification
    - [**#288**](https://github.com/IBM/mcp-context-forge/issues/288) - MariaDB Support Testing, Documentation, CI/CD (alongside PostgreSQL & SQLite)
    - [**#268**](https://github.com/IBM/mcp-context-forge/issues/268) - Sample MCP Server - Haskell Implementation ("pandoc-server") (html, docx, pptx, latex conversion)
    - [**#267**](https://github.com/IBM/mcp-context-forge/issues/267) - Sample MCP Server – Java Implementation ("plantuml-server")
    - [**#266**](https://github.com/IBM/mcp-context-forge/issues/266) - Sample MCP Server - Rust Implementation ("filesystem-server")
    - ✅ [**#243**](https://github.com/IBM/mcp-context-forge/issues/243) - a2a compatibility?
    - [**#209**](https://github.com/IBM/mcp-context-forge/issues/209) - Anthropic Desktop Extensions DTX directory/marketplace
    - [**#130**](https://github.com/IBM/mcp-context-forge/issues/130) - Dynamic LLM-Powered Tool Generation via Prompt
    - [**#123**](https://github.com/IBM/mcp-context-forge/issues/123) - Dynamic Server Catalog via Rule, Regexp, Tags - or LLM-Based Selection
    - [**#114**](https://github.com/IBM/mcp-context-forge/issues/114) - Connect to Dockerized MCP Servers via STDIO

???+ danger "🔒 Open Security (1)"
    - [**#426**](https://github.com/IBM/mcp-context-forge/issues/426) - Configurable Password and Secret Policy Engine

???+ danger "🔧 Open Chores (1)"
    - [**#290**](https://github.com/IBM/mcp-context-forge/issues/290) - Enhance Gateway Tuning Guide with PostgreSQL Deep-Dive

---

## Release 1.0.0 - General Availability & Release Candidate Hardening - stable & audited

!!! danger "Release 1.0.0 - In Progress (0%)"
    **Due:** 14 Oct 2025 | **Status:** Open
    General Availability & Release Candidate Hardening - stable & audited

???+ danger "📚 Open Documentation (1)"
    - [**#264**](https://github.com/IBM/mcp-context-forge/issues/264) - GA Documentation Review & End-to-End Validation Audit

---

## Release 1.1.0 - Post-GA Testing, Bugfixing, Documentation, Performance and Scale

!!! danger "Release 1.1.0 - In Progress (0%)"
    **Due:** 28 Oct 2025 | **Status:** Open
    Post-GA Testing, Bugfixing, Documentation, Performance and Scale

???+ danger "✨ Open Features (2)"
    - [**#707**](https://github.com/IBM/mcp-context-forge/issues/707) - Customizable Admin Panel
    - [**#293**](https://github.com/IBM/mcp-context-forge/issues/293) - Intelligent Load Balancing for Redundant MCP Servers

---

## Release 1.2.0 - Catalog Enhancements, Ratings, experience and UI

!!! danger "Release 1.2.0 - In Progress (0%)"
    **Due:** 11 Nov 2025 | **Status:** Open
    Catalog Enhancements, Ratings, experience and UI

???+ danger "✨ Open Features (2)"
    - [**#547**](https://github.com/IBM/mcp-context-forge/issues/547) - Built-in MCP Server Health Dashboard
    - [**#296**](https://github.com/IBM/mcp-context-forge/issues/296) - MCP Server Rating and Review System

---

## Release 1.3.0 - Catalog Improvements, A2A Improvements, MCP Standard Review and Sync, Technical Debt

!!! danger "Release 1.3.0 - In Progress (0%)"
    **Due:** 25 Nov 2025 | **Status:** Open
    Catalog Improvements, A2A Improvements, MCP Standard Review and Sync, Technical Debt

???+ danger "✨ Open Features (1)"
    - [**#299**](https://github.com/IBM/mcp-context-forge/issues/299) - A2A Ecosystem Integration & Marketplace (Extends A2A support)

---

## Release 1.6.0 - New MCP Servers and Agents

!!! danger "Release 1.6.0 - In Progress (0%)"
    **Due:** 06 Jan 2026 | **Status:** Open
    New MCP Servers and Agents

???+ danger "✨ Open Features (1)"
    - [**#548**](https://github.com/IBM/mcp-context-forge/issues/548) - GraphQL API Support for Tool Discovery

---

## Unassigned Issues

!!! warning "Issues Without Release Assignment"
    The following issues are currently open but not assigned to any specific release:

??? abstract "✨ Features (3 completed, 2 open)"
    - ✅ [**#708**](https://github.com/IBM/mcp-context-forge/issues/708) - MCP Elicitation (v2025-06-18
    - ✅ [**#689**](https://github.com/IBM/mcp-context-forge/issues/689) - Getting "Unknown SSE event: keepalive" when trying to use virtual servers
    - [**#683**](https://github.com/IBM/mcp-context-forge/issues/683) - Debug headers and passthrough headers, e.g. X-Tenant-Id, X-Trace-Id, Authorization for time server (go) (draft)
    - [**#679**](https://github.com/IBM/mcp-context-forge/issues/679) - [Feature] Add enabled field to plugins/config.yaml
    - ✅ [**#306**](https://github.com/IBM/mcp-context-forge/issues/306) - Quick Start (manual install) gunicorn fails

??? abstract "🐛 Bugs (7 completed, 2 open)"
    - [**#715**](https://github.com/IBM/mcp-context-forge/issues/715) - [Bug]:Tool Edit Screen Issues – Field Mismatch & MCP Tool Validation Error
    - ✅ [**#704**](https://github.com/IBM/mcp-context-forge/issues/704) - Virtual Servers don't actually work as advertised v0.5.0
    - [**#700**](https://github.com/IBM/mcp-context-forge/issues/700) - Move async_testing to tests/async (draft)
    - ✅ [**#560**](https://github.com/IBM/mcp-context-forge/issues/560) - Can't list tools when running inside of a docker
    - ✅ [**#518**](https://github.com/IBM/mcp-context-forge/issues/518) - Runtime error from Redis when multiple sessions exist
    - ✅ [**#480**](https://github.com/IBM/mcp-context-forge/issues/480) - Alembic treated as first party dependency by isort
    - ✅ [**#479**](https://github.com/IBM/mcp-context-forge/issues/479) - Update make commands for alembic
    - ✅ [**#478**](https://github.com/IBM/mcp-context-forge/issues/478) - Alembic migration is broken
    - ✅ [**#436**](https://github.com/IBM/mcp-context-forge/issues/436) - Verify content length using the content itself when the content-length header is absent.

???+ check "❓ Completed Questions (2)"
    - ✅ [**#510**](https://github.com/IBM/mcp-context-forge/issues/510) - Create users - User management & RBAC
    - ✅ [**#509**](https://github.com/IBM/mcp-context-forge/issues/509) - Enterprise LDAP Integration

---

## Legend

- ✨ **Feature Request** - New functionality or enhancement
- 🐛 **Bug** - Issues that need to be fixed
- 🔒 **Security** - Security features and improvements
- ⚡ **Performance** - Performance optimizations
- 🔧 **Chore** - Maintenance, tooling, or infrastructure work
- 📚 **Documentation** - Documentation improvements or additions
- ❓ **Question** - User questions (typically closed after resolution)
- ✅ **Completed** - Issue has been resolved and closed

!!! tip "Contributing"
    Want to contribute to any of these features? Check out the individual GitHub issues for more details and discussion!
