# Changelog

> All notable changes to this project will be documented in this file. The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and this project **adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html)**.

---

## [1.0.0-BETA-2] - 2026-01-20 - Performance, Scale & Reliability

### Overview

This release delivers **massive performance improvements**, **enterprise-scale reliability**, and **production-hardening** with **222 issues resolved** (103 features, 97 bugs, 22 tasks):

- **⚡ 103 Features** - N+1 query elimination, connection pooling (PgBouncer), caching (L1/L2), Granian HTTP server, orjson serialization
- **🔧 97 Bug Fixes** - RBAC, pagination, OAuth, Admin UI, multi-tenancy, and MCP protocol compliance
- **🔐 Security Enhancements** - JWT lifecycle management, environment isolation, team membership validation
- **🏗️ Platform Expansion** - ppc64le (IBM POWER) architecture, external PostgreSQL support, Helm improvements
- **📊 Observability** - Prometheus/Grafana monitoring profile, metrics rollup optimization, detailed request logging

> **Performance Highlights**: Under sustained load testing (4000+ concurrent users), this release achieves **10x+ latency reduction** through N+1 query elimination, **50%+ connection reduction** via PgBouncer pooling, and **3x+ throughput improvement** with Granian HTTP server.

### ⚠️ Breaking Changes

#### **🐘 PostgreSQL Driver Migration: psycopg2 → psycopg3** ([#1740](https://github.com/IBM/mcp-context-forge/issues/1740), [#2142](https://github.com/IBM/mcp-context-forge/issues/2142))

**Action Required**: Update your `DATABASE_URL` connection string format.

```bash
# OLD (psycopg2) - No longer supported
DATABASE_URL=postgresql://postgres:password@localhost:5432/mcp

# NEW (psycopg3) - Required format
DATABASE_URL=postgresql+psycopg://postgres:password@localhost:5432/mcp
```

**Why this change?**
- **psycopg3** provides native async support, better performance, and improved connection handling
- Eliminates `psycopg2-binary` dependency issues on ARM64 and Alpine Linux
- Required for PgBouncer transaction pooling compatibility

**Migration steps:**
1. Update `DATABASE_URL` to use `postgresql+psycopg://` prefix
2. Restart the gateway - no data migration required
3. For Docker Compose users: Update your `.env` file or `docker-compose.yml`

### Added

#### **🛑 Gateway-Orchestrated Cancellation of Tool Runs** ([#1983](https://github.com/IBM/mcp-context-forge/issues/1983))
* **Configurable feature** - Control via `MCPGATEWAY_TOOL_CANCELLATION_ENABLED` (default: `true`)
  - Set to `false` to disable cancellation tracking and endpoints
  - Zero overhead when disabled - no registration, no callbacks, no endpoints
* **New `CancellationService`** - Tracks active tool executions with in-memory registry and Redis pubsub for multi-worker coordination
  - `register_run()`, `unregister_run()`, `cancel_run()`, `get_status()`, `is_registered()` methods
  - Automatic lifecycle management with `initialize()` and `shutdown()` hooks
  - Redis pubsub on `cancellation:cancel` channel for cluster-wide cancellation propagation
* **New REST API endpoints** - Gateway-authoritative cancellation control
  - `POST /cancellation/cancel` - Request cancellation with reason, broadcasts to all sessions
  - `GET /cancellation/status/{request_id}` - Query run status including cancellation state
  - RBAC protected with `admin.system_config` permission
* **Real task interruption** - Actual asyncio task cancellation, not just status marking
  - Tool executions wrapped in `asyncio.Task` with cancel callbacks
  - Handles `asyncio.CancelledError` with proper JSON-RPC error responses
  - Immediate interruption of long-running operations
* **JSON-RPC integration** - All `tools/call` requests automatically registered for cancellation
  - Pre-execution cancellation check to avoid starting cancelled tasks
  - Automatic unregistration on completion or error
  - Compatible with new authorization context (`user_email`, `token_teams`, `server_id`)
* **Session broadcasting** - `notifications/cancelled` sent to all connected MCP sessions
  - Best-effort delivery with per-session error logging
  - Allows external MCP servers to handle cancellation
* **Multi-worker support** - Production-ready for distributed deployments
  - Cancellations propagate across all workers via Redis pubsub
  - Graceful degradation if Redis unavailable (local-only cancellation)

