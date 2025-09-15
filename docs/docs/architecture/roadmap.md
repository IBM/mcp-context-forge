# MCP Gateway Roadmap

!!! info "Release Overview"
    This roadmap outlines the planned development milestones for MCP Gateway, organized by release version with completion status and due dates.

## Release Status Summary

| Release | Due Date    | Completion | Status     | Description |
| ------- | ----------- | ---------- | ---------- | ----------- |
| 1.6.0   | 03 Feb 2026 | 0  %        | Open       | New MCP Servers and Agents |
| 1.5.0   | 20 Jan 2026 | 0  %        | Open       | Documentation, Technical Debt, Bugfixes |
| 1.4.0   | 06 Jan 2026 | 0  %        | Open       | Technical Debt and Quality |
| 1.3.0   | 23 Dec 2025 | 0  %        | Open       | Catalog Improvements, A2A Improvements, MCP Standard Review and Sync, Technical Debt |
| 1.2.0   | 09 Dec 2025 | 0  %        | Open       | Catalog Enhancements, Ratings, experience and UI |
| 1.1.0   | 25 Nov 2025 | 0  %        | Open       | Post-GA Testing, Bugfixing, Documentation, Performance and Scale |
| 1.0.0   | 11 Nov 2025 | 0  %        | Open       | General Availability & Release Candidate Hardening - stable & audited |
| 0.9.0   | 14 Oct 2025 | 8  %        | Open       | Interoperability, marketplaces & advanced connectivity |
| 0.8.0   | 30 Sep 2025 | 3  %        | Open       | Enterprise Security & Policy Guardrails |
| 0.7.0   | 16 Sep 2025 | 78 %        | Open       | Multitenancy and RBAC (Private/Team/Global catalogs), Extended Connectivity, Core Observability & Starter Agents (OpenAI and A2A) |
| 0.6.0   | 19 Aug 2025 | 100 %        | **Closed** | Security, Scale & Smart Automation |
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

!!! success "Release 0.6.0 - Completed (100%)"
    **Due:** 19 Aug 2025 | **Status:** Closed
    Security, Scale & Smart Automation

