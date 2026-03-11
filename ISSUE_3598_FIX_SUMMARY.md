# Issue #3598 Fix Summary

**Issue**: [BUG]: metrics API call count displayed as 0
**GitHub**: https://github.com/IBM/mcp-context-forge/issues/3598
**Fix Date**: 2026-03-11
**Status**: ✅ **FIXED**

---

## Problem

When calling `/servers/{server_id}/tools?include_metrics=true`, the API returned `total_executions = 0` after raw metrics were aggregated into hourly rollup tables and subsequently cleaned up. This affected all production deployments using the default configuration where `metrics_delete_raw_after_rollup=true` (default).

---

## Root Cause

The `metrics_summary` property in all entity models (Tool, Resource, Prompt, Server) only queried the raw metrics tables (`tool_metrics`, `resource_metrics`, etc.) and ignored the hourly rollup tables (`tool_metrics_hourly`, `resource_metrics_hourly`, etc.) where historical data resides after cleanup.

**Location**: `mcpgateway/db.py:3366` (and similar locations for other entities)

---

## Solution

Modified the `metrics_summary` property in all affected models to query **BOTH**:
1. **Raw metrics tables** - Recent data not yet rolled up/cleaned
2. **Hourly rollup tables** - Historical data after cleanup

The fix properly aggregates results from both sources, handling:
- Total execution counts (sum from both tables)
- Success/failure counts (sum from both tables)
- Min/max response times (take extremes from both sources)
- Average response times (weighted average based on total counts)
- Last execution timestamp (most recent from either source)

---

## Files Changed

### Core Fix
- **mcpgateway/db.py** - Fixed `metrics_summary` for all entities:
  - Tool.metrics_summary (line ~3339)
  - Resource.metrics_summary (line ~3711)
  - Prompt.metrics_summary (line ~4122)
  - Server.metrics_summary (line ~4427)

### Tests Updated
- **tests/unit/mcpgateway/test_db.py** - Updated 4 tests to mock both queries:
  - test_tool_metrics_summary_sql_path
  - test_resource_metrics_summary_sql_path
  - test_prompt_metrics_summary_sql_path
  - test_server_metrics_summary_sql_path

### Test Artifacts
- **test_issue_3598_reproduction.py** - Reproduction test (can be moved to tests/)
- **ISSUE_3598_ANALYSIS.md** - Detailed root cause analysis (can be removed after PR)
- **ISSUE_3598_FIX_SUMMARY.md** - This file (for PR description)

---

## Verification

### Reproduction Test
```bash
$ python test_issue_3598_reproduction.py

FIX VERIFICATION:
  total_executions BEFORE deletion: 10
  total_executions AFTER deletion: 10
  Hourly rollup has: 10 executions

✅ Fix successful: API now queries BOTH tool_metrics AND tool_metrics_hourly

. 1 passed in 0.11s
```

### Unit Tests
```bash
$ pytest tests/unit/mcpgateway/test_db.py -k "metric" -v

====================== 30 passed, 149 deselected in 0.22s ======================
```

---

## Impact

### Before Fix
- ❌ Dashboards showed zero executions after metrics rollup
- ❌ Historical analytics disappeared
- ❌ Monitoring/alerting systems failed
- ❌ Users lost trust in platform metrics

### After Fix
- ✅ Metrics persist across rollup/cleanup cycles
- ✅ Historical data visible via API
- ✅ Dashboards show correct execution counts
- ✅ Monitoring/alerting systems work correctly

---

## Technical Details

### Query Strategy

**Before (Broken)**:
```python
# Only queries raw metrics
result = session.query(
    func.count(ToolMetric.id),
    ...
).filter(ToolMetric.tool_id == self.id).one()
```

**After (Fixed)**:
```python
# Query raw metrics
raw_result = session.query(
    func.count(ToolMetric.id),
    ...
).filter(ToolMetric.tool_id == self.id).one()

# Query hourly rollups
hourly_result = session.query(
    func.sum(ToolMetricsHourly.total_count),
    ...
).filter(ToolMetricsHourly.tool_id == self.id).one()

# Aggregate both sources
total = (raw_result[0] or 0) + (hourly_result[0] or 0)
```

