# API Connect FAM Plugin - User Stories

**Document Version:** 1.0  
**Date:** 2026-05-08  
**Audience:** Development Team  
**Purpose:** Implementation user stories for building the APIConnectFAM plugin from scratch

---

## Overview

This document contains 11 user stories for implementing the APIConnectFAM plugin. Each user story represents a complete feature with sub-tasks that can be tracked independently.

---

## User Story 1: Plugin Module Structure and Configuration Schema

**As a** developer  
**I want to** set up the plugin foundation with module structure, configuration schema, data models, and exception hierarchy  
**So that** I have a clean, validated foundation for implementing all components

**One-liner:** Foundation setup with config, models, and exceptions

**Estimated Effort:** 12 hours

### Sub-tasks

- [ ] **Task 1.1:** Create directory structure
  - Create `plugins/apiconnect_fam/` with subdirectories: `activities/`, `handlers/`, `utils/`
  - Create all `__init__.py` files with proper exports

- [ ] **Task 1.2:** Implement configuration schema
  - Create `APIConnectFAMConfig` class in `apiconnect_fam.py`
  - Add 20+ configuration fields (FAM connection, runtime registration, intervals, retry, circuit breaker)
  - Add Pydantic validators for URLs, positive integers, enums
  - Write unit tests for valid and invalid configurations (10+ tests)

- [ ] **Task 1.3:** Implement data models
  - Create `models.py` file
  - Implement `ActivityContext` model (runtime_id, fam_client, config, db_session)
  - Implement `ActivityStatistics` model (executions, successes, failures, durations)
  - Implement `SyncStatistics` model (aggregate statistics)
  - Implement `ReregistrationReport` model (parse FAM response)
  - Implement `InactiveHeartbeat` model (missed heartbeat representation)
  - Implement enums: `ActivityStatus`, `HeartbeatStatus`
  - Write unit tests for all models (10+ tests)

- [ ] **Task 1.4:** Implement exception hierarchy
  - Create `utils/errors.py` file
  - Implement base `AgentError` exception
  - Implement specific exceptions: `RegistrationError`, `RecoveryError`, `SyncError`, `FAMClientError`, `ValidationError`, `RetryExhaustedError`, `CircuitBreakerOpenError`
  - Add error codes and context to exceptions
  - Write unit tests for exception instantiation

**Files to Create:**
- `plugins/apiconnect_fam/__init__.py`
- `plugins/apiconnect_fam/apiconnect_fam.py` (config only)
- `plugins/apiconnect_fam/models.py`
- `plugins/apiconnect_fam/utils/errors.py`
- `plugins/apiconnect_fam/activities/__init__.py`
- `plugins/apiconnect_fam/handlers/__init__.py`
- `plugins/apiconnect_fam/utils/__init__.py`

---

## User Story 2: FAM Client Integration

**As a** developer  
**I want to** create an HTTP client for FAM Asset Catalog API with payload builders and state trackers  
**So that** the plugin can communicate with FAM and detect asset changes efficiently

**One-liner:** HTTP client with 10 API methods, payload builders, and state trackers

**Estimated Effort:** 16 hours

### Sub-tasks

- [ ] **Task 2.1:** Implement FAM HTTP client
  - Create `fam_client.py` file
  - Implement `FAMAssetCatalogClient` class with httpx.AsyncClient
  - Add authentication (Bearer token) and timeout handling (30s default)
  - Implement 10 API methods:
    - `register_runtime()` - POST /runtimes
    - `send_heartbeat()` - POST /heartbeats
    - `submit_metrics()` - POST /metrics
    - `create_server()` - POST /servers
    - `update_server()` - PUT /servers/{id}
    - `delete_server()` - DELETE /servers/{id}
    - `bulk_create_tools()` - POST /tools/bulk
    - `bulk_update_tools()` - PUT /tools/bulk
    - `bulk_delete_tools()` - DELETE /tools/bulk
    - `check_health()` - GET /health
  - Handle HTTP errors with `FAMClientError`
  - Add request/response logging at DEBUG level

