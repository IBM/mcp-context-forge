# ContextForge Agent Enhancement Plan

## Overview
Enhance the API Connect FAM Plugin to follow webMethods Agent SDK patterns, making it a proper MCP ContextForge Agent for syncing MCP servers and tools to FAM Asset Catalog.

## Current State Analysis

### Strengths
- ✅ Modular architecture (separate sync tasks)
- ✅ Orchestrator pattern for coordination
- ✅ Runtime auto-registration
- ✅ Heartbeat synchronization
- ✅ Metrics synchronization
- ✅ Change detection via SHA-256 hashing

### Gaps (Compared to webMethods SDK)
- ❌ No recovery mechanism for missed data
- ❌ No timestamp storage for last sync times
- ❌ No re-registration report handling
- ❌ Limited error handling and retry logic
- ❌ No health check activities
- ❌ No activity-based architecture
- ❌ No validation framework

## Enhancement Roadmap

### Phase 1: Core Infrastructure (Priority: HIGH)
1. **Add Timestamp Storage Handler**
   - Store last sync times for heartbeat, metrics, assets
   - Persist to database or file
   - Retrieve on startup for recovery

2. **Implement Re-registration Report Model**
   - Parse registration response
   - Extract last sync timestamps
   - Trigger recovery tasks

3. **Add Recovery Mechanism**
   - Recover missed heartbeats (send INACTIVE status)
   - Recover missed metrics (query historical data)
   - Recover missed asset updates (full sync)

### Phase 2: Activity Architecture (Priority: MEDIUM)
1. **Create Activity Base Classes**
   - `AbstractActivity` - Base for all activities
   - `AbstractScheduledActivity` - Base for scheduled tasks
   - `ActivityContext` - Shared context for activities

2. **Refactor Existing Tasks to Activities**
   - `RegisterRuntimeActivity` - Runtime registration
   - `SendHeartbeatActivity` - Heartbeat sync
   - `SendMetricsActivity` - Metrics sync
   - `SyncServersActivity` - Server sync
   - `SyncToolsActivity` - Tool sync

3. **Add New Activities**
   - `CheckFAMHealthActivity` - FAM health check
   - `CheckRuntimeHealthActivity` - ContextForge health check

### Phase 3: Error Handling & Resilience (Priority: HIGH)
1. **Retry Logic**
   - Exponential backoff for failed requests
   - Configurable retry attempts
   - Circuit breaker pattern

2. **Error Recovery**
   - Graceful degradation
   - Fallback mechanisms
   - Error state tracking

3. **Validation Framework**
   - Configuration validation
   - Payload validation
   - Response validation

### Phase 4: Observability (Priority: MEDIUM)
1. **Enhanced Logging**
   - Structured logging with context
   - Activity lifecycle logging
   - Performance metrics

2. **Statistics & Monitoring**
   - Activity execution stats
   - Success/failure rates
   - Latency tracking

3. **Health Endpoints**
   - Agent health status
   - Activity status
   - Sync status

### Phase 5: Documentation (Priority: LOW)
1. **Architecture Documentation**
   - Activity diagram
   - Sequence diagrams
   - Component interactions

2. **Developer Guide**
   - Adding new activities
   - Configuration guide
   - Troubleshooting guide

## Implementation Details

### 1. Timestamp Storage Handler

```python
class TimestampStorageHandler:
    """Handles persistence of last sync timestamps."""
    
    def __init__(self, storage_path: str):
        self.storage_path = storage_path
    
    def save_timestamp(self, key: str, timestamp: int) -> None:
        """Save timestamp for a sync operation."""
        pass
    
    def get_timestamp(self, key: str) -> Optional[int]:
        """Retrieve last sync timestamp."""
        pass
    
    def get_all_timestamps(self) -> Dict[str, int]:
        """Get all stored timestamps."""
        pass
```

### 2. Re-registration Report Model

```python
class ReregistrationReport(BaseModel):
    """Report received from FAM on runtime registration."""
    
    last_registration_time: Optional[int] = None
    last_heartbeat_time: Optional[int] = None
    last_metrics_time: Optional[int] = None
    last_asset_sync_time: Optional[int] = None
    runtime_id: str
```

### 3. Recovery Tasks

```python
class RecoveryHandler:
    """Handles recovery of missed sync operations."""
    
    async def recover_heartbeats(
        self,
        last_heartbeat_time: int,
        heartbeat_interval: int
    ) -> None:
        """Send INACTIVE heartbeats for missed intervals."""
        pass
    
    async def recover_metrics(
        self,
        last_metrics_time: int,
        metrics_interval: int
    ) -> None:
        """Send historical metrics data."""
        pass
    
    async def recover_assets(
        self,
        last_asset_sync_time: int
    ) -> None:
        """Perform full asset sync."""
        pass
```

