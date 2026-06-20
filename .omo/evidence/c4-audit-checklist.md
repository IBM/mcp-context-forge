# Task 8 Evidence — C4 compliance coverage audit

**Plan reference**: `.omo/plans/a2a-native-passthrough.md` T8 + P5
**Scope**: A2A 1.0.0 protocol surface in `tests/live_gateway/a2a_compliance/v1_0_0/`
**Audited at**: 2026-06-20 (Wave 2, after T28 Part A fixture wiring)
**Existing test count (v1.0.0)**: 20 across 7 files

## Audit method

For each of the 9 A2A 1.0.0 protocol-requirement sections from the plan, this checklist either:

- **CITES** the existing assertion that covers it (test file::function), OR
- **GAPS** the requirement with severity:
  - **GAP-BLOCK**: must be closed in Wave 2 (T9/T10 add the assertion). The gateway-target columns will fail until Wave 3 implementation lands; tests are authored anyway so the gap-closure-then-implementation flow is real.
  - **GAP-NICE**: can be closed in a follow-up. Lower priority because either (a) the spec marks it optional, (b) it covers an edge case unlikely to drift, or (c) it duplicates coverage from another section.

Wave 2 closes only **GAP-BLOCK** entries. **GAP-NICE** entries are tracked here for visibility but not on the Wave 2 work surface.

---

## Section 1 — Card discovery + field names

