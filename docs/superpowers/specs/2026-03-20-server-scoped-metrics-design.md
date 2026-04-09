# Server-Scoped Metrics Design

**Issue:** [#3642](https://github.com/IBM/mcp-context-forge/issues/3642) - Metrics not scoped to server_id

**Date:** 2026-03-20

**Status:** Approved

## Problem Statement

When querying `/servers/{server_id}/tools?include_metrics=true`, the API returns incorrect metrics aggregated across ALL servers using the tool, instead of metrics specific to the requested server.

### Impact
- Cannot track per-server SLAs or performance
- Multi-tenant deployments cannot isolate server-specific issues
- Misleading data for capacity planning and troubleshooting

### Root Cause
Metric tables are missing `server_id` column:
- `tool_metrics`, `resource_metrics`, `prompt_metrics` only have entity_id
- Hourly rollup tables have the same issue
- Prometheus counters only have `["tool_name"]` label dimension

## Solution Overview

Add `server_id` column to all metrics tables and update recording/aggregation logic to filter by server context. Use Approach A: Single-Phase Migration with opt-in Prometheus labels for cardinality protection.

## Design Details

### 1. Database Schema Changes

#### Migration Creation
```bash
# First update ORM models in mcpgateway/db.py
# Then generate migration:
make db-migrate
# Message: "add server_id to metrics tables"
```

#### ORM Model Updates
Update all 6 metrics models in `mcpgateway/db.py`:

```python
class ToolMetric(Base):
    __tablename__ = "tool_metrics"
    # ... existing fields ...
    server_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True, index=True)

class ResourceMetric(Base):
    __tablename__ = "resource_metrics"
    # ... existing fields ...
    server_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True, index=True)

class PromptMetric(Base):
    __tablename__ = "prompt_metrics"
    # ... existing fields ...
    server_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True, index=True)

# Same for ToolMetricsHourly, ResourceMetricsHourly, PromptMetricsHourly
```

#### Why Nullable?
- **Legacy metrics:** Existing data before this fix
- **Admin UI executions:** Direct invocations without virtual server
- **Backward compatibility:** Unfiltered queries still work

#### Idempotent Migration
Enhance auto-generated migration with checks:

```python
def upgrade():
    inspector = sa.inspect(op.get_bind())

    if "tool_metrics" not in inspector.get_table_names():
        return  # Fresh DB uses db.py models

    columns = [col["name"] for col in inspector.get_columns("tool_metrics")]
    if "server_id" in columns:
        return  # Already applied

    # Auto-generated changes...
```

### 2. Metric Recording

#### Buffered Metrics Service
Update `mcpgateway/services/metrics_buffer_service.py`:

**Add server_id parameter:**
```python
def record_tool_metric(
    self,
    tool_id: str,
    start_time: float,
    success: bool,
    error_message: Optional[str] = None,
    server_id: Optional[str] = None,  # NEW
) -> None:
```

**Update dataclass:**
```python
@dataclass
class BufferedToolMetric:
    tool_id: str
    timestamp: datetime
    response_time: float
    is_success: bool
    error_message: Optional[str]
    server_id: Optional[str] = None  # NEW
```

#### Tool Service Updates
Update tool execution in `mcpgateway/services/tool_service.py`:

```python
await metrics_buffer.record_tool_metric(
    tool_id=tool.id,
    start_time=start_time,
    success=not is_error,
    error_message=error_msg,
    server_id=server_id,  # NEW - from route/transport context
)
```

**Similar changes needed:**
- `resource_service.py`
- `prompt_service.py`

#### Execution Paths to Update
1. JSON-RPC handler (`/rpc`) - has server_id in route
2. SSE transport (`/sse/{server_id}`)
3. WebSocket transport - server_id from session
4. Streamable HTTP (`/mcp`)
5. Direct tool execution endpoints

### 3. Metrics Aggregation

#### metrics_summary Property
Update in `mcpgateway/db.py` for Tool/Resource/Prompt models:

```python
def metrics_summary(self, server_id: Optional[str] = None) -> Dict[str, Any]:
    """Aggregated metrics, optionally filtered by server_id.

    Args:
        server_id: If provided, only include metrics for this server.
                   If None, aggregate all (current behavior).
    """
```

**In-memory path (metrics loaded):**
```python
if self._metrics_loaded():
    raw_metrics = self.metrics
    hourly_metrics = self.metrics_hourly if hasattr(self, 'metrics_hourly') else []

    # Filter by server_id if provided
    if server_id is not None:
        raw_metrics = [m for m in raw_metrics if m.server_id == server_id]
        hourly_metrics = [m for m in hourly_metrics if m.server_id == server_id]

    return _compute_metrics_summary(raw_metrics, hourly_metrics)
```

**SQL query path (metrics not loaded):**
```python
query = (
    select(
        func.count().label("total"),
        func.sum(case((ToolMetric.is_success, 1), else_=0)).label("success"),
        # ... aggregations
    )
    .where(ToolMetric.tool_id == self.id)
)

# Add server_id filter if provided
if server_id is not None:
    query = query.where(ToolMetric.server_id == server_id)
```

#### Service Layer
Update `convert_tool_to_read` in `mcpgateway/services/tool_service.py`:

```python
def convert_tool_to_read(
    self,
    tool: DbTool,
    include_metrics: bool = False,
    server_id: Optional[str] = None,  # NEW
    # ... other params
) -> ToolRead:
    if include_metrics:
        metrics = tool.metrics_summary(server_id=server_id)  # NEW
        tool_dict["metrics"] = metrics
```

Update `list_server_tools`:
```python
for tool in tools:
    result.append(
        self.convert_tool_to_read(
            tool,
            include_metrics=include_metrics,
            server_id=server_id,  # NEW
            # ... other params
        )
    )
```

### 4. Prometheus Counters

#### Configuration Flag
Add to `mcpgateway/config.py`:

```python
prometheus_server_scoped_metrics: bool = Field(
    default=False,
    description="Include server_id as Prometheus counter label dimension. "
                "Increases cardinality - use cautiously with many virtual servers."
)
```

Environment variable: `PROMETHEUS_SERVER_SCOPED_METRICS=false` (default off)

#### Conditional Counter Definition
Update `mcpgateway/services/metrics.py`:

```python
from mcpgateway.config import settings

# Conditional labels based on config
if settings.prometheus_server_scoped_metrics:
    _tool_labels = ["tool_name", "server_id"]
else:
    _tool_labels = ["tool_name"]

tool_timeout_counter = Counter(
    "tool_timeout_total",
    "Total number of tool invocation timeouts",
    _tool_labels,
)

circuit_breaker_open_counter = Counter(
    "circuit_breaker_open_total",
    "Total number of times circuit breaker opened",
    _tool_labels,
)
```

#### Counter Usage
Update call sites:

```python
# In tool_service.py
if settings.prometheus_server_scoped_metrics and server_id:
    tool_timeout_counter.labels(tool_name=name, server_id=server_id).inc()
else:
    tool_timeout_counter.labels(tool_name=name).inc()

# In plugins/circuit_breaker/circuit_breaker.py
if settings.prometheus_server_scoped_metrics and server_id:
    circuit_breaker_open_counter.labels(tool_name=tool, server_id=server_id).inc()
else:
    circuit_breaker_open_counter.labels(tool_name=tool).inc()
```

#### Cardinality Impact
- Increases cardinality by `num_tools × num_servers`
- Example: 50 tools × 100 servers = 5,000 label combinations
- Acceptable for most deployments, not for 1000+ servers

### 5. Metrics Rollup Service

#### Rollup Aggregation
Update `mcpgateway/services/metrics_rollup_service.py` to group by `server_id`:

```python
rollup_query = (
    select(
        ToolMetric.tool_id,
        ToolMetric.server_id,  # NEW
        func.date_trunc('hour', ToolMetric.timestamp).label('hour_start'),
        func.count().label('total_count'),
        # ... other aggregations
    )
    .where(ToolMetric.timestamp >= last_rollup_time)
    .where(ToolMetric.timestamp < current_hour_start)
    .group_by(
        ToolMetric.tool_id,
        ToolMetric.server_id,  # NEW
        func.date_trunc('hour', ToolMetric.timestamp)
    )
)
```

#### Handling NULL server_id
Creates separate rollup rows for each distinct server_id (including NULL).

Example for hour `2026-03-20 10:00:00`:
- 10 executions with `server_id='server1'` → 1 rollup row
- 5 executions with `server_id='server2'` → 1 rollup row
- 2 executions with `server_id=NULL` → 1 rollup row

Total: 3 rollup rows for same tool in same hour.

#### Unique Constraint Update
In `mcpgateway/db.py`:

```python
class ToolMetricsHourly(Base):
    __tablename__ = "tool_metrics_hourly"
    __table_args__ = (
        UniqueConstraint(
            "tool_id", "server_id", "hour_start",  # NEW: Include server_id
            name="uq_tool_metrics_hourly_tool_server_hour"
        ),
        Index("ix_tool_metrics_hourly_hour_start", "hour_start"),
    )
```

Migration will:
1. Drop old constraint `(tool_id, hour_start)`
2. Add new constraint `(tool_id, server_id, hour_start)`

## Testing Strategy

### Unit Tests

**Database Models:**
- Verify `server_id` column exists on all 6 metrics tables
- Test nullable `server_id` accepts None
- Test mixed server_id values (some NULL, some set)

**Metrics Recording:**
- Test `record_tool_metric` with `server_id` parameter
- Test `record_tool_metric` with `server_id=None`
- Verify buffered metrics include `server_id`

**Metrics Aggregation:**
- Test `metrics_summary()` without filter (aggregates all)
- Test `metrics_summary(server_id='server1')` returns only server1 metrics
- Test mixed metrics (some with server_id, some NULL)
- Verify legacy NULL metrics included in unfiltered queries

**Rollup Service:**
- Test rollup groups by `(tool_id, server_id, hour_start)`
- Test rollup handles NULL server_id correctly
- Test unique constraint enforcement
- Verify mixed server_id values create separate rollup rows

**Prometheus Metrics:**
- Test counter labels when flag=false (default)
- Test counter labels when flag=true
- Verify conditional increment logic
- Test graceful degradation when server_id unavailable

### Integration Tests

**End-to-End Flow:**
Matching issue #3642 scenario:
1. Create tool `weather-tool`
2. Associate with `server1` and `server2`
3. Execute:
   - 2 times via `server1`
   - 3 times via `server2`
   - 1 time via Admin UI
4. Verify `GET /servers/server1/tools?include_metrics=true`:
   - `total_executions: 2` (not 6)
5. Verify `GET /servers/server2/tools?include_metrics=true`:
   - `total_executions: 3` (not 6)
6. Verify admin UI shows aggregated metrics (6 total)

**Multi-Transport:**
- Test SSE, WebSocket, JSON-RPC, Streamable HTTP record server_id correctly

**Migration:**
- Test idempotency (run twice)
- Verify existing data preserved (server_id=NULL)
- Test fresh database creation

## Files to Modify

### Core Changes
1. `mcpgateway/db.py` - Add `server_id` to 6 metrics models
2. `mcpgateway/alembic/versions/XXXX_add_server_id_to_metrics_tables.py` - Migration
3. `mcpgateway/services/metrics_buffer_service.py` - Add server_id parameter
4. `mcpgateway/services/tool_service.py` - Pass server_id during recording
5. `mcpgateway/services/resource_service.py` - Pass server_id during recording
6. `mcpgateway/services/prompt_service.py` - Pass server_id during recording
7. `mcpgateway/services/metrics_rollup_service.py` - Group by server_id
8. `mcpgateway/config.py` - Add PROMETHEUS_SERVER_SCOPED_METRICS flag
9. `mcpgateway/services/metrics.py` - Conditional Prometheus labels
10. `plugins/circuit_breaker/circuit_breaker.py` - Conditional counter increment

### Tests
11. `tests/unit/mcpgateway/test_db.py` - Model tests
12. `tests/unit/mcpgateway/services/test_metrics_buffer_service.py` - Recording tests
13. `tests/unit/mcpgateway/services/test_tool_service.py` - Aggregation tests
14. `tests/unit/mcpgateway/services/test_metrics_rollup_service.py` - Rollup tests
15. `tests/unit/mcpgateway/services/test_metrics.py` - Prometheus tests
16. `tests/integration/test_server_scoped_metrics.py` - E2E tests (new file)

## Backward Compatibility

- Nullable `server_id` supports legacy metrics
- Unfiltered queries aggregate all metrics (preserves current behavior)
- Admin UI executions continue working with `server_id=NULL`
- Prometheus flag defaults to `false` (no cardinality impact)
- Hourly rollups handle mixed server_id values gracefully

## Deployment Notes

1. Apply Alembic migration: `make db-upgrade`
2. Restart application with updated code
3. Optionally enable `PROMETHEUS_SERVER_SCOPED_METRICS=true` for per-server observability
4. Existing metrics remain queryable but not server-scoped (server_id=NULL)
5. New metrics capture server context automatically

## Success Criteria

- ✅ `/servers/{server_id}/tools?include_metrics=true` returns server-scoped metrics
- ✅ `/servers/{server_id}/resources?include_metrics=true` returns server-scoped metrics
- ✅ `/servers/{server_id}/prompts?include_metrics=true` returns server-scoped metrics
- ✅ Admin UI executions work with `server_id=NULL`
- ✅ Backward compatibility with existing NULL metrics
- ✅ Multi-server scenarios work correctly (same tool on multiple servers)
- ✅ Hourly rollup includes `server_id` grouping
- ✅ Prometheus metrics opt-in flag works as expected
- ✅ All tests pass