### 4. Activity Base Classes

```python
class AbstractActivity(ABC):
    """Base class for all activities."""
    
    def __init__(self, context: ActivityContext):
        self.context = context
        self.logger = context.logger
    
    @abstractmethod
    async def perform(self) -> None:
        """Execute the activity."""
        pass

class AbstractScheduledActivity(AbstractActivity):
    """Base class for scheduled activities."""
    
    @abstractmethod
    def get_interval_seconds(self) -> int:
        """Get the scheduling interval."""
        pass
```

### 5. Enhanced Error Handling

```python
class RetryConfig(BaseModel):
    """Configuration for retry logic."""
    
    max_attempts: int = 3
    initial_delay: float = 1.0
    max_delay: float = 60.0
    exponential_base: float = 2.0

async def with_retry(
    func: Callable,
    retry_config: RetryConfig,
    logger: logging.Logger
) -> Any:
    """Execute function with retry logic."""
    pass
```

## File Structure (Enhanced)

```
plugins/apiconnect_fam/
├── __init__.py
├── apiconnect_fam.py              # Main plugin (simplified)
├── config.py                      # Configuration models
├── fam_client.py                  # FAM HTTP client
├── models.py                      # Data models (NEW)
│   ├── ReregistrationReport
│   ├── ActivityContext
│   └── SyncStatistics
├── activities/                    # Activity modules (NEW)
│   ├── __init__.py
│   ├── base.py                   # Abstract base classes
│   ├── register_runtime.py       # Runtime registration
│   ├── send_heartbeat.py         # Heartbeat sync
│   ├── send_metrics.py           # Metrics sync
│   ├── sync_servers.py           # Server sync
│   ├── sync_tools.py             # Tool sync
│   ├── check_fam_health.py       # FAM health check
│   └── check_runtime_health.py   # Runtime health check
├── handlers/                      # Business logic handlers (NEW)
│   ├── __init__.py
│   ├── recovery_handler.py       # Recovery logic
│   ├── timestamp_handler.py      # Timestamp storage
│   └── validation_handler.py     # Validation logic
├── utils/                         # Utility modules (NEW)
│   ├── __init__.py
│   ├── retry.py                  # Retry logic
│   └── errors.py                 # Custom exceptions
├── sync_orchestrator.py          # Orchestrator (enhanced)
├── README.md
├── SETUP.md
├── HLD.md
├── TROUBLESHOOTING.md
└── ENHANCEMENT_PLAN.md           # This file
```

## Migration Strategy

### Step 1: Add New Infrastructure (Non-breaking)
- Add models.py with new data models
- Add handlers/ directory with new handlers
- Add utils/ directory with utilities
- Add activities/ directory structure

### Step 2: Enhance Existing Components
- Update fam_client.py to handle re-registration reports
- Update sync_orchestrator.py to use activities
- Update apiconnect_fam.py to use new handlers

### Step 3: Migrate Sync Tasks to Activities
- Refactor server_sync.py → activities/sync_servers.py
- Refactor tool_sync.py → activities/sync_tools.py
- Refactor metrics_sync.py → activities/send_metrics.py
- Refactor heartbeat_sync.py → activities/send_heartbeat.py

### Step 4: Add Recovery Mechanism
- Implement timestamp storage
- Implement recovery handler
- Update registration flow

### Step 5: Testing & Documentation
- Unit tests for new components
- Integration tests for recovery
- Update documentation

## Success Criteria

1. ✅ Runtime registration returns re-registration report
2. ✅ Timestamps are persisted and retrieved correctly
3. ✅ Recovery mechanism sends missed heartbeats
4. ✅ Recovery mechanism sends missed metrics
5. ✅ Recovery mechanism syncs missed assets
6. ✅ Retry logic handles transient failures
7. ✅ Health checks monitor FAM and runtime
8. ✅ All activities follow consistent patterns
9. ✅ Configuration is validated on startup
10. ✅ Documentation is complete and accurate

## Timeline

- **Week 1**: Phase 1 (Core Infrastructure)
- **Week 2**: Phase 2 (Activity Architecture)
- **Week 3**: Phase 3 (Error Handling)
- **Week 4**: Phase 4 (Observability) + Phase 5 (Documentation)

## Notes

- Maintain backward compatibility where possible
- Follow ContextForge coding standards
- Use type hints throughout
- Add comprehensive docstrings
- Include unit tests for new components