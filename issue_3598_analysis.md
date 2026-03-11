# Issue #3598 Root Cause Analysis

**Issue**: [BUG]: metrics API call count displayed as 0
**GitHub**: https://github.com/IBM/mcp-context-forge/issues/3598
**Reported Version**: 1.0.0-BETA-2
**Verified Version**: 1.0.0-RC2 (current release)
**Status**: ✅ **CONFIRMED** - Bug still present in RC2

---

## Executive Summary

The `/servers/{server_id}/tools?include_metrics=true` API endpoint returns `total_executions = 0` after raw metrics are aggregated into hourly rollup tables and subsequently cleaned up. This affects all production deployments using the default configuration where `metrics_delete_raw_after_rollup=true`.

**Impact Severity**: HIGH
- User-facing dashboards show incorrect metrics (0 executions)
- Monitoring and alerting based on tool usage will fail
- Historical analytics are lost from the API perspective
- Trust in the platform is undermined when metrics disappear

---

## Root Cause

### Location
`mcpgateway/db.py:3366` - `Tool.metrics_summary` property

### The Problem

The `metrics_summary` property only queries the `tool_metrics` table:

```python
result = (
    session.query(
        func.count(ToolMetric.id),
        func.sum(case((ToolMetric.is_success.is_(True), 1), else_=0)),
        func.min(ToolMetric.response_time),
        func.max(ToolMetric.response_time),
        func.avg(ToolMetric.response_time),
        func.max(ToolMetric.timestamp),
    )
    .filter(ToolMetric.tool_id == self.id)  # ❌ ONLY queries tool_metrics
    .one()
)
```

### Why This Fails

1. **Default Configuration** (`mcpgateway/config.py:1343`):
   ```python
   metrics_delete_raw_after_rollup: bool = Field(default=True, ...)
   metrics_delete_raw_after_rollup_hours: int = Field(default=1, ...)
   ```

2. **Metrics Lifecycle**:
   - Tool executions create records in `tool_metrics` (raw data)
   - Rollup job runs every hour (default) and aggregates into `tool_metrics_hourly`
   - Cleanup job deletes raw `tool_metrics` records after 1 hour (default)
   - API queries only `tool_metrics` → returns 0 after cleanup

3. **Missing Aggregation**:
   - The query does NOT union with `tool_metrics_hourly` table
   - After cleanup, all historical execution counts are lost
   - The API returns `total_executions = 0` even though historical data exists

---

## Data Flow

```
Tool Execution
    ↓
tool_metrics (raw)
    ↓ [hourly rollup job]
tool_metrics_hourly (aggregated)
    ↓ [cleanup job - default after 1 hour]
tool_metrics (deleted)
    ↓
API query: SELECT COUNT(*) FROM tool_metrics → 0 ❌
Correct query should: SUM(tool_metrics + tool_metrics_hourly) → 10 ✓
```

---

## Reproduction Steps

### Test Case

Created test: `test_issue_3598_reproduction.py`

**Test Output**:
```
BUG REPRODUCED:
  total_executions BEFORE deletion: 10
  total_executions AFTER deletion: 0
  Hourly rollup has: 10 executions

Expected: API should query BOTH tool_metrics AND tool_metrics_hourly
Actual: Only queries tool_metrics, returns 0 after cleanup
```

### Production Reproduction

1. Create a server and register tools
2. Execute tools multiple times to generate metrics
3. Wait for automatic metrics rollup (runs every hour by default)
   - Check: `settings.metrics_rollup_enabled=true` (default)
   - Check: `settings.metrics_rollup_interval_hours=1` (default)
4. Wait for raw metrics cleanup (deletes raw metrics after 1 hour by default)
   - Check: `settings.metrics_delete_raw_after_rollup=true` (default)
   - Check: `settings.metrics_delete_raw_after_rollup_hours=1` (default)
5. Call `GET /servers/{server_id}/tools?include_metrics=true`
6. **Observe**: `total_executions` shows 0 instead of actual count

---

## Affected Code Paths

### API Call Flow

