# Implementation Summary: Issue #3598 - Metrics Double-Counting Fix

## ✅ Complete - All Models Updated

Fixed metrics aggregation for **Tool, Resource, Prompt, and Server** models to:
1. Query both raw and hourly aggregated metrics tables
2. Prevent double-counting using time-based partitioning
3. Handle timezone-aware/naive datetime comparisons
4. Centralize logic in a shared helper function for easy maintenance

---

## Problem Solved

**Before**: Metrics API returned 0 after raw metrics cleanup OR double-counted when cleanup was delayed

**After**: Correctly aggregates metrics from both raw (current hour) and hourly (completed hours) tables

---

## Solution Architecture

### Shared Helper Function

Created `_compute_metrics_summary()` at line ~900 in `mcpgateway/db.py`:

- **230 lines** of centralized logic (was 400+ duplicated across 4 models)
- Supports both in-memory and SQL query paths
- Automatic time partitioning to prevent double-counting
- Timezone normalization for naive/aware datetime comparison

### Time Partitioning Strategy

```
Current Hour (2:00-3:00 PM) → Query RAW metrics only
Completed Hours (before 2:00 PM) → Query HOURLY aggregates only
No overlap = No double-counting ✅
```

---

## Files Modified

**File**: `mcpgateway/db.py`

### 1. Helper Function (NEW)
- **Lines**: ~900-1115
- **Function**: `_compute_metrics_summary()`
- **Purpose**: Centralized metrics aggregation logic

### 2. Tool Model
- **Line 3044**: Added `metrics_hourly` relationship
- **Lines 3519-3565**: Updated `metrics_summary` property to use helper

### 3. Resource Model
- **Line 3610**: Added `metrics_hourly` relationship
- **Lines 3851-3893**: Updated `metrics_summary` property to use helper

### 4. Prompt Model
- **Line 3989**: Added `metrics_hourly` relationship
- **Lines 4223-4265**: Updated `metrics_summary` property to use helper

### 5. Server Model
- **Line 4318**: Added `metrics_hourly` relationship
- **Lines 4489-4531**: Updated `metrics_summary` property to use helper

---

## Testing Instructions

### 1. Restart Server
```bash
# Stop current server
pkill -f "uvicorn mcpgateway.main"

# Restart with updated code
make dev
```

### 2. Test Endpoints

**Tools:**
```bash
curl -X GET "http://localhost:4444/servers/{server_id}/tools?include_metrics=true" \
  -H "Authorization: Bearer $TOKEN" | jq '.[0].metrics'
```

**Resources:**
```bash
curl -X GET "http://localhost:4444/servers/{server_id}/resources?include_metrics=true" \
  -H "Authorization: Bearer $TOKEN" | jq '.[0].metrics'
```

**Prompts:**
```bash
curl -X GET "http://localhost:4444/servers/{server_id}/prompts?include_metrics=true" \
  -H "Authorization: Bearer $TOKEN" | jq '.[0].metrics'
```

**Servers:**
```bash
curl -X GET "http://localhost:4444/servers?include_metrics=true" \
  -H "Authorization: Bearer $TOKEN" | jq '.[0].metrics'
```

### 3. Expected Output
```json
{
  "total_executions": 150,
  "successful_executions": 145,
  "failed_executions": 5,
  "failure_rate": 0.033,
  "min_response_time": 0.02,
  "max_response_time": 3.5,
  "avg_response_time": 0.45,
  "last_execution_time": "2026-03-12T12:30:00Z"
}
```

---

## Verification Scenarios

### Scenario 1: No Raw Cleanup (`METRICS_DELETE_RAW_AFTER_ROLLUP=false`)
- ✅ Should count: Raw metrics from current hour ONLY
- ✅ Should count: All hourly aggregates
- ✅ No double-counting despite raw table having old data

### Scenario 2: Delayed Cleanup (`METRICS_DELETE_RAW_AFTER_ROLLUP=true`, delay=1hr)
- ✅ Should count: Raw metrics from current hour ONLY
- ✅ Should count: All hourly aggregates
- ✅ No double-counting during cleanup delay window

### Scenario 3: Immediate Cleanup (`METRICS_DELETE_RAW_AFTER_ROLLUP=true`, delay=0)
- ✅ Should count: Raw metrics from current hour (if any)
- ✅ Should count: All hourly aggregates
- ✅ Historical data preserved in hourly tables

---

## Database Verification Queries

```sql
-- Check raw metrics (should only have current hour data after cleanup)
SELECT tool_id, COUNT(*), MIN(timestamp), MAX(timestamp)
FROM tool_metrics
GROUP BY tool_id;

-- Check hourly aggregates (should have completed hours)
SELECT tool_id, hour_start, total_count, success_count
FROM tool_metrics_hourly
ORDER BY hour_start DESC
LIMIT 10;

-- Compare API result with DB totals
-- API result should equal:
--   SUM(tool_metrics_hourly.total_count) + COUNT(tool_metrics WHERE timestamp >= current_hour)
```

---

## Code Maintenance Benefits

| Aspect | Before | After |
|--------|--------|-------|
| **Lines of Code** | ~400 (duplicated 4x) | 230 (centralized) |
| **Bug Fix Effort** | 4 places | 1 place |
| **Consistency** | Manual sync needed | Automatic |
| **New Model Support** | Copy-paste 100+ lines | Call helper (5 lines) |
| **Timezone Handling** | Inconsistent | Normalized |

---

## Future Extensions

To add metrics to a new model (e.g., `A2AAgent`):

```python
# 1. Add hourly relationship
metrics_hourly: Mapped[List["A2AAgentMetricsHourly"]] = relationship(
    "A2AAgentMetricsHourly",
    primaryjoin="A2AAgent.id == foreign(A2AAgentMetricsHourly.agent_id)",
    viewonly=True,
)

# 2. Add metrics_summary property
@property
def metrics_summary(self) -> Dict[str, Any]:
    if self._metrics_loaded():
        try:
            hourly_metrics = self.metrics_hourly
        except AttributeError:
            hourly_metrics = []
        return _compute_metrics_summary(
            raw_metrics=self.metrics,
            hourly_metrics=hourly_metrics
        )

    session = object_session(self)
    if session is None:
        return {
            "total_executions": 0,
            "successful_executions": 0,
            "failed_executions": 0,
            "failure_rate": 0.0,
            "min_response_time": None,
            "max_response_time": None,
            "avg_response_time": None,
            "last_execution_time": None,
        }

    return _compute_metrics_summary(
        raw_metrics=None,
        hourly_metrics=None,
        session=session,
        entity_id=self.id,
        raw_metric_class=A2AAgentMetric,
        hourly_metric_class=A2AAgentMetricsHourly,
    )
```

---

## Configuration

Relevant environment variables:
- `METRICS_DELETE_RAW_AFTER_ROLLUP=true` - Enable raw metrics cleanup
- `METRICS_DELETE_RAW_AFTER_ROLLUP_HOURS=1` - Hours to wait after rollup before cleanup
- `METRICS_ROLLUP_INTERVAL_HOURS=1` - Hourly rollup interval

---

## Summary

✅ **4 models fixed**: Tool, Resource, Prompt, Server
✅ **1 helper function**: Centralized logic for easy maintenance
✅ **Double-counting prevented**: Time-based partitioning
✅ **Timezone handling**: Normalized naive/aware datetimes
✅ **Code reduction**: 400+ duplicated lines → 230 lines
✅ **Future-proof**: Easy to extend to new models

**Ready for testing!** 🚀
