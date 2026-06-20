# Task 6 Evidence — JSON-RPC error mapping table

**Plan reference**: `.omo/plans/a2a-native-passthrough.md` T6 + D6 + Oracle v3 #6 + #14
**Implementation**: `mcpgateway/services/a2a_service.py` (constants + `make_jsonrpc_error`)
**Tests**: `tests/unit/mcpgateway/services/test_a2a_service_native.py::TestJsonRpcErrorConstants` + `TestMakeJsonrpcError`

## Wire-shape contract (plan D6 + D14)

- **JSON-RPC envelope errors** are returned as `HTTP 200` plus a JSON-RPC error body. This applies to envelope, method, params, version, and upstream-protocol-level failures.
- **Transport-level failures** use HTTP status codes: 401 missing auth, 403 RBAC deny, 404 path-resource-not-found (agent unknown ahead of body parse — plan D14), 405 method-not-allowed, 5xx gateway crash.

## Error trigger table

Each gateway-owned trigger maps to a concrete test reference. Upstream-owned triggers are pass-through (the gateway forwards the upstream's JSON-RPC error verbatim).

| Trigger | Owner | Code | Wire location | Test |
|---------|-------|------|---------------|------|
| JSON syntax error in body | Gateway | `-32700` (PARSE_ERROR) | T12 manual parse | `tests/integration/test_a2a_native_routes.py::test_dispatch_parse_error` |
| Body not a JSON object (`[]`, `123`, `"x"`) | Gateway | `-32600` (INVALID_REQUEST) | T12 isinstance(dict) guard | `tests/integration/test_a2a_native_routes.py::test_dispatch_invalid_request_shape` |
| Method field missing or non-string | Gateway | `-32600` (INVALID_REQUEST) | T4 envelope validation | `tests/unit/mcpgateway/services/test_a2a_service_native.py::test_dispatch_unary_envelope_validation` |
| `A2A-Version` missing OR unsupported (and method is not a legacy v0.3 alias) | Gateway | `-32009` (VERSION_NOT_SUPPORTED) | T7 + T12 step 7 | `tests/unit/mcpgateway/services/test_a2a_version_negotiation.py::test_missing_header_v1_method_rejected` + `tests/integration/test_a2a_native_routes.py::test_dispatch_version_unsupported` |
| Unknown method on a known agent | Upstream | `-32601` (METHOD_NOT_FOUND) | upstream agent (gateway pass-through) | upstream test (out of scope) |
| Invalid params on a known method | Upstream | `-32602` (INVALID_PARAMS) | upstream agent | upstream test (out of scope) |
| Task ID not found (`GetTask`, `CancelTask`) | Upstream | `-32001` (TASK_NOT_FOUND) | upstream agent | upstream test (out of scope) |
| Task in terminal state (`CancelTask`) | Upstream | `-32002` (TASK_NOT_CANCELABLE) | upstream agent | upstream test (out of scope) |
| Push config method on agent without `pushNotifications` capability | Upstream | `-32003` (PUSH_NOT_SUPPORTED) | upstream agent (gateway pass-through; no gateway-side fast-fail in phase 1) | upstream test (out of scope) |
| Upstream returns malformed JSON in SSE chunk | Gateway | `-32006` (INVALID_AGENT_RESPONSE) | T5 SSE parser | `tests/unit/mcpgateway/services/test_a2a_service_native.py::test_dispatch_streaming_malformed_chunk` |
| `GetExtendedAgentCard` invoked when agent's `capabilities.extendedAgentCard` is False or absent | Gateway | `-32007` (AUTHENTICATED_EXTENDED_CARD_NOT_CONFIGURED) | T12 `GetExtendedAgentCard` branch | `tests/integration/test_a2a_native_routes.py::test_get_extended_card_not_configured` |
| Upstream HTTP 5xx or transport error | Gateway | `-32603` (INTERNAL_ERROR) | T4/T5 catch + map | `tests/unit/mcpgateway/services/test_a2a_service_native.py::test_dispatch_unary_upstream_5xx` |

## HTTP-level (NOT JSON-RPC) outcomes

| Trigger | Wire | Notes |
|---------|------|-------|
| Unauthorized caller per `a2a.invoke` or `a2a.read` | HTTP 403 | T12 permission check; tested via `tests/integration/test_a2a_native_routes.py::test_dispatch_rbac_denied` |
| Unknown agent at path (BEFORE body parse) | HTTP 404 | T12 `resolve_agent_for_dispatch` raises `A2AAgentNotFoundError` (D14) |
| Foreign agent at v-server path | HTTP 404 | T12 `resolve_agent_for_dispatch` raises `AgentNotInServerError` (D14); behaviorally indistinguishable from agent-unknown |
| Malformed/missing auth | HTTP 401 | middleware |

## Constant inventory (verified)

The 14 constants exported from `mcpgateway/services/a2a_service.py` (verified by `TestJsonRpcErrorConstants` — parameterized over all 14):

- **Standard JSON-RPC 2.0**: `PARSE_ERROR=-32700`, `INVALID_REQUEST=-32600`, `METHOD_NOT_FOUND=-32601`, `INVALID_PARAMS=-32602`, `INTERNAL_ERROR=-32603`
- **A2A 1.0.0 spec section 5.4**: `TASK_NOT_FOUND=-32001`, `TASK_NOT_CANCELABLE=-32002`, `PUSH_NOT_SUPPORTED=-32003`, `UNSUPPORTED_OPERATION=-32004`, `CONTENT_TYPE_NOT_SUPPORTED=-32005`, `INVALID_AGENT_RESPONSE=-32006`, `AUTHENTICATED_EXTENDED_CARD_NOT_CONFIGURED=-32007`, `MULTIPLE_PUSH_NOT_SUPPORTED=-32008`, `VERSION_NOT_SUPPORTED=-32009`

## `make_jsonrpc_error` wire shape (verified)

```json
{"jsonrpc": "2.0", "error": {"code": <int>, "message": <str>, "data": <Any>?}, "id": <request_id>}
```

- `data` field is **omitted** when None (not emitted as `"data": null`).
- `id` echoes verbatim — supports `int`, `str`, and `None` (JSON-RPC notification).
- A2A-specific codes are preserved verbatim, **NOT** silently coerced to `INTERNAL_ERROR` (Oracle v3 #6 anti-pattern).

Verified by `TestMakeJsonrpcError` (9 cases).