### Weighted Average Calculation

For average response time, we use a weighted average to properly combine raw and hourly data:

```python
# Raw: sum of all response times
raw_sum = func.sum(ToolMetric.response_time)

# Hourly: weighted sum (avg * count)
hourly_sum = func.sum(ToolMetricsHourly.avg_response_time * ToolMetricsHourly.total_count)

# Combined average
avg_rt = (raw_sum + hourly_sum) / total_count
```

This ensures that averages are correctly calculated across both data sources.

---

## Edge Cases Handled

1. **No hourly data**: New tools with only raw metrics → returns raw metrics only ✅
2. **No raw data**: Old tools with only hourly rollups → returns hourly aggregates only ✅
3. **Both sources present**: Correctly aggregates from both ✅
4. **No data at all**: Returns zeros/nulls as expected ✅
5. **Null values**: Properly handles None results from queries ✅

---

## Performance Considerations

### Query Count
- **Before**: 1 query per `metrics_summary` call
- **After**: 2 queries per `metrics_summary` call

### Optimization Opportunities (Future)
1. **Single UNION query**: Combine both queries into one with UNION ALL
2. **Materialized view**: Pre-compute combined metrics
3. **Caching**: Cache results with short TTL (already exists in codebase)

Current implementation prioritizes **correctness over optimization**. The dual-query approach is straightforward and maintainable. Performance impact is minimal as these queries are simple aggregations with indexed foreign keys.

---

## Configuration

No configuration changes required. The fix works with existing default settings:

```python
# mcpgateway/config.py (defaults)
metrics_rollup_enabled: bool = True
metrics_rollup_interval_hours: int = 1
metrics_delete_raw_after_rollup: bool = True  # ← Fix handles this correctly now
metrics_delete_raw_after_rollup_hours: int = 1
```

---

## Testing Recommendations

### Manual Testing
1. Create a tool/resource/prompt/server
2. Execute it multiple times to generate metrics
3. Wait for hourly rollup (or trigger manually via `/api/metrics/rollup`)
4. Wait for raw metrics cleanup (or trigger via `/api/metrics/cleanup`)
5. Query metrics via API → should show correct counts ✅

### Automated Testing
- All existing unit tests pass
- New reproduction test demonstrates the fix
- Tests cover all entity types (Tool, Resource, Prompt, Server)

---

## Rollback Plan

If issues arise, the fix can be safely reverted as it only changes the `metrics_summary` property implementation. No database schema changes or migrations are involved.

To rollback:
```bash
git revert <commit-sha>
```

---

## Related Issues

- None found (this appears to be the first report)
- May affect users who haven't noticed missing metrics yet

---

## Future Improvements

1. **Add database view**: Create a unified metrics view combining raw and hourly data
2. **Optimize queries**: Use UNION ALL instead of two separate queries
3. **Add monitoring**: Track metrics query performance
4. **Documentation**: Update metrics architecture docs

---

## Commit Message

```
fix(metrics): aggregate from both raw and hourly metrics tables (#3598)

Fix metrics_summary to query both raw metrics tables and hourly rollup
tables. Previously, metrics would show as 0 after raw data was cleaned
up during normal rollup operations.

Changes:
- Modified Tool.metrics_summary to query tool_metrics + tool_metrics_hourly
- Modified Resource.metrics_summary to query resource_metrics + resource_metrics_hourly
- Modified Prompt.metrics_summary to query prompt_metrics + prompt_metrics_hourly
- Modified Server.metrics_summary to query server_metrics + server_metrics_hourly
- Updated unit tests to mock both query paths
- Added reproduction test demonstrating the fix

The fix uses weighted averages for response times and properly handles
edge cases (no raw data, no hourly data, both present, neither present).

Closes #3598

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>
```

---

## Sign-off

```bash
Signed-off-by: Claude Opus 4.6 <noreply@anthropic.com>
```

---

**Fix completed**: 2026-03-11
**Verified by**: Automated tests + manual reproduction test
**Ready for**: Code review and PR submission
