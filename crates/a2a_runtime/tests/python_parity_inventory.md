# Python-to-Rust A2A Test Parity Inventory

## What This File Records

This file is the branch-local record of the Python-to-Rust A2A parity pass.

It documents:

- which Python A2A test suites were reviewed
- which runtime-visible behaviors were already covered in `crates/a2a_runtime`
- which missing runtime-visible behaviors were ported into Rust tests
- which Python tests were intentionally left in Python because they exercise Python-owned request builders, DB services, or gateway internals

This is meant to answer "what happened?" without having to reconstruct the work from diffs or commit history.

This inventory reviews the Python A2A tests in:

- `tests/unit/mcpgateway/services/test_a2a_protocol.py`
- `tests/unit/mcpgateway/test_internal_a2a_endpoints.py`
- `tests/unit/mcpgateway/services/test_a2a_service.py`
- `tests/unit/mcpgateway/services/test_rust_a2a_runtime.py`

Buckets:

- `already covered in Rust`
- `ported to Rust unit test`
- `ported to Rust integration test`
- `non-portable Python-only implementation detail`

## Summary Of What Happened

The parity pass focused on the Rust runtime boundary, not raw test-count parity.

What was added to Rust:

- request-resolution tests in `src/http.rs` for metadata preservation and non-overriding correlation/tracing headers
- `/invoke` integration coverage for decrypted auth header forwarding, decrypted auth query-param forwarding, and correlation/trace header forwarding
- A2A task route coverage for missing-field `400`, not-found `404`, and resolve-before-proxy short-circuit behavior
- A2A push-config route coverage for missing-field `400`, invalid-schema `400`, not-found `404`, and resolve-before-proxy short-circuit behavior
- config/auth/trust/queue unit coverage for Rust-owned fail-closed branches
- proxy and webhook tests for header-stripping and no-auth-token webhook behavior
- health and authenticated-card happy-path coverage for crate-emitted/public runtime responses

What stayed in Python:

- Python request-builder normalization and wire-shape helpers
- Python DB-backed visibility, ownership, rollback, invalidation, and CRUD service internals
- Python runtime-client singleton/URL/transport wrapper behavior that does not belong to the Rust crate itself

## Verification Used

The Rust parity work was verified with:

- `cargo test -p contextforge_a2a_runtime --test integration`
- `cargo test -p contextforge_a2a_runtime`
- `cargo fmt --check --all`

One repo-level limitation remains outside this specific parity work:

- `cargo clippy -p contextforge_a2a_runtime --all-targets -- -D warnings`
- currently fails on pre-existing `clippy::multiple_crate_versions` dependency-graph noise, not on these parity additions

## `test_a2a_protocol.py`

| Python group | Bucket | Rust location | Notes |
| --- | --- | --- | --- |
| `TestIsV1A2AProtocol` | non-portable Python-only implementation detail | n/a | Python request-builder protocol parsing. No equivalent runtime helper in `crates/a2a_runtime`. |
| `TestNormalizeA2AVersionHeader` | non-portable Python-only implementation detail | n/a | Python-side wire-shape normalization before the runtime is called. |
| `TestIsJsonrpcA2AAgent` | non-portable Python-only implementation detail | n/a | Python agent-selection heuristic. |
| `TestNormalizeA2AMethod` | non-portable Python-only implementation detail | n/a | Python request-construction logic. Rust receives already-shaped JSON-RPC bodies. |
| `TestNormalizeRole` / `TestNormalizePart` / `TestNormalizeTaskState` / `TestNormalizeTaskStatus` / `TestNormalizeMessage` / `TestNormalizeTask` / `TestNormalizeA2AParams` | non-portable Python-only implementation detail | n/a | Python payload normalization helpers with no Rust runtime analogue. |
| `TestBuildDefaultMessage` / `TestBuildA2AJsonrpcRequest` | non-portable Python-only implementation detail | n/a | Python-side request assembly only. |
| `test_prepare_a2a_invocation_*` auth/header/query-param/base-header/encrypted-field contract | already covered in Rust | `src/http.rs`, `tests/integration.rs` | Runtime-visible contract is covered by `resolve_requests_*`, `correlation_*`, `content_type_*`, `test_invoke_with_encrypted_auth_rejects_when_no_secret`, `test_invoke_applies_decrypted_auth_header_to_upstream`, `test_invoke_applies_decrypted_auth_query_param_to_upstream`, and `test_invoke_forwards_correlation_and_trace_headers`. |
| `test_prepare_a2a_invocation_*` protocol-version/method/message-shape builder behavior | non-portable Python-only implementation detail | n/a | Python owns the request builder and version/method translation layer. |