- [ ] **Task 2.2:** Implement payload builders
  - Add `build_runtime_payload()` method
  - Add `build_heartbeat_payload()` method
  - Add `build_metrics_payload()` method
  - Add `build_server_payload()` method
  - Add `build_tool_payload()` method
  - Validate required fields and handle optional fields
  - Map ContextForge models to FAM format

- [ ] **Task 2.3:** Implement state trackers
  - Create `ServerStateTracker` class
  - Create `ToolStateTracker` class
  - Implement hash computation utility (MD5 of relevant fields)
  - Detect new, updated, deleted assets
  - Return sync operations needed

- [ ] **Task 2.4:** Write unit tests
  - Mock httpx responses for all API methods (10+ tests)
  - Test payload builders (5+ tests)
  - Test state trackers for all scenarios (5+ tests)

**Files to Create:**
- `plugins/apiconnect_fam/fam_client.py` (1400+ lines)

**Dependencies:** User Story 1

---

## User Story 3: Runtime Registration

**As a** developer  
**I want to** implement activity base classes and runtime registration activity  
**So that** the plugin can register itself with FAM on startup and get a runtime ID

**One-liner:** Activity base classes and registration activity

**Estimated Effort:** 10 hours

### Sub-tasks

- [ ] **Task 3.1:** Implement activity base classes
  - Create `activities/base.py` file
  - Implement `AbstractActivity` class:
    - Abstract `perform()` method
    - `execute()` method with timing and error handling
    - Statistics tracking (success/failure, duration)
    - Logging with context
  - Implement `AbstractScheduledActivity` class:
    - Extends `AbstractActivity`
    - Abstract `get_interval_seconds()` method
    - Track last execution time
    - Skip if already running
  - Add lifecycle methods: `initialize()`, `cleanup()`

- [ ] **Task 3.2:** Implement registration activity
  - Create `activities/register_runtime.py` file
  - Implement `RegisterRuntimeActivity` extending `AbstractActivity`
  - Build registration payload from config
  - Call `fam_client.register_runtime()` with retry
  - Parse `ReregistrationReport` from response
  - Store runtime_id in context
  - Return report for recovery handler

- [ ] **Task 3.3:** Handle registration scenarios
  - First-time registration (no previous timestamps)
  - Re-registration (has previous timestamps)
  - Registration failure (retry exhausted)

- [ ] **Task 3.4:** Write unit tests
  - Test base classes (5+ tests)
  - Test successful first-time registration
  - Test successful re-registration with timestamps
  - Test registration failure handling
  - Test retry behavior

**Files to Create:**
- `plugins/apiconnect_fam/activities/base.py`
- `plugins/apiconnect_fam/activities/register_runtime.py`

**Dependencies:** User Story 1, User Story 2

---

## User Story 4: Heartbeat Management

**As a** developer  
**I want to** implement periodic heartbeat activity  
**So that** FAM knows the runtime is alive and active

**One-liner:** Periodic ACTIVE heartbeat sending every 60 seconds

**Estimated Effort:** 4 hours

### Sub-tasks

- [ ] **Task 4.1:** Implement heartbeat activity
  - Create `activities/send_heartbeat.py` file
  - Implement `SendHeartbeatActivity` extending `AbstractScheduledActivity`
  - Return interval from config (`fam_heartbeat_interval_seconds`, default 60s)
  - Build heartbeat payload with ACTIVE status and runtime_id

- [ ] **Task 4.2:** Integrate with resilience layer
  - Call `fam_client.send_heartbeat()` with retry logic
  - Handle circuit breaker state (skip if open)
  - Update statistics on each execution

- [ ] **Task 4.3:** Add logging and error handling
  - Log heartbeat attempts and results
  - Log failures but don't crash
  - Track success/failure counts

- [ ] **Task 4.4:** Write unit tests
  - Test successful heartbeat send
  - Test retry on transient failure
  - Test circuit breaker open (skip)
  - Test interval configuration

**Files to Create:**
- `plugins/apiconnect_fam/activities/send_heartbeat.py`

**Dependencies:** User Story 3, User Story 2

---

## User Story 5: Server Synchronization

