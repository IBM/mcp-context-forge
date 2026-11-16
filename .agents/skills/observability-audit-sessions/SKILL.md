---
name: observability-audit-sessions
description: Change code that writes traces, spans, metrics, or audit entries. Use when you touch `ObservabilityService`, `ObservabilityMiddleware`, `instrumentation/sqlalchemy.py`, or a `log_action()` / `log_audit()` call site, or when you size connection pools.
---

# Observability and Audit Trail Session Behavior

Observability writes and audit writes use sessions separate from the main request transaction. This is an intentional trade-off.

## Observability Transaction Behavior

**Issue #3883 - Separate Session Pattern**

The HTTP middleware reuses one observability session per traced request. This means:

- Observability data persists even when the main request fails.
- Traces can show "in progress" or partial states for failed requests.
- Observability writes are **NOT atomic** with the main request transaction.
- You get visibility into partial failures at the cost of atomicity.

### Implementation Details

**Write methods** (create independent sessions unless callers supply a supported `obs_db` parameter):
- `start_trace()`, `end_trace()`
- `start_span()`, `end_span()`
- `add_event()`, `record_token_usage()`, `record_metric()`, `delete_old_traces()`

**Query methods** (use request-scoped sessions):
- `get_trace()`, `get_traces()`, `get_spans()`, etc.
- These accept a `db: Session` parameter for RBAC/token scoping.

**Context managers** (create one independent session for the lifecycle):
- `trace_span()`, `trace_tool_invocation()`, `trace_a2a_request()`

**Middleware lifecycle**: Commit parent traces and HTTP spans before request processing so independent child writers can see them. Commit span and trace completion independently. Roll back caught span failures before attempting trace completion. Keep this session separate from application transactions.

**Pattern**: SQL instrumentation also reuses a session for each query span in `instrumentation/sqlalchemy.py`.

## Audit Trail Transaction Behavior

**Issue #2871 - Separate Session Pattern**

`AuditTrailService.log_action()` (`mcpgateway/services/audit_trail_service.py`) opens its own `SessionLocal()` when no `db` is supplied. It closes and rolls back that session itself. Callers in `tool_service.py`, `resource_service.py`, `gateway_service.py`, `prompt_service.py`, `server_service.py`, and `admin.py` must **never** pass `db=db` (the caller's request-scoped session) to `log_action()`. In `admin.py`, plugin-view audit logging goes through `log_audit()`. It is a thin wrapper over `log_action()` and inherits the same optional-session behavior.

Passing the shared session caused **"This transaction is inactive"** errors. The main CRUD operation already calls `db.commit()` before the audit call. A second commit on the same session leaves it in a state that breaks rollback on later errors.

- `log_action()` swallows its own exceptions and returns `None` on failure. It does not propagate them to the caller in production.
- The main resource (tool/gateway/resource/prompt/server) is committed **before** `log_action()` runs. An audit-logging failure never rolls back persisted data. The generic `except Exception` handlers of callers still call `db.rollback()` and surface an error to the API caller, even though the row is already committed.
- Do not add `db: Session` back to a `log_action()` call site. If a service needs the audit entry in the same transaction as the main write, that is a deliberate design change that requires review.

**Middleware**: `ObservabilityMiddleware` creates one observability session per HTTP trace lifecycle and closes it after completion. Child spans, metrics, and SQL instrumentation can create additional sessions. The middleware does not create `request.state.db`.

**Security**: Query operations use request-scoped sessions for RBAC/token scoping. Write operations are not RBAC-protected. Observability visibility is platform-wide.

**Connection Pool Sizing**: Session allocations do not equal simultaneous connections. Commits release connections before subsequent lifecycle operations. Size pools from measured concurrent connection use, worker counts, and database limits. The SQLite lifecycle comparison measures session allocations and checkouts. It does not establish production capacity. See `docs/docs/manage/tuning.md` for measurements and limitations.
