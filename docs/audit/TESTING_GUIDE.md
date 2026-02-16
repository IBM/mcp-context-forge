# Testing Guide: Policy Audit System

## Test Files

| File | Coverage |
|------|----------|
| `tests/unit/mcpgateway/services/test_policy_decision_service.py` | Service logic, per-decision toggles, DB error handling |
| `tests/unit/mcpgateway/services/test_siem_export_service.py` | SIEM factory, batch processor, flush/retry behavior |
| `tests/unit/mcpgateway/routers/test_policy_decisions_api.py` | REST endpoints, auth enforcement, health check |

## Running Tests

```bash
# Run all audit-related tests
pytest tests/unit/mcpgateway/services/test_policy_decision_service.py \
       tests/unit/mcpgateway/services/test_siem_export_service.py \
       tests/unit/mcpgateway/routers/test_policy_decisions_api.py -v

# Run with coverage
pytest tests/unit/mcpgateway/services/test_policy_decision_service.py \
       tests/unit/mcpgateway/services/test_siem_export_service.py \
       tests/unit/mcpgateway/routers/test_policy_decisions_api.py \
       --cov=mcpgateway/services/policy_decision_service \
       --cov=mcpgateway/services/siem_export_service \
       --cov=mcpgateway/routers/policy_decisions_api \
       --cov-report=term-missing -v

# Run a specific test class or function
pytest tests/unit/mcpgateway/services/test_policy_decision_service.py::test_happy_path_creates_and_returns_record -v
pytest tests/unit/mcpgateway/services/test_siem_export_service.py -k "batch" -v
```

## Test Structure

**`test_policy_decision_service.py`** tests the core service:
- Disabled service returns a stub `PolicyDecision` (no DB hit)
- Enabled service creates, commits, and returns records
- DB exceptions produce a fallback record (never `None`)
- Per-decision toggles (`policy_audit_log_allowed` / `policy_audit_log_denied`) skip DB writes
- Sort column allowlist rejects invalid values
- Statistics query returns expected structure

**`test_siem_export_service.py`** tests the SIEM integration:
- Factory creates correct exporter type (Splunk, Elasticsearch, Webhook)
- Factory returns `None` for disabled/misconfigured SIEM
- Batch processor flushes when queue reaches batch size
- Failed batches are re-queued
- Graceful shutdown flushes all remaining records
- Shutdown does not hang when flush repeatedly fails

**`test_policy_decisions_api.py`** tests the REST API:
- Authenticated endpoints reject unauthenticated requests (401)
- `GET /decisions` returns filtered decision list
- `POST /decisions/query` passes filter parameters to service
- `GET /statistics` returns aggregate stats
- `GET /health` works without authentication