**As a** developer  
**I want to** implement server sync activity with hash-based change detection  
**So that** FAM has an up-to-date catalog of MCP servers

**One-liner:** Hash-based server change detection and sync

**Estimated Effort:** 8 hours

### Sub-tasks

- [ ] **Task 5.1:** Implement server sync activity
  - Create `activities/sync_servers.py` file
  - Implement `SyncServersActivity` extending `AbstractScheduledActivity`
  - Return interval from config (`fam_server_sync_interval_seconds`, default 300s)

- [ ] **Task 5.2:** Implement database queries
  - Query all servers from ContextForge database using SQLAlchemy
  - Filter active servers only

- [ ] **Task 5.3:** Implement change detection and sync
  - Use `ServerStateTracker` to detect new, updated, deleted servers
  - Create new servers via `fam_client.create_server()`
  - Update changed servers via `fam_client.update_server()`
  - Delete removed servers via `fam_client.delete_server()`
  - Update state tracker after successful sync

- [ ] **Task 5.4:** Handle errors and track statistics
  - Retry individual operations on failure
  - Continue on partial failures
  - Track sync statistics (created/updated/deleted counts)
  - Log all operations

- [ ] **Task 5.5:** Write unit tests
  - Test no changes (skip sync)
  - Test new servers created
  - Test servers updated
  - Test servers deleted
  - Test mixed operations
  - Test partial failure handling

**Files to Create:**
- `plugins/apiconnect_fam/activities/sync_servers.py`

**Dependencies:** User Story 3, User Story 2

---

## User Story 6: Tool Synchronization

**As a** developer  
**I want to** implement tool sync activity with bulk operations and batching  
**So that** FAM has an up-to-date catalog of MCP tools efficiently

**One-liner:** Bulk tool operations with batching (100 tools per batch)

**Estimated Effort:** 10 hours

### Sub-tasks

- [ ] **Task 6.1:** Implement tool sync activity
  - Create `activities/sync_tools.py` file
  - Implement `SyncToolsActivity` extending `AbstractScheduledActivity`
  - Return interval from config (`fam_tool_sync_interval_seconds`, default 300s)

- [ ] **Task 6.2:** Implement database queries
  - Query all tools from ContextForge database using SQLAlchemy
  - Filter active tools only

- [ ] **Task 6.3:** Implement change detection and bulk sync
  - Use `ToolStateTracker` to detect new, updated, deleted tools
  - Bulk create new tools via `fam_client.bulk_create_tools()`
  - Bulk update changed tools via `fam_client.bulk_update_tools()`
  - Bulk delete removed tools via `fam_client.bulk_delete_tools()`
  - Update state tracker after successful sync

- [ ] **Task 6.4:** Implement batching
  - Batch size: 100 tools per request
  - Process batches sequentially
  - Continue on batch failure

- [ ] **Task 6.5:** Handle errors and track statistics
  - Retry batch operations on failure
  - Log failed batches
  - Track sync statistics (created/updated/deleted counts)
  - Continue with remaining batches

- [ ] **Task 6.6:** Write unit tests
  - Test no changes (skip sync)
  - Test new tools created (single batch)
  - Test new tools created (multiple batches)
  - Test tools updated
  - Test tools deleted
  - Test mixed operations
  - Test batch failure handling

**Files to Create:**
- `plugins/apiconnect_fam/activities/sync_tools.py`

**Dependencies:** User Story 3, User Story 2

---

## User Story 7: Metrics Synchronization

**As a** developer  
**I want to** implement metrics aggregation and sync activity  
**So that** FAM has visibility into runtime performance data

**One-liner:** Performance metrics aggregation and sync

**Estimated Effort:** 10 hours

### Sub-tasks

- [ ] **Task 7.1:** Implement metrics sync activity
  - Create `activities/send_metrics.py` file
  - Implement `SendMetricsActivity` extending `AbstractScheduledActivity`
  - Return interval from config (`fam_metrics_interval_seconds`, default 300s)