## `test_internal_a2a_endpoints.py`

| Python group | Bucket | Rust location | Notes |
| --- | --- | --- | --- |
| `TestUntrustedRequestsReturn403` | non-portable Python-only implementation detail | n/a | Tests Python `/_internal/a2a/*` trust gate, not public Rust runtime routes. |
| `TestInternalA2AAuthzTrusted` | already covered in Rust | `tests/integration.rs` | Covered by `test_a2a_invoke_authz_denied` and the happy-path method routing tests. |
| `TestInternalA2AScopeContext` | non-portable Python-only implementation detail | n/a | Python DB/token-scope helper behavior. |
| `TestTasksGetTrusted.test_returns_task` | already covered in Rust | `tests/integration.rs` | Covered by `test_a2a_invoke_get_task_routes_to_python`. |
| `TestTasksGetTrusted.test_task_not_found_returns_404` | ported to Rust integration test | `tests/integration.rs` | `test_a2a_invoke_get_task_not_found_returns_error_envelope` |
| `TestTasksGetTrusted.test_missing_task_id_returns_400` | ported to Rust integration test | `tests/integration.rs` | `test_a2a_invoke_get_task_missing_task_id_returns_error_envelope` |
| `TestTasksGetTrusted.test_invalid_agent_id_returns_400` | non-portable Python-only implementation detail | n/a | Rust overrides `agent_id` from URL-path resolution; it does not trust client `agent_id`. |
| `TestTasksListTrusted.test_returns_tasks` | already covered in Rust | `tests/integration.rs` | `test_a2a_invoke_list_tasks_routes_to_python` |
| `TestTasksListTrusted.test_invalid_agent_id_returns_400` | non-portable Python-only implementation detail | n/a | Same reason as task get: Rust overwrites `agent_id`. |
| `TestTasksListTrusted.test_invalid_state_returns_400` | ported to Rust integration test | `tests/integration.rs` | `test_a2a_invoke_list_tasks_invalid_state_returns_error_envelope` |
| `TestTasksCancelTrusted.test_cancels_task` | already covered in Rust | `tests/integration.rs` | Covered by `test_a2a_invoke_cancel_task_routes_to_python`. |
| `TestTasksCancelTrusted.test_task_not_found_returns_404` | ported to Rust integration test | `tests/integration.rs` | `test_a2a_invoke_cancel_task_not_found_returns_error_envelope` |
| `TestTasksCancelTrusted.test_missing_task_id_returns_400` | ported to Rust integration test | `tests/integration.rs` | `test_a2a_invoke_cancel_task_missing_task_id_returns_error_envelope` |
| `TestTasksCancelTrusted.test_scope_context_passed_through` | non-portable Python-only implementation detail | n/a | Python service call kwargs, not public Rust runtime output. |
| `TestTasksCancelTrusted.test_invalid_agent_id_returns_400` | non-portable Python-only implementation detail | n/a | Rust ignores caller-supplied `agent_id`. |
| `TestPushCreateTrusted.test_creates_config` / `TestPushGetTrusted.test_returns_config` / `TestPushListTrusted.test_returns_configs` / `TestPushDeleteTrusted.test_deletes_config` | already covered in Rust | `tests/integration.rs` | Existing route tests cover create/get/list/delete success paths. |
| `TestPushCreateTrusted.test_missing_required_fields_returns_400` | ported to Rust integration test | `tests/integration.rs` | `test_a2a_invoke_create_push_config_missing_required_fields_returns_error_envelope` |
| `TestPushCreateTrusted.test_invalid_schema_returns_400` | ported to Rust integration test | `tests/integration.rs` | `test_a2a_invoke_create_push_config_invalid_schema_returns_error_envelope` |
| `TestPushCreateTrusted.test_hidden_agent_returns_404` | ported to Rust integration test | `tests/integration.rs` | `test_a2a_invoke_create_push_config_agent_not_found_short_circuits_before_proxy` pins the pre-proxy 404 behavior. |
| `TestPushGetTrusted.test_config_not_found_returns_404` / `.test_hidden_config_returns_404` | ported to Rust integration test | `tests/integration.rs` | `test_a2a_invoke_get_push_config_not_found_returns_error_envelope` covers the runtime-visible 404 envelope shape. |
| `TestPushGetTrusted.test_missing_task_id_returns_400` | ported to Rust integration test | `tests/integration.rs` | `test_a2a_invoke_get_push_config_missing_task_id_returns_error_envelope` |
| `TestPushListTrusted.test_forwards_scope_context_to_service` | non-portable Python-only implementation detail | n/a | Python internal service wiring only. |
| `TestPushDeleteTrusted.test_config_not_found_returns_404` / `.test_hidden_config_returns_404` | ported to Rust integration test | `tests/integration.rs` | `test_a2a_invoke_delete_push_config_not_found_returns_error_envelope` covers the runtime-visible 404 envelope shape. |
| `TestPushDeleteTrusted.test_missing_config_id_returns_400` | ported to Rust integration test | `tests/integration.rs` | `test_a2a_invoke_delete_push_config_missing_config_id_returns_error_envelope` |
| `TestEventsFlushTrusted` / `TestEventsReplayTrusted` | non-portable Python-only implementation detail | n/a | Python internal maintenance endpoints. Rust exposes replay through streaming/event-store behavior instead. |
| `TestAgentResolveTrusted` / `TestAgentCardTrusted` | already covered in Rust | `tests/integration.rs` | Existing resolve/card routing and error-envelope tests cover runtime-visible behavior. |
| `TestInternalA2AExceptionHandling` | non-portable Python-only implementation detail | n/a | Python DB rollback/invalidate behavior. |
| `TestInternalA2ADenyPaths` | mixed | `tests/integration.rs` / n/a | Runtime-visible authz deny is already covered; wrong-team and feature-flag internals remain Python-only. |

