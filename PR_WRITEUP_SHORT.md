# Fix Metrics Returning 0 After Cleanup + Extend include_metrics Support

## Summary

Fixes #3598 where metrics API returned 0 after raw metrics cleanup. The API only queried the raw metrics table, ignoring hourly aggregates. Also extends `include_metrics=true` support to Resources, Prompts, and Servers (Tools already had this).

## Problem

When calling `/servers/{server_id}/tools?include_metrics=true`, `total_executions` returned 0 after raw metrics were cleaned up. Historical data existed in `tool_metrics_hourly` but wasn't being queried.

## Solution

### 1. Centralized Helper Function
Created `_compute_metrics_summary()` in `mcpgateway/db.py` (~230 lines) that:
- Queries both raw and hourly metrics tables
- Uses time-based partitioning (current hour = raw only, completed hours = hourly only)
- Prevents double-counting
- Handles timezone normalization

### 2. Updated 4 Models
Applied fix to Tool, Resource, Prompt, and Server models:
- Added `metrics_hourly` relationship
- Updated `metrics_summary` property to use helper function

### 3. Extended API Support
Added `include_metrics=true` parameter to:
- `GET /servers/{server_id}/resources?include_metrics=true`
- `GET /servers/{server_id}/prompts?include_metrics=true`
- `GET /servers?include_metrics=true`

## Files Changed

- `mcpgateway/db.py`: Helper function + 4 model updates (+554/-298)
- `mcpgateway/main.py`: Added `include_metrics` to 3 endpoints (+13)
- `mcpgateway/services/{resource,prompt,server}_service.py`: Pass-through support (+12/-3)
- `tests/unit/mcpgateway/test_metrics_aggregation_fix.py`: **NEW** comprehensive tests (+258)
- `tests/unit/mcpgateway/test_db.py`: Updated tests (+144)

**Total**: 8 files, 925 insertions(+), 298 deletions(-)

## Benefits

- **Bug Fixed**: Metrics correctly aggregated from both tables
- **Code Reduced**: 400+ duplicated lines → 230 centralized
- **Consistent API**: All 4 services support `include_metrics=true`
- **Maintainable**: Single function to update instead of 4 places
- **Future-proof**: Adding metrics to new models now takes 5 lines vs 100+

## Testing

```bash
# All endpoints now support include_metrics=true
curl "http://localhost:4444/servers/{id}/tools?include_metrics=true" -H "Authorization: Bearer $TOKEN"
curl "http://localhost:4444/servers/{id}/resources?include_metrics=true" -H "Authorization: Bearer $TOKEN"
curl "http://localhost:4444/servers/{id}/prompts?include_metrics=true" -H "Authorization: Bearer $TOKEN"
curl "http://localhost:4444/servers?include_metrics=true" -H "Authorization: Bearer $TOKEN"
```

Expected metrics response:
```json
{
  "total_executions": 150,
  "successful_executions": 145,
  "failed_executions": 5,
  "failure_rate": 0.033,
  "avg_response_time": 0.45,
  "last_execution_time": "2026-03-12T12:30:00Z"
}
```

## Test Coverage

- Added 258 lines of new tests covering current hour, completed hours, mixed scenarios, and edge cases
- Updated existing tests (+144 lines)
- All tests passing ✅

---

Closes #3598

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>