#### **🏗️ Platform & Architecture**
* **ppc64le (IBM POWER) Architecture Support** ([#2205](https://github.com/IBM/mcp-context-forge/issues/2205)) - Container images now available for IBM POWER systems
* **External PostgreSQL Support** ([#1722](https://github.com/IBM/mcp-context-forge/issues/1722), [#2052](https://github.com/IBM/mcp-context-forge/issues/2052)) - CloudNativePG compatible external database hosting
* **Helm extraEnvFrom Support** ([#2047](https://github.com/IBM/mcp-context-forge/issues/2047)) - Mount secrets and configmaps as environment variables
* **Full Stack CI/CD** ([#1148](https://github.com/IBM/mcp-context-forge/issues/1148)) - Single configuration build and deployment pipeline

#### **🔐 Authentication & Security**
* **OAuth 2.0 Browser-Based SSO** ([#2022](https://github.com/IBM/mcp-context-forge/issues/2022)) - RFC 9728 compliant OAuth authentication for MCP clients
* **Microsoft EntraID Integration** ([#2054](https://github.com/IBM/mcp-context-forge/issues/2054)) - Role and group claim mapping for enterprise SSO
* **Query Parameter Authentication** ([#2195](https://github.com/IBM/mcp-context-forge/issues/2195), [#1580](https://github.com/IBM/mcp-context-forge/issues/1580)) - API key auth support via query parameters for A2A agents
* **RFC 8707 OAuth Resource Indicators** ([#2149](https://github.com/IBM/mcp-context-forge/issues/2149)) - Enables OAuth providers to return JWT tokens instead of opaque tokens
* **Configurable Password Enforcement** ([#1843](https://github.com/IBM/mcp-context-forge/issues/1843)) - Control password change requirements on login

#### **🎛️ Admin UI & Developer Experience**
* **Architecture Overview Tab** ([#1978](https://github.com/IBM/mcp-context-forge/issues/1978)) - Visual architecture diagram in Admin UI
* **Optimized Table Layouts** ([#1977](https://github.com/IBM/mcp-context-forge/issues/1977)) - Reduced horizontal scrolling for tools, prompts, and resources
* **Tool List/Spec Refresh** ([#1984](https://github.com/IBM/mcp-context-forge/issues/1984)) - Polling, API, and list_changed support for tool discovery
* **Gateway Re-discovery** ([#1910](https://github.com/IBM/mcp-context-forge/issues/1910)) - Refresh tools for already registered MCP gateways
* **Client CLI** ([#1414](https://github.com/IBM/mcp-context-forge/issues/1414)) - Command-line interface for gateway operations
* **Virtual Server Tool Naming** ([#1318](https://github.com/IBM/mcp-context-forge/issues/1318)) - Tool list in `<server_name>_<tool_name>` format
* **Form Field Validation** ([#1933](https://github.com/IBM/mcp-context-forge/issues/1933)) - Focus-out validation for improved UX

#### **📊 Observability & Metrics**
* **Execution Metrics Recording Switch** ([#1804](https://github.com/IBM/mcp-context-forge/issues/1804)) - `DB_METRICS_RECORDING_ENABLED` to disable per-operation metrics
* **Monitoring Profile** ([#1844](https://github.com/IBM/mcp-context-forge/issues/1844)) - Optional Prometheus + Grafana + exporters for load testing
* **Audit Trail Toggle** ([#1743](https://github.com/IBM/mcp-context-forge/issues/1743)) - `AUDIT_TRAIL_ENABLED` flag to disable audit logging
* **Observability Path Exclusions** ([#2068](https://github.com/IBM/mcp-context-forge/issues/2068)) - Restrict tracing to MCP/A2A endpoints

#### **⚡ Resilience & Reliability**
* **Database Startup Resilience** ([#2025](https://github.com/IBM/mcp-context-forge/issues/2025)) - Exponential backoff with jitter for database and Redis connections
* **Resilient Session Handling** ([#1766](https://github.com/IBM/mcp-context-forge/issues/1766)) - Connection pool exhaustion recovery
* **Session Persistence & Pooling** ([#975](https://github.com/IBM/mcp-context-forge/issues/975), [#1918](https://github.com/IBM/mcp-context-forge/issues/1918)) - MCP client session pooling for reduced per-request overhead
* **Session Isolation Tests** ([#1925](https://github.com/IBM/mcp-context-forge/issues/1925)) - Verification tests for MCP session pool isolation
* **MCP `_meta` Field Propagation** ([#2094](https://github.com/IBM/mcp-context-forge/issues/2094)) - Support for metadata in tool calls
* **Forced Password Change** ([#974](https://github.com/IBM/mcp-context-forge/issues/974)) - Require default password changes for production deployments

#### **🧪 Testing & Performance**
* **Rust MCP Test Server** ([#1908](https://github.com/IBM/mcp-context-forge/issues/1908)) - High-performance test server for load testing
* **Performance Test Profiling** ([#2061](https://github.com/IBM/mcp-context-forge/issues/2061)) - Guidelines and profiling for plugin performance
* **Locust Load Test Improvements** ([#1806](https://github.com/IBM/mcp-context-forge/issues/1806)) - Enhanced client performance for 4000+ concurrent users

### Changed

#### **🚀 Server Infrastructure**
* **Granian HTTP Server** ([#1695](https://github.com/IBM/mcp-context-forge/issues/1695)) - Migrated from Gunicorn to Granian for improved async performance
* **Granian Backpressure** ([#1859](https://github.com/IBM/mcp-context-forge/issues/1859)) - Overload protection for high-concurrency scenarios
* **uvicorn[standard]** ([#1699](https://github.com/IBM/mcp-context-forge/issues/1699)) - Enhanced server performance with uvloop and httptools
* **Nginx Optimization** ([#1768](https://github.com/IBM/mcp-context-forge/issues/1768), [#1719](https://github.com/IBM/mcp-context-forge/issues/1719)) - High-concurrency reverse proxy with UBI 10.x base

#### **📦 JSON Serialization**
* **orjson Migration** ([#2113](https://github.com/IBM/mcp-context-forge/issues/2113), [#1696](https://github.com/IBM/mcp-context-forge/issues/1696), [#2030](https://github.com/IBM/mcp-context-forge/issues/2030)) - Replaced stdlib json with orjson throughout codebase
* **ORJSONResponse** ([#1692](https://github.com/IBM/mcp-context-forge/issues/1692)) - Default response class for all endpoints

#### **⚡ Metrics Performance Defaults** ([#1799](https://github.com/IBM/mcp-context-forge/issues/1799))
* **Changed default behavior** - Raw metrics now deleted after hourly rollups exist (1 hour retention)
  - `METRICS_DELETE_RAW_AFTER_ROLLUP`: `false` → `true`
  - `METRICS_DELETE_RAW_AFTER_ROLLUP_DAYS` → `METRICS_DELETE_RAW_AFTER_ROLLUP_HOURS` (units now hours)
  - `METRICS_DELETE_RAW_AFTER_ROLLUP_HOURS`: `168` → `1`
  - `METRICS_ROLLUP_LATE_DATA_HOURS`: `4` → `1`
  - `METRICS_CLEANUP_INTERVAL_HOURS`: `24` → `1`
  - `METRICS_RETENTION_DAYS`: `30` → `7`
* **Rationale**: Prevents unbounded table growth under sustained load while preserving analytics in hourly rollups
* **Opt-out**: Set `METRICS_DELETE_RAW_AFTER_ROLLUP=false` to preserve previous behavior

#### **🔄 Redis & Caching**
* **Hiredis Parser** ([#1702](https://github.com/IBM/mcp-context-forge/issues/1702)) - Default Redis parser with fallback option for improved performance
* **Async Redis Client** ([#1661](https://github.com/IBM/mcp-context-forge/issues/1661)) - Shared async Redis client factory with atomic lock release
* **Distributed Cache** ([#1680](https://github.com/IBM/mcp-context-forge/issues/1680)) - Registry and admin cache with L1 (memory) + L2 (Redis) layers

#### **📝 Logging & Observability**
* **Logging Consistency** ([#1657](https://github.com/IBM/mcp-context-forge/issues/1657), [#1850](https://github.com/IBM/mcp-context-forge/issues/1850)) - Consistent component names in structured logs
* **Reduced Logging Overhead** ([#2084](https://github.com/IBM/mcp-context-forge/issues/2084), [#1837](https://github.com/IBM/mcp-context-forge/issues/1837)) - Avoid eager f-string evaluation in hot paths
* **Request Logging CPU** ([#1808](https://github.com/IBM/mcp-context-forge/issues/1808)) - Reduced CPU cost of detailed request logging

### Deprecated

#### **🔌 Federation Auto-Discovery & Forwarding Services** ([#1912](https://github.com/IBM/mcp-context-forge/issues/1912))
* **Removed `DiscoveryService`** - mDNS/Zeroconf auto-discovery is no longer supported
* **Removed `ForwardingService`** - Functionality consolidated into `ToolService` with improved OAuth, plugin, and SSE support
* **Deprecated environment variables:**
  - `FEDERATION_ENABLED` - No longer used
  - `FEDERATION_DISCOVERY` - No longer used
  - `FEDERATION_PEERS` - No longer used
  - `FEDERATION_SYNC_INTERVAL` - No longer used
* **Retained:** `FEDERATION_TIMEOUT` for gateway request timeouts
* **Unaffected:** Gateway peer management via `/gateways` REST API remains fully functional

### Fixed

#### **🔐 Authentication & Authorization**
* **CORS Preflight on /mcp** ([#2152](https://github.com/IBM/mcp-context-forge/issues/2152)) - OPTIONS requests no longer return 401
* **OAuth Opaque Tokens** ([#2149](https://github.com/IBM/mcp-context-forge/issues/2149)) - Fixed JWT verification failures with opaque tokens
* **JWT Audience Validation** ([#1792](https://github.com/IBM/mcp-context-forge/issues/1792)) - `JWT_AUDIENCE_VERIFICATION=false` now properly disables issuer validation
* **Basic Auth & API Key A2A** ([#2002](https://github.com/IBM/mcp-context-forge/issues/2002)) - Fixed authentication for A2A agents
* **Non-admin API Tokens** ([#1501](https://github.com/IBM/mcp-context-forge/issues/1501)) - Non-admin users can now create API tokens
* **Password Change Flag** ([#1842](https://github.com/IBM/mcp-context-forge/issues/1842), [#1914](https://github.com/IBM/mcp-context-forge/issues/1914)) - API password change now clears `password_change_required`
* **Login 500 on Password Change** ([#1653](https://github.com/IBM/mcp-context-forge/issues/1653)) - Fixed 500 error when password change is required
* **email_auth HTTPException** ([#1841](https://github.com/IBM/mcp-context-forge/issues/1841)) - Router no longer swallows exceptions returning 500

#### **👥 Multi-Tenancy & RBAC**
* **team_id in RBAC** ([#2183](https://github.com/IBM/mcp-context-forge/issues/2183)) - Fixed `team_id` being None for non-admin gateway list calls
* **HTMX Team Filters** ([#1966](https://github.com/IBM/mcp-context-forge/issues/1966)) - Partial endpoints now respect team_id filters
* **A2A Agent Team ID** ([#1956](https://github.com/IBM/mcp-context-forge/issues/1956)) - New A2A agent tools include team ID
* **Tool Visibility** ([#1582](https://github.com/IBM/mcp-context-forge/issues/1582), [#1915](https://github.com/IBM/mcp-context-forge/issues/1915)) - Tools now honor gateway visibility settings
* **Resource Visibility** ([#1497](https://github.com/IBM/mcp-context-forge/issues/1497)) - Toggling resource visibility no longer hides it
* **Team Add Member** ([#1644](https://github.com/IBM/mcp-context-forge/issues/1644)) - Team owners can add members without `teams.write` permission
* **User Creation is_admin** ([#1643](https://github.com/IBM/mcp-context-forge/issues/1643)) - POST /admin/users now respects `is_admin` flag
* **team_id Dict Parsing** ([#1486](https://github.com/IBM/mcp-context-forge/issues/1486)) - Handle team_id as dict in token claims

#### **📊 Admin UI**
* **Pagination** ([#2108](https://github.com/IBM/mcp-context-forge/issues/2108)) - Fixed broken pagination on Admin UI tables
* **Show Inactive Toggle** ([#2080](https://github.com/IBM/mcp-context-forge/issues/2080), [#2111](https://github.com/IBM/mcp-context-forge/issues/2111)) - Toggle now updates tables correctly
* **Action Buttons Scroll** ([#2077](https://github.com/IBM/mcp-context-forge/issues/2077)) - Buttons no longer hidden by horizontal scroll
* **Button Clutter** ([#2073](https://github.com/IBM/mcp-context-forge/issues/2073)) - Cleaned up MCP Servers table action column
* **Add Server Button** ([#2072](https://github.com/IBM/mcp-context-forge/issues/2072)) - Consistent "Add Server" behavior in MCP Registry
* **Metrics Tables Readability** ([#2058](https://github.com/IBM/mcp-context-forge/issues/2058)) - Improved advanced metrics table display
* **Token Usage Stats** ([#2031](https://github.com/IBM/mcp-context-forge/issues/2031)) - Fixed always null/zero token usage statistics
* **LLM Chat Server Status** ([#1707](https://github.com/IBM/mcp-context-forge/issues/1707)) - Servers no longer incorrectly tagged as inactive
* **SSE Stream Timeout** ([#1948](https://github.com/IBM/mcp-context-forge/issues/1948)) - Admin events stream no longer times out when idle
* **Form Field Focus** ([#1916](https://github.com/IBM/mcp-context-forge/issues/1916)) - Required fields no longer trap focus
* **Input Cursors** ([#1463](https://github.com/IBM/mcp-context-forge/issues/1463)) - Cursors now display in text fields
* **Token Validity** ([#1742](https://github.com/IBM/mcp-context-forge/issues/1742)) - Token creation respects selected validity period
* **Chart.js Canvas Reuse** ([#1788](https://github.com/IBM/mcp-context-forge/issues/1788)) - Fixed graphs disappearing with canvas error
* **Resource Fullscreen** ([#1787](https://github.com/IBM/mcp-context-forge/issues/1787)) - Fullscreen mode in resource test no longer vanishes
* **initializeSearchInputs** ([#2121](https://github.com/IBM/mcp-context-forge/issues/2121)) - Fixed recurrent initialization calls

#### **🔧 MCP Protocol & Tools**
* **tools/list Limit** ([#1937](https://github.com/IBM/mcp-context-forge/issues/1937), [#1664](https://github.com/IBM/mcp-context-forge/issues/1664)) - Returns all registered tools, not just ~50
* **REST Stale Visibility** ([#2018](https://github.com/IBM/mcp-context-forge/issues/2018)) - Tool visibility updates reflected immediately
* **Prompt Namespacing** ([#1762](https://github.com/IBM/mcp-context-forge/issues/1762)) - Proper name/ID resolution matching tool behavior
* **LLM Settings** ([#1725](https://github.com/IBM/mcp-context-forge/issues/1725)) - Support for provider-specific configuration parameters
* **Virtual Server LangChain** ([#1508](https://github.com/IBM/mcp-context-forge/issues/1508)) - Fixed tool invocation with LangChain clients
* **Claude Desktop Types** ([#1357](https://github.com/IBM/mcp-context-forge/issues/1357)) - Fixed invalid type responses for Claude Desktop
* **Deeply Nested Schemas** ([#1875](https://github.com/IBM/mcp-context-forge/issues/1875)) - Tool import works with deep JSON schemas
* **Text Response REST** ([#1576](https://github.com/IBM/mcp-context-forge/issues/1576)) - REST API with text-based responses now works
* **ExceptionGroup Unwrap** ([#1902](https://github.com/IBM/mcp-context-forge/issues/1902)) - Tool invocation errors show root cause
* **A2A Agent Test** ([#840](https://github.com/IBM/mcp-context-forge/issues/840)) - Fixed A2A agent test functionality

#### **🗄️ Database & Sessions**
* **Session State Leakage** ([#2055](https://github.com/IBM/mcp-context-forge/issues/2055)) - MCP session pool now isolates state between users
* **Entity Parsing Failure** ([#2172](https://github.com/IBM/mcp-context-forge/issues/2172)) - Single entity parsing failure no longer stops listing
* **Idle-in-Transaction** ([#1885](https://github.com/IBM/mcp-context-forge/issues/1885), [#1934](https://github.com/IBM/mcp-context-forge/issues/1934)) - Fixed connections stuck in transaction under load
* **PgBouncer Timeout** ([#1877](https://github.com/IBM/mcp-context-forge/issues/1877)) - Client idle timeout errors recognized as disconnects
* **User Deletion FK** ([#1663](https://github.com/IBM/mcp-context-forge/issues/1663)) - Fixed foreign key constraint on `email_team_member_history`
* **Transaction Rollbacks** ([#1108](https://github.com/IBM/mcp-context-forge/issues/1108)) - Fixed high rollback rate with PostgreSQL
* **Existing Postgres DB** ([#1465](https://github.com/IBM/mcp-context-forge/issues/1465)) - Gateway now builds with existing databases
* **Alembic Migrations** ([#2096](https://github.com/IBM/mcp-context-forge/issues/2096)) - Fixed incorrect migration placement and history

#### **🐳 Deployment & Infrastructure**
* **ARM64 Support** ([#1913](https://github.com/IBM/mcp-context-forge/issues/1913), [#1581](https://github.com/IBM/mcp-context-forge/issues/1581)) - Fixed broken ARM64 and Apple Silicon compatibility
* **Docker nginx Volume** ([#2134](https://github.com/IBM/mcp-context-forge/issues/2134)) - Fixed volume mount conflicts with Dockerfile COPY
* **Helm Pod Restart** ([#1423](https://github.com/IBM/mcp-context-forge/issues/1423)) - Fixed deployment causing pod restarts
* **Docker Start Error** ([#1526](https://github.com/IBM/mcp-context-forge/issues/1526)) - Fixed startup errors in Docker
* **External Plugin Start** ([#1633](https://github.com/IBM/mcp-context-forge/issues/1633)) - External plugins now start automatically
* **DATABASE_URL Encoding** ([#1533](https://github.com/IBM/mcp-context-forge/issues/1533)) - Fixed configparser interpolation error with encoded URLs
* **PassThrough Headers** ([#1530](https://github.com/IBM/mcp-context-forge/issues/1530)) - Environment variable configuration now works
* **Settings Parsing** ([#1415](https://github.com/IBM/mcp-context-forge/issues/1415)) - Fixed `observability_exclude_paths` Pydantic parsing
* **Native Plugin Issues** ([#2103](https://github.com/IBM/mcp-context-forge/issues/2103)) - Fixed issues in several native plugins

#### **🌐 Gateway & Federation**
* **Gateway Registration** ([#1047](https://github.com/IBM/mcp-context-forge/issues/1047), [#1440](https://github.com/IBM/mcp-context-forge/issues/1440)) - Fixed MCP Server and remote gateway registration
* **Self-Signed HTTPS** ([#1539](https://github.com/IBM/mcp-context-forge/issues/1539)) - HTTPS MCP servers with self-signed certificates now work
* **Spring MCP OOM** ([#1549](https://github.com/IBM/mcp-context-forge/issues/1549)) - Fixed JVM OutOfMemoryError with Spring MCP Server

### Security

* **Environment Isolation Warnings** ([#2141](https://github.com/IBM/mcp-context-forge/issues/2141)) - Optional environment claim validation with warnings
* **REQUIRE_USER_IN_DB** ([#2128](https://github.com/IBM/mcp-context-forge/issues/2128)) - Configuration option to require users exist in database
* **JWT Lifecycle Management** ([#2127](https://github.com/IBM/mcp-context-forge/issues/2127)) - Enhanced token lifecycle with revocation and refresh
* **MCP Team Validation** ([#2125](https://github.com/IBM/mcp-context-forge/issues/2125)) - Authentication controls and team membership validation

### Performance

#### **🗄️ Database Query Optimization**
* **N+1 Query Elimination** ([#1609](https://github.com/IBM/mcp-context-forge/issues/1609), [#1879](https://github.com/IBM/mcp-context-forge/issues/1879), [#1880](https://github.com/IBM/mcp-context-forge/issues/1880), [#1883](https://github.com/IBM/mcp-context-forge/issues/1883), [#1962](https://github.com/IBM/mcp-context-forge/issues/1962), [#1964](https://github.com/IBM/mcp-context-forge/issues/1964), [#1994](https://github.com/IBM/mcp-context-forge/issues/1994)) - Fixed N+1 queries in list_tools, list_prompts, list_servers, list_agents, gateway sync, and single-entity retrieval
* **Database Indexing** ([#1353](https://github.com/IBM/mcp-context-forge/issues/1353), [#1893](https://github.com/IBM/mcp-context-forge/issues/1893)) - Optimized indexes including partial index for team member counts
* **Duplicate COUNT Queries** ([#1684](https://github.com/IBM/mcp-context-forge/issues/1684)) - Eliminated redundant count queries
* **Batch Operations** ([#1674](https://github.com/IBM/mcp-context-forge/issues/1674), [#1686](https://github.com/IBM/mcp-context-forge/issues/1686), [#1727](https://github.com/IBM/mcp-context-forge/issues/1727)) - Bulk insert for imports, batch team membership queries, batch exports
* **SQL Aggregations** ([#1756](https://github.com/IBM/mcp-context-forge/issues/1756), [#1764](https://github.com/IBM/mcp-context-forge/issues/1764), [#1810](https://github.com/IBM/mcp-context-forge/issues/1810), [#1817](https://github.com/IBM/mcp-context-forge/issues/1817)) - Moved percentile calculations to SQL for log aggregation, observability, metrics rollup, and admin views
* **SELECT FOR UPDATE** ([#1641](https://github.com/IBM/mcp-context-forge/issues/1641)) - Prevent race conditions under high concurrency
* **Bulk UPDATE** ([#1760](https://github.com/IBM/mcp-context-forge/issues/1760)) - Token cleanup uses bulk operations

#### **🔗 Connection Pooling**
* **PgBouncer Integration** ([#1750](https://github.com/IBM/mcp-context-forge/issues/1750), [#1753](https://github.com/IBM/mcp-context-forge/issues/1753)) - Connection pooling for Docker Compose and Helm deployments
* **PostgreSQL Read Replicas** ([#1861](https://github.com/IBM/mcp-context-forge/issues/1861)) - Support for horizontal scaling with read replicas
* **HTTP Client Pool** ([#1676](https://github.com/IBM/mcp-context-forge/issues/1676), [#1897](https://github.com/IBM/mcp-context-forge/issues/1897)) - Configurable httpx connection limits preventing exhaustion
* **DB Connection Exhaustion** ([#1706](https://github.com/IBM/mcp-context-forge/issues/1706)) - Sessions released during upstream HTTP calls
* **Session Handling** ([#1732](https://github.com/IBM/mcp-context-forge/issues/1732), [#1770](https://github.com/IBM/mcp-context-forge/issues/1770)) - Fixed rollback rate and unnecessary close without commit
* **Health Check Commits** ([#1996](https://github.com/IBM/mcp-context-forge/issues/1996)) - Explicit commits release PgBouncer connections

#### **💾 Caching**
* **L1/L2 Auth Cache** ([#1881](https://github.com/IBM/mcp-context-forge/issues/1881)) - Check in-memory cache before Redis
* **JWT Verification Cache** ([#1677](https://github.com/IBM/mcp-context-forge/issues/1677)) - Cache token verification results
* **Tool Lookup Cache** ([#1940](https://github.com/IBM/mcp-context-forge/issues/1940)) - L1 memory + L2 Redis for tool lookups by name
* **Team Membership Cache** ([#1773](https://github.com/IBM/mcp-context-forge/issues/1773), [#1888](https://github.com/IBM/mcp-context-forge/issues/1888)) - Cached `get_user_teams()` and token scoping validation
* **GlobalConfig Cache** ([#1715](https://github.com/IBM/mcp-context-forge/issues/1715)) - In-memory cache for configuration lookups
* **Top Metrics Cache** ([#1737](https://github.com/IBM/mcp-context-forge/issues/1737)) - Prevent full table scans for `get_top_*` methods
* **Jinja Template Cache** ([#1814](https://github.com/IBM/mcp-context-forge/issues/1814)) - Compiled templates for prompt rendering
* **jq Filter Cache** ([#1813](https://github.com/IBM/mcp-context-forge/issues/1813)) - Cached filter compilation in `extract_using_jq`
* **JSONPath Cache** ([#1812](https://github.com/IBM/mcp-context-forge/issues/1812)) - Cached parsing for jsonpath_modifier and mappings
* **Resource URI Cache** ([#1811](https://github.com/IBM/mcp-context-forge/issues/1811)) - Cached regex/parse for URI templates
* **JSON Schema Cache** ([#1809](https://github.com/IBM/mcp-context-forge/issues/1809)) - Cached validators for tool output validation
* **Crypto Key Cache** ([#1831](https://github.com/IBM/mcp-context-forge/issues/1831)) - Cached auth/crypto key material and derived objects
* **Admin Page Cache** ([#1946](https://github.com/IBM/mcp-context-forge/issues/1946)) - Nginx caching with multi-tenant isolation
* **Template Auto-Reload** ([#1944](https://github.com/IBM/mcp-context-forge/issues/1944)) - `TEMPLATES_AUTO_RELOAD` setting for production

#### **⚡ Transport & Protocol**
* **Async I/O** ([#2164](https://github.com/IBM/mcp-context-forge/issues/2164)) - Replaced blocking calls with async in async functions
* **SSE Serialization** ([#1838](https://github.com/IBM/mcp-context-forge/issues/1838)) - Avoid bytes→str decode overhead
* **Transport Micro-Optimizations** ([#1832](https://github.com/IBM/mcp-context-forge/issues/1832)) - Streamable regex and stdio send improvements
* **SSE Keepalives** ([#1828](https://github.com/IBM/mcp-context-forge/issues/1828)) - Avoid TimeoutError control flow
* **HTTP Replay** ([#1827](https://github.com/IBM/mcp-context-forge/issues/1827)) - Optimize streamable HTTP replay without full deque scans
* **MCP Health Check** ([#2033](https://github.com/IBM/mcp-context-forge/issues/2033), [#1691](https://github.com/IBM/mcp-context-forge/issues/1691)) - Lightweight ping replaces blocking session health check

#### **🔌 Plugin Framework**
* **Plugin Manager Init** ([#2010](https://github.com/IBM/mcp-context-forge/issues/2010)) - Initialize once per worker, not per request
* **Plugin Logging** ([#2084](https://github.com/IBM/mcp-context-forge/issues/2084), [#2064](https://github.com/IBM/mcp-context-forge/issues/2064)) - Removed logging overhead and exc_info from critical path
* **Hook Execution** ([#1678](https://github.com/IBM/mcp-context-forge/issues/1678)) - Optimized plugin hook execution path
* **has_hooks_for** ([#1777](https://github.com/IBM/mcp-context-forge/issues/1777), [#1778](https://github.com/IBM/mcp-context-forge/issues/1778)) - Skip hook invocation when no hooks registered
* **Memory Optimization** ([#1608](https://github.com/IBM/mcp-context-forge/issues/1608)) - Copy-on-write for context state
* **OPA Plugin Async** ([#1931](https://github.com/IBM/mcp-context-forge/issues/1931)) - Replaced synchronous requests with async httpx
* **aiohttp Singleton** ([#1929](https://github.com/IBM/mcp-context-forge/issues/1929)) - Shared ClientSession for DCR and OAuth services
* **OAuth/DCR Pooling** ([#1987](https://github.com/IBM/mcp-context-forge/issues/1987)) - Connection pooling effective across requests

#### **📊 Metrics & Observability**
* **Metrics Table Growth** ([#1799](https://github.com/IBM/mcp-context-forge/issues/1799)) - Fixed unbounded growth under sustained load
* **Metrics Cleanup/Rollup** ([#1735](https://github.com/IBM/mcp-context-forge/issues/1735)) - Long-term performance with hourly rollups
* **Metrics Aggregation** ([#1734](https://github.com/IBM/mcp-context-forge/issues/1734)) - Optimized aggregation to prevent degradation
* **Buffered Metrics Writes** ([#1714](https://github.com/IBM/mcp-context-forge/issues/1714)) - Skip metrics on list endpoints
* **Double Token Scoping** ([#2160](https://github.com/IBM/mcp-context-forge/issues/2160)) - Fixed duplicate scoping for /mcp requests with email_auth
* **execution_count N+1** ([#1891](https://github.com/IBM/mcp-context-forge/issues/1891)) - Property no longer loads all metrics into memory
* **psutil Throttling** ([#1820](https://github.com/IBM/mcp-context-forge/issues/1820)) - Throttled net_connections in system metrics

#### **🔧 Middleware & Auth**
* **Middleware Chain** ([#1683](https://github.com/IBM/mcp-context-forge/issues/1683)) - Optimized execution path
* **Double JWT Decode** ([#1815](https://github.com/IBM/mcp-context-forge/issues/1815)) - Avoid duplicate decode and per-request config validation
* **Token Scoping Regex** ([#1816](https://github.com/IBM/mcp-context-forge/issues/1816)) - Precompiled patterns and permission maps
* **Auth Decoding Skip** ([#1758](https://github.com/IBM/mcp-context-forge/issues/1758)) - Skip on tool list endpoints
* **Header Mapping** ([#1829](https://github.com/IBM/mcp-context-forge/issues/1829)) - Optimized extraction avoiding nested scans
* **Session Middleware** ([#1887](https://github.com/IBM/mcp-context-forge/issues/1887)) - Combined double DB sessions in token_scoping

#### **⚙️ Core Optimizations**
* **Precompiled Regex** ([#1819](https://github.com/IBM/mcp-context-forge/issues/1819), [#1830](https://github.com/IBM/mcp-context-forge/issues/1830)) - DB query logging normalization and validation paths
* **LRU Cache Eviction** ([#1614](https://github.com/IBM/mcp-context-forge/issues/1614)) - O(n) → O(1) optimization
* **Stream Parser Buffer** ([#1613](https://github.com/IBM/mcp-context-forge/issues/1613)) - O(n²) → O(n) buffer management
* **Performance Tracker** ([#1610](https://github.com/IBM/mcp-context-forge/issues/1610), [#1757](https://github.com/IBM/mcp-context-forge/issues/1757)) - O(n) → O(1) buffer management and percentile calculation
* **ResourceCache Cleanup** ([#1818](https://github.com/IBM/mcp-context-forge/issues/1818)) - Avoid full scan in cleanup loop
* **Log Search Windows** ([#1826](https://github.com/IBM/mcp-context-forge/issues/1826)) - Avoid per-window recomputation
* **Startup Slug Refresh** ([#1611](https://github.com/IBM/mcp-context-forge/issues/1611)) - Batch processing optimization
* **JSON Encoding** ([#1615](https://github.com/IBM/mcp-context-forge/issues/1615)) - Eliminated redundant encoding in session registry
* **Session Cleanup** ([#1616](https://github.com/IBM/mcp-context-forge/issues/1616)) - Parallelized with asyncio.gather()
* **Session Registry Polling** ([#1675](https://github.com/IBM/mcp-context-forge/issues/1675)) - Reduced database polling overhead
* **httpx Client Churn** ([#1731](https://github.com/IBM/mcp-context-forge/issues/1731)) - Fixed memory pressure under load
* **Admin Dashboard Queries** ([#1687](https://github.com/IBM/mcp-context-forge/issues/1687)) - Optimized Admin UI dashboard

### Chores

* **Multi-Arch CI** ([#2209](https://github.com/IBM/mcp-context-forge/issues/2209)) - Build non-amd64 architectures only on main branch
* **Containerfile User** ([#2190](https://github.com/IBM/mcp-context-forge/issues/2190)) - Replace echo /etc/passwd with useradd
* **Code Quality** ([#2166](https://github.com/IBM/mcp-context-forge/issues/2166)) - Fix regex empty match and clean up docstring examples
* **Plugin Template** ([#1606](https://github.com/IBM/mcp-context-forge/issues/1606)) - Updated MCP runtime in plugins template

## [1.0.0-BETA-1] - 2025-12-16 - Multi-Architecture Containers, gRPC Translation, Performance & Security Enhancements

### Overview

This release marks the first beta milestone toward 1.0.0 GA, delivering **multi-architecture container support**, **gRPC-to-MCP protocol translation**, **air-gapped deployment capabilities**, and **significant performance improvements** with **84 issues resolved**:

- **🏗️ Multi-Architecture Containers** - ARM64 and s390x architecture support for broader deployment options
- **🔌 gRPC-to-MCP Translation** - Experimental gRPC service interface for MCP protocol operations
- **🌐 Air-Gapped Deployment** - CDN asset bundling for fully offline/disconnected environments
- **⚡ Performance Improvements** - Concurrent health checks and N+1 query optimizations reducing gateway operations latency by 10x+
- **🔐 Security Enhancements** - Password expiration policies, one-time authentication, and input validation
- **🛠️ Developer Experience** - Performance benchmarking framework, test resource buttons, and improved bulk import feedback
- **🗄️ Database Support** - Enhanced MariaDB documentation and testing

### 🎉 Announcements

#### **🖥️ ContextForge Desktop App**
We're excited to announce the **ContextForge Desktop** application - a native desktop client for managing MCP servers and gateways:
- **Repository:** [contextforge-org/contextforge-desktop](https://github.com/contextforge-org/contextforge-desktop)
- Cross-platform support (Windows, macOS, Linux)
- Visual MCP server management and monitoring
- Integrated gateway configuration

#### **⌨️ ContextForge CLI**
A new command-line interface for ContextForge operations:
- **Repository:** [contextforge-org/contextforge-cli](https://github.com/contextforge-org/contextforge-cli)
- Scriptable MCP server and gateway management
- CI/CD integration support
- Configuration export/import utilities

#### **🏢 New ContextForge Organization**
We've established the [contextforge-org](https://github.com/contextforge-org) GitHub organization to host the growing ContextForge ecosystem. In upcoming releases, several components will migrate to this organization:
- Plugins
- MCP Servers
- Agent runtimes
- Desktop and CLI tools

> **Note:** The main gateway repository remains at [IBM/mcp-context-forge](https://github.com/IBM/mcp-context-forge).

### Added

#### **🏗️ Multi-Architecture Container Support** ([#80](https://github.com/IBM/mcp-context-forge/issues/80), [#1138](https://github.com/IBM/mcp-context-forge/issues/1138))
* **ARM64 Support** - Container images now available for ARM64 architecture (Apple Silicon, AWS Graviton)
* **s390x Support** - IBM Z/LinuxONE architecture support for enterprise mainframe deployments
* **Multi-Platform Builds** - Automated CI/CD pipeline produces `linux/amd64`, `linux/arm64`, and `linux/s390x` images

#### **🔌 gRPC-to-MCP Protocol Translation** ([#1171](https://github.com/IBM/mcp-context-forge/issues/1171))
* **Experimental gRPC Service** - New gRPC interface for MCP protocol operations
  - Tool listing, discovery, and invocation via gRPC
  - Resource and prompt management endpoints
  - Server health and capability queries
* **Protocol Buffers** - Well-defined `.proto` schemas for type-safe client generation
* **Optional Dependency** - Install with `pip install mcp-contextforge-gateway[grpc]`

#### **🌐 Air-Gapped Environment Support** ([#932](https://github.com/IBM/mcp-context-forge/issues/932))
* **CDN Asset Bundling** - All frontend assets (HTMX, Alpine.js, CSS) bundled in container image
* **Offline Deployment** - No external network requests required for Admin UI
* **Asset Download Script** - `scripts/download-cdn-assets.sh` for manual asset updates

#### **🔐 Password Expiration & Security** ([#1282](https://github.com/IBM/mcp-context-forge/issues/1282), [#1387](https://github.com/IBM/mcp-context-forge/issues/1387))
* **Configurable Password Expiration** - Set password validity periods via `PASSWORD_EXPIRY_DAYS`
* **Forced Password Change** - Users prompted to change expired passwords on login
* **One-Time Authentication Mode** - Support for WXO integration with single-use auth tokens
* **Multiple Gateway Registrations** - Allow same gateway URL with different authentication contexts ([#1392](https://github.com/IBM/mcp-context-forge/issues/1392))

#### **🧪 Performance Testing Framework** ([#1203](https://github.com/IBM/mcp-context-forge/issues/1203), [#1219](https://github.com/IBM/mcp-context-forge/issues/1219))
* **Benchmarking Framework** - Comprehensive performance testing infrastructure
* **Benchmark MCP Server** - Dedicated server for load testing and performance analysis
* **N+1 Query Detection** - Automated tests to catch database query performance regressions

#### **📦 Sample MCP Servers**
* **Go System Monitor Server** ([#898](https://github.com/IBM/mcp-context-forge/issues/898)) - Reference implementation in Go for system monitoring

#### **🛠️ Developer Experience Improvements**
* **Test Button for Resources** ([#1560](https://github.com/IBM/mcp-context-forge/issues/1560)) - Quick resource testing from Admin UI
* **Tool Tag Structure** ([#1442](https://github.com/IBM/mcp-context-forge/issues/1442)) - Enhanced tag structure with metadata support (objects instead of strings)
* **Authentication Plugin Architecture** ([#1019](https://github.com/IBM/mcp-context-forge/issues/1019)) - Extensible authentication through plugin system
* **Bulk Import Feedback** ([#806](https://github.com/IBM/mcp-context-forge/issues/806)) - Improved error messages and registration feedback in UI

### Fixed

#### **⚡ Performance Fixes**
* **Concurrent Health Checks** ([#1522](https://github.com/IBM/mcp-context-forge/issues/1522)) - Gateway health checks now run in parallel instead of sequentially, reducing latency from O(n) to O(1)
* **N+1 Query Elimination** ([#1523](https://github.com/IBM/mcp-context-forge/issues/1523)) - Major performance fix for gateway/tool/server services, reducing database queries by 90%+ in multi-gateway scenarios

#### **🐛 Bug Fixes**
* **Gateway Status Updates** ([#464](https://github.com/IBM/mcp-context-forge/issues/464)) - MCP Server "Active" status now properly updates when servers shutdown
* **Resource Listing** ([#1259](https://github.com/IBM/mcp-context-forge/issues/1259)) - Fixed MCP resources not appearing in listings
* **StreamableHTTP Redirects** ([#1280](https://github.com/IBM/mcp-context-forge/issues/1280)) - Proper redirect handling in gateway URL validation
* **Tool Schema team_id** ([#1395](https://github.com/IBM/mcp-context-forge/issues/1395)) - Team ID now correctly applied in tool schemas
* **Virtual Server Structured Content** ([#1406](https://github.com/IBM/mcp-context-forge/issues/1406)) - Fixed missing structured content in Streamable HTTP responses
* **One-Time Auth Gateway Registration** ([#1448](https://github.com/IBM/mcp-context-forge/issues/1448)) - Multiple gateways with same URL now supported with one-time auth
* **SSL Key Passphrase** ([#1577](https://github.com/IBM/mcp-context-forge/issues/1577)) - Support for passphrase-protected SSL keys in HTTPS configuration

### Security

* **Input Validation & Output Sanitization** ([#221](https://github.com/IBM/mcp-context-forge/issues/221)) - Gateway-level input validation to prevent path traversal and injection attacks

### Changed

#### **🗄️ Database Support**
* **MariaDB Documentation** ([#288](https://github.com/IBM/mcp-context-forge/issues/288)) - Comprehensive MariaDB testing, documentation, and CI/CD integration

---

## [0.9.0] - 2025-11-09 - REST Passthrough, Ed25519 Certificate Signing, Multi-Tenancy Fixes & Platform Enhancements

### Overview

This release delivers **Ed25519 Certificate Signing**, **REST API Passthrough Capabilities**, **API & UI Pagination**, **Multi-Tenancy Bug Fixes**, and **Platform Enhancements** with **60+ issues resolved** and **50+ PRs merged**, bringing significant improvements across security, observability, and developer experience:

- **📄 REST API & UI Pagination** - Comprehensive pagination support for all admin endpoints with HTMX-based UI and performance testing up to 10K records
- **🔌 REST Passthrough API Fields** - Comprehensive REST tool configuration with query/header mapping, timeouts, and plugin chains
- **🔐 Multi-Tenancy & RBAC Fixes** - Critical bug fixes for team management, API tokens, and resource access control
- **🛠️ Developer Experience** - Support bundle generation, LLM chat interface, system metrics, and performance testing
- **🔒 Security Enhancements** - Plugin mTLS support, CSP headers, cookie scope fixes, and RBAC vulnerability patches
- **🌐 Platform Support** - s390x architecture support, multiple StreamableHTTP content, and MCP tool output schema
- **🧪 Quality & Testing** - Complete build pipeline verification, enhanced linting, mutation testing, and fuzzing
- **⚡ Performance Optimizations** - Response compression middleware (Brotli, Zstd, GZip) reducing bandwidth by 30-70% + orjson JSON serialization providing 5-6x faster JSON encoding
- **🦀 Rust Plugin Framework** - Optional Rust-accelerated plugins with 5-100x performance improvements
- **💻 Admin UI** - Quality of life improvements for admins when managing MCP servers
- **🗄️ Enhanced Database Support** - Complete MariaDB/MySQL documentation, migration guides, and observability metrics

### ⚠️ BREAKING CHANGES

#### **🗄️ PostgreSQL 17 → 18 Upgrade Required**

**Docker Compose users must run the upgrade utility before starting the stack.**

The default PostgreSQL image has been upgraded from version 17 to 18. This is a **major version upgrade** that requires a one-time data migration using `pg_upgrade`.

**Migration Steps:**

1. **Stop your existing stack:**
   ```bash
   docker compose down
   ```

2. **Run the automated upgrade utility:**
   ```bash
   make compose-upgrade-pg18
   ```

   This will:
   - Prompt for confirmation (⚠️ **backup recommended**)
   - Run `pg_upgrade` to migrate data from Postgres 17 → 18
   - Automatically copy `pg_hba.conf` to preserve network access settings
   - Create a new `pgdata18` volume with upgraded data

3. **Start the upgraded stack:**
   ```bash
   make compose-up
   ```

4. **(Optional) Run maintenance commands** to update statistics:
   ```bash
   docker compose exec postgres /usr/lib/postgresql/18/bin/vacuumdb --all --analyze-in-stages --missing-stats-only -U postgres
   docker compose exec postgres /usr/lib/postgresql/18/bin/vacuumdb --all --analyze-only -U postgres
   ```

5. **Verify the upgrade:**
   ```bash
   docker compose exec postgres psql -U postgres -c 'SELECT version();'
   # Should show: PostgreSQL 18.x
   ```

6. **(Optional) Clean up old volume** after confirming everything works:
   ```bash
   docker volume rm mcp-context-forge_pgdata
   ```

**Manual Upgrade (without Make):**

If you prefer not to use the Makefile:

```bash
# Stop stack
docker compose down

# Run upgrade
docker compose -f docker-compose.yml -f compose.upgrade.yml run --rm pg-upgrade

# Copy pg_hba.conf
docker compose -f docker-compose.yml -f compose.upgrade.yml run --rm pg-upgrade \
  sh -c "cp /var/lib/postgresql/OLD/pg_hba.conf /var/lib/postgresql/18/docker/pg_hba.conf"

# Start upgraded stack
docker compose up -d
```

**Why This Change:**

- Postgres 18 introduces a new directory structure (`/var/lib/postgresql/18/docker`) for better compatibility with `pg_ctlcluster`
- Enables future upgrades using `pg_upgrade --link` without mount point boundary issues
- Aligns with official PostgreSQL Docker image best practices (see [postgres#1259](https://github.com/docker-library/postgres/pull/1259))

**What Changed:**

- `docker-compose.yml`: Updated from `postgres:17` → `postgres:18`
- Volume mount: Changed from `pgdata:/var/lib/postgresql/data` → `pgdata18:/var/lib/postgresql`
- Added `compose.upgrade.yml` for automated upgrade process
- Added `make compose-upgrade-pg18` target for one-command upgrades

**Troubleshooting:**

- **Error: "data checksums mismatch"** - Fixed automatically in upgrade script (disables checksums to match old cluster)
- **Error: "no pg_hba.conf entry"** - Fixed automatically by copying old `pg_hba.conf` during upgrade
- **Error: "Invalid cross-device link"** - Upgrade uses copy mode (not `--link`) to work across different Docker volumes

### Added

#### **🗄️ Enhanced Database Support & Documentation**
* **Complete MariaDB/MySQL Documentation** - Comprehensive documentation for MariaDB and MySQL support
  - New "Supported Databases" page with sample connection URLs and limitations
  - Detailed MariaDB/MySQL configuration examples with version requirements
  - Known limitations documentation (JSONPath indexes, foreign key constraints)
  - Performance optimization guidelines for MariaDB/MySQL deployments
* **Simplified Database Migration** - MariaDB compatibility with existing PostgreSQL schemas
  - No complex migration required - simply change the `DATABASE_URL`
  - Automatic schema creation and migration handling
  - Full compatibility between PostgreSQL and MariaDB deployments
* **Enhanced Observability Metrics** - Database engine detection in Prometheus metrics
  - Automatic `engine="mariadb"` labels in metrics for MariaDB deployments
  - `database_info` gauge with engine and URL scheme labels
  - Support for monitoring MariaDB-specific performance characteristics
* **Quick Start Documentation Updates** - Docker Compose and Helm examples
  - Docker Compose quick-start with MariaDB as the recommended database
  - Helm chart deployment examples with MariaDB configuration
  - Production-ready stack examples with Redis and admin tools

#### **📄 REST API and UI Pagination** (#1224, #1277)
* **Paginated REST API Endpoints** - All admin API endpoints now support pagination with configurable page size
  - `/admin/tools` endpoint returns paginated response with `data`, `pagination`, and `links` keys
  - Maintains backward compatibility with legacy list format
  - Configurable page size (1-500 items per page, default: 50)
  - Total count and page metadata included in responses
* **Database Indexes for Pagination** - New composite indexes for efficient paginated queries
  - Indexes on `created_at` + `id` for tools, servers, resources, prompts, gateways
  - Team-scoped indexes for multi-tenant pagination performance
  - Auth events and API tokens indexed for audit log pagination
* **UI Pagination with HTMX** - Seamless client-side pagination for admin UI
  - New `/admin/tools/partial` endpoint for HTMX-based pagination
  - Pagination controls with keyboard navigation support
  - Tested with up to 10,000 tools for performance validation
  - Tag filtering works within paginated results
* **Pagination Configuration** - 11 new environment variables for fine-tuning pagination behavior
  - `PAGINATION_DEFAULT_PAGE_SIZE` - Default items per page (default: 50)
  - `PAGINATION_MAX_PAGE_SIZE` - Maximum allowed page size (default: 500)
  - `PAGINATION_CURSOR_THRESHOLD` - Threshold for cursor-based pagination (default: 10000)
  - `PAGINATION_CURSOR_ENABLED` - Enable cursor-based pagination (default: true)
  - `PAGINATION_INCLUDE_LINKS` - Include navigation links in responses (default: true)
  - Additional settings for sort order, caching, and offset limits
* **Pagination Utilities** - New `mcpgateway/utils/pagination.py` module with reusable pagination helpers
  - Offset-based pagination for simple use cases (<10K records)
  - Cursor-based pagination for large datasets (>10K records)
  - Automatic strategy selection based on result set size
  - Navigation link generation with query parameter support
* **Comprehensive Test Coverage** - 1,089+ lines of pagination tests
  - Integration tests for paginated endpoints
  - Unit tests for pagination utilities
  - Performance validation with large datasets

#### **🔌 REST Passthrough Configuration** (#746, #1273)
* **Query & Header Mapping** - Configure dynamic query parameter and header mappings for REST tools
* **Path Templates** - Support for URL path templates with variable substitution
* **Timeout Configuration** - Per-tool timeout settings (default: 20000ms for REST passthrough)
* **Endpoint Exposure Control** - Toggle passthrough endpoint visibility with `expose_passthrough` flag
* **Host Allowlists** - Configure allowed upstream hosts/schemes for enhanced security
* **Plugin Chain Support** - Pre and post-request plugin chains for REST tools
* **Base URL Extraction** - Automatic extraction of base URL and path template from tool URLs
* **Admin UI Integration** - "Advanced: Add Passthrough" button in tool creation form with dynamic field generation

#### **🛡️ REST Tool Validation** (#1273)
* **URL Structure Validation** - Ensures base URLs have valid scheme and netloc
* **Path Template Validation** - Enforces leading slash in path templates
* **Timeout Validation** - Validates timeout values are positive integers
* **Allowlist Validation** - Regex-based validation for allowed hosts/schemes
* **Plugin Chain Validation** - Restricts plugins to known safe plugins (deny_filter, rate_limit, pii_filter, response_shape, regex_filter, resource_filter)
* **Integration Type Enforcement** - REST-specific fields only allowed for `integration_type='REST'`

#### **🛠️ Developer & Operations Tools** (#1197, #1202, #1228, #1204)
* **Support Bundle Generation** (#1197) - Automated diagnostics collection with sanitized logs, configuration, and system information
  - Command-line tool: `mcpgateway --support-bundle --output-dir /tmp --log-lines 1000`
  - API endpoint: `GET /admin/support-bundle/generate?log_lines=1000`
  - Admin UI: "Download Support Bundle" button in Diagnostics tab
  - Automatic sanitization of secrets (passwords, tokens, API keys)
* **LLM Chat Interface** (#1202, #1200, #1236) - Built-in MCP client with LLM chat service for virtual servers
  - Agent-enabled tool orchestration with MCP protocol integration
  - **Redis-based session consistency** (#1236) for multi-worker distributed environments
  - Concurrent user management with worker coordination and session isolation
  - Prevents race conditions via Redis locks and TTLs
  - Direct testing of virtual servers and tools from the Admin UI
* **System Statistics in Metrics** (#1228, #1232) - Comprehensive system monitoring in metrics page
  - CPU, memory, disk usage, and network statistics
  - Process information and resource consumption
  - System health indicators for production monitoring
* **Performance Testing Framework** (#1203, #1204, #1226) - Load testing and benchmarking capabilities
  - Production-scale load data generator for multi-tenant testing (#1225, #1226)
  - Benchmark MCP server for performance analysis (#1219, #1220, #1221)
  - Fixed TokenUsageLog SQLite bug in load testing framework
* **Metrics Export Enhancement** (#1218) - Export all metrics data for external analysis and integration

#### **🔐 SSO & Authentication Enhancements** (#1212, #1213, #1216, #1217)
* **Microsoft Entra ID Support** (#1212, #1211) - Complete Entra ID integration with environment variable configuration
* **Generic OIDC Provider Support** (#1213) - Flexible OIDC integration for any compliant provider
* **Keycloak Integration** (#1217, #1216, #1109) - Full Keycloak support with application/x-www-form-urlencoded
* **OAuth Timeout Configuration** (#1201) - Configurable `OAUTH_DEFAULT_TIMEOUT` for OAuth providers

#### **� Ed25519 Certificate Signing** - Enhanced certificate validation and integrity verification
* **Digital Certificate Signing** - Sign and verify certificates using Ed25519 cryptographic signatures
  - Ensures certificate authenticity and prevents tampering
  - Built on proven Ed25519 algorithm (RFC 8032) for high security and performance
  - Zero-dependency Python implementation using `cryptography` library
* **Key Generation Utility** - Built-in key generation tool at `mcpgateway/utils/generate_keys.py`
  - Generates secure Ed25519 private keys in base64 format
  - Simple command-line interface for development and production use
* **Key Rotation Support** - Graceful key rotation with zero downtime
  - Configure both current (`ED25519_PRIVATE_KEY`) and previous (`PREV_ED25519_PRIVATE_KEY`) keys
  - Automatic fallback to previous key for verification during rotation period
  - Supports rolling updates in distributed deployments
* **Environment Variable Configuration** - Three new environment variables for certificate signing
  - `ENABLE_ED25519_SIGNING` - Enable/disable signing (default: "false")
  - `ED25519_PRIVATE_KEY` - Current signing key (base64-encoded)
  - `PREV_ED25519_PRIVATE_KEY` - Previous key for rotation support (base64-encoded)
* **Kubernetes & Helm Support** - Full integration with Helm chart deployment
  - Secret management via `values.yaml` configuration
  - JSON Schema validation in `values.schema.json`
  - External Secrets Operator integration examples
* **Production Ready** - Comprehensive documentation and security best practices
  - Complete documentation in main README.md
  - Helm chart documentation with Kubernetes examples
  - Security guidelines for key storage and rotation

#### **�🔌 Plugin Framework Enhancements** (#1196, #1198, #1137, #1240, #1289)
* **🦀 Rust Plugin Framework** (#1289, #1249) - Optional Rust-accelerated plugins with automatic Python fallback
  - Complete PyO3-based framework for building high-performance plugins
  - **PII Filter (Rust)**: 5-100x faster than Python implementation with identical functionality
    - Bulk detection: ~100x faster (Python: 2287ms → Rust: 22ms)
    - Single pattern: ~5-10x faster across all PII types
    - Memory efficient with Rust's ownership model
  - **Auto-Detection**: Automatically selects Rust or Python implementation at runtime
  - **UI Integration**: Plugin catalog displays implementation type (🦀 Rust / 🐍 Python)
  - **Comprehensive Testing**: Unit tests, integration tests, differential tests, and benchmarks
  - **CI/CD Pipeline**: Automated builds, tests, and publishing for Rust plugins
  - **Multi-Platform Builds**: Linux (x86_64, aarch64), macOS (universal2), Windows (x86_64)
  - **Zero Breaking Changes**: Pure Python fallback when Rust not available
  - Optional installation: `pip install mcp-contextforge-gateway[rust]`
* **Plugin Client-Server mTLS Support** (#1196) - Mutual TLS authentication for external plugins
* **Complete OPA Plugin Hooks** (#1198, #1137) - All missing hooks implemented in OPA plugin
* **Plugin Linters & Quality** (#1240) - Comprehensive linting for all plugins with automated fixes
* **Plugin Compose Configuration** (#1174) - Enhanced plugin and catalog configuration in docker-compose

#### **🌐 Protocol & Platform Enhancements**
* **MCP Tool Output Schema Support** (#1258, #1263, #1269) - Full support for MCP tool `outputSchema` field
  - Database and service layer implementation (#1263)
  - Admin UI support for viewing and editing output schemas (#1269)
  - Preserves output schema during tool discovery and invocation
* **Multiple StreamableHTTP Content** (#1188, #1189) - Support for multiple content blocks in StreamableHTTP responses
* **s390x Architecture Support** (#1138, #1206) - Container builds for IBM Z platform (s390x)
* **System Monitor MCP Server** (#977) - Go-based MCP server for system monitoring and metrics

#### **📚 Documentation Enhancements**
* **Langflow MCP Server Integration** (#1205) - Documentation for Langflow integration
* **SSO Tutorial Updates** (#277) - Comprehensive GitHub SSO integration tutorial
* **Environment Variable Documentation** (#1215) - Updated and clarified environment variable settings
* **Documentation Formatting Fixes** (#1214) - Fixed newlines and formatting across documentation

#### **⚡ Performance Optimizations** (#1298, #1292, #1294)
* **Response Compression Middleware** (#1298, #1292) - Automatic compression reducing bandwidth by 30-70%
  - **Multi-Algorithm Support**: Brotli, Zstd, and GZip compression with automatic negotiation
  - **Bandwidth Reduction**: 30-70% smaller responses for text-based content (JSON, HTML, CSS, JS)
  - **Algorithm Priority**: Brotli (best compression) > Zstd (fastest) > GZip (universal fallback)
  - **Smart Compression**: Only compresses responses >500 bytes to avoid overhead
  - **Optimal Settings**: Balanced compression levels for CPU/bandwidth trade-off
    - Brotli quality 4 (0-11 scale) for best compression ratio
    - Zstd level 3 (1-22 scale) for fastest compression
    - GZip level 6 (1-9 scale) for balanced performance
  - **Cache-Friendly**: Adds `Vary: Accept-Encoding` header for proper cache behavior
  - **Zero Client Changes**: Transparent to API clients, browsers handle decompression automatically
  - **Browser Support**: Brotli supported by 96%+ of browsers, GZip universal fallback
  - **Configurable**: Environment variables for enabling/disabling and tuning compression levels
    - `COMPRESSION_ENABLED` - Enable/disable compression (default: true)
    - `COMPRESSION_MINIMUM_SIZE` - Minimum response size to compress (default: 500 bytes)
    - `COMPRESSION_GZIP_LEVEL` - GZip compression level (default: 6)
    - `COMPRESSION_BROTLI_QUALITY` - Brotli quality level (default: 4)
    - `COMPRESSION_ZSTD_LEVEL` - Zstd compression level (default: 3)

* **orjson JSON Serialization** (#1294) - High-performance JSON encoding/decoding with 5-6x performance improvement
  - **Performance Gains**: 5-6x faster serialization, 1.5-2x faster deserialization vs stdlib json
  - **Compact Output**: 7% smaller JSON payloads for reduced bandwidth usage
  - **Rust Implementation**: Fast, correct JSON library implemented in Rust (RFC 8259 compliant)
  - **Native Type Support**: datetime, UUID, numpy arrays, Pydantic models handled natively
  - **Zero Configuration**: Drop-in replacement for stdlib json, fully transparent to clients
  - **Production Ready**: Used by major companies (Reddit, Stripe) for high-throughput APIs
  - **Benchmark Script**: `scripts/benchmark_json_serialization.py` for performance validation
  - **API Benefits**: 15-30% higher throughput, 10-20% lower CPU usage, 20-40% faster response times
  - **Options**: OPT_NON_STR_KEYS (integer dict keys), OPT_SERIALIZE_NUMPY (numpy arrays)
  - **Implementation**: `mcpgateway/utils/orjson_response.py` configured as default FastAPI response class
  - **Test Coverage**: 29 comprehensive unit tests with 100% code coverage

#### **💻 Admin UI enhancements** (#1336)
* **Inspectable auth passwords, tokens and headers** (#1336) - Admins can now view and verify passwords, tokens and custom headers they set when creating or editing MCP servers.


### Fixed

#### **🐛 Critical Multi-Tenancy & RBAC Bugs**
* **RBAC Vulnerability Patch** (#1248, #1250) - Fixed unauthorized access to resource status toggling
  - Ownership checks now enforced for all resource operations
  - Toggle permissions restricted to resource owners only
* **Backend Multi-Tenancy Issues** (#969) - Comprehensive fixes for team-based resource scoping
* **Team Member Re-addition** (#959) - Fixed unique constraint preventing re-adding team members
* **Public Resource Ownership** (#1209, #1210) - Implemented ownership checks for public resources
  - Users can only edit/delete their own public resources
  - Prevents unauthorized modification of team-shared resources
* **Incomplete Visibility Implementation** (#958) - Fixed visibility enforcement across all resource types

#### **🔒 Security & Authentication Fixes**
* **JWT Token Fixes** (#1254, #1255, #1262, #1261)
  - Fixed JWT jti mismatch between token and database record (#1254, #1255)
  - Fixed JWT token following default expiry instead of UI configuration (#1262)
  - Fixed API token expiry override by environment variables (#1261)
* **Cookie Scope & RBAC Redirects** (#1252, #448) - Aligned cookie scope with app root path
  - Fixed custom base path support (e.g., `/api` instead of `/mcp`)
  - Proper RBAC redirects for custom app paths
* **OAuth & Login Issues** (#1048, #1101, #1117, #1181, #1190)
  - Fixed HTTP login requiring `SECURE_COOKIES=false` warning (#1048, #1181)
  - Fixed login failures in v0.7.0 (#1101, #1117)
  - Fixed virtual MCP server access with JWT instead of OAuth (#1190)
* **CSP & Iframe Embedding** (#922, #1241) - Fixed iframe embedding with consistent CSP and X-Frame-Options headers

#### **🔧 UI/UX & Display Fixes**
* **UI Margins & Layout** (#1272, #1276, #1275) - Fixed UI margin issues and catalog display
* **Request Payload Visibility** (#1098, #1242) - Fixed request payload not visible in UI
* **Tool Annotations** (#835) - Added custom annotation support for tools
* **Header-Modal Overlap** (#1178, #1179) - Fixed header overlapping with modals
* **Passthrough Headers** (#861, #1024) - Fixed passthrough header parameters not persisted to database
  - Plugin `tool_prefetch` hook can now access PASSTHROUGH_HEADERS and tags

#### **🛠️ Infrastructure & Build Fixes**
* **CI/CD Pipeline Verification** (#1257) - Complete build pipeline verification with all stages
* **Makefile Clean Target** (#1238) - Fixed Makefile clean target for proper cleanup
* **UV Lock Conflicts** (#1230, #1234, #1243) - Resolved conflicting dependencies with semgrep
* **Deprecated Config Parameters** (#1237) - Removed deprecated 'env=...' parameters in config.py
* **Bandit Security Scan** (#1244) - Fixed all bandit security warnings
* **Test Warnings & Mypy Issues** (#1268) - Fixed test warnings and mypy type issues

#### **🧪 Test Reliability & Quality Improvements** (#1281, #1283, #1284, #1291)
* **Gateway Test Stability** (#1281) - Fixed gateway test failures and eliminated warnings
  - Integrated pytest-httpx for cleaner HTTP mocking (eliminated manual mock complexity)
  - Eliminated RuntimeWarnings from improper async context manager mocking
  - Added url-normalize library for consistent URL normalization
  - Reduced test file complexity by 388 lines (942 → 554 lines)
  - Consolidated validation tests into parameterized test cases
* **Logger Test Reliability** (#1283, #1284) - Resolved intermittent logger capture failures
  - Scoped logger configuration to specific loggers to prevent inter-test conflicts (#1283)
  - Fixed email verification logic error in auth.py (email_verified_at vs is_email_verified) (#1283)
  - Fixed caplog logger name specification for reliable debug message capture (#1284)
  - Added proper type hints and improved type safety across test suite
* **Prompt Test Fixes** (#1291) - Fixed test failures and prompt-related test issues

#### **🐳 Container & Deployment Fixes**
* **Gateway Registration on MacOS** (#625) - Fixed gateway registration and tool invocation on MacOS
* **Non-root Container Users** (#1231) - Added non-root user to scratch Go containers
* **Container Runtime Detection** - Improved Docker/Podman detection in Makefile

#### **💻 Admin UI Fixes** (#1370)
* **Saved custom headers not visible** (#1370) - Fixed custom headers not visible to Admins when editing a MCP server using custom headers for auth.

### Changed

#### **🗄️ Database Schema & Multi-Tenancy Enhancements** (#1246, #1273)

**Scoped Uniqueness for Multi-Tenant Resources** (#1246):
* **Enforced team-scoped uniqueness constraints** for improved multi-tenancy isolation
  - Prompts: unique within `(team_id, owner_email, name)` - prevents naming conflicts across teams
  - Resources: unique within `(team_id, owner_email, uri)` - ensures URI uniqueness per team/owner
  - A2A Agents: unique within `(team_id, owner_email, slug)` - team-scoped agent identifiers
  - Dropped legacy single-column unique constraints (name, uri) for multi-tenant compatibility
* **ID-Based Resource Endpoints** (#1184) - All prompt and resource endpoints now use unique IDs for lookup
  - Prevents naming conflicts across teams and owners
  - Enhanced API security and consistency
  - Migration compatible with SQLite, MySQL, and PostgreSQL
* **Enhanced Prompt Editing** (#1180) - Prompt edit form now correctly includes team_id in form data
* **Plugin Hook Updates** - PromptPrehookPayload and PromptPosthookPayload now use prompt_id instead of name
* **Resource Content Schema** - ResourceContent now includes id field for unique identification

**REST Passthrough Configuration** (#1273):
* **New Tool Columns** - Added 9 new columns to tools table via Alembic migration `8a2934be50c0`:
  - `base_url` - Base URL for REST passthrough
  - `path_template` - Path template for URL construction
  - `query_mapping` - JSON mapping for query parameters
  - `header_mapping` - JSON mapping for headers
  - `timeout_ms` - Request timeout in milliseconds
  - `expose_passthrough` - Boolean flag to enable/disable passthrough
  - `allowlist` - JSON array of allowed hosts/schemes
  - `plugin_chain_pre` - Pre-request plugin chain
  - `plugin_chain_post` - Post-request plugin chain

#### **🔧 API Schemas** (#1273)
* **ToolCreate Schema** - Enhanced with passthrough field validation and auto-extraction logic
* **ToolUpdate Schema** - Updated with same validation logic for modifications
* **ToolRead Schema** - Extended to expose passthrough configuration in API responses

#### **⚙️ Configuration & Defaults** (#1194)
* **APP_DOMAIN Default** - Updated default URL to be compatible with Pydantic v2
* **OAUTH_DEFAULT_TIMEOUT** - New configuration for OAuth provider timeouts
* **Environment Variables** - Comprehensive cleanup and documentation updates

#### **🧹 Code Quality & Developer Experience Improvements** (#1271, #1233)
* **Consolidated Linting Configuration** (#1271) - Single source of truth for all Python linting tools
  - Migrated ruff and interrogate configs from separate files into pyproject.toml
  - Enhanced ruff with import sorting checks (I) and docstring presence checks (D1)
  - Unified pre-commit hooks to match CI/CD pipeline enforcement
  - Reduced configuration sprawl: removed `.ruff.toml` and `.interrogaterc`
  - Better IDE integration with comprehensive real-time linting
* **CONTRIBUTING.md Cleanup** (#1233) - Simplified contribution guidelines
* **Lint-smart Makefile Fix** (#1233) - Fixed syntax error in lint-smart target
* **Plugin Linting** (#1240) - Comprehensive linting across all plugins with automated fixes
* **Deprecation Removal** - Removed all deprecated Pydantic v1 patterns

### Security

* **RBAC Vulnerability Patch** - Fixed unauthorized resource access (#1248)
* **Plugin mTLS Support** - Mutual TLS for external plugin communication (#1196)
* **CSP Headers** - Proper Content-Security-Policy for iframe embedding (#1241)
* **Cookie Scope Security** - Aligned cookie scope with app root path (#1252)
* **Support Bundle Sanitization** - Automatic secret redaction in diagnostic bundles (#1197)
* **Ownership Enforcement** - Strict ownership checks for public resources (#1209)

### Infrastructure

* **Multi-Architecture Support** - s390x platform builds for IBM Z (#1206)
* **Complete Build Verification** - End-to-end CI/CD pipeline testing (#1257)
* **Performance Testing Framework** - Production-scale load testing capabilities (#1204)
* **System Monitoring** - Comprehensive system statistics and health indicators (#1228)

### Documentation

* **REST Passthrough Configuration** - Complete REST API passthrough guide
* **SSO Integration Tutorials** - GitHub, Entra ID, Keycloak, and generic OIDC
* **Support Bundle Usage** - CLI, API, and Admin UI documentation
* **Performance Testing Guide** - Load testing and benchmarking documentation
* **LLM Chat Interface** - MCP-enabled tool orchestration guide

### Issues Closed

**REST Integration:**
- Closes #746 - REST Passthrough API configuration fields

**Multi-Tenancy & RBAC:**
- Closes #969 - Backend Multi-Tenancy Issues - Critical bugs and missing features
- Closes #967 - UI Gaps in Multi-Tenancy Support - Visibility fields missing for most resource types
- Closes #959 - Unable to Re-add Team Member Due to Unique Constraint
- Closes #958 - Incomplete Visibility Implementation
- Closes #946 - Alembic migrations fails in docker compose setup
- Closes #945 - Scoped uniqueness for prompts, resources, and A2A agents
- Closes #926 - Bootstrap fails to assign platform_admin role due to foreign key constraint violation
- Closes #1180 - Prompt editing to include team_id in form data
- Closes #1184 - Prompt and resource endpoints to use unique IDs instead of name/URI
- Closes #1222 - Already addressed as part of #945
- Closes #1248 - RBAC Vulnerability: Unauthorized Access to Resource Status Toggling
- Closes #1209 - Finalize RBAC/ABAC implementation for Ownership Checks on Public Resources

**Security & Authentication:**
- Closes #1254 - JWT jti mismatch between token and database record
- Closes #1262 - JWT token follows default variable payload expiry instead of UI
- Closes #1261 - API Token Expiry Issue: UI Configuration overridden by default env Variable
- Closes #1111 - Support application/x-www-form-urlencoded Requests in MCP Gateway UI for OAuth2 / Keycloak Integration
- Closes #1094 - Creating an MCP OAUTH2 server fails if using API
- Closes #1092 - After issue 1078 change, how to add X-Upstream-Authorization header when clicking Authorize in admin UI
- Closes #1048 - Login issue - Serving over HTTP requires SECURE_COOKIES=false
- Closes #1101 - Login issue with v0.7.0
- Closes #1117 - Login not working with 0.7.0 version
- Closes #1181 - Secure cookie warnings for HTTP development
- Closes #1190 - Virtual MCP server requiring OAUTH instead of JWT in 0.7.0
- Closes #1109 - MCP Gateway UI OAuth2 Integration Fails with Keycloak

**SSO Integration:**
- Closes #1211 - Microsoft Entra ID Integration Support and Tutorial
- Closes #1213 - Generic OIDC Provider Support via Environment Variables
- Closes #1216 - Keycloak Integration Support with Environment Variables
- Closes #277 - GitHub SSO Integration Tutorial

**Developer Tools & Operations:**
- Closes #1197 - Support Bundle Generation - Automated Diagnostics Collection
- Closes #1200 - In built MCP client - LLM Chat service for virtual servers
- Closes #1239 - LLMChat Multi-Worker: Add Documentation and Integration Tests
- Closes #1202 - LLM Chat Interface with MCP Enabled Tool Orchestration
- Closes #1228 - Show system statistics in metrics page
- Closes #1225 - Production-Scale Load Data Generator for Multi-Tenant Testing
- Closes #1219 - Benchmark MCP Server for Load Testing and Performance Analysis
- Closes #1203 - Performance Testing & Benchmarking Framework

**Code Quality & Developer Experience:**
- Closes #1271 - Consolidated linting configuration in pyproject.toml

**Plugin Framework:**
- Closes #1249 - Rust-Powered PII Filter Plugin - 5-10x Performance Improvement
- Closes #1196 - Plugin client server mTLS support
- Closes #1137 - Add missing hooks to OPA plugin
- Closes #1198 - Complete OPA plugin hook implementation

**Platform & Protocol:**
- Closes #1381 - Resource view error - mime type handling for resource added via mcp server
- Closes #1348 - Add support for IBM Watsonx.ai LLM provider
- Closes #1258 - MCP Tool outputSchema Field is Stripped During Discovery
- Closes #1188 - Allow multiple StreamableHTTP content
- Closes #1138 - Support for container builds for s390x

**Performance Optimizations:**
- Closes #1294 - orjson JSON Serialization for 5-6x faster JSON encoding/decoding
- Closes #1292 - Brotli/Zstd/GZip Response Compression reducing bandwidth by 30-70%

**Bug Fixes:**
- Closes #1336 - Add toggles to password/sensitive textboxes to mask/unmask the input value
- Closes #1098 - Unable to see request payload being sent
- Closes #1024 - plugin tool_prefetch hook cannot access PASSTHROUGH_HEADERS, tags
- Closes #1020 - Edit Button Functionality - A2A
- Closes #861 - Passthrough header parameters not persisted to database
- Closes #1178 - Header overlaps with modals in UI
- Closes #922 - IFraming the admin UI is not working
- Closes #625 - Gateway unable to register gateway or call tools on MacOS
- Closes #1230 - pyproject.toml conflicting dependencies with uv
- Closes #448 - MCP server with custom base path "/api" not working
- Closes #835 - Adding Custom annotation for tools
- Closes #409 - Add configurable limits for data cleaning / XSS prevention in .env.example and helm

**Documentation:**
- Closes #1159 - Several minor quirks in main README.md
- Closes #1093 - RBAC - support generic OAuth provider or ldap provider (documentation)
- Closes #869 - 0.7.0 Release timeline

---

## [0.8.0] - 2025-10-07 - Advanced OAuth, Plugin Ecosystem, MCP Registry & gRPC Protocol Translation

### Overview

This release focuses on **Advanced OAuth Integration, Plugin Ecosystem, MCP Registry & gRPC Protocol Translation** with **110 issues resolved** and **47+ PRs merged**, bringing significant improvements across authentication, plugin framework, gRPC integration, and developer experience:

- **🔌 gRPC-to-MCP Protocol Translation** - Zero-configuration gRPC service discovery, automatic protocol translation, TLS/mTLS support
- **🔐 Advanced OAuth Features** - Password Grant Flow, Dynamic Client Registration (DCR), PKCE support, token refresh
- **🔌 Plugin Ecosystem Expansion** - 15+ new plugins, plugin management UI/API, comprehensive plugin documentation
- **📦 MCP Server Registry** - Local catalog of MCP servers, improved server discovery and registration
- **🏢 Enhanced Multi-Tenancy** - Team-level API token scoping, team columns in admin UI
- **🔒 Policy & Security** - OPA policy engine enhancements, content moderation, secure cookie warnings
- **🛠️ Developer Experience** - Dynamic environment variables for STDIO servers, improved OAuth2 gateway editing

### Added

#### **🔌 gRPC-to-MCP Protocol Translation** (#1171, #1172) [EXPERIMENTAL - OPT-IN]

!!! warning "Experimental Feature - Disabled by Default"
    gRPC support is an experimental opt-in feature that requires:

    1. **Installation**: `pip install mcp-contextforge-gateway[grpc]`
    2. **Enablement**: `MCPGATEWAY_GRPC_ENABLED=true` in environment

    The feature is disabled by default and requires explicit activation. All gRPC dependencies are optional and not installed with the base package.

* **Automatic Service Discovery** - Zero-configuration gRPC service integration via Server Reflection Protocol
  - Discovers all services and methods automatically from gRPC servers
  - Parses FileDescriptorProto for complete method signatures and message types
  - Stores discovered schemas in database for fast lookups
  - Handles partial discovery failures gracefully

* **Protocol Translation Layer** - Bidirectional conversion between Protobuf and JSON
  - **GrpcEndpoint Class** (`translate_grpc.py`, 214 lines) - Core protocol translation
  - Dynamic JSON ↔ Protobuf message conversion using descriptor pool
  - 18 Protobuf type mappings to JSON Schema for MCP tool definitions
  - Support for nested messages, repeated fields, and complex types
  - Message factory for dynamic Protobuf message creation

* **Method Invocation Support**
  - **Unary RPCs** - Request-response method invocation with full JSON/Protobuf conversion
  - **Server-Streaming RPCs** - Incremental JSON responses via async generators
  - Dynamic gRPC channel creation (insecure and TLS)
  - Proper error handling and gRPC status code propagation

* **Security & TLS/mTLS Support**
  - Secure gRPC connections with custom client certificates
  - Certificate-based mutual authentication (mTLS)
  - Fallback to system CA certificates when custom certs not provided
  - TLS validation before marking services as reachable

* **Service Management Layer** - Complete CRUD operations for gRPC services
  - **GrpcService Class** (`services/grpc_service.py`, 222 lines)
  - Service registration with automatic reflection
  - Team-based access control and visibility settings
  - Enable/disable services without deletion
  - Re-trigger service discovery on demand

* **Database Schema** - New `grpc_services` table with 30+ columns
  - Cross-database compatible (SQLite, MySQL, PostgreSQL)
  - Service metadata, discovered schemas, and configuration
  - Team scoping with foreign key to `email_teams`
  - Audit metadata (created_by, modified_by, IP tracking)
  - Alembic migration `3c89a45f32e5_add_grpc_services_table.py`

* **REST API Endpoints** - 8 new endpoints in `admin.py`
  - `POST /grpc` - Register new gRPC service
  - `GET /grpc` - List all gRPC services with team filtering
  - `GET /grpc/{id}` - Get service details
  - `PUT /grpc/{id}` - Update service configuration
  - `POST /grpc/{id}/state` - Enable/disable service
  - `POST /grpc/{id}/delete` - Delete service
  - `POST /grpc/{id}/reflect` - Re-trigger service discovery
  - `GET /grpc/{id}/methods` - List discovered methods

* **Admin UI Integration** - New "gRPC Services" tab
  - Visual service registration form with TLS configuration
  - Service list with status indicators (enabled, reachable)
  - Service details modal showing discovered methods
  - Inline actions (enable/disable, delete, reflect, view methods)
  - Real-time connection status and metadata display

* **CLI Integration** - Standalone gRPC-to-SSE server mode
  - `python3 -m mcpgateway.translate --grpc <target> --port 9000`
  - TLS arguments: `--tls-cert`, `--tls-key`
  - Custom metadata headers: `--grpc-metadata "key=value"`
  - Graceful shutdown handling

* **Comprehensive Testing** - 40 unit tests with edge case coverage
  - `test_translate_grpc.py` (360+ lines, 23 tests)
  - `test_grpc_service.py` (370+ lines, 17 tests)
  - Protocol translation tests, service discovery tests, method invocation tests
  - Error scenario tests
  - Coverage: 49% translate_grpc, 65% grpc_service

* **Complete Documentation**
  - `docs/docs/using/grpc-services.md` (500+ lines) - Complete user guide
  - Updated `docs/docs/overview/features.md` - gRPC feature section
  - Updated `docs/docs/using/mcpgateway-translate.md` - CLI examples
  - Updated `.env.example` - gRPC configuration variables

* **Configuration** - Feature flag and environment variables
  - `MCPGATEWAY_GRPC_ENABLED=false` (default) - Feature disabled by default
  - `MCPGATEWAY_GRPC_ENABLED=true` - Enable gRPC features (requires `[grpc]` extras)
  - Optional dependency group: `mcp-contextforge-gateway[grpc]`
  - Backward compatible - opt-in feature, no breaking changes
  - Conditional imports - gracefully handles missing grpcio packages
  - UI tab and API endpoints hidden/disabled when feature is off

* **Performance Benefits**
  - **1.25-1.6x faster** method invocation compared to REST (Protobuf binary vs JSON)
  - **3-10x smaller** payloads with Protobuf binary encoding
  - **20-100x faster** serialization compared to JSON
  - **Type safety** - Strong typing prevents runtime schema mismatches
  - **Zero configuration** - Automatic service discovery eliminates manual schema definition

#### **🔐 Advanced OAuth & Authentication** (#1168, #1158)
* **OAuth Password Grant Flow** - Complete implementation of OAuth 2.0 Password Grant Flow for programmatic authentication
* **OAuth Dynamic Client Registration (DCR)** - Support for OAuth DCR with PKCE (Proof Key for Code Exchange)
* **Token Refresh Support** (#1023, #1078) - Multi-tenancy support with user-specific token handling and refresh mechanisms
* **Secure Cookie Warnings** (#1181, #1048) - Clear warnings for HTTP development environments requiring `SECURE_COOKIES=false`
* **OAuth Token Management** (#1097, #1119, #1112) - Fixed OAuth state signatures, tool refresh, and server test/ping functionality

#### **🔌 Plugin Framework & Ecosystem** (#1130, #1147, #1139, #1118)
* **Plugin Management API & UI** (#1129, #1130) - Complete plugin management interface in Admin Dashboard
* **Plugin Framework Specification** (#1118) - Comprehensive specification document for plugin development
* **Enhanced Plugin Documentation** (#1147) - Updated plugin usage guides and built-in plugin documentation
* **Plugin Design Consolidation** (#1139) - Revised and consolidated plugin specification and design docs

#### **🔌 New Built-in Plugins**
* **Content Moderation Plugin** (#1114) - IBM-supported content moderation with AI-powered filtering
* **Webhook Notification Plugin** (#1113) - Event-driven webhook notifications for gateway events
* **Circuit Breaker Plugin** (#1070, #1150) - Fault tolerance with automatic circuit breaking
* **Response Cache by Prompt** (#1071) - Intelligent caching based on prompt patterns
* **License Header Injector** (#1072) - Automated license header management
* **Privacy Notice Injector** (#1073) - Privacy notice injection for compliance
* **Citation Validator** (#1069) - Validate and track citations in responses
* **Robots License Guard** (#1066) - License compliance enforcement
* **AI Artifacts Normalizer** (#1067) - Standardize AI-generated artifacts
* **Code Formatter** (#1068) - Automatic code formatting in responses
* **Safe HTML Sanitizer** (#1063) - XSS prevention and HTML sanitization
* **Harmful Content Detector** (#1064) - Detect and filter harmful content
* **SQL Sanitizer** (#1065) - SQL injection prevention
* **Summarizer Plugin** (#1076) - Automatic response summarization
* **ClamAV External Plugin** (#1077) - Virus scanning integration
* **Timezone Translator** (#1074) - Automatic timezone conversion
* **Watchdog Plugin** (#1075) - System monitoring and health checks

#### **📦 MCP Server Registry & Catalog** (#1132, #1170, #295)
* **Local MCP Server Catalog** (#1132) - Local catalog of MCP servers for registry and marketplace
* **MCP Server Catalog Improvements** (#1170) - Enhanced server discovery and registration
* **Catalog Search** (#1144) - Improved search functionality for MCP server catalog
* **Catalog UX Updates** (#1153, #1152) - Enhanced user experience for catalog browsing

#### **🏢 Multi-Tenancy Enhancements** (#1177, #1107)
* **Team-Level API Token Scoping** (#1176, #1177) - Public-only token support with team-level scoping
* **Team Columns in Admin UI** (#1035, #1107) - Team visibility across all admin tables (Tools, Gateway Server, Virtual Servers, Prompts, Resources)

#### **🔒 Policy & Security Features** (#1145, #1102, #1106)
* **Customizable OPA Policy Path** (#1145) - Enable customization of OPA policy file path
* **OPA Policy Input Mapping** (#1102) - Enhanced OPA policy input data mapping support
* **Multi-arch OPA Support** (#1106) - Multi-architecture support for OPA policy server

#### **🛠️ Developer Experience** (#1162, #1155, #1154, #1165)
* **Dynamic Environment Variables for STDIO** (#1162, #1081) - Dynamic environment variable injection for STDIO MCP servers
* **Configuration Tab** (#1155, #1154) - New configuration management tab in Admin UI
* **Scale Documentation** (#1165) - Comprehensive scaling and performance documentation

### Fixed

#### **🐛 Critical Bug Fixes**
* **Gateway Addition from UI** (#1173) - Fixed gateway addition failures from Admin UI
* **Role Assignment Failure** (#1175) - Fixed role assignment during bootstrap due to FK constraint
* **A2A Tool Call** (#1163) - Fixed A2A agent tool invocation issues
* **Global Tools for A2A Agents** (#1123, #841) - Fixed Global Tools not being listed for A2A Agents
* **Login Issues** (#1101, #1117, #1048) - Resolved login problems in 0.7.0 with HTTP/HTTPS configurations

#### **🔧 OAuth & Authentication Fixes**
* **OAuth2 Gateway Editing** (#1146, #1025) - Preserve tools/resources/prompts when editing OAuth2 gateways without URL change
* **OAuth Client Auth** (#1096) - Fixed MCP_CLIENT_AUTH_ENABLED not taking effect in v0.7.0
* **Header Propagation** (#1134, #1046, #1115, #1104, #1142) - Fixed pass-through headers, X-Upstream-Authorization, and X-Vault-Headers handling
* **Gateway Update** (#1039, #1120) - Fixed gateway update failures and auth value DB constraints

#### **🖥️ UI/UX Fixes**
* **Header-Modal Overlap** (#1179, #1178) - Fixed header overlapping with modals in UI
* **Resource Filter** (#1131) - Fixed resource filtering issues
* **README Updates** (#1169, #1159) - Corrected minor quirks in main README.md
* **Project Name Normalization** (#1157) - Normalized project name across documentation

#### **📊 Metrics & Monitoring**
* **Metrics Recording** (#1127, #1103) - Added metrics recording for prompts, resources, and servers; fixed metrics collection
* **A2A Endpoint Error** (#1128, #1125) - Fixed GET /a2a/ returning 500 due to datatype mismatch

#### **🔌 Plugin Fixes**
* **Plugin Linting** (#1151) - Fixed lint issues across all plugins
* **Circuit Breaker Plugin** (#1150) - Removed unused variables in circuit breaker plugin
* **PII Filter Dead Code** (#1149) - Removed dead code from PII filter plugin

#### **🔐 Security & Encoding Fixes**
* **SecretStr Encoding** (#1133) - Fixed encode method in SecretStr implementation
* **Tool Limit Removal** (#1141) - Temporarily removed limit for tools until pagination is properly implemented
* **Team Request UI** (#1022) - Fixed "Join Request" button showing no pending requests

#### **🔌 gRPC Improvements & Fixes**
* **Made gRPC Opt-In** (#1172) - Feature-flagged gRPC support for stability
  - Moved grpcio packages to optional `[grpc]` dependency group
  - Default `MCPGATEWAY_GRPC_ENABLED=false` (must be explicitly enabled)
  - Conditional imports - no errors if grpcio packages not installed
  - Tests automatically skipped when packages unavailable
  - UI tab and API endpoints hidden when feature disabled
  - Install with: `pip install mcp-contextforge-gateway[grpc]`
* **Database Migration Compatibility** - Cross-database integer defaults
  - Fixed `server_default` values in Alembic migration to use `sa.text()`
  - Ensures compatibility across SQLite, MySQL, and PostgreSQL
  - Prevents potential migration failures with string literals

### Changed

#### **📦 Configuration & Validation** (#1110)
* **Pydantic v2 Config Validation** (#285, #1110) - Complete migration to Pydantic v2 configuration validation
* **Plugin Configuration** - Enhanced plugin configuration with enable/disable flags and better validation

#### **🔄 Infrastructure Updates**
* **Multi-Arch Support** - Expanded multi-architecture support for OPA and other components
* **Helm Chart Improvements** (#1105) - Fixed "Too many redirects" issue in Helm deployments

#### **🔌 gRPC Dependency Updates**
* **Dependency Updates** - Resolved version conflicts for gRPC compatibility
  - **Made optional**: Moved all grpcio packages to `[grpc]` extras group
  - Constrained `grpcio>=1.62.0,<1.68.0` for protobuf 4.x compatibility
  - Constrained `grpcio-reflection>=1.62.0,<1.68.0`
  - Constrained `grpcio-tools>=1.62.0,<1.68.0`
  - Updated `protobuf>=4.25.0` (removed `<5.0` constraint)
  - Updated `semgrep>=1.99.0` (was `>=1.139.0`) for jsonschema compatibility
  - Binary wheels preferred automatically (no manual flags needed)
  - All dependencies resolve without conflicts

* **Code Quality Improvements**
  - Fixed Bandit security issue (try/except/pass with proper logging)
  - Achieved Pylint 10.00/10 rating with appropriate suppressions
  - Fixed JavaScript linting in admin.js (quote style, formatting)
  - Increased async test timeout for CI environment stability (150ms → 200ms)

### Security

* OAuth DCR with PKCE support for enhanced authentication security
* Content moderation plugin with AI-powered threat detection
* Enhanced policy enforcement with customizable OPA integration
* Secure cookie warnings for development environments
* SQL and HTML sanitization plugins for injection prevention
* Multi-layer security with circuit breaker and watchdog plugins
* gRPC TLS/mTLS support for secure microservice communication

### Infrastructure

* Multi-architecture support for OPA policy server
* Enhanced plugin framework with management API/UI
* Local MCP server catalog for better registry management
* Dynamic environment variable support for STDIO servers
* gRPC-to-MCP protocol translation layer for enterprise microservices

### Documentation

* Comprehensive plugin framework specification
* Updated plugin usage and development guides
* Scale and performance documentation
* OAuth integration tutorials (Password Grant, DCR, PKCE)
* MCP server catalog documentation
* Complete gRPC integration guide with examples

### Issues Closed

**gRPC Integration:**
- Closes #1171 - [EPIC]: Complete gRPC-to-MCP Protocol Translation

**OAuth & Authentication:**
- Closes #1048 - Login issue with HTTP requiring SECURE_COOKIES=false
- Closes #1101, #1117 - Login not working with 0.7.0 version
- Closes #1109 - OAuth2 Integration fails with Keycloak
- Closes #1023 - MCP gateway ping fails due to missing refresh token
- Closes #1078 - OAuth Token Multi-Tenancy Support
- Closes #1096 - MCP_CLIENT_AUTH_ENABLED not effective in v0.7.0

**Multi-Tenancy & Teams:**
- Closes #1176 - Team-Level Scoping for API Tokens
- Closes #1035 - Add "Team" Column to All Admin UI Tables
- Closes #1022 - "Join Request" button shows no pending request

**A2A (Agent-to-Agent) Integration:**
- Closes #298 - A2A Initial Support - Add A2A Servers as Tools
- Closes #841 - Global Tools not listed for A2A Agents
- Closes #1125 - GET /a2a/ returns 500 due to datatype mismatch

**Plugins & Framework:**
- Closes #1129 - Plugin Management API and UI to Admin Dashboard
- Closes #1076 - Summarizer Plugin
- Closes #1077 - ClamAV External Plugin
- Closes #1074 - Timezone Translator Plugin
- Closes #1075 - Watchdog Plugin
- Closes #1071 - Response Cache by Prompt Plugin
- Closes #1072 - License Header Injector Plugin
- Closes #1073 - Privacy Notice Injector Plugin
- Closes #1069 - Citation Validator Plugin
- Closes #1070 - Circuit Breaker Plugin
- Closes #1066 - Robots License Guard Plugin
- Closes #1067 - AI Artifacts Normalizer Plugin
- Closes #1068 - Code Formatter Plugin
- Closes #1063 - Safe HTML Sanitizer Plugin
- Closes #1064 - Harmful Content Detector Plugin
- Closes #1065 - SQL Sanitizer Plugin

**MCP Server Catalog:**
- Closes #295 - Local Catalog of MCP servers
- Closes #1143 - Adding any server in MCP Registry fails
- Closes #1061, #1062, #1058, #1059, #1060 - Python MCP Server Samples
- Closes #1055, #1056, #1057, #1053, #1054, #1045, #1052 - Additional Python MCP Server Samples
- Closes #1043 - Pandoc MCP server in Go

**Bug Fixes:**
- Closes #1178 - Header overlaps with modals
- Closes #1025 - OAuth2 gateway edit requires tool fetch
- Closes #1046 - Pass-through headers not functioning
- Closes #1039 - Update Gateway fails
- Closes #1104 - X-Upstream-Authorization Header not working
- Closes #1105 - Too many redirects in Helm deployment
- Closes #1081 - STDIO transport support

**Documentation & Infrastructure:**
- Closes #1159 - Minor quirks in main README.md
- Closes #1037 - Fix Mend Configuration File

---

## [0.7.0] - 2025-09-16 - Enterprise Multi-Tenancy, RBAC, Teams, SSO

### Overview

**This major release implements [EPIC #860]: Complete Enterprise Multi-Tenancy System with Team-Based Resource Scoping**, transforming MCP Gateway from a single-tenant system into a **production-ready enterprise multi-tenant platform** with team-based resource scoping, comprehensive authentication, and enterprise SSO integration. **38 issues resolved**.

**Impact:** Complete architectural transformation enabling secure team collaboration, enterprise SSO integration, and scalable multi-tenant deployments.

### 🚀 **Migration Guide**

**⚠️ IMPORTANT**: This is a **major architectural change** requiring database migration.

**📖 Complete migration instructions**: See **[MIGRATION-0.7.0.md](./MIGRATION-0.7.0.md)** for detailed upgrade guidance from v0.6.0 to v0.7.0.

**📋 Migration includes**:
- Automated database schema upgrade
- Team assignment for existing servers/resources
- Platform admin user creation
- Configuration export/import tools
- Comprehensive verification and troubleshooting

**🔑 Password Management**: After migration, platform admin password must be changed using the API endpoint `/auth/email/change-password`. The `PLATFORM_ADMIN_PASSWORD` environment variable is only used during initial setup.

### Added

#### **🔐 Authentication & Authorization System**
* **Email-based Authentication** (#544) - Complete user authentication system with Argon2id password hashing replacing basic auth
* **Complete RBAC System** (#283) - Platform Admin, Team Owner, Team Member roles with full multi-tenancy support
* **Enhanced JWT Tokens** (#87) - JWT tokens with team context, scoped permissions, and per-user expiry
* **Asymmetric JWT Algorithm Support** - Complete support for RSA (RS256/384/512) and ECDSA (ES256/384/512) algorithms alongside existing HMAC support
  - **Multiple Algorithm Support**: HS256/384/512 (HMAC), RS256/384/512 (RSA), ES256/384/512 (ECDSA)
  - **Enterprise Security**: Public/private key separation for distributed architectures
  - **Configuration Validation**: Runtime validation ensures proper keys exist for chosen algorithm
  - **Backward Compatibility**: Existing HMAC JWT configurations continue working unchanged
  - **Key Management Integration**: `make certs-jwt` and `make certs-jwt-ecdsa` for secure key generation
  - **Container Support**: `make container-run-ssl-jwt` for full TLS + JWT asymmetric deployment
  - **Dynamic Client Registration**: Configurable audience verification for DCR scenarios
* **Password Policy Engine** (#426) - Configurable security requirements with password complexity rules
* **Password Change API** - Secure `/auth/email/change-password` endpoint for changing user passwords with old password verification
* **Multi-Provider SSO Framework** (#220, #278, #859) - GitHub, Google, and IBM Security Verify integration
* **Per-Virtual-Server API Keys** (#282) - Scoped access tokens for individual virtual servers

#### **👥 Team Management System**
* **Personal Teams Auto-Creation** - Every user automatically gets a personal team on registration
* **Multi-Team Membership** - Users can belong to multiple teams with different roles (owner/member)
* **Team Invitation System** - Email-based invitations with secure tokens and expiration
* **Team Visibility Controls** - Private/Public team discovery and cross-team collaboration
* **Team Administration** - Complete team lifecycle management via API and Admin UI

#### **🔒 Resource Scoping & Visibility**
* **Three-Tier Resource Visibility System**:
  - **Private**: Owner-only access
  - **Team**: Team member access
  - **Public**: Cross-team access for collaboration
* **Applied to All Resource Types**: Tools, Servers, Resources, Prompts, A2A Agents
* **Team-Scoped API Endpoints** with proper access validation and filtering
* **Cross-Team Resource Discovery** for public resources

#### **🏗️ Platform Administration**
* **Platform Admin Role** separate from team roles for system-wide management
* **Domain-Based Auto-Assignment** via SSO (SSO_AUTO_ADMIN_DOMAINS)
* **Enterprise Domain Trust** (SSO_TRUSTED_DOMAINS) for controlled access
* **System-Wide Team Management** for administrators

#### **🗄️ Database & Infrastructure**
* **Complete Multi-Tenant Database Schema** with proper indexing and performance optimization
* **Team-Based Query Filtering** for performance and security
* **Automated Migration Strategy** from single-tenant to multi-tenant with rollback support
* **All APIs Redesigned** to be team-aware with backward compatibility

#### **🔧 Configuration & Security**
* **Database Connection Pool Configuration** - Optimized settings for multi-tenant workloads:
  ```bash
  # New .env.example settings for performance:
  DB_POOL_SIZE=50              # Maximum persistent connections (default: 200, SQLite capped at 50)
  DB_MAX_OVERFLOW=20           # Additional connections beyond pool_size (default: 10, SQLite capped at 20)
  DB_POOL_TIMEOUT=30           # Seconds to wait for connection before timeout (default: 30)
  DB_POOL_RECYCLE=3600         # Seconds before recreating connection (default: 3600)
  ```
* **Complete MariaDB & MySQL Database Support** (#925) - Full production support for MariaDB and MySQL backends:
  ```bash
  # MariaDB (recommended MySQL-compatible option):
  DATABASE_URL=mysql+pymysql://mysql:changeme@localhost:3306/mcp

  # Docker deployment with MariaDB:
  DATABASE_URL=mysql+pymysql://mysql:changeme@mariadb:3306/mcp
  ```
  - **36+ database tables** fully compatible with MariaDB 10.6+ and MySQL 8.0+
  - All **VARCHAR length issues** resolved for MySQL compatibility
  - **Container support**: MariaDB and MySQL drivers included in all container images
  - **Complete feature parity** with SQLite and PostgreSQL backends
  - **Production ready**: Supports all MCP Gateway features including federation, caching, and A2A agents

* **Enhanced JWT Configuration** - Audience, issuer claims, and improved token validation:
  ```bash
  # New JWT configuration options:
  JWT_AUDIENCE=mcpgateway-api      # JWT audience claim for token validation
  JWT_ISSUER=mcpgateway           # JWT issuer claim for token validation
  ```
* **Account Security Configuration** - Lockout policies and failed login attempt limits:
  ```bash
  # New security policy settings:
  MAX_FAILED_LOGIN_ATTEMPTS=5              # Maximum failed attempts before lockout
  ACCOUNT_LOCKOUT_DURATION_MINUTES=30      # Account lockout duration in minutes
  ```

### Changed

#### **🔄 Authentication Migration**
* **Username to Email Migration** - All authentication now uses email addresses instead of usernames
  ```bash
  # OLD (v0.6.0 and earlier):
  python3 -m mcpgateway.utils.create_jwt_token --username admin --exp 10080 --secret my-test-key

  # NEW (v0.7.0+):
  python3 -m mcpgateway.utils.create_jwt_token --username admin@example.com --exp 10080 --secret my-test-key
  ```
* **JWT Token Format Enhanced** - Tokens now include team context and scoped permissions
* **API Authentication Updated** - All examples and documentation updated to use email-based authentication

#### **📊 Database Schema Evolution**
* **New Multi-Tenant Tables**: email_users, email_teams, email_team_members, email_team_invitations, **token_usage_logs**
* **Token Management Tables**: email_api_tokens, token_usage_logs, token_revocations - Complete API token lifecycle tracking
* **Extended Resource Tables** - All resource tables now include team_id, owner_email, visibility columns
* **Performance Indexing** - Strategic indexes on team_id, owner_email, visibility for optimal query performance

#### **🚀 API Enhancements**
* **New Authentication Endpoints** - Email registration/login and SSO provider integration
* **New Team Management Endpoints** - Complete CRUD operations for teams and memberships
* **Enhanced Resource Endpoints** - All resource endpoints support team-scoping parameters
* **Backward Compatibility** - Existing API endpoints remain functional with feature flags

### Security

* **Data Isolation** - Team-scoped queries prevent cross-tenant data access
* **Resource Ownership** - Every resource has owner_email and team_id validation
* **Visibility Enforcement** - Private/Team/Public visibility strictly enforced
* **Secure Tokens** - Invitation tokens with expiration and single-use validation
* **Domain Restrictions** - Corporate domain enforcement via SSO_TRUSTED_DOMAINS
* **MFA Support** - Automatic enforcement of SSO provider MFA policies

### Documentation

* **Architecture Documentation** - `docs/docs/architecture/multitenancy.md` - Complete multi-tenancy architecture guide
* **SSO Integration Tutorials**:
  - `docs/docs/manage/sso.md` - General SSO configuration guide
  - `docs/docs/manage/sso-github-tutorial.md` - GitHub SSO integration tutorial
  - `docs/docs/manage/sso-google-tutorial.md` - Google SSO integration tutorial
  - `docs/docs/manage/sso-ibm-tutorial.md` - IBM Security Verify integration tutorial
  - `docs/docs/manage/sso-okta-tutorial.md` - Okta SSO integration tutorial
* **Configuration Reference** - Complete environment variable documentation with examples
* **Migration Guide** - Single-tenant to multi-tenant upgrade path with troubleshooting
* **API Reference** - Team-scoped endpoint documentation with usage examples

### Infrastructure

* **Team-Based Indexing** - Optimized database queries for multi-tenant workloads
* **Connection Pooling** - Enhanced configuration for enterprise scale
* **Migration Scripts** - Automated Alembic migrations with rollback support
* **Performance Monitoring** - Team-scoped metrics and observability

### Migration Guide

#### **Environment Configuration Updates**
Update your `.env` file with the new multi-tenancy settings:

```bash
#####################################
# Email-Based Authentication
#####################################

# Enable email-based authentication system
EMAIL_AUTH_ENABLED=true

# Platform admin user (bootstrap from environment)
PLATFORM_ADMIN_EMAIL=admin@example.com
PLATFORM_ADMIN_PASSWORD=changeme
PLATFORM_ADMIN_FULL_NAME=Platform Administrator

# Argon2id Password Hashing Configuration
ARGON2ID_TIME_COST=3
ARGON2ID_MEMORY_COST=65536
ARGON2ID_PARALLELISM=1

# Password Policy Configuration
PASSWORD_MIN_LENGTH=8
PASSWORD_REQUIRE_UPPERCASE=false
PASSWORD_REQUIRE_LOWERCASE=false
PASSWORD_REQUIRE_NUMBERS=false
PASSWORD_REQUIRE_SPECIAL=false

#####################################
# Personal Teams Configuration
#####################################

# Enable automatic personal team creation for new users
AUTO_CREATE_PERSONAL_TEAMS=true

# Personal team naming prefix
PERSONAL_TEAM_PREFIX=personal

# Team Limits
MAX_TEAMS_PER_USER=50
MAX_MEMBERS_PER_TEAM=100

# Team Invitation Settings
INVITATION_EXPIRY_DAYS=7
REQUIRE_EMAIL_VERIFICATION_FOR_INVITES=true

#####################################
# SSO Configuration (Optional)
#####################################

# Master SSO switch - enable Single Sign-On authentication
SSO_ENABLED=false

# GitHub OAuth Configuration
SSO_GITHUB_ENABLED=false
# SSO_GITHUB_CLIENT_ID=your-github-client-id
# SSO_GITHUB_CLIENT_SECRET=your-github-client-secret

# Google OAuth Configuration
SSO_GOOGLE_ENABLED=false
# SSO_GOOGLE_CLIENT_ID=your-google-client-id.googleusercontent.com
# SSO_GOOGLE_CLIENT_SECRET=your-google-client-secret

# IBM Security Verify OIDC Configuration
SSO_IBM_VERIFY_ENABLED=false
# SSO_IBM_VERIFY_CLIENT_ID=your-ibm-verify-client-id
# SSO_IBM_VERIFY_CLIENT_SECRET=your-ibm-verify-client-secret
# SSO_IBM_VERIFY_ISSUER=https://your-tenant.verify.ibm.com/oidc/endpoint/default
```

#### **Database Migration**
Database migrations run automatically on startup:
```bash
# Backup your database AND .env file first
cp mcp.db mcp.db.backup.$(date +%Y%m%d_%H%M%S)
cp .env .env.bak

# Update .env with new multi-tenancy settings
cp .env.example .env  # then configure PLATFORM_ADMIN_EMAIL and other settings

# Migrations run automatically when you start the server
make dev  # Migrations execute automatically, then server starts

# Or for production
make serve  # Migrations execute automatically, then production server starts
```

#### **JWT Token Generation Updates**
All JWT token generation now uses email addresses:
```bash
# Generate development tokens
export MCPGATEWAY_BEARER_TOKEN=$(python3 -m mcpgateway.utils.create_jwt_token \
    --username admin@example.com --exp 10080 --secret my-test-key)

# For API testing
curl -s -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN" \
     http://127.0.0.1:4444/version | jq
```

### Breaking Changes

* **Database Schema** - New tables and extended resource tables (backward compatible with feature flags)
* **Authentication System** - Migration from username to email-based authentication
  - **Action Required**: Update JWT token generation to use email addresses instead of usernames
  - **Action Required**: Update `.env` with new authentication configuration
* **API Changes** - New endpoints added, existing endpoints enhanced with team parameters
  - **Backward Compatible**: Existing endpoints work with new team-scoping parameters
* **Configuration** - New required environment variables for multi-tenancy features
  - **Action Required**: Copy updated `.env.example` to `.env` and configure multi-tenancy settings

### Issues Closed

**Primary Epic:**
- Closes #860 - [EPIC]: Complete Enterprise Multi-Tenancy System with Team-Based Resource Scoping

**Core Security & Authentication:**
- Closes #544 - Database-Backed User Authentication with Argon2id (replace BASIC auth)
- Closes #283 - Role-Based Access Control (RBAC) - User/Team/Global Scopes for full multi-tenancy support
- Closes #426 - Configurable Password and Secret Policy Engine
- Closes #87 - Epic: Secure JWT Token Catalog with Per-User Expiry and Revocation
- Closes #282 - Per-Virtual-Server API Keys with Scoped Access

**SSO Integration:**
- Closes #220 - Authentication & Authorization - SSO + Identity-Provider Integration
- Closes #278 - Authentication & Authorization - Google SSO Integration Tutorial
- Closes #859 - Authentication & Authorization - IBM Security Verify Enterprise SSO Integration

**Future Foundation:**
- Provides foundation for #706 - ABAC Virtual Server Support (RBAC foundation implemented)

---

## [0.6.0] - 2025-08-22 - Security, Scale & Smart Automation

### Overview

This major release focuses on **Security, Scale & Smart Automation** with **118 commits** and **93 issues resolved**, bringing significant improvements across multiple domains:

- **🔌 Plugin Framework** - Comprehensive plugin system with pre/post hooks for extensible gateway capabilities
- **🤖 A2A (Agent-to-Agent) Support** - Full integration for external AI agents (OpenAI, Anthropic, custom agents)
- **📊 OpenTelemetry Observability** - Vendor-agnostic observability with Phoenix integration and comprehensive metrics
- **🔄 Bulk Import System** - Enterprise-grade bulk tool import with 200-tool capacity and rate limiting
- **🔐 Enhanced Security** - OAuth 2.0 support, improved headers, well-known URI handlers, and security validation
- **⚡ Performance & Scale** - Streamable HTTP improvements, better caching, connection optimizations
- **🛠️ Developer Experience** - Enhanced UI/UX, better error handling, tool annotations, mutation testing

### Added

#### **🔌 Plugin Framework & Extensibility** (#319, #313)
* **Comprehensive Plugin System** - Full plugin framework with manifest-based configuration
* **Pre/Post Request Hooks** - Plugin hooks for request/response interception and modification
* **Tool Invocation Hooks** (#682) - `tool_pre_invoke` and `tool_post_invoke` plugin hooks
* **Plugin CLI Tools** (#720) - Command-line interface for authoring and packaging plugins
* **Phoenix Observability Plugin** (#727) - Built-in Phoenix integration for observability
* **External Plugin Support** (#773) - Support for loading external plugins with configuration management

#### **🤖 A2A (Agent-to-Agent) Integration** (#298, #792)
* **Multi-Agent Support** - Integration for OpenAI, Anthropic, and custom AI agents
* **Agent as Tools** - A2A agents automatically exposed as tools within virtual servers
* **Protocol Versioning** - A2A protocol version support for compatibility
* **Authentication Support** - Flexible auth types (API key, OAuth, bearer tokens) for agents
* **Metrics & Monitoring** - Comprehensive metrics collection for agent interactions
* **Admin UI Integration** - Dedicated A2A management tab in admin interface

#### **📊 OpenTelemetry Observability** (#735)
* **Vendor-Agnostic Observability** - Full OpenTelemetry instrumentation across the gateway
* **Phoenix Integration** (#727) - Built-in Phoenix observability plugin for ML monitoring
* **Distributed Tracing** - Request tracing across federated gateways and MCP servers
* **Metrics Export** - Comprehensive metrics export to OTLP-compatible backends
* **Performance Monitoring** - Detailed performance metrics for tools, resources, and agents

#### **🔄 Bulk Operations & Scale**
* **Bulk Tool Import** (#737, #798) - Enterprise-grade bulk import with 200-tool capacity
* **Rate Limiting** - Built-in rate limiting for bulk operations (10 requests/minute)
* **Batch Processing** - Efficient batch processing with progress tracking
* **Import Validation** - Comprehensive validation during bulk import operations
* **Export Capabilities** (#186, #185) - Granular configuration export/import via UI & API

#### **🔐 Security Enhancements**
* **OAuth 2.0 Support** (#799) - OAuth authentication support in gateway edit functionality
* **Well-Known URI Handler** (#540) - Configurable handlers for security.txt, robots.txt
* **Enhanced Security Headers** (#533, #344) - Additional configurable security headers for Admin UI
* **Header Passthrough Security** (#685) - Improved security for HTTP header passthrough
* **Bearer Token Removal Option** (#705) - Option to completely disable bearer token authentication

#### **💾 Admin UI Log Viewer** (#138, #364)
* **Real-time Log Monitoring** - Built-in log viewer with live streaming via Server-Sent Events
* **Advanced Filtering** - Filter by log level, entity type, time range, and full-text search
* **Export Capabilities** - Export filtered logs to JSON or CSV format
* **In-memory Buffer** - Configurable circular buffer (1MB default) with size-based eviction
* **Color-coded Severity** - Visual indicators for debug, info, warning, error, critical levels
* **Request Tracing** - Track logs by request ID for debugging distributed operations

#### **🏷️ Tagging & Metadata System** (#586)
* **Comprehensive Tag Support** - Tags for tools, resources, prompts, gateways, and A2A agents
* **Tag-based Filtering** - Filter and search by tags across all entities
* **Tag Validation** - Input validation and editing support for tags
* **Metadata Tracking** (#137) - Creator and timestamp metadata for servers, tools, resources

#### **🔄 MCP Protocol Enhancements**
* **MCP Elicitation Support** (#708) - Implementation of MCP elicitation protocol (v2025-06-18)
* **Streamable HTTP Virtual Server Support** (#320) - Full virtual server support for Streamable HTTP
* **SSE Keepalive Configuration** (#690) - Configurable keepalive events for SSE transport
* **Enhanced Tool Annotations** (#774) - Fixed and improved tool annotation system

#### **🚀 Performance & Infrastructure**
* **Mutation Testing** (#280, #256) - Comprehensive mutation testing with mutmut for test quality
* **Async Performance Testing** (#254) - Async code testing and performance profiling
* **Database Caching Improvements** (#794) - Enhanced caching with database as cache type
* **Connection Optimizations** (#787) - Improved connection handling and authentication decoding

### Fixed

#### **🐛 Critical Bug Fixes**
* **Virtual Server Functionality** (#704) - Fixed virtual servers not working as advertised in v0.5.0
* **Tool Invocation Errors** (#753, #696) - Fixed tool invocation returning 'Invalid method' errors
* **Streamable HTTP Issues** (#728, #560) - Fixed translation feature connection and tool listing issues
* **Database Migration** (#661, #478, #479) - Fixed database migration issues during doctest execution
* **Resource & Prompt Loading** (#716, #393) - Fixed resources and prompts not displaying in Admin Dashboard

#### **🔧 Tool & Gateway Management**
* **Tool Edit Screen Issues** (#715, #786) - Fixed field mismatch and MCP tool validation errors
* **Duplicate Gateway Registration** (#649) - Fixed bypassing of uniqueness check for equivalent URLs
* **Gateway Registration Failures** (#646) - Fixed MCP Server/Federated Gateway registration issues
* **Tool Description Display** (#557) - Fixed cleanup of tool descriptions (newline removal, text truncation)

#### **🚦 Connection & Transport Issues**
* **DNS Resolution Issues** (#744) - Fixed gateway failures with CDNs/load balancers
* **Docker Container Issues** (#560) - Fixed tool listing when running inside Docker
* **Connection Authentication** - Fixed auth header issues and connection reliability
* **Session Management** (#518) - Fixed Redis runtime errors with multiple sessions

#### **🖥️ UI/UX Improvements**
* **Tool Annotations Display** (#774) - Fixed annotations not working with improved specificity
* **Escape Key Handler** (#802) - Added event handler for escape key functionality
* **Content Validation** (#436) - Fixed content length verification when headers absent
* **Resource MIME Types** (#520) - Fixed resource mime-type always storing as text/plain

### Changed

#### **🔄 Architecture & Protocol Updates**
* **Wrapper Functionality** (#779, #780) - Major redesign of wrapper functionality for performance
* **Integration Type Migration** (#452) - Removed "Integration Type: MCP", now supports only REST
* **Transport Protocol Updates** - Enhanced Streamable HTTP support with virtual servers
* **Plugin Configuration** - New plugin configuration system with enabled/disabled flags (#679)

#### **📊 Metrics & Monitoring Enhancements** (#368)
* **Enhanced Metrics Tab UI** - Virtual servers and top 5 performance tables
* **Comprehensive Metrics Collection** - Improved metrics for A2A agents, plugins, and tools
* **Performance Monitoring** - Better performance tracking across all system components

#### **🔧 Developer Experience Improvements**
* **Enhanced Error Messages** (#666, #672) - Improved error handling throughout main.py and frontend
* **Better Validation** (#694) - Enhanced validation for gateway creation and all endpoints
* **Documentation Updates** - Improved plugin development workflow and architecture documentation

#### **⚙️ Configuration & Environment**
* **Plugin Configuration** - New `plugins/config.yaml` system with enable/disable flags
* **A2A Configuration** - Comprehensive A2A configuration options with feature flags
* **Security Configuration** - Enhanced security configuration validation and startup checks

### Security

* **OAuth 2.0 Integration** - Secure OAuth authentication flow support
* **Enhanced Header Security** - Improved HTTP header passthrough with security validation
* **Well-Known URI Security** - Secure implementation of security.txt and robots.txt handlers
* **Plugin Security Model** - Secure plugin loading with manifest validation
* **A2A Security** - Encrypted credential storage for A2A agent authentication

### Infrastructure & DevOps

* **Comprehensive Testing** - Mutation testing, fuzz testing, async performance testing
* **Enhanced CI/CD** - Improved build processes with better error handling
* **Plugin Development Tools** - CLI tools for plugin authoring and packaging
* **Observability Integration** - Full OpenTelemetry and Phoenix integration

### Performance

* **Bulk Import Optimization** - Efficient batch processing for large-scale tool imports
* **Database Caching** - Enhanced caching strategies with database-backed cache
* **Connection Pool Management** - Optimized connection handling for better performance
* **Async Processing** - Improved async handling throughout the system

---

### 🌟 Release Contributors

This release represents a major milestone in MCP Gateway's evolution toward enterprise-grade security, scale, and intelligent automation. With contributions from developers worldwide, 0.6.0 delivers groundbreaking features including a comprehensive plugin framework, A2A agent integration, and advanced observability.

#### 🏆 Top Contributors in 0.6.0
- **Mihai Criveti** (@crivetimihai) - Release coordination, A2A architecture, plugin framework, OpenTelemetry integration, and comprehensive testing infrastructure
- **Manav Gupta** (@manavg) - Transport-translation enhancements, MCP eval server, reverse proxy implementation, and protocol optimizations
- **Madhav Kandukuri** (@madhav165) - Tool service refactoring, database optimizations, UI improvements, and performance enhancements
- **Keval Mahajan** (@kevalmahajan) - Plugin architecture, A2A catalog implementation, authentication improvements, and security enhancements

#### 🎉 New Contributors
Welcome to our first-time contributors who joined us in 0.6.0:

- **Multiple Contributors** - Multiple contributors helped with OAuth implementation, bulk import features, UI enhancements, and bug fixes across the codebase
- **Community Contributors** - Various developers contributed to plugin development, testing improvements, and documentation updates

#### 💪 Returning Contributors
Thank you to our dedicated contributors who continue to strengthen MCP Gateway:

- **Core Team Members** - Continued contributions to architecture, testing, documentation, and feature development
- **Community Members** - Ongoing support with bug reports, feature requests, and code improvements

This release showcases the power of open-source collaboration, bringing together expertise in AI/ML, distributed systems, security, and developer experience to create a truly enterprise-ready MCP gateway solution.

---

## [0.5.0] - 2025-08-06 - Enterprise Operability, Auth, Configuration & Observability

### Overview

This release focuses on enterprise-grade operability with **45 issues resolved**, bringing major improvements to authentication, configuration management, error handling, and developer experience. Key achievements include:

- **Enhanced JWT token security** with mandatory expiration when configured
- **Improved UI/UX** with better error messages, validation, and test tool enhancements
- **Stronger input validation** across all endpoints with XSS prevention
- **Developer productivity** improvements including file-specific linting and enhanced Makefile
- **Better observability** with masked sensitive data and improved status reporting

### Added

#### **Security & Authentication**
* **JWT Token Expiration Enforcement** (#425) - Made JWT token expiration mandatory when `REQUIRE_TOKEN_EXPIRATION=true`
* **Masked Authentication Values** (#601, #602) - Auth credentials now properly masked in API responses for gateways
* **API Docs Basic Auth Support** (#663) - Added basic authentication support for API documentation endpoints with `DOCS_BASIC_AUTH_ENABLED` flag
* **Enhanced XSS Prevention** (#576) - Added validation for RPC methods to prevent XSS attacks
* **SPDX License Headers** (#315, #317, #656) - Added script to verify and fix file headers with SPDX compliance

#### **Developer Experience**
* **File-Specific Linting** (#410, #660) - Added `make lint filename|dirname` target for targeted linting
* **MCP Server Name Column** (#506, #624) - New "MCP Server Name" column in Global tools/resources for better visibility
* **Export Connection Strings** (#154) - Enhanced connection string export for various clients from UI and API
* **Time Server Integration** (#403, #637) - Added time server to docker-compose.yaml for testing
* **Enhanced Makefile** (#365, #397, #507, #597, #608, #611, #612) - Major Makefile improvements:
  - Fixed database migration commands
  - Added comprehensive file-specific linting support
  - Improved formatting and readability
  - Consolidated run-gunicorn scripts
  - Added `.PHONY` declarations where missing
  - Fixed multiple server startup prevention (#430)

#### **UI/UX Improvements**
* **Test Tool Enhancements**:
  - Display default values from input_schema (#623, #644)
  - Fixed boolean inputs passing as on/off instead of true/false (#622)
  - Fixed array inputs being passed as strings (#620, #641)
  - Support for multiline text input (#650)
  - Improved parameter type conversion logic (#628)
* **Checkbox Selection** (#392, #619) - Added checkbox selection for servers, tools, and resources in UI
* **Improved Error Messages** (#357, #363, #569, #607, #629, #633, #648) - Comprehensive error message improvements:
  - More user-friendly error messages throughout
  - Better validation feedback for gateways, tools, prompts
  - Fixed "Unexpected error when registering gateway with same name" (#603)
  - Enhanced error handling for add/edit operations

#### **Code Quality & Testing**
* **Security Scanners**:
  - Added Snyk security scanning (#638, #639)
  - Integrated DevSkim static analysis tool (#590, #592)
  - Added nodejsscan for JavaScript security (#499)
* **Web Linting** (#390, #614) - Added lint-web to CI/CD with additional linters (jshint, jscpd, markuplint)
* **Package Linters** (#615, #616) - Added pypi package linters: check-manifest and pyroma

### Fixed

#### **Critical Bugs**
* **Gateway Issues**:
  - Fixed gateway ID returned as null by Create API (#521)
  - Fixed duplicate gateway registration bypassing uniqueness check (#603, #649)
  - Gateway update no longer fails silently in UI (#630)
  - Fixed validation for invalid gateway URLs (#578)
  - Improved STREAMABLEHTTP transport validation (#662)
  - Fixed unexpected error when registering gateway with same name (#603)
* **Tool & Resource Handling**:
  - Fixed edit tool update failures with integration_type="REST" (#579)
  - Fixed inconsistent acceptable length of tool names (#631, #651)
  - Fixed long input names being reflected in error messages (#598)
  - Fixed edit tool sending invalid "STREAMABLE" value (#610)
  - Fixed GitHub MCP Server registration flow (#584)
* **Authentication & Security**:
  - Fixed auth_username and auth_password not being set correctly (#472)
  - Fixed _populate_auth functionality (#471)
  - Properly masked auth values in gateway APIs (#601)

#### **UI/UX Fixes**
* **Edit Functionality**:
  - Fixed edit prompt failing when template field is empty (#591)
  - Fixed edit screens for servers and resources (#633, #648)
  - Improved consistency in displaying error messages (#357)
* **Version Panel & Status**:
  - Clarified difference between "Reachable" and "Available" status (#373, #621)
  - Fixed service status display in version panel
* **Input Validation**:
  - Fixed array input parsing in test tool UI (#620, #641)
  - Fixed boolean input handling (#622)
  - Added support for multiline text input (#650)

#### **Infrastructure & Build**
* **Docker & Deployment**:
  - Fixed database migration commands in Makefile (#365)
  - Resolved Docker container issues (#560)
  - Fixed internal server errors during CRUD operations (#85)
* **Documentation & API**:
  - Fixed OpenAPI title from "MCP_Gateway" to "MCP Gateway" (#522)
  - Added mcp-cli documentation (#46)
  - Fixed invalid HTTP request logs (#434)
* **Code Quality**:
  - Fixed redundant conditional expressions (#423, #653)
  - Fixed lint-web issues in admin.js (#613)
  - Updated default .env examples to enable UI (#498)

### Changed

#### **Configuration & Defaults**
* **UI Enabled by Default** - Updated .env.example to set `MCPGATEWAY_UI_ENABLED=true` and `MCPGATEWAY_ADMIN_API_ENABLED=true`
* **Enhanced Validation** - Stricter validation rules for gateway URLs, tool names, and input parameters
* **Improved Error Handling** - More descriptive and actionable error messages across all operations

#### **Performance & Reliability**
* **Connection Handling** - Better retry mechanisms and timeout configurations
* **Session Management** - Improved stateful session handling for Streamable HTTP
* **Resource Management** - Enhanced cleanup and resource disposal

#### **Developer Workflow**
* **Simplified Scripts** - Consolidated run-gunicorn scripts into single improved version
* **Better Testing** - Enhanced test coverage with additional security and validation tests
* **Improved Tooling** - Comprehensive linting and security scanning integration

### Security

* Mandatory JWT token expiration when configured
* Masked sensitive authentication data in API responses
* Enhanced XSS prevention in RPC methods
* Comprehensive security scanning with Snyk, DevSkim, and nodejsscan
* SPDX-compliant file headers for license compliance

### Infrastructure

* Improved Makefile with better target organization and documentation
* Enhanced Docker compose with integrated time server
* Better CI/CD with comprehensive linting and security checks
* Simplified deployment with consolidated scripts

---

### 🌟 Release Contributors

This release represents a major step forward in enterprise readiness with contributions from developers worldwide focusing on security, usability, and operational excellence.

#### 🏆 Top Contributors in 0.5.0
- **Mihai Criveti** (@crivetimihai) - Release coordinator, infrastructure improvements, security enhancements
- **Madhav Kandukuri** (@madhav165) - XSS prevention, validation improvements, security fixes
- **Keval Mahajan** (@kevalmahajan) - UI enhancements, test tool improvements, checkbox implementation
- **Manav Gupta** - File-specific linting support and Makefile improvements
- **Rakhi Dutta** (@rakdutta) - Comprehensive error message improvements across add/edit operations
- **Shoumi Mukherjee** (@shoummu1) - Array input parsing, tool creation fixes, UI improvements

#### 🎉 New Contributors
Welcome to our first-time contributors who joined us in 0.5.0:

- **JimmyLiao** (@jimmyliao) - Fixed STREAMABLEHTTP transport validation
- **Arnav Bhattacharya** (@arnav264) - Added file header verification script
- **Guoqiang Ding** (@dgq8211) - Fixed tool parameter type conversion and API docs auth
- **Pascal Roessner** (@roessner) - Added MCP Gateway Name to tools overview
- **Kumar Tiger** (@kumar-tiger) - Fixed duplicate gateway name registration
- **Shamsul Arefin** (@shams) - Improved JavaScript validation patterns and UUID support
- **Emmanuel Ferdman** (@emmanuelferdman) - Fixed prompt service test cases
- **Tomas Pilar** (@thomas7pilar) - Fixed missing ID in gateway response and auth flag issues

#### 💪 Returning Contributors
Thank you to our dedicated contributors who continue to strengthen MCP Gateway:

- **Nayana R Gowda** - Fixed redundant conditional expressions and Makefile formatting
- **Mohan Lakshmaiah** - Improved tool name consistency validation
- **Abdul Samad** - Continued UI polish and improvements
- **Satya** (@TS0713) - Gateway URL validation improvements
- **ChrisPC-39** - Updated default .env to enable UI and added tool search functionality

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

This release represents a major milestone in code quality, security, and reliability. With [59 issues resolved](https://github.com/IBM/mcp-context-forge/issues?q=is%3Aissue%20state%3Aclosed%20milestone%3A%22Release%200.4.0%22), we've achieved:
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
  VALIDATION_MAX_JSON_DEPTH=30
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