???+ check "✨ Completed Features (30)"
    - ✅ [**#773**](https://github.com/IBM/mcp-context-forge/issues/773) - Add support for external plugins
    - ✅ [**#749**](https://github.com/IBM/mcp-context-forge/issues/749) - MCP Reverse Proxy - Bridge Local Servers to Remote Gateways
    - ✅ [**#737**](https://github.com/IBM/mcp-context-forge/issues/737) - Bulk Tool Import
    - ✅ [**#735**](https://github.com/IBM/mcp-context-forge/issues/735) - Epic: Vendor Agnostic OpenTelemetry Observability Support
    - ✅ [**#727**](https://github.com/IBM/mcp-context-forge/issues/727) - Phoenix Observability Integration plugin
    - ✅ [**#720**](https://github.com/IBM/mcp-context-forge/issues/720) - Add CLI for authoring and packaging plugins
    - ✅ [**#708**](https://github.com/IBM/mcp-context-forge/issues/708) - MCP Elicitation (v2025-06-18)
    - ✅ [**#705**](https://github.com/IBM/mcp-context-forge/issues/705) - Option to completely remove Bearer token auth to MCP gateway
    - ✅ [**#690**](https://github.com/IBM/mcp-context-forge/issues/690) - Make SSE Keepalive Events Configurable
    - ✅ [**#689**](https://github.com/IBM/mcp-context-forge/issues/689) - Getting "Unknown SSE event: keepalive" when trying to use virtual servers
    - ✅ [**#682**](https://github.com/IBM/mcp-context-forge/issues/682) - Add tool hooks (tool_pre_invoke / tool_post_invoke) to plugin system
    - ✅ [**#673**](https://github.com/IBM/mcp-context-forge/issues/673) - Identify Next Steps for Plugin Development
    - ✅ [**#668**](https://github.com/IBM/mcp-context-forge/issues/668) - Add Null Checks and Improve Error Handling in Frontend Form Handlers (admin.js)
    - ✅ [**#586**](https://github.com/IBM/mcp-context-forge/issues/586) - Tag support with editing and validation across all APIs endpoints and UI (tags)
    - ✅ [**#540**](https://github.com/IBM/mcp-context-forge/issues/540) - Configurable Well-Known URI Handler including security.txt and robots.txt
    - ✅ [**#533**](https://github.com/IBM/mcp-context-forge/issues/533) - Add Additional Configurable Security Headers to APIs for Admin UI
    - ✅ [**#492**](https://github.com/IBM/mcp-context-forge/issues/492) - Change UI ID field name to UUID
    - ✅ [**#404**](https://github.com/IBM/mcp-context-forge/issues/404) - Add resources and prompts/prompt templates to time server
    - ✅ [**#380**](https://github.com/IBM/mcp-context-forge/issues/380) - REST Endpoints for Go fast-time-server
    - ✅ [**#368**](https://github.com/IBM/mcp-context-forge/issues/368) - Enhance Metrics Tab UI with Virtual Servers and Top 5 Performance Tables
    - ✅ [**#364**](https://github.com/IBM/mcp-context-forge/issues/364) - Add Log File Support to MCP Gateway
    - ✅ [**#344**](https://github.com/IBM/mcp-context-forge/issues/344) - Implement additional security headers and CORS configuration
    - ✅ [**#320**](https://github.com/IBM/mcp-context-forge/issues/320) - Update Streamable HTTP to fully support Virtual Servers
    - ✅ [**#319**](https://github.com/IBM/mcp-context-forge/issues/319) - AI Middleware Integration / Plugin Framework for extensible gateway capabilities
    - ✅ [**#186**](https://github.com/IBM/mcp-context-forge/issues/186) - Granular Configuration Export & Import (via UI & API)
    - ✅ [**#185**](https://github.com/IBM/mcp-context-forge/issues/185) - Portable Configuration Export & Import CLI (registry, virtual servers and prompts)
    - ✅ [**#138**](https://github.com/IBM/mcp-context-forge/issues/138) - View & Export Logs from Admin UI
    - ✅ [**#137**](https://github.com/IBM/mcp-context-forge/issues/137) - Track Creator & Timestamp Metadata for Servers, Tools, and Resources
    - ✅ [**#136**](https://github.com/IBM/mcp-context-forge/issues/136) - Downloadable JSON Client Config Generator from Admin UI
    - ✅ [**#94**](https://github.com/IBM/mcp-context-forge/issues/94) - Transport-Translation Bridge (`mcpgateway.translate`) any to any protocol conversion cli tool

???+ check "🐛 Completed Bugs (22)"
    - ✅ [**#774**](https://github.com/IBM/mcp-context-forge/issues/774) - Tools Annotations not working and need specificity for mentioning annotations
    - ✅ [**#765**](https://github.com/IBM/mcp-context-forge/issues/765) - Illegal IP address string passed to inet_aton during discovery process
    - ✅ [**#753**](https://github.com/IBM/mcp-context-forge/issues/753) - Tool invocation returns 'Invalid method' error after PR #746
    - ✅ [**#744**](https://github.com/IBM/mcp-context-forge/issues/744) - Gateway fails to connect to services behind CDNs/load balancers due to DNS resolution
    - ✅ [**#741**](https://github.com/IBM/mcp-context-forge/issues/741) - Enhance Server Creation/Editing UI for Prompt and Resource Association
    - ✅ [**#728**](https://github.com/IBM/mcp-context-forge/issues/728) - Streamable HTTP Translation Feature: Connects but Fails to List Tools, Resources, or Support Tool Calls
    - ✅ [**#716**](https://github.com/IBM/mcp-context-forge/issues/716) - Resources and Prompts not displaying in Admin Dashboard while Tools are visible
    - ✅ [**#696**](https://github.com/IBM/mcp-context-forge/issues/696) - SSE Tool Invocation Fails After Integration Type Migration post PR #678
    - ✅ [**#694**](https://github.com/IBM/mcp-context-forge/issues/694) - Enhanced Validation Missing in GatewayCreate
    - ✅ [**#685**](https://github.com/IBM/mcp-context-forge/issues/685) - Multiple Fixes and improved security for HTTP Header Passthrough Feature
    - ✅ [**#666**](https://github.com/IBM/mcp-context-forge/issues/666) - Vague/Unclear Error Message "Validation Failed" When Adding a REST Tool
    - ✅ [**#661**](https://github.com/IBM/mcp-context-forge/issues/661) - Database migration runs during doctest execution
    - ✅ [**#649**](https://github.com/IBM/mcp-context-forge/issues/649) - Duplicate Gateway Registration with Equivalent URLs Bypasses Uniqueness Check
    - ✅ [**#646**](https://github.com/IBM/mcp-context-forge/issues/646) - MCP Server/Federated Gateway Registration is failing
    - ✅ [**#560**](https://github.com/IBM/mcp-context-forge/issues/560) - Can't list tools when running inside of a docker
    - ✅ [**#557**](https://github.com/IBM/mcp-context-forge/issues/557) - Cleanup tool descriptions to remove newlines and truncate text
    - ✅ [**#526**](https://github.com/IBM/mcp-context-forge/issues/526) - Unable to add multiple headers when adding a gateway through UI
    - ✅ [**#520**](https://github.com/IBM/mcp-context-forge/issues/520) - Resource mime-type is always stored as text/plain
    - ✅ [**#518**](https://github.com/IBM/mcp-context-forge/issues/518) - Runtime error from Redis when multiple sessions exist
    - ✅ [**#481**](https://github.com/IBM/mcp-context-forge/issues/481) - Intermittent test_resource_cache.py::test_expiration - AssertionError: assert 'bar' is None
    - ✅ [**#452**](https://github.com/IBM/mcp-context-forge/issues/452) - integrationType should only support REST, not MCP (Remove Integration Type: MCP)
    - ✅ [**#405**](https://github.com/IBM/mcp-context-forge/issues/405) - Fix the go time server annotation (it shows as destructive)

???+ check "🔒 Completed Security (3)"
    - ✅ [**#540**](https://github.com/IBM/mcp-context-forge/issues/540) - Configurable Well-Known URI Handler including security.txt and robots.txt
    - ✅ [**#533**](https://github.com/IBM/mcp-context-forge/issues/533) - Add Additional Configurable Security Headers to APIs for Admin UI
    - ✅ [**#208**](https://github.com/IBM/mcp-context-forge/issues/208) - HTTP Header Passthrough (forward headers to MCP server)

???+ check "🔧 Completed Chores (6)"
    - ✅ [**#672**](https://github.com/IBM/mcp-context-forge/issues/672) - Part 2: Replace Raw Errors with Friendly Messages in main.py
    - ✅ [**#317**](https://github.com/IBM/mcp-context-forge/issues/317) - Script to add relative file path header to each file and verify top level docstring
    - ✅ [**#315**](https://github.com/IBM/mcp-context-forge/issues/315) - Check SPDX headers Makefile and GitHub Actions target - ensure all files have File, Author(s) and SPDX headers
    - ✅ [**#280**](https://github.com/IBM/mcp-context-forge/issues/280) - Add mutation testing with mutmut for test quality validation
    - ✅ [**#256**](https://github.com/IBM/mcp-context-forge/issues/256) - Implement comprehensive fuzz testing automation and Makefile targets (hypothesis, atheris, schemathesis, RESTler)
    - ✅ [**#254**](https://github.com/IBM/mcp-context-forge/issues/254) - Async Code Testing and Performance Profiling Makefile targets (flake8-async, cprofile, snakeviz, aiomonitor)



---

## Release 0.7.0 - Multitenancy and RBAC (Private/Team/Global catalogs), Extended Connectivity, Core Observability & Starter Agents (OpenAI and A2A)

!!! success "Release 0.7.0 - Nearly Complete (78%)"
    **Due:** 16 Sep 2025 | **Status:** Open
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
    - ✅ [**#282**](https://github.com/IBM/mcp-context-forge/issues/282) - [SECURITY FEATURE]: Per-Virtual-Server API Keys with Scoped Access
    - ✅ [**#283**](https://github.com/IBM/mcp-context-forge/issues/283) - [SECURITY FEATURE]: Role-Based Access Control (RBAC) - User/Team/Global Scopes for full multi-tenancy support
    - ✅ [**#278**](https://github.com/IBM/mcp-context-forge/issues/278) - [Feature Request]: Authentication & Authorization - Google SSO Integration Tutorial (Depends on #220)
    - ✅ [**#220**](https://github.com/IBM/mcp-context-forge/issues/220) - [AUTH FEATURE]: Authentication & Authorization - SSO + Identity-Provider Integration
    - ✅ [**#87**](https://github.com/IBM/mcp-context-forge/issues/87) - [Feature Request]: Epic: Secure JWT Token Catalog with Per-User Expiry and Revocation

???+ check "🐛 Completed Bugs (5)"
    - ✅ [**#958**](https://github.com/IBM/mcp-context-forge/issues/958) - [Bug]: Incomplete Visibility Implementation
    - ✅ [**#955**](https://github.com/IBM/mcp-context-forge/issues/955) - [Bug]: Team Selection implementation not tagging or loading added servers, tools, gateways
    - ✅ [**#942**](https://github.com/IBM/mcp-context-forge/issues/942) - [Bug]: DateTime UTC Fixes Required
    - ✅ [**#587**](https://github.com/IBM/mcp-context-forge/issues/587) - [Bug]: REST Tool giving error
    - ✅ [**#232**](https://github.com/IBM/mcp-context-forge/issues/232) - [Bug]: Leaving Auth to None fails

???+ check "📚 Completed Documentation (3)"
    - ✅ [**#323**](https://github.com/IBM/mcp-context-forge/issues/323) - Add Developer Guide for using fast-time-server via JSON-RPC commands using curl or stdio
    - ✅ [**#19**](https://github.com/IBM/mcp-context-forge/issues/19) - Add Developer Guide for using MCP via the CLI (curl commands, JSON-RPC)
    - ✅ [**#818**](https://github.com/IBM/mcp-context-forge/issues/818) - [Docs]: Readme ghcr.io/ibm/mcp-context-forge:0.6.0 image still building

???+ danger "🐛 Open Bugs (5)"
    - [**#969**](https://github.com/IBM/mcp-context-forge/issues/969) - Backend Multi-Tenancy Issues - Critical bugs and missing features
    - [**#967**](https://github.com/IBM/mcp-context-forge/issues/967) - UI Gaps in Multi-Tenancy Support - Visibility fields missing for most resource types
    - [**#625**](https://github.com/IBM/mcp-context-forge/issues/625) - [Bug]: Gateway unable to register gateway or call tools on MacOS
    - [**#464**](https://github.com/IBM/mcp-context-forge/issues/464) - [Bug]: MCP Server "Active" status not getting updated under "Gateways/MCP Servers" when the MCP Server shutdown.
    - [**#448**](https://github.com/IBM/mcp-context-forge/issues/448) - [Bug]: MCP server with custom base path "/api" instead of "mcp" or "sse" is not working

???+ danger "✨ Open Features (2)"
    - [**#386**](https://github.com/IBM/mcp-context-forge/issues/386) - [Feature Request]: Gateways/MCP Servers Page Refresh
    - [**#172**](https://github.com/IBM/mcp-context-forge/issues/172) - [Feature Request]: Enable Auto Refresh and Reconnection for MCP Servers in Gateways

???+ danger "📚 Open Documentation (1)"
    - [**#834**](https://github.com/IBM/mcp-context-forge/issues/834) - [Bug]: Existing tool configurations are not updating after changes to the MCP server configuration.

---

## Release 0.8.0 - Enterprise Security & Policy Guardrails

!!! danger "Release 0.8.0 - In Progress (3%)"
    **Due:** 30 Sep 2025 | **Status:** Open
    Enterprise Security & Policy Guardrails

???+ check "🐛 Completed Bugs (2)"
    - ✅ [**#949**](https://github.com/IBM/mcp-context-forge/issues/949) - [Bug]: Tool invocation for an MCP server authorized by OAUTH2 fails
    - ✅ [**#948**](https://github.com/IBM/mcp-context-forge/issues/948) - [Bug]:MCP OAUTH2 authenticate server is shown as offline after is added

???+ check "🏗️ Completed Sample Servers (2)"
    - ✅ [**#920**](https://github.com/IBM/mcp-context-forge/issues/920) - Sample MCP Server - Go (calculator-server)
    - ✅ [**#900**](https://github.com/IBM/mcp-context-forge/issues/900) - Sample MCP Server - Python (data-analysis-server)

???+ danger "🔌 Open Plugin Features (12)"
    - [**#1005**](https://github.com/IBM/mcp-context-forge/issues/1005) - [Plugin] Create VirusTotal Checker Plugin using Plugin Framework
    - [**#1004**](https://github.com/IBM/mcp-context-forge/issues/1004) - [Plugin] Create URL Reputation Plugin using Plugin Framework
    - [**#1003**](https://github.com/IBM/mcp-context-forge/issues/1003) - [Plugin] Create Schema Guard Plugin using Plugin Framework
    - [**#1002**](https://github.com/IBM/mcp-context-forge/issues/1002) - [Plugin] Create Retry with Backoff Plugin using Plugin Framework
    - [**#1001**](https://github.com/IBM/mcp-context-forge/issues/1001) - [Plugin] Create Rate Limiter Plugin using Plugin Framework
    - [**#1000**](https://github.com/IBM/mcp-context-forge/issues/1000) - [Plugin] Create Output Length Guard Plugin using Plugin Framework
    - [**#999**](https://github.com/IBM/mcp-context-forge/issues/999) - [Plugin] Create Markdown Cleaner Plugin using Plugin Framework
    - [**#998**](https://github.com/IBM/mcp-context-forge/issues/998) - [Plugin] Create JSON Repair Plugin using Plugin Framework
    - [**#997**](https://github.com/IBM/mcp-context-forge/issues/997) - [Plugin] Create HTML to Markdown Plugin using Plugin Framework
    - [**#996**](https://github.com/IBM/mcp-context-forge/issues/996) - [Plugin] Create File Type Allowlist Plugin using Plugin Framework
    - [**#995**](https://github.com/IBM/mcp-context-forge/issues/995) - [Plugin] Create Code Safety Linter Plugin using Plugin Framework
    - [**#994**](https://github.com/IBM/mcp-context-forge/issues/994) - [Plugin] Create Cached Tool Result Plugin using Plugin Framework

???+ danger "🔒 Open Security Features (44)"
    - [**#979**](https://github.com/IBM/mcp-context-forge/issues/979) - [Feature Request]: OAuth Dynamic Client Registration
    - [**#975**](https://github.com/IBM/mcp-context-forge/issues/975) - Feature Request: Implement Session Persistence & Pooling for Improved Performance and State Continuity
    - [**#974**](https://github.com/IBM/mcp-context-forge/issues/974) - [Feature Request]: Make users change default admin passwords and secrets for production deployments.
    - [**#964**](https://github.com/IBM/mcp-context-forge/issues/964) - Support dynamic environment variable injection in mcpgateway.translate for STDIO MCP servers
    - [**#950**](https://github.com/IBM/mcp-context-forge/issues/950) - Session Management & Tool Invocation with Gateway vs Direct MCP Client–Server
    - [**#946**](https://github.com/IBM/mcp-context-forge/issues/946) - [Bug]: Alembic migrations fails in docker compose setup
    - [**#945**](https://github.com/IBM/mcp-context-forge/issues/945) - [Bug]: Unique Constraint is not allowing Users to create servers/tools/resources/prompts with Names already used by another User
    - [**#941**](https://github.com/IBM/mcp-context-forge/issues/941) - [Bug]: Access Token scoping not working
    - [**#939**](https://github.com/IBM/mcp-context-forge/issues/939) - [Bug]: Missing Document links in SSO page for Team/RBAC management
    - [**#932**](https://github.com/IBM/mcp-context-forge/issues/932) - [Feature Request]: Air-Gapped Environment Support
    - [**#931**](https://github.com/IBM/mcp-context-forge/issues/931) - [Bug]: Helm install does not work when kubeVersion has vendor specific suffix
    - [**#926**](https://github.com/IBM/mcp-context-forge/issues/926) - Bootstrap fails to assign platform_admin role due to foreign key constraint violation
    - [**#922**](https://github.com/IBM/mcp-context-forge/issues/922) - [Bug]: In 0.6.0 Version, IFraming the admin UI is not working.
    - [**#810**](https://github.com/IBM/mcp-context-forge/issues/810) - [Bug]: Ensure Test Cases Use Mock Database instead of Main DB
    - [**#806**](https://github.com/IBM/mcp-context-forge/issues/806) - [CHORE]: Bulk Import – Missing error messages and registration feedback in UI
    - [**#782**](https://github.com/IBM/mcp-context-forge/issues/782) - [Feature Request]: OAuth Enhancement following PR 768
    - [**#758**](https://github.com/IBM/mcp-context-forge/issues/758) - Implement missing MCP protocol methods
    - [**#756**](https://github.com/IBM/mcp-context-forge/issues/756) - [Feature Request]: REST Passthrough APIs with Pre/Post Plugins (JSONPath and filters)
    - [**#751**](https://github.com/IBM/mcp-context-forge/issues/751) - [Feature] Implement MCP Evaluation Benchmarks Suite
    - [**#743**](https://github.com/IBM/mcp-context-forge/issues/743) - [Feature Request]: Enhance Server Creation/Editing UI for Prompt and Resource Association
    - [**#738**](https://github.com/IBM/mcp-context-forge/issues/738) - [Feature Request]: Configuration Database for Dynamic Settings Management
    - [**#732**](https://github.com/IBM/mcp-context-forge/issues/732) - [Feature Request]: Enhance Handling of Long Tool Descriptions
    - [**#699**](https://github.com/IBM/mcp-context-forge/issues/699) - [Feature]: Metrics Enhancement (export all data, capture all metrics, fix last used timestamps, UI improvements)
    - [**#683**](https://github.com/IBM/mcp-context-forge/issues/683) - [Feature Request]: Debug headers and passthrough headers, e.g. X-Tenant-Id, X-Trace-Id, Authorization for time server (go) (draft)
    - [**#674**](https://github.com/IBM/mcp-context-forge/issues/674) - [CHORE]: Automate release management process (draft)
    - [**#654**](https://github.com/IBM/mcp-context-forge/issues/654) - [Feature Request]: Pre-register checks (mcp server scan) (draft)
    - [**#647**](https://github.com/IBM/mcp-context-forge/issues/647) - Configurable caching for tools (draft)
    - [**#636**](https://github.com/IBM/mcp-context-forge/issues/636) - [Feature]: Add PyInstaller support for building standalone binaries for all platforms
    - [**#595**](https://github.com/IBM/mcp-context-forge/issues/595) - [CHORE] Investigate potential migration to UUID7 (draft)
    - [**#589**](https://github.com/IBM/mcp-context-forge/issues/589) - [CHORE]: generating build provenance attestations for workflow artifacts (draft)
    - [**#574**](https://github.com/IBM/mcp-context-forge/issues/574) - [CHORE]: Run pyupgrade to upgrade python syntax (draft)
    - [**#568**](https://github.com/IBM/mcp-context-forge/issues/568) - [Feature Request]: Configurable client require TLS cert, and certificate setup for MCP Servers with private CA (draft)
    - [**#566**](https://github.com/IBM/mcp-context-forge/issues/566) - [Feature Request]: Add support for limiting specific fields to user defined values (draft)
    - [**#565**](https://github.com/IBM/mcp-context-forge/issues/565) - [Feature Request]: Docs for https://github.com/block/goose (draft)
    - [**#543**](https://github.com/IBM/mcp-context-forge/issues/543) - [SECURITY FEATURE]: CSRF Token Protection System
    - [**#542**](https://github.com/IBM/mcp-context-forge/issues/542) - [SECURITY FEATURE]: Helm Chart - Enterprise Secrets Management Integration (Vault)
    - [**#541**](https://github.com/IBM/mcp-context-forge/issues/541) - [SECURITY FEATURE]: Enhanced Session Management for Admin UI
    - [**#539**](https://github.com/IBM/mcp-context-forge/issues/539) - [SECURITY FEATURE]: Tool Execution Limits & Resource Controls
    - [**#538**](https://github.com/IBM/mcp-context-forge/issues/538) - [SECURITY FEATURE] Content Size & Type Security Limits for Resources & Prompts
    - [**#537**](https://github.com/IBM/mcp-context-forge/issues/537) - [SECURITY FEATURE]: Simple Endpoint Feature Flags (selectively enable or disable tools, resources, prompts, servers, gateways, roots)
    - [**#536**](https://github.com/IBM/mcp-context-forge/issues/536) - [SECURITY FEATURE]: Generic IP-Based Access Control (allowlist)
    - [**#535**](https://github.com/IBM/mcp-context-forge/issues/535) - [SECURITY FEATURE]: Audit Logging System
    - [**#534**](https://github.com/IBM/mcp-context-forge/issues/534) - [SECURITY FEATURE]: Add Security Configuration Validation and Startup Checks
    - [**#505**](https://github.com/IBM/mcp-context-forge/issues/505) - [Feature Request]: Add ENV token forwarding management per tool (draft)

???+ danger "🐛 Open Bugs (14)"
    - [**#959**](https://github.com/IBM/mcp-context-forge/issues/959) - [Bug]: Unable to Re-add Team Member Due to Unique Constraint on (team_id, user_email)
    - [**#867**](https://github.com/IBM/mcp-context-forge/issues/867) - [Bug]: update_gateway does not persist passthrough_headers field
    - [**#865**](https://github.com/IBM/mcp-context-forge/issues/865) - [Bug]: Static assets return 404 when APP_ROOT_PATH is configured
    - [**#861**](https://github.com/IBM/mcp-context-forge/issues/861) - [Bug]: Passthrough header parameters not persisted to database
    - [**#856**](https://github.com/IBM/mcp-context-forge/issues/856) - [Bug]: Admin UI: Associated tools checkboxes on Virtual Servers edit not pre-populated due to ID vs name mismatch
    - [**#848**](https://github.com/IBM/mcp-context-forge/issues/848) - [Feature Request]: Allow same prompt name when adding two different mcp server
    - [**#845**](https://github.com/IBM/mcp-context-forge/issues/845) - [Bug]:2025-08-28 05:47:06,733 - mcpgateway.services.gateway_service - ERROR - FileLock health check failed: can't start new thread
    - [**#842**](https://github.com/IBM/mcp-context-forge/issues/842) - [Bug]: 401 on privileged actions after cold restart despite valid login
    - [**#841**](https://github.com/IBM/mcp-context-forge/issues/841) - [Bug]: For A2A Agent, tools are not getting listed under Global Tools
    - [**#840**](https://github.com/IBM/mcp-context-forge/issues/840) - [Bug]: For A2A Agent test not working
    - [**#839**](https://github.com/IBM/mcp-context-forge/issues/839) - [Bug]:Getting 401 un-authorized on Testing tools in "In-Cognito" mode.
    - [**#836**](https://github.com/IBM/mcp-context-forge/issues/836) - [Bug]: Server Tags Not Propagated to Tools via /tools Endpoint
    - [**#835**](https://github.com/IBM/mcp-context-forge/issues/835) - [Feature Request]: Adding Custom annotation for the tools
    - [**#383**](https://github.com/IBM/mcp-context-forge/issues/383) - [Bug]: Remove migration step from Helm chart (now automated, no longer needed)

???+ danger "🔌 Additional Plugin Features (3)"
    - [**#895**](https://github.com/IBM/mcp-context-forge/issues/895) - [Plugin] Create Header Injector Plugin using Plugin Framework
    - [**#894**](https://github.com/IBM/mcp-context-forge/issues/894) - [Plugin] Create Secrets Detection Plugin using Plugin Framework
    - [**#893**](https://github.com/IBM/mcp-context-forge/issues/893) - [Plugin] Create JSON Schema Validator Plugin using Plugin Framework

???+ danger "🏗️ Open Sample Servers & Agents (15)"
    - [**#921**](https://github.com/IBM/mcp-context-forge/issues/921) - Sample MCP Server - Python (weather-data-server)
    - [**#919**](https://github.com/IBM/mcp-context-forge/issues/919) - Sample MCP Server - Python (qr-code-server)
    - [**#912**](https://github.com/IBM/mcp-context-forge/issues/912) - Sample Agent - IBM BeeAI Framework Integration (OpenAI & A2A Endpoints)
    - [**#911**](https://github.com/IBM/mcp-context-forge/issues/911) - Create IBM Granite Embedding Models MCP Server
    - [**#910**](https://github.com/IBM/mcp-context-forge/issues/910) - Create IBM Granite Geospatial Models MCP Server
    - [**#909**](https://github.com/IBM/mcp-context-forge/issues/909) - Create IBM Granite Guardian Safety Models MCP Server
    - [**#908**](https://github.com/IBM/mcp-context-forge/issues/908) - Create IBM Granite Time Series Models MCP Server
    - [**#907**](https://github.com/IBM/mcp-context-forge/issues/907) - Create IBM Granite Speech Models MCP Server
    - [**#906**](https://github.com/IBM/mcp-context-forge/issues/906) - Create IBM Granite Vision Models MCP Server
    - [**#905**](https://github.com/IBM/mcp-context-forge/issues/905) - Create IBM Granite Language Models MCP Server
    - [**#904**](https://github.com/IBM/mcp-context-forge/issues/904) - Sample MCP Server - TypeScript (real-time-collaboration-server)
    - [**#903**](https://github.com/IBM/mcp-context-forge/issues/903) - Sample MCP Server - TypeScript (web-automation-server)
    - [**#902**](https://github.com/IBM/mcp-context-forge/issues/902) - Sample MCP Server - Rust (performance-benchmark-server)
    - [**#901**](https://github.com/IBM/mcp-context-forge/issues/901) - Sample MCP Server - Rust (crypto-tools-server)
    - [**#899**](https://github.com/IBM/mcp-context-forge/issues/899) - Sample MCP Server - Python (ml-inference-server)

???+ danger "🖥️ Open Sample Servers (3)"
    - [**#898**](https://github.com/IBM/mcp-context-forge/issues/898) - Sample MCP Server - Go (system-monitor-server)
    - [**#897**](https://github.com/IBM/mcp-context-forge/issues/897) - Sample MCP Server - Go (database-query-server)
    - [**#896**](https://github.com/IBM/mcp-context-forge/issues/896) - Add Prompt Authoring Tools Category to MCP Eval Server

???+ danger "📚 Open Documentation (30)"
    - [**#918**](https://github.com/IBM/mcp-context-forge/issues/918) - Document Javadocs.dev MCP Server integration with MCP Gateway
    - [**#917**](https://github.com/IBM/mcp-context-forge/issues/917) - Document Hugging Face MCP Server integration with MCP Gateway
    - [**#916**](https://github.com/IBM/mcp-context-forge/issues/916) - Document monday.com MCP Server integration with MCP Gateway
    - [**#915**](https://github.com/IBM/mcp-context-forge/issues/915) - Document GitHub MCP Server integration with MCP Gateway
    - [**#914**](https://github.com/IBM/mcp-context-forge/issues/914) - Document Box MCP Server integration with MCP Gateway
    - [**#913**](https://github.com/IBM/mcp-context-forge/issues/913) - Document Atlassian MCP Server integration with MCP Gateway
    - [**#892**](https://github.com/IBM/mcp-context-forge/issues/892) - Update and test IBM Cloud deployment documentation and automation
    - [**#891**](https://github.com/IBM/mcp-context-forge/issues/891) - Document BeeAI Framework integration with MCP Gateway
    - [**#890**](https://github.com/IBM/mcp-context-forge/issues/890) - Document Langflow as MCP Server integration with MCP Gateway
    - [**#889**](https://github.com/IBM/mcp-context-forge/issues/889) - Document MCP Composer integration with MCP Gateway
    - [**#888**](https://github.com/IBM/mcp-context-forge/issues/888) - Document Docling MCP Server integration with MCP Gateway
    - [**#887**](https://github.com/IBM/mcp-context-forge/issues/887) - Document DataStax Astra DB MCP Server integration with MCP Gateway
    - [**#886**](https://github.com/IBM/mcp-context-forge/issues/886) - Document Vault Radar MCP Server integration with MCP Gateway
    - [**#885**](https://github.com/IBM/mcp-context-forge/issues/885) - Document Terraform MCP Server integration with MCP Gateway
    - [**#884**](https://github.com/IBM/mcp-context-forge/issues/884) - Document WxMCPServer (webMethods Hybrid Integration) integration with MCP Gateway
    - [**#883**](https://github.com/IBM/mcp-context-forge/issues/883) - Document IBM API Connect for GraphQL MCP integration with MCP Gateway
    - [**#882**](https://github.com/IBM/mcp-context-forge/issues/882) - Document IBM Storage Insights MCP Server integration with MCP Gateway
    - [**#881**](https://github.com/IBM/mcp-context-forge/issues/881) - Document IBM Instana MCP Server integration with MCP Gateway
    - [**#880**](https://github.com/IBM/mcp-context-forge/issues/880) - Document IBM Cloud VPC MCP Server integration with MCP Gateway
    - [**#879**](https://github.com/IBM/mcp-context-forge/issues/879) - Document IBM Cloud Code Engine MCP Server integration with MCP Gateway
    - [**#878**](https://github.com/IBM/mcp-context-forge/issues/878) - Document IBM Cloud MCP Server integration with MCP Gateway
    - [**#877**](https://github.com/IBM/mcp-context-forge/issues/877) - Document IBM watsonx.data Document Retrieval MCP Server integration with MCP Gateway
    - [**#876**](https://github.com/IBM/mcp-context-forge/issues/876) - Document IBM ODM MCP Server integration with MCP Gateway
    - [**#875**](https://github.com/IBM/mcp-context-forge/issues/875) - Document IBM MQ Server MCP integration with MCP Gateway
    - [**#874**](https://github.com/IBM/mcp-context-forge/issues/874) - Document IBM Decision Intelligence MCP Server integration with MCP Gateway
    - [**#873**](https://github.com/IBM/mcp-context-forge/issues/873) - Document watsonx Orchestrate integration with MCP Gateway
    - [**#872**](https://github.com/IBM/mcp-context-forge/issues/872) - Document watsonx.ai integration with MCP Gateway
    - [**#871**](https://github.com/IBM/mcp-context-forge/issues/871) - Document Langflow integration with MCP Gateway
    - [**#503**](https://github.com/IBM/mcp-context-forge/issues/503) - Tutorial: OpenWebUI with Ollama, LiteLLM, MCPO, and MCP Gateway Deployment Guide (Draft)
    - [**#277**](https://github.com/IBM/mcp-context-forge/issues/277) - [Feature Request]: Authentication & Authorization - GitHub SSO Integration Tutorial (Depends on #220)

!!! info "177 Total Issues (4 completed, 173 open)"
    This release contains a comprehensive set of enterprise security features, plugins, sample servers, and documentation. Due to the large scope, issues are grouped by category for better organization.

    **Issue Breakdown:**
    - 🔌 15 Plugin Features (12 main + 3 additional)
    - 🔒 44 Security Features
    - 🐛 16 Bugs (2 completed + 14 open)
    - 🏗️ 20 Sample Servers & Agents
    - 📚 30 Documentation Issues
    - 🔧 Various chores and infrastructure improvements

---

## Release 0.9.0 - Interoperability, marketplaces & advanced connectivity

!!! danger "Release 0.9.0 - In Progress (8%)"
    **Due:** 14 Oct 2025 | **Status:** Open
    Interoperability, marketplaces & advanced connectivity

???+ check "✨ Completed Features (2)"
    - ✅ [**#298**](https://github.com/IBM/mcp-context-forge/issues/298) - A2A Initial Support - Add A2A Servers as Tools
    - ✅ [**#243**](https://github.com/IBM/mcp-context-forge/issues/243) - a2a compatibility?

???+ danger "✨ Open Features (13)"
    - [**#546**](https://github.com/IBM/mcp-context-forge/issues/546) - Protocol Version Negotiation & Backward Compatibility
    - [**#545**](https://github.com/IBM/mcp-context-forge/issues/545) - Hot-Reload Configuration Without Restart (move from .env to configuration database table) (draft)
    - [**#295**](https://github.com/IBM/mcp-context-forge/issues/295) - MCP Server Marketplace
    - [**#294**](https://github.com/IBM/mcp-context-forge/issues/294) - Automated MCP Server Testing and Certification
    - [**#288**](https://github.com/IBM/mcp-context-forge/issues/288) - MariaDB Support Testing, Documentation, CI/CD (alongside PostgreSQL & SQLite)
    - [**#276**](https://github.com/IBM/mcp-context-forge/issues/276) - Terraform Module – "mcp-gateway-ibm-cloud" supporting IKS, ROKS, Code Engine targets
    - [**#275**](https://github.com/IBM/mcp-context-forge/issues/275) - Terraform Module - "mcp-gateway-gcp" supporting GKE and Cloud Run
    - [**#274**](https://github.com/IBM/mcp-context-forge/issues/274) - Terraform Module - "mcp-gateway-azure" supporting AKS and ACA
    - [**#273**](https://github.com/IBM/mcp-context-forge/issues/273) - Terraform Module - "mcp-gateway-aws" supporting both EKS and ECS Fargate targets
    - [**#272**](https://github.com/IBM/mcp-context-forge/issues/272) - Observability - Pre-built Grafana Dashboards & Loki Log Export
    - [**#270**](https://github.com/IBM/mcp-context-forge/issues/270) - MCP Server – Go Implementation ("libreoffice-server")
    - [**#269**](https://github.com/IBM/mcp-context-forge/issues/269) - MCP Server - Go Implementation (LaTeX Service)
    - [**#268**](https://github.com/IBM/mcp-context-forge/issues/268) - Sample MCP Server - Haskell Implementation ("pandoc-server") (html, docx, pptx, latex conversion)

???+ danger "✨ Open Features (8)"
    - [**#267**](https://github.com/IBM/mcp-context-forge/issues/267) - Sample MCP Server – Java Implementation ("plantuml-server")
    - [**#266**](https://github.com/IBM/mcp-context-forge/issues/266) - Sample MCP Server - Rust Implementation ("filesystem-server")
    - [**#209**](https://github.com/IBM/mcp-context-forge/issues/209) - Anthropic Desktop Extensions DTX directory/marketplace
    - [**#182**](https://github.com/IBM/mcp-context-forge/issues/182) - Semantic tool auto-filtering
    - [**#130**](https://github.com/IBM/mcp-context-forge/issues/130) - Dynamic LLM-Powered Tool Generation via Prompt
    - [**#123**](https://github.com/IBM/mcp-context-forge/issues/123) - Dynamic Server Catalog via Rule, Regexp, Tags - or LLM-Based Selection
    - [**#114**](https://github.com/IBM/mcp-context-forge/issues/114) - Connect to Dockerized MCP Servers via STDIO
    - [**#80**](https://github.com/IBM/mcp-context-forge/issues/80) - Publish a multi-architecture container (including ARM64) support

???+ danger "🔧 Open Chores (1)"
    - [**#290**](https://github.com/IBM/mcp-context-forge/issues/290) - Enhance Gateway Tuning Guide with PostgreSQL Deep-Dive

---

## Release 1.0.0 - General Availability & Release Candidate Hardening - stable & audited

!!! danger "Release 1.0.0 - In Progress (0%)"
    **Due:** 11 Nov 2025 | **Status:** Open
    General Availability & Release Candidate Hardening - stable & audited

???+ danger "📚 Open Documentation (2)"
    - [**#264**](https://github.com/IBM/mcp-context-forge/issues/264) - GA Documentation Review & End-to-End Validation Audit
    - [**#22**](https://github.com/IBM/mcp-context-forge/issues/22) - Add BeeAI Framework client integration (Python & TypeScript)

---

## Release 1.1.0 - Post-GA Testing, Bugfixing, Documentation, Performance and Scale

!!! danger "Release 1.1.0 - In Progress (0%)"
    **Due:** 25 Nov 2025 | **Status:** Open
    Post-GA Testing, Bugfixing, Documentation, Performance and Scale

???+ danger "✨ Open Features (2)"
    - [**#707**](https://github.com/IBM/mcp-context-forge/issues/707) - Customizable Admin Panel
    - [**#293**](https://github.com/IBM/mcp-context-forge/issues/293) - Intelligent Load Balancing for Redundant MCP Servers

---

## Release 1.2.0 - Catalog Enhancements, Ratings, experience and UI

!!! danger "Release 1.2.0 - In Progress (0%)"
    **Due:** 09 Dec 2025 | **Status:** Open
    Catalog Enhancements, Ratings, experience and UI

???+ danger "✨ Open Features (2)"
    - [**#547**](https://github.com/IBM/mcp-context-forge/issues/547) - Built-in MCP Server Health Dashboard
    - [**#296**](https://github.com/IBM/mcp-context-forge/issues/296) - MCP Server Rating and Review System

---

## Release 1.3.0 - Catalog Improvements, A2A Improvements, MCP Standard Review and Sync, Technical Debt

!!! danger "Release 1.3.0 - In Progress (0%)"
    **Due:** 23 Dec 2025 | **Status:** Open
    Catalog Improvements, A2A Improvements, MCP Standard Review and Sync, Technical Debt

???+ danger "✨ Open Features (1)"
    - [**#299**](https://github.com/IBM/mcp-context-forge/issues/299) - A2A Ecosystem Integration & Marketplace (Extends A2A support)

---

## Unassigned Issues

!!! warning "Issues Without Release Assignment"
    The following issues are not assigned to any specific release (open or completed):

??? abstract "✨ Features (2 completed, 1 open)"
    - ✅ [**#752**](https://github.com/IBM/mcp-context-forge/issues/752) - [Feature] Create mcp-eval-server: MCP Server for Agent Performance Evaluation
    - ✅ [**#679**](https://github.com/IBM/mcp-context-forge/issues/679) - [Feature] Add enabled field to plugins/config.yaml
    - [**#978**](https://github.com/IBM/mcp-context-forge/issues/978) - Support Content-Type: application/x-www-form-urlencoded

??? abstract "🐛 Bugs (12 completed, 0 open)"
    - ✅ [**#962**](https://github.com/IBM/mcp-context-forge/issues/962) - Bridge stdio MCP with ENV variable requirement
    - ✅ [**#954**](https://github.com/IBM/mcp-context-forge/issues/954) - [Bug]: Metadata fields not populated in view
    - ✅ [**#952**](https://github.com/IBM/mcp-context-forge/issues/952) - [Bug]: Tool's long descriptions make Create MCP Server to fail
    - ✅ [**#943**](https://github.com/IBM/mcp-context-forge/issues/943) - [Bug]: Team/RBAC feature not working as expected
    - ✅ [**#857**](https://github.com/IBM/mcp-context-forge/issues/857) - [Bug]: Prompts, Servers, Tools, Resources - Filtering via tags from swagger UI - not working
    - ✅ [**#855**](https://github.com/IBM/mcp-context-forge/issues/855) - [Bug]: Tool calls are failing due to 20s timeout
    - ✅ [**#804**](https://github.com/IBM/mcp-context-forge/issues/804) - [Bug]: JSON-RPC methods misrouted as tools in MCP Gateway v0.5.0 (Tool not found: notifications/initialized / tools/call)
    - ✅ [**#803**](https://github.com/IBM/mcp-context-forge/issues/803) - [Bug]: streamable_http - ERROR - Error in message router - ClosedResourceError
    - ✅ [**#779**](https://github.com/IBM/mcp-context-forge/issues/779) - [Bug]: Refactor and Optimize MCP Gateway Wrapper for Performance and Maintainability
    - ✅ [**#740**](https://github.com/IBM/mcp-context-forge/issues/740) - [Bug]:"REST" Add Tool and All Integration Edit Tool Not Working After PR #731
    - ✅ [**#715**](https://github.com/IBM/mcp-context-forge/issues/715) - [Bug]:Tool Edit Screen Issues – Field Mismatch & MCP Tool Validation Error
    - ✅ [**#700**](https://github.com/IBM/mcp-context-forge/issues/700) - [Bug]: Move async_testing to tests/async

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