```
GET /servers/{server_id}/tools?include_metrics=true
    ↓
mcpgateway/admin.py (no direct endpoint found, likely in service)
    ↓
mcpgateway/services/tool_service.py:2029
    async def list_server_tools(..., include_metrics=True)
    ↓
Line 2081-2095: Preload metrics if include_metrics=True
    query.options(selectinload(DbTool.metrics))
    ↓
Line 2139-2141: Convert to ToolRead
    convert_tool_to_read(tool, include_metrics=include_metrics)
    ↓
Line 818-856: convert_tool_to_read method
    if include_metrics:
        metrics = tool.metrics_summary  # ← BUG HERE
    ↓
mcpgateway/db.py:3294
    @property
    def metrics_summary(self) -> Dict[str, Any]:
    ↓
Line 3366: SQL query only checks tool_metrics
    .filter(ToolMetric.tool_id == self.id)  # ❌ Missing hourly table
```

---

## Affected Entity Types

The same bug pattern exists in:

1. ✅ **Tools** - `mcpgateway/db.py:3294-3383` (Issue #3598)
2. ⚠️ **Resources** - `mcpgateway/db.py:3667-3756` (similar pattern)
3. ⚠️ **Prompts** - `mcpgateway/db.py:4078-4167` (similar pattern)
4. ⚠️ **Servers** - `mcpgateway/db.py:4383-4472` (similar pattern)
5. ⚠️ **A2A Agents** - (likely similar pattern)

All use the same `metrics_summary` property pattern that only queries raw tables.

---

## Recommended Fix

### Strategy

The `metrics_summary` property should aggregate from **BOTH** tables:

1. Query raw metrics (`tool_metrics`) for recent data
2. Query hourly rollups (`tool_metrics_hourly`) for historical data
3. Aggregate both sources
4. Handle overlaps (avoid double-counting if raw metrics haven't been cleaned up yet)

### Implementation Approach

```python
@property
def metrics_summary(self) -> Dict[str, Any]:
    """Aggregated metrics from both raw and hourly rollup tables."""

    session = object_session(self)
    if session is None:
        return self._empty_metrics_dict()

    # Query raw metrics (recent data)
    raw_result = (
        session.query(
            func.count(ToolMetric.id),
            func.sum(case((ToolMetric.is_success.is_(True), 1), else_=0)),
            func.min(ToolMetric.response_time),
            func.max(ToolMetric.response_time),
            func.avg(ToolMetric.response_time),
            func.max(ToolMetric.timestamp),
        )
        .filter(ToolMetric.tool_id == self.id)
        .one()
    )

    # Query hourly rollups (historical data)
    hourly_result = (
        session.query(
            func.sum(ToolMetricsHourly.total_count),
            func.sum(ToolMetricsHourly.success_count),
            func.min(ToolMetricsHourly.min_response_time),
            func.max(ToolMetricsHourly.max_response_time),
            # Weighted average: SUM(avg * count) / SUM(count)
            func.sum(ToolMetricsHourly.avg_response_time * ToolMetricsHourly.total_count),
        )
        .filter(ToolMetricsHourly.tool_id == self.id)
        .one()
    )

    # Aggregate results
    raw_total = raw_result[0] or 0
    hourly_total = hourly_result[0] or 0
    total = raw_total + hourly_total

    raw_success = raw_result[1] or 0
    hourly_success = hourly_result[1] or 0
    successful = raw_success + hourly_success

    # ... combine min/max/avg properly ...

    return {
        "total_executions": total,
        "successful_executions": successful,
        "failed_executions": total - successful,
        # ... rest of metrics ...
    }
```

### Challenges to Address

1. **Overlap Handling**: Raw metrics might not be cleaned up immediately
   - Solution: Track `hour_start` ranges and exclude raw metrics already in rollups
   - Or: Accept slight double-counting during transition periods

2. **Performance**: Two queries instead of one
   - Solution: Use UNION ALL for single query
   - Or: Cache metrics with short TTL

3. **Weighted Averages**: Can't simply average averages
   - Solution: `SUM(avg * count) / SUM(count)` for weighted average

4. **Consistency**: Apply same fix to all entity types (Resource, Prompt, Server, A2A Agent)

---

## Files Requiring Changes

### Core Bug Fix
- `mcpgateway/db.py:3294-3383` - Tool.metrics_summary
- `mcpgateway/db.py:3667-3756` - Resource.metrics_summary
- `mcpgateway/db.py:4078-4167` - Prompt.metrics_summary
- `mcpgateway/db.py:4383-4472` - Server.metrics_summary
- Check A2A Agent models for similar pattern

### Test Files
- Create/update tests in `tests/unit/mcpgateway/services/test_tool_service.py`
- Create/update tests in `tests/unit/mcpgateway/services/test_resource_service.py`
- Create/update tests in `tests/unit/mcpgateway/services/test_prompt_service.py`
- Create/update tests in `tests/unit/mcpgateway/services/test_server_service.py`
- Integration test: `tests/e2e/test_admin_apis.py`

### Documentation
- Update `docs/docs/manage/metrics.md` (if exists)
- Update API documentation for metrics endpoints

---

## Configuration Impact

### Current Default Configuration

```python
# mcpgateway/config.py
metrics_rollup_enabled: bool = True  # Rollup runs automatically
metrics_rollup_interval_hours: int = 1  # Every hour
metrics_delete_raw_after_rollup: bool = True  # ← CAUSES THE BUG
metrics_delete_raw_after_rollup_hours: int = 1  # Delete after 1 hour
```

### Workaround (Not Recommended)

Users can disable raw metric deletion:
```bash
METRICS_DELETE_RAW_AFTER_ROLLUP=false
```

**Downsides**:
- Database grows indefinitely
- Performance degrades over time
- Not a proper solution

---

## Timeline of the Bug

1. **Feature Added**: Metrics rollup and cleanup system
   - Commit: `762c21515` - "Redis-backed metrics cache for multi-instance deployments"
   - Commit: `2f0716a5b` - "optimize metrics aggregation to prevent performance degradation"

2. **Default Behavior**: `metrics_delete_raw_after_rollup=true`
   - Intended to keep database size manageable
   - Unintentionally broke API metrics

3. **Reported**: Issue #3598 on 2026-03-11
   - User discovered after BETA-2 deployment
   - Historical metrics disappeared after rollup

4. **Current Status**: Still present in v1.0.0-RC2

---

## Verification Evidence

### Git Check (v1.0.0-RC2)
```bash
$ git show v1.0.0-RC2:mcpgateway/db.py | grep -A 30 "Use single SQL query"
# Confirmed: Still only queries ToolMetric table
```

### Test Execution
```bash
$ python test_issue_3598_reproduction.py
============================= test session starts ==============================
test_issue_3598_reproduction.py
BUG REPRODUCED:
  total_executions BEFORE deletion: 10
  total_executions AFTER deletion: 0
  Hourly rollup has: 10 executions
.
============================== 1 passed in 0.13s ===============================
```

---

## Related Issues

- No duplicate issues found in GitHub
- Likely affects all users running production deployments with default config
- May be unreported because users assume metrics are not being recorded

---

## Next Steps

### Immediate Actions
1. ✅ Document root cause (this file)
2. ⬜ Implement fix for all entity types (Tools, Resources, Prompts, Servers, A2A Agents)
3. ⬜ Write comprehensive test coverage
4. ⬜ Test performance impact of dual-table queries
5. ⬜ Create PR with fix

### Testing Plan
1. Unit tests for `metrics_summary` property with rollup data
2. Integration tests for API endpoints with metrics
3. Performance tests for large datasets (millions of records)
4. Regression tests to ensure no double-counting

### Documentation Updates
1. Update API documentation
2. Add metrics architecture doc explaining rollup system
3. Release notes warning about the bug fix

---

## Appendix: Test Case

Test file: `test_issue_3598_reproduction.py`

```python
def test_metrics_with_rollup_and_deletion(test_db: Session):
    # 1. Create tool
    tool = Tool(id="test-tool-001", ...)

    # 2. Add 10 raw metrics
    for i in range(10):
        metric = ToolMetric(tool_id=tool.id, ...)
        test_db.add(metric)

    # 3. Rollup into hourly table
    rollup = ToolMetricsHourly(tool_id=tool.id, total_count=10, ...)
    test_db.add(rollup)

    # 4. Delete raw metrics (simulating cleanup)
    test_db.query(ToolMetric).delete()

    # 5. BUG: Returns 0 instead of 10
    assert tool.metrics_summary["total_executions"] == 0  # Current behavior
    # assert tool.metrics_summary["total_executions"] == 10  # Expected
```

---

**Analysis Date**: 2026-03-11
**Analyzer**: Claude Code (Systematic Debugging Skill)
**Verification**: Reproduced in v1.0.0-RC2