## `test_a2a_service.py`

| Python group | Bucket | Rust location | Notes |
| --- | --- | --- | --- |
| Agent registry CRUD, visibility, team ownership, masking, caching, invalidation, SQL visibility helpers | non-portable Python-only implementation detail | n/a | Python DB/service logic. |
| `invoke_agent` success/error/custom headers/basic auth/bearer auth/query-param auth/correlation-id/runtime delegation | already covered in Rust | `src/http.rs`, `src/invoke.rs`, `tests/integration.rs` | Runtime boundary covered by invoke unit tests and `/invoke` integration tests. |
| `invoke_agent` Python-side request builder details | non-portable Python-only implementation detail | n/a | Owned by Python `a2a_protocol` and service wrappers, not Rust runtime. |
| Task CRUD groups (`TestCancelTask`, `TestGetTask`, `TestListTasks`) | already covered in Rust or ported to Rust integration test | `tests/integration.rs` | Public method routing plus new 400-envelope tests cover runtime-visible task behavior. |
| Push config CRUD groups (`TestPushConfigCRUD`) | already covered in Rust or ported to Rust integration test | `tests/integration.rs` | Success and validation/error envelopes now covered at runtime boundary. |
| Event flush/replay persistence and Redis invalidation publish helpers | non-portable Python-only implementation detail | n/a | Internal Python services and storage semantics. |
| Shadow mode comparison | non-portable Python-only implementation detail | n/a | Python delegation policy. |

## `test_rust_a2a_runtime.py`