- [ ] **Task 7.2:** Implement database queries
  - Query server metrics from ContextForge database (ServerMetric table)
  - Query tool metrics from ContextForge database (ToolMetric table)
  - Filter by timestamp (since last sync)

- [ ] **Task 7.3:** Implement metrics aggregation
  - Aggregate metrics by server ID
  - Aggregate metrics by tool ID
  - Calculate totals: request count, error count, avg latency

- [ ] **Task 7.4:** Build and send metrics
  - Build metrics payload in FAM format
  - Call `fam_client.submit_metrics()` with aggregated data
  - Track last sync timestamp

- [ ] **Task 7.5:** Handle edge cases
  - Handle empty results gracefully (skip sync)
  - Handle partial failures (log and continue)
  - Handle database query errors

- [ ] **Task 7.6:** Write unit tests
  - Test successful metrics sync
  - Test no metrics available
  - Test database query failure
  - Test aggregation logic
  - Test timestamp tracking

**Files to Create:**
- `plugins/apiconnect_fam/activities/send_metrics.py`

**Dependencies:** User Story 3, User Story 2

---

## User Story 8: Activity Orchestration

**As a** developer  
**I want to** implement an orchestrator to manage activity lifecycle and scheduling  
**So that** all activities are coordinated and executed correctly

**One-liner:** Activity lifecycle and scheduling coordinator

**Estimated Effort:** 10 hours

### Sub-tasks

- [ ] **Task 8.1:** Implement orchestrator class
  - Create `activity_orchestrator.py` file
  - Implement `ActivityOrchestrator` class
  - Initialize with activity context

- [ ] **Task 8.2:** Register activities
  - Register `RegisterRuntimeActivity` (one-time)
  - Register `SendHeartbeatActivity` (scheduled)
  - Register `SendMetricsActivity` (scheduled)
  - Register `SyncServersActivity` (scheduled)
  - Register `SyncToolsActivity` (scheduled)

- [ ] **Task 8.3:** Implement start() method
  - Execute registration activity first
  - Start all scheduled activities
  - Create asyncio tasks for each activity
  - Track running tasks

- [ ] **Task 8.4:** Implement stop() method
  - Cancel all running tasks
  - Wait for graceful shutdown
  - Cleanup resources

- [ ] **Task 8.5:** Implement statistics aggregation
  - Implement `get_statistics()` method
  - Aggregate statistics from all activities
  - Return comprehensive statistics

- [ ] **Task 8.6:** Add error handling
  - Catch and log activity errors
  - Restart failed activities automatically
  - Track error counts

- [ ] **Task 8.7:** Write unit tests
  - Test start/stop lifecycle
  - Test activity scheduling
  - Test error handling
  - Test statistics aggregation
  - Test graceful shutdown

**Files to Create:**
- `plugins/apiconnect_fam/activity_orchestrator.py`

**Dependencies:** User Story 3, User Story 4, User Story 5, User Story 6, User Story 7

---

## User Story 9: Plugin Integration

**As a** developer  
**I want to** implement the main plugin class and integrate with ContextForge framework  
**So that** the plugin can be loaded and managed by ContextForge

**One-liner:** Main plugin class and ContextForge integration

**Estimated Effort:** 12 hours

### Sub-tasks

- [ ] **Task 9.1:** Implement main plugin class
  - Complete `apiconnect_fam.py` file
  - Implement `APIConnectFAMPlugin` class extending ContextForge `Plugin`
  - Load and validate configuration

- [ ] **Task 9.2:** Implement initialize() method
  - Validate configuration
  - Create FAM client
  - Create activity context
  - Create orchestrator
  - Start orchestrator
  - Trigger recovery if needed

- [ ] **Task 9.3:** Implement shutdown() method
  - Stop orchestrator
  - Close FAM client
  - Cleanup resources
  - Log shutdown completion

- [ ] **Task 9.4:** Expose statistics endpoint
  - Implement `get_statistics()` method
  - Return orchestrator statistics
  - Expose via plugin API

- [ ] **Task 9.5:** Add comprehensive logging
  - Log initialization steps
  - Log configuration (sanitize secrets)
  - Log runtime_id
  - Log all lifecycle events

