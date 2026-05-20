# API Connect FAM Plugin - Low Level Design (LLD)

**Document Version:** 2.0
**Date:** 2026-05-07
**Audience:** Core Architectural Software Development Team
**Purpose:** Implementation-specific technical specifications

**Note:** This document provides implementation details. For architectural overview, component responsibilities, and design decisions, refer to `HLD_REFINEMENT.md`.

---

## Table of Contents

1. [File Structure & Organization](#1-file-structure--organization)
2. [Class Signatures & Attributes](#2-class-signatures--attributes)
3. [Method Signatures](#3-method-signatures)
4. [Data Models & Validation](#4-data-models--validation)
5. [Database Queries](#5-database-queries)
6. [API Endpoint Specifications](#6-api-endpoint-specifications)
7. [Error Handling Patterns](#7-error-handling-patterns)
8. [Testing Specifications](#8-testing-specifications)
9. [Configuration Schema](#9-configuration-schema)
10. [Implementation Checklist](#10-implementation-checklist)

---

## 1. File Structure & Organization

### 1.1 Complete File Layout (Actual Implementation)

```
plugins/apiconnect_fam/
├── __init__.py                      # ~10 lines - Package exports
├── apiconnect_fam.py                # 307 lines - APIConnectFAMPlugin main class
├── activity_orchestrator.py         # 308 lines - ActivityOrchestrator
├── fam_client.py                    # 1405 lines - FAMAssetCatalogClient + payload builders + state trackers
├── models.py                        # 276 lines - Data models (ActivityContext, ActivityStatistics, etc.)
├── heartbeat_sync.py                # Legacy/unused - kept for reference
├── metrics_sync.py                  # Legacy/unused - kept for reference
├── server_sync.py                   # Legacy/unused - kept for reference
├── sync_orchestrator.py             # Legacy/unused - kept for reference
├── tool_sync.py                     # Legacy/unused - kept for reference
│
├── activities/
│   ├── __init__.py                  # ~5 lines
│   ├── base.py                      # 154 lines - AbstractActivity, AbstractScheduledActivity
│   ├── check_fam_health.py          # 147 lines - CheckFAMHealthActivity
│   ├── check_runtime_health.py      # ~120 lines - CheckRuntimeHealthActivity
│   ├── register_runtime.py          # ~100 lines - RegisterRuntimeActivity
│   ├── send_heartbeat.py            # 102 lines - SendHeartbeatActivity
│   ├── send_metrics.py              # 175 lines - SendMetricsActivity
│   ├── sync_servers.py              # 129 lines - SyncServersActivity
│   └── sync_tools.py                # 236 lines - SyncToolsActivity
│
├── handlers/
│   ├── __init__.py                  # ~5 lines
│   └── recovery_handler.py          # 261 lines - RecoveryHandler
│
├── utils/
│   ├── __init__.py                  # ~10 lines - Exports errors and retry utilities
│   ├── errors.py                    # 65 lines - Custom exception classes
│   └── retry.py                     # 271 lines - Retry logic + CircuitBreaker
│
└── docs/
    ├── HLD.md                       # High-level design
    ├── HLD_REFINEMENT.md            # Refined HLD
    ├── LLD.md                       # This document
    ├── README.md                    # Plugin overview
    ├── SETUP.md                     # Setup instructions
    ├── TROUBLESHOOTING.md           # Troubleshooting guide
    ├── ENHANCEMENT_PLAN.md          # Future enhancements
    └── IMPLEMENTATION_STATUS.md     # Implementation tracking

Total: ~3,500 lines of code (excluding docs and legacy files)
```

**Key Differences from Original LLD:**
- **Flat structure**: No nested `orchestrator/`, `resilience/`, `client/`, `models/`, `state/` directories
- **Consolidated files**: `fam_client.py` contains client + payload builders + state trackers (1405 lines)
- **Handlers directory**: Recovery logic separated into `handlers/`
- **Legacy files**: Old sync files kept for reference but not used
- **Documentation**: Comprehensive docs directory added


### 1.2 Import Dependencies

```python
# External dependencies (already in ContextForge)
# - httpx (async HTTP client)
# - pydantic (data validation)
# - sqlalchemy (database ORM)

# Standard library imports used across plugin
import asyncio
import hashlib
import json
import logging
import random
import time
from abc import ABC, abstractmethod
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Set, Tuple, TYPE_CHECKING

# First-party imports (ContextForge)
from mcpgateway.db import Server, SessionLocal, Tool, ServerMetric, ToolMetric
from mcpgateway.plugins.framework import Plugin, PluginConfig
```

---

## 2. Class Signatures & Attributes

### 2.1 APIConnectFAMPlugin (apiconnect_fam.py)

```python
class APIConnectFAMPlugin(Plugin):
    """Main plugin class - entry point for FAM integration."""
    
    # Instance attributes
    _cfg: APIConnectFAMConfig                    # Plugin configuration
    _fam_client: Optional[FAMAssetCatalogClient] # FAM HTTP client
    _orchestrator: Optional[ActivityOrchestrator] # Activity coordinator
    _runtime_id: Optional[str]                   # FAM runtime ID
    
    def __init__(self, config: PluginConfig) -> None:
        """Initialize plugin with configuration."""
    
    async def initialize(self) -> None:
        """
        Start the activity orchestrator and HTTP client.
        - Validates configuration
        - Creates FAM client
        - Registers runtime in FAM
        - Starts activity orchestrator
        - Triggers recovery if re-registration
        """
    
    async def _trigger_recovery_async(self) -> None:
        """Trigger recovery of missed operations asynchronously."""
    
    async def shutdown(self) -> None:
        """Stop the activity orchestrator and close HTTP client."""
```

### 2.2 ActivityOrchestrator (activity_orchestrator.py)

```python
class ActivityOrchestrator:
    """Orchestrates all activities for the Server Monitor Plugin."""
    
    # Instance attributes
    context: ActivityContext                      # Shared context
    fam_client: FAMAssetCatalogClient            # FAM API client
    runtime_id: str                              # Runtime ID
    recovery_handler: RecoveryHandler            # Recovery handler
    activities: List[AbstractScheduledActivity]   # All managed activities
    
    # Activity references (optional based on config)
    fam_health_activity: CheckFAMHealthActivity
    runtime_health_activity: CheckRuntimeHealthActivity
    heartbeat_activity: SendHeartbeatActivity
    metrics_activity: Optional[SendMetricsActivity]
    server_sync_activity: Optional[SyncServersActivity]
    tool_sync_activity: Optional[SyncToolsActivity]
    
    # Internal state
    _running: bool                               # Orchestrator running flag
    _task: Optional[asyncio.Task]                # Background task
    _servers_synced_this_cycle: bool             # Server sync flag for tool dependency
    _server_id_mapping: Dict[str, str]           # CF server ID -> FAM server ID
    
    def __init__(
        self,
        fam_client: FAMAssetCatalogClient,
        runtime_id: str,
        fam_base_url: str,
        config: Dict[str, Any],
        heartbeat_interval: int = 60,
        metrics_interval: int = 300,
        server_sync_interval: int = 60,
        tool_sync_interval: int = 60,
        fam_health_check_interval: int = 30,
        runtime_health_check_interval: int = 60
    ) -> None:
        """Initialize orchestrator with activities."""
    
    def get_server_id_mapping(self) -> Dict[str, str]:
        """Get mapping of ContextForge server IDs to FAM server IDs."""
    
    def update_server_id_mapping(self, contextforge_id: str, fam_id: str) -> None:
        """Update server ID mapping (called by server sync activity)."""
    
    async def start(self) -> None:
        """Start the orchestrator and begin activity execution."""
    
    async def stop(self) -> None:
        """Stop the orchestrator and cancel all activities."""
    
    async def _run_loop(self) -> None:
        """
        Main execution loop for activities.
        - Checks every second if activities should execute
        - Enforces server->tool dependency ordering
        """
    
    async def trigger_recovery(self) -> None:
        """Trigger recovery of missed operations."""
    
    def get_statistics(self) -> SyncStatistics:
        """Get aggregated statistics from all activities."""
    
    def get_activity_statistics(self) -> Dict[str, Dict[str, Any]]:
        """Get individual statistics for each activity."""
    
    def get_health_status(self) -> Dict[str, Any]:
        """Get health status of orchestrator and all activities."""
```

### 2.3 AbstractActivity & AbstractScheduledActivity (activities/base.py)

```python
class AbstractActivity(ABC):
    """Base class for all activities."""
    
    # Instance attributes
    context: ActivityContext          # Shared context
    logger: logging.Logger           # Activity logger
    stats: ActivityStatistics        # Execution statistics
    
    def __init__(self, context: ActivityContext) -> None:
        """Initialize activity with context."""
    
    @abstractmethod
    async def perform(self) -> None:
        """Execute the activity (implemented by subclasses)."""
    
    async def execute(self) -> bool:
        """
        Execute activity with statistics tracking.
        Returns: True if successful, False otherwise
        """
    
    def get_statistics(self) -> ActivityStatistics:
        """Get execution statistics."""


class AbstractScheduledActivity(AbstractActivity):
    """Base class for scheduled activities."""
    
    # Instance attributes
    last_execution_time: Optional[float]  # Timestamp of last execution
    
    @abstractmethod
    def get_interval_seconds(self) -> int:
        """Get the scheduling interval in seconds."""
    
    def should_execute(self) -> bool:
        """Check if activity should execute based on interval."""
    
    async def execute(self) -> bool:
        """Execute scheduled activity if interval has elapsed."""
```

### 2.4 FAMAssetCatalogClient (fam_client.py)

```python
class FAMAssetCatalogClient:
    """HTTP client for FAM Asset Catalog API."""
    
    # Instance attributes
    base_url: str                    # FAM API base URL
    runtime_id: str                  # Runtime ID
    username: str                    # Basic auth username
    password: str                    # Basic auth password
    timeout: int                     # Request timeout
    verify_ssl: bool                 # SSL verification flag
    _client: httpx.AsyncClient       # HTTP client
    
    def __init__(
        self,
        base_url: str,
        runtime_id: str,
        username: str,
        password: str,
        timeout: int = 30,
        verify_ssl: bool = True
    ) -> None:
        """Initialize FAM client."""
    
    async def close(self) -> None:
        """Close HTTP client."""
    
    async def register_runtime(
        self,
        name: str,
        description: str,
        runtime_type: str,
        deployment_type: str,
        region: Optional[str] = None,
        location: Optional[str] = None,
        host: Optional[str] = None,
        tags: List[str] = None,
        capacity_value: str = "100",
        capacity_unit: str = "per minute",
        heartbeat_interval: int = 60,
        publish_assets: bool = True,
        sync_assets: bool = True,
        send_metrics: bool = False
    ) -> Optional[ReregistrationReport]:
        """Register or re-register runtime in FAM."""
    
    async def send_heartbeat(self, runtime_id: str) -> bool:
        """Send heartbeat to FAM."""
    
    async def create_server(self, server: Any) -> Optional[str]:
        """Create server in FAM. Returns FAM server ID."""
    
    async def update_server(self, fam_server_id: str, server: Any) -> bool:
        """Update server in FAM."""
    
    async def delete_server(self, fam_server_id: str) -> bool:
        """Delete server from FAM."""
    
    async def create_tool(self, tool: Any, fam_server_id: str) -> Optional[str]:
        """Create tool in FAM. Returns FAM tool ID."""
    
    async def update_tool(self, fam_tool_id: str, tool: Any, fam_server_id: str) -> bool:
        """Update tool in FAM."""
    
    async def delete_tool(self, fam_tool_id: str) -> bool:
        """Delete tool from FAM."""
    
    async def bulk_create_tools(self, tools: List[Any], fam_server_id: str) -> Optional[str]:
        """Bulk create tools. Returns job ID."""
    
    async def bulk_update_tools(self, tools: List[Any], fam_server_id: str) -> Optional[str]:
        """Bulk update tools. Returns job ID."""
    
    async def bulk_delete_tools(self, tool_ids: List[str], fam_server_id: str) -> Optional[str]:
        """Bulk delete tools. Returns job ID."""
    
    async def submit_metrics(self, payload: FAMMetricsPayload) -> bool:
        """Submit metrics to FAM."""
```

### 2.5 State Trackers (fam_client.py)

```python
class ServerStateTracker:
    """Hash-based change detection for servers."""
    
    # Instance attributes
    _server_hashes: Dict[str, str]      # server_id -> hash
    _fam_server_ids: Dict[str, str]     # CF server_id -> FAM server_id
    
    def compute_hash(self, server: Any) -> str:
        """Compute hash for server state."""
    
    def is_new_server(self, server_id: str) -> bool:
        """Check if server is new (not yet synced)."""
    
    def has_changed(self, server_id: str, current_hash: str) -> bool:
        """Check if server has changed since last sync."""
    
    def mark_synced(self, server_id: str, hash_value: str, fam_server_id: str) -> None:
        """Mark server as synced with FAM."""
    
    def mark_deleted(self, server_id: str) -> None:
        """Mark server as deleted."""
    
    def get_deleted_servers(self, current_ids: Set[str]) -> Set[str]:
        """Get servers that were deleted since last sync."""


class ToolStateTracker:
    """Hash-based change detection for tools."""
    
    # Instance attributes
    _tool_hashes: Dict[str, str]        # tool_id -> hash
    _fam_tool_ids: Dict[str, str]       # CF tool_id -> FAM tool_id
    
    def compute_hash(self, tool: Any) -> str:
        """Compute hash for tool state."""
    
    def is_new_tool(self, tool_id: str) -> bool:
        """Check if tool is new (not yet synced)."""
    
    def has_changed(self, tool_id: str, current_hash: str) -> bool:
        """Check if tool has changed since last sync."""
    
    def mark_synced(self, tool_id: str, hash_value: str) -> None:
        """Mark tool as synced with FAM."""
    
    def mark_deleted(self, tool_id: str) -> None:
        """Mark tool as deleted."""
    
    def get_deleted_tools(self, current_ids: Set[str]) -> Set[str]:
        """Get tools that were deleted since last sync."""
```

### 2.6 CircuitBreaker (utils/retry.py)

```python
class CircuitBreaker:
    """Circuit breaker pattern for fault tolerance."""
    
    # Instance attributes
    failure_threshold: int              # Failures before opening
    recovery_timeout: float             # Seconds before retry
    success_threshold: int              # Successes to close
    _failure_count: int                 # Current failure count
    _success_count: int                 # Current success count (half-open)
    _last_failure_time: Optional[float] # Last failure timestamp
    _state: str                         # "CLOSED", "OPEN", "HALF_OPEN"
    
    def __init__(
        self,
        failure_threshold: int = 5,
        recovery_timeout: float = 60.0,
        success_threshold: int = 2
    ) -> None:
        """Initialize circuit breaker."""
    
    def _should_attempt(self) -> bool:
        """Check if request should be attempted."""
    
    def record_success(self) -> None:
        """Record successful operation."""
    
    def record_failure(self) -> None:
        """Record failed operation."""
    
    async def call(self, func: Callable[..., T], *args: Any, **kwargs: Any) -> T:
        """Execute function with circuit breaker protection."""
```

---

## 3. Method Signatures

### 3.1 Retry Function (utils/retry.py)

```python
async def with_retry(
    func: Callable[..., T],
    *args: Any,
    retry_config: Optional[RetryConfig] = None,
    operation_name: str = "operation",
    **kwargs: Any
) -> T:
    """
    Execute function with retry logic.
    
    Args:
        func: Function to execute (can be sync or async)
        *args: Positional arguments for func
        retry_config: Retry configuration (uses defaults if None)
        operation_name: Name for logging
        **kwargs: Keyword arguments for func
        
    Returns:
        Result from successful execution
        
    Raises:
        RetryExhaustedError: If all retry attempts fail
    """


def exponential_backoff(attempt: int, config: RetryConfig) -> float:
    """
    Calculate exponential backoff delay.
    
    Args:
        attempt: Current attempt number (0-based)
        config: Retry configuration
        
    Returns:
        Delay in seconds
    """
```

### 3.2 Activity Perform Methods

```python
# SendHeartbeatActivity (activities/send_heartbeat.py)
async def perform(self) -> None:
    """Send heartbeat to FAM. Raises SyncError on failure."""

# SendMetricsActivity (activities/send_metrics.py)
async def perform(self) -> None:
    """Send metrics to FAM. Raises SyncError on failure."""

# SyncServersActivity (activities/sync_servers.py)
async def perform(self) -> None:
    """Sync servers to FAM. Raises SyncError on failure."""

# SyncToolsActivity (activities/sync_tools.py)
async def perform(self) -> None:
    """Sync tools to FAM using bulk operations. Raises SyncError on failure."""

# CheckFAMHealthActivity (activities/check_fam_health.py)
async def perform(self) -> None:
    """Check FAM API health. Logs errors but doesn't raise."""

# CheckRuntimeHealthActivity (activities/check_runtime_health.py)
async def perform(self) -> None:
    """Check runtime health. Logs errors but doesn't raise."""

```

### 3.3 Recovery Handler Methods (handlers/recovery_handler.py)

```python
class RecoveryHandler:
    async def recover_heartbeats(
        self,
        last_heartbeat_time: int,
        heartbeat_interval: int
    ) -> int:
        """
        Send INACTIVE heartbeats for missed intervals.
        Returns: Number of heartbeats recovered
        """
    
    async def recover_metrics(
        self,
        last_metrics_time: int,
        metrics_interval: int
    ) -> int:
        """
        Send historical metrics data.
        Returns: Number of metric records recovered
        """
    
    async def recover_assets(
        self,
        last_asset_sync_time: Optional[int] = None
    ) -> Dict[str, int]:
        """
        Perform full asset sync.
        Returns: {"servers_synced": int, "tools_synced": int, "errors": int}
        """
    
    async def perform_recovery(
        self,
        last_heartbeat_time: Optional[int] = None,
        last_metrics_time: Optional[int] = None,
        last_asset_sync_time: Optional[int] = None,
        heartbeat_interval: int = 60,
        metrics_interval: int = 300
    ) -> Dict[str, Any]:
        """
        Perform complete recovery of all missed operations.
        Returns: Recovery statistics dictionary
        """
```

---

## 4. Data Models & Validation

### 4.1 APIConnectFAMConfig (apiconnect_fam.py)

```python
class APIConnectFAMConfig(BaseModel):
    """Plugin configuration with Pydantic validation."""
    
    # Core settings
    interval_seconds: int = 60
    log_details: bool = True
    
    # FAM connection
    fam_enabled: bool = False
    fam_base_url: Optional[str] = Field(default=None, description="FAM API base URL")
    fam_runtime_id: Optional[str] = Field(default=None, description="FAM runtime ID (REQUIRED when fam_enabled is true)")
    fam_username: Optional[str] = Field(default=None, description="FAM username for Basic Authentication")
    fam_password: Optional[str] = Field(default=None, description="FAM password for Basic Authentication")
    fam_timeout: int = 30
    fam_verify_ssl: bool = True
    
    # Sync settings
    fam_asset_sync_enabled: bool = True
    fam_asset_sync_interval: int = 60  # Sync assets every 60 seconds
    metrics_sync_enabled: bool = False
    metrics_sync_interval: int = 300  # 5 minutes default
    
    # Runtime metadata (for reference only, not used after initial registration)
    fam_runtime_name: str = "ContextForge Gateway"
    fam_runtime_description: str = "ContextForge MCP Gateway Runtime"
    fam_runtime_type: str = "MCP_CONTEXT_FORGE"
    fam_runtime_deployment_type: str = "ON_PREMISE"
    fam_runtime_region: Optional[str] = Field(default=None, description="Runtime region")
    fam_runtime_location: Optional[str] = Field(default=None, description="Runtime location")
    fam_runtime_host: Optional[str] = Field(default=None, description="Runtime host identifier")
    fam_runtime_tags: List[str] = Field(default_factory=lambda: ["contextforge", "mcp"])
    fam_runtime_capacity_value: str = "100"
    fam_runtime_capacity_unit: str = "per minute"
    fam_runtime_heartbeat_interval_seconds: int = 60  # Heartbeat interval in seconds
```

### 4.2 Activity Models (models.py)

```python
class ActivityStatus(str, Enum):
    """Status of an activity execution."""
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"


class HeartbeatStatus(str, Enum):
    """Status of runtime heartbeat."""
    ACTIVE = "active"
    INACTIVE = "inactive"
    UNKNOWN = "unknown"


class ReregistrationReport(BaseModel):
    """Report received from FAM on runtime registration."""
    runtime_id: str
    status_code: int = Field(description="HTTP status code (201=created, 200/409=re-registered)")
    last_registration_time: Optional[int] = Field(default=None, description="Last registration timestamp in milliseconds")
    last_heartbeat_time: Optional[int] = Field(default=None, description="Last heartbeat timestamp in milliseconds")
    last_metrics_time: Optional[int] = Field(default=None, description="Last metrics sync timestamp in milliseconds")
    last_asset_sync_time: Optional[int] = Field(default=None, description="Last asset sync timestamp in milliseconds")
    
    def is_reregistration(self) -> bool:
        """Check if this is a re-registration (status 200 or 409)."""
        return self.status_code in (200, 409)


class ActivityContext(BaseModel):
    """Context shared across all activities."""
    runtime_id: str
    fam_base_url: str
    config: Dict[str, Any] = Field(default_factory=dict)
    
    class Config:
        arbitrary_types_allowed = True


class ActivityStatistics(BaseModel):
    """Statistics for an activity execution."""
    activity_name: str
    status: ActivityStatus = ActivityStatus.PENDING
    total_executions: int = 0
    successful_executions: int = 0
    failed_executions: int = 0
    last_execution_time: Optional[datetime] = None
    last_success_time: Optional[datetime] = None
    last_failure_time: Optional[datetime] = None
    last_error: Optional[str] = None
    average_duration_ms: float = 0.0
    
    def record_execution(self, success: bool, duration_ms: float, error: Optional[str] = None) -> None:
        """Record an activity execution."""
    
    def get_success_rate(self) -> float:
        """Calculate success rate as percentage."""


class SyncStatistics(BaseModel):
    """Overall synchronization statistics."""
    runtime_id: str
    uptime_seconds: int = 0
    activities: Dict[str, ActivityStatistics] = Field(default_factory=dict)
    total_servers_synced: int = 0
    total_tools_synced: int = 0
    total_metrics_sent: int = 0
    total_heartbeats_sent: int = 0
    
    def get_activity_stats(self, activity_name: str) -> ActivityStatistics:
        """Get or create statistics for an activity."""
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""


class InactiveHeartbeat(BaseModel):
    """Represents an inactive heartbeat for recovery."""
    runtime_id: str
    created: int
    status: HeartbeatStatus = HeartbeatStatus.INACTIVE
    
    def to_payload(self) -> Dict[str, Any]:
        """Convert to FAM API payload format."""
```

### 4.3 Retry Configuration (utils/retry.py)

```python
class RetryConfig(BaseModel):
    """Configuration for retry logic."""
    max_attempts: int = Field(default=3, ge=1, le=10)
    initial_delay: float = Field(default=1.0, ge=0.1, le=60.0)
    max_delay: float = Field(default=60.0, ge=1.0, le=300.0)
    exponential_base: float = Field(default=2.0, ge=1.1, le=10.0)
    jitter: float = Field(default=0.1, ge=0.0, le=1.0)
```

### 4.4 Custom Exceptions (utils/errors.py)

```python
class AgentError(Exception):
    """Base exception for all agent errors."""
    def __init__(self, message: str, cause: Exception = None):
        super().__init__(message)
        self.cause = cause


class RegistrationError(AgentError):
    """Error during runtime registration."""
    pass


class RecoveryError(AgentError):
    """Error during recovery operations."""
    pass


class SyncError(AgentError):
    """Error during sync operations."""
    pass


class FAMClientError(AgentError):
    """Error in FAM API client operations."""
    pass


class ValidationError(AgentError):
    """Error in configuration or data validation."""
    pass


class RetryExhaustedError(AgentError):
    """Error when retry attempts are exhausted."""
    def __init__(self, message: str, attempts: int, last_error: Exception):
        super().__init__(message, last_error)
        self.attempts = attempts
        self.last_error = last_error
```

---

## 5. Database Queries (Actual Implementation)

### 5.1 Query All Servers for Sync

**Location:** `activities/sync_servers.py:104-105`

```python
def query_all_servers(db: Session) -> List[Server]:
    """
    Query all MCP servers for synchronization to FAM.
    
    SQL Generated:
        SELECT servers.id, servers.name, servers.url, servers.transport,
               servers.config, servers.enabled, servers.created_at,
               servers.updated_at
        FROM servers
    
    Returns:
        List of Server ORM objects
        
    Usage:
        Used by SyncServersActivity to fetch all servers for sync
    """
    from mcpgateway.db import Server
    
    return db.query(Server).all()
```

---

### 5.2 Query All Tools and Servers for Sync

**Location:** `activities/sync_tools.py:111-112`

```python
def query_tools_and_servers(db: Session) -> Tuple[List[Tool], List[Server]]:
    """
    Query all tools with eager-loaded server relationships and all servers.
    
    SQL Generated:
        -- Query 1: Get all tools with servers (LEFT OUTER JOIN for eager loading)
        SELECT tools.id, tools.name, tools.description, tools.input_schema,
               tools.server_id, tools.created_at, tools.updated_at,
               servers_1.id AS servers_1_id, servers_1.name AS servers_1_name,
               servers_1.url AS servers_1_url, servers_1.transport AS servers_1_transport,
               servers_1.config AS servers_1_config, servers_1.enabled AS servers_1_enabled,
               servers_1.created_at AS servers_1_created_at,
               servers_1.updated_at AS servers_1_updated_at
        FROM tools
        LEFT OUTER JOIN servers AS servers_1 ON servers_1.id = tools.server_id
        
        -- Query 2: Get all servers (for tool-to-server mapping)
        SELECT servers.id, servers.name, servers.url, servers.transport,
               servers.config, servers.enabled, servers.created_at,
               servers.updated_at
        FROM servers
    
    Returns:
        Tuple of (tools list with loaded servers, servers list)
        
    Usage:
        Used by SyncToolsActivity to:
        1. Fetch all tools with eager-loaded server relationships (avoids N+1 queries)
        2. Build tool-to-server mapping (needed for FAM mcpServerId field)
        
    Performance Note:
        Uses joinedload(Tool.servers) to eager load server relationships,
        preventing N+1 query problem when accessing tool.servers in loops.
    """
    from mcpgateway.db import Tool, Server
    from sqlalchemy.orm import joinedload
    
    # Eager load the servers relationship to avoid N+1 queries
    tools = db.query(Tool).options(joinedload(Tool.servers)).all()
    servers = db.query(Server).all()
    
    return tools, servers
```

---

### 5.3 Query Recent Server Metrics

**Location:** `activities/send_metrics.py:103`

```python
def query_recent_server_metrics(
    db: Session,
    time_window_start: datetime
) -> List[ServerMetric]:
    """
    Query server metrics within a time window for FAM submission.
    
    SQL Generated:
        SELECT server_metrics.id, server_metrics.server_id,
               server_metrics.timestamp, server_metrics.metric_type,
               server_metrics.value, server_metrics.metadata
        FROM server_metrics
        WHERE server_metrics.timestamp >= :time_window_start
    
    Args:
        db: Database session
        time_window_start: Start of time window (typically now - 5 minutes)
        
    Returns:
        List of ServerMetric ORM objects within time window
        
    Usage:
        Used by SendMetricsActivity to fetch recent server metrics.
        Default time window: 5 minutes (metrics_interval / 60)
        
    Example:
        time_window_start = datetime.now(timezone.utc) - timedelta(minutes=5)
        metrics = query_recent_server_metrics(db, time_window_start)
    """
    from mcpgateway.db import ServerMetric
    
    return db.query(ServerMetric).filter(
        ServerMetric.timestamp >= time_window_start
    ).all()
```

---

### 5.4 Query Recent Tool Metrics

**Location:** `activities/send_metrics.py:105`

```python
def query_recent_tool_metrics(
    db: Session,
    time_window_start: datetime
) -> List[ToolMetric]:
    """
    Query tool metrics within a time window for FAM submission.
    
    SQL Generated:
        SELECT tool_metrics.id, tool_metrics.tool_id,
               tool_metrics.timestamp, tool_metrics.metric_type,
               tool_metrics.value, tool_metrics.metadata
        FROM tool_metrics
        WHERE tool_metrics.timestamp >= :time_window_start
    
    Args:
        db: Database session
        time_window_start: Start of time window (typically now - 5 minutes)
        
    Returns:
        List of ToolMetric ORM objects within time window
        
    Usage:
        Used by SendMetricsActivity to fetch recent tool metrics.
        Default time window: 5 minutes (metrics_interval / 60)
        
    Example:
        time_window_start = datetime.now(timezone.utc) - timedelta(minutes=5)
        metrics = query_recent_tool_metrics(db, time_window_start)
    """
    from mcpgateway.db import ToolMetric
    
    return db.query(ToolMetric).filter(
        ToolMetric.timestamp >= time_window_start
    ).all()
```

---

### 5.5 Query Servers and Tools for Metrics Organization

**Location:** `activities/send_metrics.py:96-97`

```python
def query_servers_and_tools_for_metrics(db: Session) -> Tuple[List[Server], List[Tool]]:
    """
    Query all servers and tools for organizing metrics by entity.
    
    SQL Generated:
        -- Query 1: Get all servers
        SELECT servers.id, servers.name, servers.url, servers.transport,
               servers.config, servers.enabled, servers.created_at,
               servers.updated_at
        FROM servers
        
        -- Query 2: Get all tools
        SELECT tools.id, tools.name, tools.description, tools.input_schema,
               tools.server_id, tools.created_at, tools.updated_at
        FROM tools
    
    Returns:
        Tuple of (servers list, tools list)
        
    Usage:
        Used by SendMetricsActivity to:
        1. Build server ID to name mapping for metrics
        2. Build tool-to-server mapping for organizing tool metrics
        3. Group metrics by server before sending to FAM
    """
    from mcpgateway.db import Server, Tool
    
    servers = db.query(Server).all()
    tools = db.query(Tool).all()
    
    return servers, tools
```

---

### 5.6 Query Historical Server Metrics for Recovery

**Location:** `handlers/recovery_handler.py:141`

```python
def query_historical_server_metrics(
    db: Session,
    from_time: datetime,
    to_time: datetime
) -> List[ServerMetric]:
    """
    Query historical server metrics for recovery after downtime.
    
    SQL Generated:
        SELECT server_metrics.id, server_metrics.server_id,
               server_metrics.timestamp, server_metrics.metric_type,
               server_metrics.value, server_metrics.metadata
        FROM server_metrics
        WHERE server_metrics.timestamp >= :from_time
          AND server_metrics.timestamp <= :to_time
    
    Args:
        db: Database session
        from_time: Start of recovery window (from FAM lastMetricsTime)
        to_time: End of recovery window (current time)
        
    Returns:
        List of ServerMetric ORM objects in recovery window
        
    Usage:
        Used by RecoveryHandler to recover missed metrics during downtime.
        from_time is derived from FAM's lastMetricsTime (milliseconds).
        
    Example:
        # If lastMetricsTime = 1715000000000 (milliseconds)
        from_time = datetime.fromtimestamp(1715000000000 / 1000, tz=timezone.utc)
        to_time = datetime.now(timezone.utc)
        metrics = query_historical_server_metrics(db, from_time, to_time)
    """
    from mcpgateway.db import ServerMetric
    
    return db.query(ServerMetric).filter(
        ServerMetric.timestamp >= from_time,
        ServerMetric.timestamp <= to_time
    ).all()
```

---

### 5.7 Query Historical Tool Metrics for Recovery

**Location:** `handlers/recovery_handler.py:144`

```python
def query_historical_tool_metrics(
    db: Session,
    from_time: datetime,
    to_time: datetime
) -> List[ToolMetric]:
    """
    Query historical tool metrics for recovery after downtime.
    
    SQL Generated:
        SELECT tool_metrics.id, tool_metrics.tool_id,
               tool_metrics.timestamp, tool_metrics.metric_type,
               tool_metrics.value, tool_metrics.metadata
        FROM tool_metrics
        WHERE tool_metrics.timestamp >= :from_time
          AND tool_metrics.timestamp <= :to_time
    
    Args:
        db: Database session
        from_time: Start of recovery window (from FAM lastMetricsTime)
        to_time: End of recovery window (current time)
        
    Returns:
        List of ToolMetric ORM objects in recovery window
        
    Usage:
        Used by RecoveryHandler to recover missed metrics during downtime.
        from_time is derived from FAM's lastMetricsTime (milliseconds).
        
    Example:
        # If lastMetricsTime = 1715000000000 (milliseconds)
        from_time = datetime.fromtimestamp(1715000000000 / 1000, tz=timezone.utc)
        to_time = datetime.now(timezone.utc)
        metrics = query_historical_tool_metrics(db, from_time, to_time)
    """
    from mcpgateway.db import ToolMetric
    
    return db.query(ToolMetric).filter(
        ToolMetric.timestamp >= from_time,
        ToolMetric.timestamp <= to_time
    ).all()
```

---

### 5.8 Query All Assets for Full Recovery

**Location:** `handlers/recovery_handler.py:184-189`

```python
def query_all_assets_for_recovery(db: Session) -> Tuple[List[Server], List[Tool]]:
    """
    Query all servers and tools for full asset recovery.
    
    SQL Generated:
        -- Query 1: Get all servers
        SELECT servers.id, servers.name, servers.url, servers.transport,
               servers.config, servers.enabled, servers.created_at,
               servers.updated_at
        FROM servers
        
        -- Query 2: Get all tools
        SELECT tools.id, tools.name, tools.description, tools.input_schema,
               tools.server_id, tools.created_at, tools.updated_at
        FROM tools
    
    Returns:
        Tuple of (servers list, tools list)
        
    Usage:
        Used by RecoveryHandler to perform full asset synchronization.
        Ensures FAM has current state after downtime.
        Queries all assets regardless of last sync time.
        
    Example:
        servers, tools = query_all_assets_for_recovery(db)
        # Sync all servers and tools to FAM
    """
    from mcpgateway.db import Server, Tool
    
    servers = db.query(Server).all()
    tools = db.query(Tool).all()
    
    return servers, tools
```

---

### 5.7 Database Query Summary

| Query Location | Tables Queried | Filter Conditions | Purpose |
|----------------|----------------|-------------------|---------|
| `sync_servers.py:105` | `servers` | None (all rows) | Sync all servers to FAM |
| `sync_tools.py:107-108` | `tools`, `servers` | None (all rows) | Sync all tools to FAM with server mapping |
| `send_metrics.py:96-105` | `servers`, `tools`, `server_metrics`, `tool_metrics` | `timestamp >= time_window_start` | Send recent metrics to FAM |
| `recovery_handler.py:141-144` | `server_metrics`, `tool_metrics` | `timestamp >= from_time AND timestamp <= current_time` | Recover historical metrics |
| `recovery_handler.py:184-189` | `servers`, `tools` | None (all rows) | Full asset recovery |

**Query Performance Notes:**
- All queries use simple `SELECT *` or single-column filters
- No complex joins (relationships loaded via ORM)
- Metrics queries use indexed `timestamp` column for efficient filtering
- Time window queries typically return small result sets (5-minute windows)
- Recovery queries may return larger datasets depending on downtime duration

**Database Tables Used:**
- `servers` - MCP server configurations
- `tools` - MCP tool definitions
- `server_metrics` - Server performance metrics (if observability enabled)
- `tool_metrics` - Tool invocation metrics (if observability enabled)

**Note:** `ServerMetric` and `ToolMetric` tables are only queried when observability is enabled in ContextForge. If observability is disabled, metrics queries return empty results.

---

## 6. API Endpoint Specifications

### 6.1 FAM Asset Catalog API Endpoints (Actual Implementation)

**Base URL:** Configured via `fam_base_url` (e.g., `https://fam.example.com`)

**Authentication:** Basic Authentication (username/password)

#### Register/Re-register Runtime

```http
PUT /asset-catalog/v1/rest/runtime/{runtime_id}
Content-Type: application/json
Authorization: Basic {base64(username:password)}

Request Body:
{
  "name": "ContextForge Gateway",
  "description": "ContextForge MCP Gateway Runtime",
  "type": "MCP_CONTEXT_FORGE",
  "deploymentType": "ON_PREMISE",
  "region": "us-east-1",
  "location": "US East",
  "host": "gateway-01",
  "tags": ["contextforge", "mcp"],
  "capacity": {
    "value": "100",
    "unit": "per minute"
  },
  "heartbeatInterval": 60000,
  "capabilities": {
    "publishAssets": true,
    "syncAssets": true,
    "sendMetrics": false
  }
}

Response: 200 OK (re-registration) or 201 Created (first-time)
{
  "runtimeId": "runtime-abc123",
  "lastRegistrationTime": 1715000000000,
  "lastHeartbeatTime": 1715000060000,
  "lastMetricsTime": 1715000300000,
  "lastAssetSyncTime": 1715000120000
}
```

#### Send Heartbeat

```http
POST /asset-catalog/v1/rest/runtime/{runtime_id}/heartbeat
Content-Type: application/json
Authorization: Basic {base64(username:password)}

Request Body:
{
  "runtimeId": "runtime-abc123",
  "created": 1715000000000,
  "active": 1
}

Response: 204 No Content
```

#### Create Server

```http
POST /asset-catalog/v1/rest/runtime/{runtime_id}/mcp-servers
Content-Type: application/json
Authorization: Basic {base64(username:password)}

Request Body:
{
  "name": "server-1",
  "description": "MCP Server 1",
  "url": "http://localhost:3000",
  "transport": "sse",
  "status": "ACTIVE",
  "tags": ["mcp", "server"],
  "capabilities": ["tools", "resources"]
}

Response: 201 Created
{
  "id": "fam-server-abc123"
}
```

#### Update Server

```http
PUT /asset-catalog/v1/rest/runtime/{runtime_id}/mcp-servers/{server_id}
Content-Type: application/json
Authorization: Basic {base64(username:password)}

Request Body: (same as create)

Response: 200 OK
```

#### Delete Server

```http
DELETE /asset-catalog/v1/rest/runtime/{runtime_id}/mcp-servers/{server_id}
Authorization: Basic {base64(username:password)}

Response: 204 No Content
```

#### Bulk Create Tools

```http
POST /asset-catalog/v1/rest/runtime/{runtime_id}/mcp-servers/{server_id}/tools/bulk
Content-Type: application/json
Authorization: Basic {base64(username:password)}

Request Body:
{
  "tools": [
    {
      "name": "tool-1",
      "description": "Tool 1",
      "inputSchema": {...},
      "annotations": {...}
    }
  ]
}

Response: 202 Accepted
{
  "jobId": "job-xyz789"
}
```

#### Bulk Update Tools

```http
PUT /asset-catalog/v1/rest/runtime/{runtime_id}/mcp-servers/{server_id}/tools/bulk
Content-Type: application/json
Authorization: Basic {base64(username:password)}

Request Body: (same as bulk create)

Response: 202 Accepted
{
  "jobId": "job-xyz789"
}
```

#### Bulk Delete Tools

```http
DELETE /asset-catalog/v1/rest/runtime/{runtime_id}/mcp-servers/{server_id}/tools/bulk
Content-Type: application/json
Authorization: Basic {base64(username:password)}

Request Body:
{
  "toolIds": ["tool-1", "tool-2", "tool-3"]
}

Response: 202 Accepted
{
  "jobId": "job-xyz789"
}
```

#### Submit Metrics

```http
POST /asset-catalog/v1/rest/runtime/{runtime_id}/metrics
Content-Type: application/json
Authorization: Basic {base64(username:password)}

Request Body:
{
  "runtimeId": "runtime-abc123",
  "timestamp": 1715000000000,
  "runtimeMetrics": {...},
  "serverMetrics": [...],
  "toolMetrics": [...]
}

Response: 204 No Content
```

---

## 7. Error Handling Patterns

### 7.1 Exception Hierarchy (Actual Implementation)

```python
Exception
└── AgentError (utils/errors.py)
    ├── RegistrationError
    ├── RecoveryError
    ├── SyncError
    ├── FAMClientError
    ├── ValidationError
    └── RetryExhaustedError
        # Attributes: attempts: int, last_error: Exception
```

### 7.2 Activity Error Handling Pattern (Actual Implementation)

```python
# From activities/send_heartbeat.py
async def perform(self) -> None:
    """Send heartbeat to FAM."""
    try:
        print(f"🔄 [FAM Heartbeat] Sending heartbeat to FAM...")
        
        # Send heartbeat with retry logic
        await with_retry(
            self._send_heartbeat,
            retry_config=RetryConfig(max_attempts=2, initial_delay=0.5),
            operation_name="Send Heartbeat"
        )
        
        # Track success
        self._consecutive_failures = 0
        self._total_heartbeats_sent += 1
        
        print(f"✅ [FAM Heartbeat] Sent successfully (total: {self._total_heartbeats_sent})")
        
    except Exception as e:
        self._consecutive_failures += 1
        error_msg = f"Failed to send heartbeat (consecutive failures: {self._consecutive_failures}): {e}"
        print(f"❌ [FAM Heartbeat] {error_msg}")
        self.logger.error(error_msg, exc_info=True)
        raise SyncError(error_msg, e)
```

### 7.3 Orchestrator Error Handling Pattern (Actual Implementation)

```python
# From activity_orchestrator.py
async def _run_loop(self) -> None:
    """Main execution loop for activities."""
    logger.info("ActivityOrchestrator execution loop started")
    
    while self._running:
        try:
            # Reset server sync flag at start of each cycle
            self._servers_synced_this_cycle = False
            
            # Execute activities in dependency order
            for activity in self.activities:
                if activity.should_execute():
                    # Special handling for tool sync - must wait for server sync
                    if activity == self.tool_sync_activity:
                        if not self._servers_synced_this_cycle:
                            logger.debug("Skipping tool sync - waiting for server sync to complete first")
                            continue
                    
                    try:
                        await activity.execute()
                        
                        # Track if servers were synced
                        if activity == self.server_sync_activity:
                            self._servers_synced_this_cycle = True
                            logger.debug("Server sync completed - tools can now sync")
                    
                    except Exception as e:
                        logger.error(f"Error executing activity {activity.__class__.__name__}: {e}", exc_info=True)
            
            # Sleep for 1 second before next check
            await asyncio.sleep(1)
        
        except asyncio.CancelledError:
            logger.info("ActivityOrchestrator execution loop cancelled")
            break
        except Exception as e:
            logger.error(f"Error in orchestrator execution loop: {e}", exc_info=True)
            await asyncio.sleep(5)  # Back off on error
```

---

## 8. Testing Specifications

### 8.1 Unit Test Structure

```python
# Test file structure
tests/plugins/apiconnect_fam/
├── test_plugin.py                    # Plugin initialization and lifecycle
├── test_activity_orchestrator.py     # Orchestrator logic
├── test_fam_client.py                # FAM API client
├── test_activities/
│   ├── test_send_heartbeat.py
│   ├── test_send_metrics.py
│   ├── test_sync_servers.py
│   └── test_sync_tools.py
├── test_handlers/
│   └── test_recovery_handler.py
└── test_utils/
    ├── test_retry.py
    └── test_errors.py
```

### 8.2 Key Test Cases

```python
# Test: Retry with transient failure
@pytest.mark.asyncio
async def test_retry_with_transient_failure():
    """Test retry logic succeeds after transient failures."""
    call_count = 0
    
    async def failing_func():
        nonlocal call_count
        call_count += 1
        if call_count < 3:
            raise TimeoutError("Transient failure")
        return "success"
    
    config = RetryConfig(max_attempts=3)
    result = await with_retry(failing_func, retry_config=config)
    
    assert result == "success"
    assert call_count == 3


# Test: Circuit breaker opens after threshold
@pytest.mark.asyncio
async def test_circuit_breaker_opens_after_threshold():
    """Test circuit breaker opens after failure threshold."""
    cb = CircuitBreaker(failure_threshold=3)
    
    async def failing_func():
        raise Exception("Failure")
    
    for _ in range(3):
        with pytest.raises(Exception):
            await cb.call(failing_func)
    
    assert cb.state == CircuitState.OPEN
    
    with pytest.raises(CircuitBreakerError):
        await cb.call(failing_func)

# Test: Circuit breaker recovery
@pytest.mark.asyncio
async def test_circuit_breaker_half_open_recovery():
    cb = CircuitBreaker(
        failure_threshold=2,
        recovery_timeout=0.1,
        success_threshold=2
    )
    
    async def failing_func():
        raise Exception("Failure")
    
    async def success_func():
        return "success"
    
    # Open circuit
    for _ in range(2):
        with pytest.raises(Exception):
            await cb.call(failing_func)
    
    assert cb.state == CircuitState.OPEN
    
    # Wait for recovery timeout
    await asyncio.sleep(0.2)
    
    # Should transition to HALF_OPEN
    result = await cb.call(success_func)
    assert result == "success"
    assert cb.state == CircuitState.HALF_OPEN
    
    # Second success should close circuit
    result = await cb.call(success_func)
    assert result == "success"
    assert cb.state == CircuitState.CLOSED
```

### 8.2 Integration Test Cases

```python
@pytest.mark.asyncio
async def test_registration_and_recovery_flow(mock_fam_api):
    """Test complete registration and recovery flow."""
    # Setup mock
    mock_fam_api.register_runtime.return_value = {
        "runtime_id": "runtime-test",
        "last_heartbeat_time": int((datetime.now() - timedelta(minutes=5)).timestamp() * 1000),
        "last_metrics_time": None,
        "last_asset_sync_time": None
    }
    
    # Initialize plugin
    config = {
        "fam_base_url": "http://localhost:8000",
        "fam_auth_token": "test-token",
        "fam_auto_register": True,
        "recovery_enabled": True
    }
    plugin = APIConnectFAMPlugin(config)
    
    # Start plugin
    await plugin.on_startup()
    
    # Verify registration
    assert mock_fam_api.register_runtime.called
    
    # Verify recovery
    assert mock_fam_api.send_heartbeat_batch.called
    
    # Verify orchestrator started
    assert plugin.orchestrator is not None
    assert plugin.orchestrator._running == True
    
    # Cleanup
    await plugin.on_shutdown()
```

### 8.3 Performance Test Targets

| Component | Metric | Target | Test Method |
|-----------|--------|--------|-------------|
| SendHeartbeatActivity | Avg duration | <200ms | Execute 100 times, measure average |
| SendHeartbeatActivity | P95 duration | <500ms | Execute 100 times, calculate 95th percentile |
| SendMetricsActivity | Avg duration | <1000ms | Execute 100 times, measure average |
| SyncServersActivity | Avg duration | <2000ms | Execute with 100 servers |
| SyncToolsActivity | Avg duration | <3000ms | Execute with 500 tools |
| Plugin | CPU overhead | <1% | Monitor process CPU during operation |
| Plugin | Memory footprint | <50MB | Monitor process RSS |

---

## 9. Configuration Schema

### 9.1 Minimal Configuration

```yaml
apiconnect_fam:
  fam_base_url: "https://fam.example.com"
  fam_auth_token: "${FAM_AUTH_TOKEN}"
```

### 9.2 Production Configuration

```yaml
apiconnect_fam:
  # Core
  interval_seconds: 60
  log_details: true
  
  # FAM
  fam_enabled: true
  fam_base_url: "https://fam.example.com"
  fam_auth_token: "${FAM_AUTH_TOKEN}"
  fam_timeout: 30
  
  # Runtime
  fam_auto_register: true
  fam_runtime_name: "ContextForge Gateway - Production"
  fam_runtime_type: "MCP_CONTEXT_FORGE"
  fam_runtime_deployment_type: "ON_PREMISE"
  fam_runtime_region: "us-east-1"
  fam_runtime_location: "US East"
  fam_runtime_host: "gateway-prod-01"
  fam_runtime_tags: ["contextforge", "mcp", "production"]
  
  # Intervals
  fam_heartbeat_interval_seconds: 60
  metrics_sync_interval: 300
  metrics_time_window: 60
  health_check_interval: 300
  
  # Retry
  retry_max_attempts: 3
  retry_initial_delay: 1.0
  retry_max_delay: 60.0
  retry_exponential_base: 2.0
  retry_jitter: 0.1
  
  # Circuit Breaker
  circuit_breaker_enabled: true
  circuit_breaker_failure_threshold: 5
  circuit_breaker_recovery_timeout: 60.0
  circuit_breaker_success_threshold: 2
  
  # Recovery
  recovery_enabled: true
  recovery_heartbeat_batch_size: 100
```

---

## 10. Implementation Checklist

### Phase 1: Core Infrastructure (Week 1)
- [ ] Create module structure (all `__init__.py` files)
- [ ] Implement `config.py` (APIConnectFAMConfig with all validators)
- [ ] Implement `exceptions.py` (all exception classes)
- [ ] Implement `activities/base.py` (AbstractActivity, AbstractScheduledActivity)
- [ ] Write unit tests for config validation
- [ ] Write unit tests for base activity classes

### Phase 2: Resilience Layer (Week 1-2)
- [ ] Implement `resilience/retry.py` (with_retry function, RetryConfig)
- [ ] Implement `resilience/circuit_breaker.py` (CircuitBreaker class)
- [ ] Write unit tests for retry logic (3 test cases minimum)
- [ ] Write unit tests for circuit breaker (5 test cases minimum)
- [ ] Integration tests for combined retry + circuit breaker

### Phase 3: Integration Layer (Week 2)
- [ ] Implement `client/fam_client.py` (FAMClient with all 11 methods)
- [ ] Implement `state/tracker.py` (StateTracker with hash-based detection)
- [ ] Implement `utils/hash.py` (compute_hash utility)
- [ ] Implement `utils/time.py` (time utilities)
- [ ] Write unit tests for FAM client (mock httpx)
- [ ] Write unit tests for state tracker

### Phase 4: Activities (Week 2-3)
- [ ] Implement `activities/register.py` (RegisterRuntimeActivity)
- [ ] Implement `activities/heartbeat.py` (SendHeartbeatActivity)
- [ ] Implement `activities/metrics.py` (SendMetricsActivity with DB queries)
- [ ] Implement `activities/sync_servers.py` (SyncServersActivity with hash detection)
- [ ] Implement `activities/sync_tools.py` (SyncToolsActivity with bulk operations)
- [ ] Implement `activities/health_fam.py` (CheckFAMHealthActivity)
- [ ] Implement `activities/health_runtime.py` (CheckRuntimeHealthActivity)
- [ ] Write unit tests for each activity (minimum 2 tests per activity)

### Phase 5: Orchestration (Week 3-4)
- [ ] Implement `orchestrator/orchestrator.py` (ActivityOrchestrator)
- [ ] Implement `orchestrator/recovery.py` (RecoveryHandler)
- [ ] Write unit tests for orchestrator
- [ ] Write unit tests for recovery handler
- [ ] Integration tests for full orchestration flow

### Phase 6: Plugin Integration (Week 4)
- [ ] Implement `plugin.py` (APIConnectFAMPlugin)
- [ ] Register statistics endpoint in ContextForge
- [ ] Write integration tests (registration + recovery flow)
- [ ] Write end-to-end tests (full plugin lifecycle)
- [ ] Performance testing (verify all targets met)

### Phase 7: Documentation & Deployment (Week 4-5)
- [ ] Update plugin README with usage examples
- [ ] Create configuration examples (minimal, dev, production)
- [ ] Write deployment guide
- [ ] Create troubleshooting guide
- [ ] Performance tuning guide
- [ ] Code review and final testing

---

**End of Low-Level Design Document**

This LLD provides implementation-specific details complementing the architectural design in HLD_REFINEMENT.md. Focus areas: file structure, method signatures, data models, database queries, API specifications, error handling patterns, and testing specifications.