| Python group | Bucket | Rust location | Notes |
| --- | --- | --- | --- |
| `TestBuildRuntimeInvokeUrl` | non-portable Python-only implementation detail | n/a | Python client URL construction. |
| `TestGetRustA2ARuntimeClient` | non-portable Python-only implementation detail | n/a | Python singleton/client caching. |
| `TestRustA2ARuntimeClient.test_invoke_success` / timeout / connect / protocol / invalid JSON / encrypted auth / base endpoint behavior | already covered in Rust | `src/invoke.rs`, `tests/integration.rs` | Runtime behavior is covered in the crate at the service boundary. |
| `TestRustA2ARuntimeClient.test_get_runtime_client_returns_shared_http_client_when_no_uds` / `.test_get_runtime_client_creates_uds_client` | non-portable Python-only implementation detail | n/a | Python client transport selection. |
| `TestRustA2ARuntimeClient.test_proxy_timeout_is_at_least_request_timeout_plus_five` | non-portable Python-only implementation detail | n/a | Python runtime-client timeout padding policy. |

## Newly ported in this change

- `test_a2a_invoke_get_task_missing_task_id_returns_error_envelope`
- `test_a2a_invoke_get_task_not_found_returns_error_envelope`
- `test_a2a_invoke_get_task_agent_not_found_short_circuits_before_proxy`
- `test_a2a_invoke_list_tasks_invalid_state_returns_error_envelope`
- `test_a2a_invoke_cancel_task_missing_task_id_returns_error_envelope`
- `test_a2a_invoke_cancel_task_not_found_returns_error_envelope`
- `test_a2a_invoke_create_push_config_missing_required_fields_returns_error_envelope`
- `test_a2a_invoke_create_push_config_invalid_schema_returns_error_envelope`
- `test_a2a_invoke_create_push_config_agent_not_found_short_circuits_before_proxy`
- `test_a2a_invoke_get_push_config_missing_task_id_returns_error_envelope`
- `test_a2a_invoke_get_push_config_not_found_returns_error_envelope`
- `test_a2a_invoke_delete_push_config_missing_config_id_returns_error_envelope`
- `test_a2a_invoke_delete_push_config_not_found_returns_error_envelope`
- `test_invoke_applies_decrypted_auth_query_param_to_upstream`
- `test_invoke_forwards_correlation_and_trace_headers`
- `test_invoke_rejects_malformed_encrypted_auth_header_without_upstream_call`
- `test_invoke_rejects_malformed_encrypted_auth_query_params_without_upstream_call`
- `health_and_healthz_return_full_schema_with_uds`
- `test_a2a_invoke_get_authenticated_card_routes_successfully`
- `correlation_headers_do_not_override_existing_values`
- `resolve_requests_preserves_request_metadata_fields`
- `validate_cross_field_rejects_zero_agent_cache_entries`
- `validate_cross_field_rejects_zero_circuit_failure_threshold`
- `decrypt_rejects_non_utf8_plaintext`
- `decrypt_rejects_non_json_plaintext`
- `decode_auth_context_rejects_non_json_payload`
- `authenticate_rejects_malformed_json_response`
- `authorize_rejects_unexpected_status`
- `try_submit_batch_rejects_when_queue_not_initialized`
- `dispatch_webhooks_sends_matching_webhook_without_authorization_when_token_is_null`
- `proxy_to_backend_strips_smuggling_headers_on_request_and_response`

## Coverage By Category Added In Follow-On Pass

- happy-path
  - `/health` and `/healthz` full schema with UDS
  - `agent/getAuthenticatedExtendedCard` success routing
  - webhook dispatch with `auth_token: null`
- non-happy-path
  - malformed encrypted auth blobs fail closed before upstream traffic
  - config cross-field zero-value rejects
  - trust parsing and malformed backend JSON rejects
  - queue submission before initialization rejects
- security
  - proxy strips hop-by-hop and smuggling headers
  - malformed encrypted auth is `400`, not upstream traffic or hidden `5xx`
  - auth-context decode rejects non-JSON payloads

## Remaining Gap

The previous session-replay gap is now closed:

- replayed `x-a2a-session-id` with a changed fingerprint now has direct
  integration coverage and asserts old-session invalidation plus fresh
  authentication