| Requirement | Status | Citation / Severity |
|---|---|---|
| Required top-level fields present (`name`, `description`, `supportedInterfaces`, `version`, `capabilities`, `defaultInputModes`, `defaultOutputModes`, `skills`) | ✅ CITED | `test_agent_card.py::test_agent_card_required_fields` |
| `supportedInterfaces` is a non-empty list | ✅ CITED | `test_agent_card.py::test_supported_interfaces_non_empty` |
| Each `supportedInterfaces[]` entry has `protocolVersion` | ✅ CITED | `test_agent_card.py::test_each_interface_has_protocol_version` |
| `securitySchemes` is a JSON object when present | ✅ CITED | `test_security.py::test_security_schemes_well_typed_when_present` |
| `securityRequirements` is a JSON array of objects when present | ✅ CITED | `test_security.py::test_security_requirements_well_typed_when_present` |
| `.well-known/agent-card.json` returns 200 + JSON | ✅ CITED | `test_well_known.py::test_canonical_well_known_route` |
| Canonical and compat well-known aliases serve identical bodies | ✅ CITED | `test_well_known.py::test_compat_well_known_alias` |
| Extended agent card route reachable | ✅ CITED | `test_well_known.py::test_extended_agent_card_route` |
| `protocolBinding` field is camelCase (NOT `transportProtocol`) | ✅ CITED (T9) | `test_agent_card_extra.py::test_protocol_binding_is_camelcase_not_transport_protocol` |
| URL field rewritten to gateway-public coordinates (NOT upstream's `endpoint_url`) | ✅ CITED (T9) | `test_agent_card_extra.py::test_interface_url_matches_target_base` |
| `protocolBinding` value is `"JSONRPC"` for the JSON-RPC interface | ✅ CITED (T9) | `test_agent_card_extra.py::test_protocol_binding_value_is_jsonrpc` |
| `extra="forbid"` on `AgentCard` rejects unknown fields | ❌ GAP-NICE | Pydantic-model contract; covered by T1 unit tests |

## Section 2 — JSON-RPC envelope validation

| Requirement | Status | Citation / Severity |
|---|---|---|
| Missing `method` field → `-32600 INVALID_REQUEST` | ✅ CITED | `test_error_handling.py::test_missing_method_returns_invalid_request` |
| Malformed JSON in body → `-32700 PARSE_ERROR` | ✅ CITED | `test_error_handling.py::test_malformed_json_returns_parse_error` |
| Body not a JSON object (`[]`, `123`, `"x"`) → `-32600 INVALID_REQUEST` | ✅ CITED (T10) | `test_jsonrpc_envelope_extra.py::test_non_dict_body_returns_invalid_request` |
| `jsonrpc` field != `"2.0"` → `-32600 INVALID_REQUEST` | ❌ GAP-NICE | Covered by T4 unit tests |
| `params` not dict-or-null → `-32602 INVALID_PARAMS` | ❌ GAP-NICE | Covered by T4 unit tests |

## Section 3 — Method catalog (per F8 + spec section 9.4)

| Method | Status | Citation / Severity |
|---|---|---|
| `SendMessage` | ✅ CITED | `test_jsonrpc_methods.py::test_send_message_returns_at_least_one_response`, `test_send_message_echoes_input_text`, `test_messages_artifacts.py::test_send_message_response_populates_message_or_task`, `test_echo_response_carries_text_part` |
| `SendStreamingMessage` | ✅ CITED (T10) | `test_method_catalog_extra.py::test_send_streaming_message_method_recognized` |
| `GetTask` (not-found case) | ✅ CITED | `test_jsonrpc_methods.py::test_get_task_for_unknown_id_raises` (verifies `-32001 TASK_NOT_FOUND` via SDK exception) |
| `GetTask` (success case after `SendMessage`) | ❌ GAP-NICE | Requires task-lifecycle test fixture; defer |
| `ListTasks` | ✅ CITED | `test_jsonrpc_methods.py::test_list_tasks_returns_response` |
| `CancelTask` (not-found case) | ✅ CITED | `test_jsonrpc_methods.py::test_cancel_task_for_unknown_id_raises` |
| `SubscribeToTask` | ✅ CITED (T10) | `test_method_catalog_extra.py::test_subscribe_to_task_method_recognized` |
| `CreateTaskPushNotificationConfig` | ❌ GAP-NICE | Push notifications optional per capability flag |
| `GetTaskPushNotificationConfig` | ❌ GAP-NICE | Same |
| `ListTaskPushNotificationConfigs` | ❌ GAP-NICE | Same |
| `DeleteTaskPushNotificationConfig` | ❌ GAP-NICE | Same |
| `GetExtendedAgentCard` as a JSON-RPC method (not just HTTP route) | ✅ CITED (T10) | `test_method_catalog_extra.py::test_get_extended_agent_card_method_recognized` |

## Section 4 — Error codes (standard `-32700..-32603` + A2A-specific `-32001..-32009`)

| Code | Status | Citation / Severity |
|---|---|---|
| `-32700 PARSE_ERROR` | ✅ CITED | `test_error_handling.py::test_malformed_json_returns_parse_error` |
| `-32600 INVALID_REQUEST` | ✅ CITED | `test_error_handling.py::test_missing_method_returns_invalid_request` |
| `-32601 METHOD_NOT_FOUND` | ✅ CITED | `test_error_handling.py::test_unknown_method_returns_method_not_found` |
| `-32602 INVALID_PARAMS` | ✅ CITED (T10) | `test_error_codes_extra.py::test_invalid_params_returns_32602` |
| `-32603 INTERNAL_ERROR` | ✅ CITED (T10) | `test_error_codes_extra.py::test_internal_error_returns_32603_on_upstream_5xx` (gateway-only) |
| `-32001 TASK_NOT_FOUND` | ✅ CITED | `test_get_task_for_unknown_id_raises`, `test_cancel_task_for_unknown_id_raises` |
| `-32002 TASK_NOT_CANCELABLE` | ❌ GAP-NICE | Requires task-lifecycle setup; defer |
| `-32003 PUSH_NOT_SUPPORTED` | ❌ GAP-NICE | Push methods deferred |
| `-32004 UNSUPPORTED_OPERATION` | ❌ GAP-NICE | Spec-level edge case |
| `-32005 CONTENT_TYPE_NOT_SUPPORTED` | ❌ GAP-NICE | Spec-level edge case |
| `-32006 INVALID_AGENT_RESPONSE` | ✅ CITED (T10) | `test_error_codes_extra.py::test_invalid_agent_response_returns_32006_on_sse_parse_error` (gateway-only) |
| `-32007 AUTHENTICATED_EXTENDED_CARD_NOT_CONFIGURED` | ✅ CITED (T10) | `test_error_codes_extra.py::test_extended_card_not_configured_returns_32007` (gateway-only) |
| `-32008 MULTIPLE_PUSH_NOT_SUPPORTED` | ❌ GAP-NICE | Push methods deferred |
| `-32009 VERSION_NOT_SUPPORTED` | ✅ CITED (T10) | `test_error_codes_extra.py::test_version_not_supported_returns_32009` (gateway-only) |

## Section 5 — SSE shape (streaming methods)

| Requirement | Status | Citation / Severity |
|---|---|---|
| Streaming response has `Content-Type: text/event-stream` | ✅ CITED (T10) | `test_sse_streaming_extra.py::test_streaming_content_type_is_text_event_stream` |
| Each `data:` chunk parses as a complete JSON-RPC response | ✅ CITED (T10) | `test_sse_streaming_extra.py::test_sse_chunks_parse_as_jsonrpc` |
| At least one chunk yielded for a successful streaming method invocation | ✅ CITED (T10) | `test_sse_streaming_extra.py::test_streaming_yields_at_least_one_chunk` |
| Terminal state handling (stream closes cleanly on terminal/interrupted state) | ❌ GAP-NICE | Hard to test deterministically; defer |

## Section 6 — `A2A-Version` header negotiation

| Requirement | Status | Citation / Severity |
|---|---|---|
| Card advertises expected `protocolVersion` per interface | ✅ CITED | `test_version_negotiation.py::test_card_advertises_expected_protocol_version` |
| Card's `protocolVersion` is sem-ver-shaped | ✅ CITED | `test_version_negotiation.py::test_protocol_version_is_semver_shape` |
| Inbound: gateway rejects missing `A2A-Version` for v1 method → `-32009` | ✅ CITED (T10) | `test_version_negotiation_extra.py::test_missing_a2a_version_for_v1_method_returns_32009` (gateway-only) |
| Inbound: gateway tolerates missing `A2A-Version` for legacy v0.3 alias method | ✅ CITED (T10) | `test_version_negotiation_extra.py::test_missing_a2a_version_for_v03_alias_is_tolerated` (gateway-only) |
| Outbound: gateway sets `A2A-Version` from `agent.protocol_version` | ✅ CITED (T10) | `test_version_negotiation_extra.py::test_outbound_a2a_version_header_is_set` (gateway-only) |
| Inbound: gateway rejects unsupported version (e.g. `"2.0"`) → `-32009` | ❌ GAP-NICE | Same shape as missing-header path; covered by T7 unit tests |

## Section 7 — v0.3 method alias acceptance (excluding `tasks/list`)

| Requirement | Status | Citation / Severity |
|---|---|---|
| `message/send` → forwarded as `SendMessage` | ✅ CITED (T10) | `test_v03_aliases_extra.py::test_message_send_alias_recognized` (gateway-only) |
| `tasks/get` → forwarded as `GetTask` | ✅ CITED (T10) | `test_v03_aliases_extra.py::test_tasks_get_alias_recognized` (gateway-only) |
| `message/stream` → forwarded as `SendStreamingMessage` | ✅ CITED (T10) | `test_v03_aliases_extra.py::test_message_stream_alias_recognized` (gateway-only) |
| All 10 legacy aliases mapped per F8 | ❌ GAP-NICE | Full inventory covered by T4 unit tests |
| `tasks/list` is NOT mapped (it is NEW in v1.0, not a legacy alias) | ✅ CITED (T10) | `test_v03_aliases_extra.py::test_tasks_list_is_NOT_a_legacy_alias` (gateway-only) |
| Gateway logs an info message when accepting a missing `A2A-Version` for a legacy method | ❌ GAP-NICE | Log-side check; covered by T7 unit tests |

## Section 8 — RBAC + Layer-1 visibility denial

| Requirement | Status | Citation / Severity |
|---|---|---|
| Missing `Authorization` → HTTP 401 | ✅ CITED (T10) | `test_rbac_extra.py::test_missing_authorization_returns_401` (gateway-only) |
| Invalid token → HTTP 401 | ✅ CITED (T10) | `test_rbac_extra.py::test_invalid_token_returns_401` (gateway-only) |
| Authenticated caller without `a2a.invoke` permission → HTTP 403 | ✅ CITED (T10) | `test_rbac_extra.py::test_no_invoke_permission_returns_403` (gateway-only) |
| Team-scoped agent + wrong-team token → HTTP 404 | ✅ CITED (T10, deferred) | `test_rbac_extra.py::test_team_scoped_agent_wrong_team_returns_404` (skip+TODO Wave 7 T28-B for fixture) |
| `GetExtendedAgentCard` with only `a2a.read` permission → 200 | ✅ CITED (T10, deferred) | `test_rbac_extra.py::test_extended_card_with_read_permission_returns_200` (skip+TODO Wave 7 T28-B for fixture) |
| `GetExtendedAgentCard` without `a2a.read` permission → HTTP 403 | ✅ CITED (T10) | `test_rbac_extra.py::test_extended_card_without_read_permission_returns_403` (gateway-only) |
| Public-only token (`token_teams=[]`) admin bypass suppression | ❌ GAP-NICE | Covered by T3 + T12 unit tests via `_check_agent_access` |

## Section 9 — Virtual-server scoping

| Requirement | Status | Citation / Severity |
|---|---|---|
| Agent in server: `/servers/{srv}/a2a/{name}/.well-known/agent-card.json` returns the card with `/servers/{srv}/...` URL prefix | ❌ GAP-NICE | Deferred to Wave 7 (gateway_virtual target joins parametrize set in T28 Part B) |
| Foreign agent at `/servers/{srv}/a2a/{foreign}` → HTTP 404 | ❌ GAP-NICE | Same — deferred to Wave 7 |
| Dispatch via `/servers/{srv}/a2a/{name}` works identically to per-agent URL | ❌ GAP-NICE | Same — deferred to Wave 7 |

**Note**: Section 9 is intentionally deferred to Wave 7. Wave 2 fixtures parametrize only over `{reference, gateway_proxy}` (T28 Part A). `gateway_virtual` joins via T28 Part B AFTER T20 verifies server-CRUD wiring. The integration test for v-server composition lives in T19 (Wave 4).

---

## Summary (post-T9 + T10 re-audit)

| Section | CITED pre-Wave2 | CITED via T9/T10 | Remaining BLOCK | GAP-NICE |
|---|---|---|---|---|
| 1. Card discovery + field names | 8 | 3 (T9) | 0 | 1 |
| 2. JSON-RPC envelope validation | 2 | 1 (T10) | 0 | 2 |
| 3. Method catalog | 6 | 3 (T10) | 0 | 5 |
| 4. Error codes | 4 | 5 (T10) | 0 | 5 |
| 5. SSE shape | 0 | 3 (T10) | 0 | 1 |
| 6. A2A-Version | 2 | 3 (T10) | 0 | 1 |
| 7. v0.3 alias acceptance | 0 | 4 (T10) | 0 | 2 |
| 8. RBAC denial | 0 | 6 (T10, 2 deferred via skip+TODO) | 0 | 1 |
| 9. V-server scoping (deferred to Wave 7) | 0 | 0 | 0 (Wave 7) | 3 |
| **TOTAL** | **22** | **28** | **0** | **21** |

**Wave 2 closure: ALL 28 GAP-BLOCK rows closed.** 3 by T9 (`test_agent_card_extra.py`), 25 by T10 (7 new `*_extra.py` files). 2 of the 25 T10 rows (team-scoped 404, extended-card-with-read 200) require Wave 7 T28 Part B RBAC fixtures and live in the harness as `pytest.skip()` with TODO pointers; the wire-level contract is encoded in their docstrings for Wave 3 implementation reference.

## Wave 2 closure plan (HISTORICAL — refers to in-flight state)

- **T9 (card discovery gap closure)**: implemented the 3 GAP-BLOCK entries in Section 1 (`protocolBinding` camelCase, URL rewrite, `protocolBinding="JSONRPC"`). Committed `fd03f8f05`.
- **T10 (dispatch / streaming / errors / auth gap closure)**: implemented the 25 remaining GAP-BLOCK entries across Sections 2-8. Committed `d219df7e9`.
- **GAP-NICE entries are NOT scheduled for Wave 2.** They are tracked here so a future contributor can pick them up if desired; the plan's compliance harness completion in Wave 7 (T28-T30) does not require them.
- **Section 9 stays deferred** — Wave 7 T28 Part B adds `gateway_virtual` to the parametrize set and Wave 4 T19 covers the v-server composition integration test.

When T9 + T10 land, every GAP-BLOCK row in this checklist gets a "T9" or "T10" tag converted to a `tests/live_gateway/a2a_compliance/...::test_...` citation in the same file (re-audit pass at end of Wave 2). **Re-audit pass: complete; every BLOCK row above now carries a `✅ CITED (T9)` or `✅ CITED (T10)` tag with the test file + function path.**