- [ ] **Task 9.6:** Create plugin manifest
  - Create `plugin-manifest.yaml` file
  - Define plugin metadata (name, version, description, author)
  - Define configuration schema
  - Define plugin dependencies
  - Define plugin capabilities

- [ ] **Task 9.7:** Create documentation
  - Update `docs/README.md` with plugin overview
  - Update `docs/SETUP.md` with installation and configuration
  - Create configuration examples (minimal, dev, production)

- [ ] **Task 9.8:** Write integration tests
  - Test full plugin lifecycle
  - Test configuration loading
  - Test statistics endpoint
  - Test error handling
  - Test graceful shutdown

**Files to Create:**
- `plugins/apiconnect_fam/apiconnect_fam.py` (complete)
- `plugins/apiconnect_fam/plugin-manifest.yaml`
- Update `plugins/apiconnect_fam/docs/README.md`
- Update `plugins/apiconnect_fam/docs/SETUP.md`

**Dependencies:** User Story 1, User Story 8

---

## User Story 10: Resilience Layer & Circuit Breaker

**As a** developer  
**I want to** implement retry logic with exponential backoff and circuit breaker pattern  
**So that** transient failures are handled gracefully and cascading failures are prevented

**One-liner:** Retry logic with exponential backoff and circuit breaker

**Estimated Effort:** 14 hours

### Sub-tasks

- [ ] **Task 10.1:** Implement retry configuration
  - Create `utils/retry.py` file
  - Implement `RetryConfig` dataclass
  - Add fields: max_attempts, initial_delay, max_delay, exponential_base, jitter

- [ ] **Task 10.2:** Implement retry logic
  - Implement `with_retry()` async function
  - Accept callable and retry config
  - Implement exponential backoff calculation: `min(initial_delay * (base ^ attempt), max_delay)`
  - Add jitter to prevent thundering herd: `delay ± (jitter * delay)`
  - Log retry attempts with context

- [ ] **Task 10.3:** Handle different error types
  - Retry on network errors (timeouts, connection errors)
  - Retry on 5xx server errors
  - Retry on 429 rate limiting
  - Don't retry on 4xx client errors (except 429)
  - Raise `RetryExhaustedError` after max attempts

- [ ] **Task 10.4:** Implement circuit breaker
  - Implement `CircuitBreaker` class
  - Define three states: CLOSED, OPEN, HALF_OPEN
  - Implement state transitions:
    - CLOSED → OPEN: After failure_threshold consecutive failures
    - OPEN → HALF_OPEN: After recovery_timeout seconds
    - HALF_OPEN → CLOSED: After success_threshold successes
    - HALF_OPEN → OPEN: On any failure

- [ ] **Task 10.5:** Implement circuit breaker call method
  - Implement `call()` method
  - Check current state
  - Block if OPEN (raise `CircuitBreakerOpenError`)
  - Execute callable and track result
  - Update state based on result

- [ ] **Task 10.6:** Add metrics tracking
  - Track total calls, successes, failures
  - Track state transition timestamps
  - Log state transitions at WARNING level

- [ ] **Task 10.7:** Write unit tests for retry
  - Test successful operation (no retries)
  - Test transient failure then success
  - Test all retries exhausted
  - Test backoff calculation
  - Test jitter application

- [ ] **Task 10.8:** Write unit tests for circuit breaker
  - Test state transitions
  - Test blocking when open
  - Test recovery flow
  - Test concurrent access safety
  - Test metrics tracking

**Files to Create:**
- `plugins/apiconnect_fam/utils/retry.py`

**Dependencies:** User Story 1 (exception hierarchy)

**Integration Points:** User Story 2 (FAM client), User Story 4-7 (activities)

---

## User Story 11: Recovery Mechanism

**As a** developer  
**I want to** implement automatic recovery handler  
**So that** missed heartbeats, metrics, and asset syncs are recovered after downtime

**One-liner:** Automatic recovery of missed operations after downtime

**Estimated Effort:** 12 hours

### Sub-tasks

- [ ] **Task 11.1:** Implement recovery handler class
  - Create `handlers/recovery_handler.py` file
  - Implement `RecoveryHandler` class
  - Initialize with FAM client, config, and database session
  - Accept `ReregistrationReport` with timestamps

- [ ] **Task 11.2:** Implement trigger_recovery() method
  - Check if recovery is needed (has previous timestamps)
  - Orchestrate recovery operations in order:
    1. Recover heartbeats
    2. Recover metrics
    3. Recover assets
  - Return recovery statistics

- [ ] **Task 11.3:** Implement recover_heartbeats() method
  - Calculate missed heartbeat intervals
  - Generate INACTIVE heartbeats for missed periods
  - Send in batches of 100
  - Return count of recovered heartbeats

- [ ] **Task 11.4:** Implement recover_metrics() method
  - Query historical metrics from database
  - Filter by time window (last sync to now)
  - Aggregate by time windows
  - Send to FAM via `submit_metrics()`
  - Return count of metric records

- [ ] **Task 11.5:** Implement recover_assets() method
  - Query all current servers from database
  - Query all current tools from database
  - Perform full sync to FAM
  - Return recovery statistics (servers synced, tools synced)

- [ ] **Task 11.6:** Add comprehensive logging
  - Log recovery start/end
  - Log each recovery operation
  - Log recovery statistics
  - Log any failures

- [ ] **Task 11.7:** Write unit tests
  - Test no recovery needed (first registration)
  - Test heartbeat recovery
  - Test metrics recovery
  - Test asset recovery
  - Test full recovery flow
  - Test recovery failure handling
  - Test batching logic

**Files to Create:**
- `plugins/apiconnect_fam/handlers/recovery_handler.py`

**Dependencies:** User Story 1 (models), User Story 2 (FAM client), User Story 3 (registration)

**Integration Points:** User Story 8 (orchestrator triggers recovery)

---

## Implementation Summary

### Total Estimated Effort: ~118 hours (~3 weeks)

### Recommended Implementation Order

**Week 1: Foundation (36 hours)**
1. US-1: Plugin Module Structure and Configuration Schema (12h)
2. US-10: Resilience Layer & Circuit Breaker (14h)
3. US-2: FAM Client Integration (10h of 16h)

**Week 2: Core Activities (42 hours)**
4. US-2: FAM Client Integration (remaining 6h)
5. US-3: Runtime Registration (10h)
6. US-4: Heartbeat Management (4h)
7. US-5: Server Synchronization (8h)
8. US-6: Tool Synchronization (10h)
9. US-7: Metrics Synchronization (4h of 10h)

**Week 3: Integration & Recovery (40 hours)**
10. US-7: Metrics Synchronization (remaining 6h)
11. US-11: Recovery Mechanism (12h)
12. US-8: Activity Orchestration (10h)
13. US-9: Plugin Integration (12h)

### Dependencies Graph

```
US-1 (Foundation)
  ↓
US-10 (Resilience) ──→ US-2 (FAM Client)
  ↓                        ↓
  └──────────────→ US-3 (Runtime Registration)
                           ↓
                   ┌───────┴───────┬───────────┬───────────┐
                   ↓               ↓           ↓           ↓
              US-4 (Heartbeat) US-5 (Servers) US-6 (Tools) US-7 (Metrics)
                   ↓               ↓           ↓           ↓
                   └───────┬───────┴───────────┴───────────┘
                           ↓
                   US-8 (Orchestration) ←── US-11 (Recovery)
                           ↓
                   US-9 (Plugin Integration)
```

### Definition of Done

Each user story is complete when:
- [ ] All sub-tasks completed
- [ ] Code follows ContextForge coding standards
- [ ] Unit tests written and passing (80%+ coverage)
- [ ] Integration tests passing (where applicable)
- [ ] Code reviewed by peer
- [ ] Documentation updated
- [ ] No critical bugs or security issues
- [ ] Logging and error handling implemented
- [ ] Performance requirements met

---

**Document Status:** Ready for Implementation  
**Target Audience:** Development Team  
**Related Documents:** HLD.md, HLD_REFINEMENT.md, LLD.md