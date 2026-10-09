# [BUG]: Gateway registration loses the failure cause in logs, and admin CA signing failures return 422

Revised version of issue #6724. Claims verified against the worktree at `fix-issue-6724`.

### 🐞 Bug Summary

Two defects, one shared root.

**1. Validation logs cannot name the failure cause.** `GatewayCreate.validate_url` calls `validate_core_url()` ([`mcpgateway/schemas.py:3387`](mcpgateway/schemas.py)). That path runs SSRF checks inside Pydantic model validation ([`mcpgateway/common/validators.py:1392`](mcpgateway/common/validators.py)), including a synchronous `socket.getaddrinfo()` call ([`validators.py:1575`](mcpgateway/common/validators.py)). Every rejection — malformed syntax, blocked destination, DNS failure — raises a plain `ValueError`. `sanitize_validation_error_for_log()` ([`mcpgateway/utils/error_formatter.py:304`](mcpgateway/utils/error_formatter.py)) records only count, `loc`, and `type`, so all three collapse to the same line. The sanitizer is correct: it must not log values. The gap is the missing non-sensitive reason code.

Measured on this worktree:

```text
fail_closed=True  (https://does-not-exist.invalid/mcp)   1 error(s): [loc=('url',) type=value_error]
blocked destination (http://169.254.169.254/latest/...)  1 error(s): [loc=('url',) type=value_error]
malformed URL       (ht!tp://bad url)                    1 error(s): [loc=('url',) type=value_error]
```

**2. The same destination policy violation maps to two statuses.** `SSRF_DNS_FAIL_CLOSED` defaults to `true` ([`mcpgateway/config.py:827`](mcpgateway/config.py)). An unresolvable host then fails model validation and returns `422`. With the flag off, the same host passes validation and fails at connect time: `connect_to_*_server` turns a URL policy `ValueError` into `GatewayConnectionError` ([`mcpgateway/services/gateway_service.py:7486`](mcpgateway/services/gateway_service.py), `:7660`, `:7830`), and both API and admin map that to `502` ([`mcpgateway/main.py:7642`](mcpgateway/main.py), [`mcpgateway/admin.py:12918`](mcpgateway/admin.py)). Operators see `422` or `502` for one cause, selected by configuration.

**3. Admin CA signing failure returns 422 instead of 500.** `admin_add_gateway()` wraps a signing failure as `RuntimeError("Failed to sign CA certificate")` ([`mcpgateway/admin.py:12844`](mcpgateway/admin.py)). The `except RuntimeError` block in the preprocessing `try` returns `422` ([`admin.py:12863`](mcpgateway/admin.py)). A second `except RuntimeError` in the same endpoint returns `500` ([`admin.py:12926`](mcpgateway/admin.py)). A server signing-key fault is not a client input fault, so `422` is wrong.

---

### 🧩 Affected Component

- [x] `mcpgateway` - API
- [x] `mcpgateway` - UI (admin panel)
- [ ] `mcpgateway.wrapper` - stdio wrapper
- [ ] Federation or Transports
- [ ] CLI, Makefiles, or shell scripts
- [ ] Container setup (Docker/Podman/Compose)
- [x] Other: validation logging and URL policy error classification

---

### 🔁 Steps to Reproduce

Log indistinguishability (no server needed):

1. Keep `SSRF_PROTECTION_ENABLED=true` and `SSRF_DNS_FAIL_CLOSED=true` (both defaults).
2. Build `GatewayCreate` with `https://does-not-exist.invalid/mcp`, then with `http://169.254.169.254/latest/meta-data`, then with `ht!tp://bad url`.
3. Pass each `ValidationError` to `sanitize_validation_error_for_log()`.
4. Observe one identical line per case: `1 error(s): [loc=('url',) type=value_error]`.

Status split:

5. `POST /gateways` with `https://does-not-exist.invalid/mcp` and transport `STREAMABLEHTTP`. Observe `422`.
6. Set `SSRF_DNS_FAIL_CLOSED=false` and repeat. Observe `502`.
7. Step 6 holds only while `GATEWAY_ASYNC_LIFECYCLE_ENABLED=false` (the default, [`config.py:3001`](mcpgateway/config.py)). With async lifecycle on, `POST /gateways` returns `202` and the failure appears in the gateway record status, not in the HTTP status.

Admin CA signing:

8. Set `ENABLE_ED25519_SIGNING=true`, supply a `ca_certificate`, and make `sign_data()` fail.
9. Observe `422` from `admin.py:12863`, while `admin.py:12926` returns `500` for runtime failures raised later in the same handler.

---

### 🤔 Expected Behavior

**Status mapping.** Most rows already hold. Only the last row is a defect.

| Failure | Status | State today |
|---|---:|---|
| Malformed request or URL syntax | `422` | correct |
| Destination blocked by URL policy (SSRF, private, loopback, DNS) | `422` | correct at model validation; `502` when the same check runs at connect time |
| DNS, TCP, TLS, timeout, or upstream MCP failure | `502` | correct |
| Duplicate gateway or name conflict | `409` | correct |
| Internal encryption, signing, or unexpected runtime failure | `500` | `422` for CA signing |

Keep `422` for destination-policy rejection. Do not return `403`. `403` already means an authorization denial on this endpoint ([`main.py:7599`](mcpgateway/main.py), `:7638`), and the repo's existing URI policy rejection uses a status plus a reason code, not `403` ([`mcpgateway/services/root_service.py:47`](mcpgateway/services/root_service.py), [`main.py:7930`](mcpgateway/main.py), [`admin.py:14394`](mcpgateway/admin.py)). Moving `422` to `403` would also change a consumer contract for every existing client.

**Reason codes.** Reuse the `RootServiceValidationError` pattern: an exception that carries a stable `reason_code`, logged by code and surfaced in the response detail. Do not parse human-readable messages. Suggested codes:

- `url_invalid_syntax`
- `url_scheme_not_allowed`
- `url_destination_blocked`
- `url_private_network_blocked`
- `url_dns_resolution_failed`
- `url_dns_no_addresses`
- `gateway_connection_failed`
- `gateway_tls_failed`
- `gateway_initialization_failed`
- `gateway_ca_signing_failed`

Target log line:

```text
Gateway registration rejected: field=body.url reason_code=url_dns_resolution_failed request_id=<correlation-id>
```

Logs must keep excluding request values, raw URLs, credentials, tokens, Pydantic `input`, and `ctx`.

**SSRF behavior must not regress.** If DNS resolution moves out of Pydantic into a service-layer preflight, keep it fail-closed and keep the DNS pinning in `_resolve_hostname_for_connection_pinning` ([`validators.py:1736`](mcpgateway/common/validators.py)) so no time-of-check/time-of-use gap opens.

**Log attribution.** `correlation_id` is already emitted on request start, completion, and failure ([`mcpgateway/middleware/request_logging_middleware.py:468`](mcpgateway/middleware/request_logging_middleware.py), `:495`, `:557`). `user_email` is emitted when identity resolution succeeds (`:455`). `team_id` is accepted by the structured logger ([`mcpgateway/services/structured_logger.py:332`](mcpgateway/services/structured_logger.py)) but no call site in `request_logging_middleware.py` ever passes it, so it is always null. Pass `team_id` from `request.state.team_id` when it is set.

---

### 📓 Logs / Error Output

Fail-closed:

```text
Request validation error on /gateways: 1 error(s): [loc=('body', 'url') type=value_error]
POST /gateways HTTP/1.1 422
```

Fail-open, same hostname:

```text
connect_tcp.failed exception=ConnectError(gaierror(8, 'nodename nor servname provided, or not known'))
Gateway initialization failed: [Errno 8] nodename nor servname provided, or not known
POST /gateways HTTP/1.1 502
```

Admin CA signing:

```text
RuntimeError: Failed to sign CA certificate
HTTP 422
```

⚠️ **Do not paste secrets, credentials, or tokens.**

---

### 🧠 Environment Info

| Key | Value |
|-----|-------|
| Version or commit | worktree `fix-issue-6724` |
| Runtime | Python 3.12, Uvicorn |
| Platform / OS | Kubernetes deployment and macOS local reproduction |
| Container | Kubernetes for fail-closed reproduction; none for local reproduction |

---

### 🧩 Additional Context

Relevant code:

- `mcpgateway/schemas.py::GatewayCreate.validate_url` (`:3387`)
- `mcpgateway/common/validators.py::SecurityValidator.validate_url` (`:1074`)
- `mcpgateway/common/validators.py::SecurityValidator._validate_ssrf` (`:1506`)
- `mcpgateway/utils/error_formatter.py::sanitize_validation_error_for_log` (`:304`)
- `mcpgateway/main.py::request_validation_exception_handler` (`:2457`)
- `mcpgateway/main.py::register_gateway` (`:7563`)
- `mcpgateway/admin.py::admin_add_gateway` (`:12763`)
- `mcpgateway/services/root_service.py::RootServiceValidationError` (`:47`) — the reason-code pattern to copy

Tests:

- `tests/unit/mcpgateway/test_admin.py::test_admin_add_gateway_ca_certificate_signing_failure` asserts `422` at line 7478. Change it to `500`.
- Add deny-path coverage for malformed URL, blocked destination, DNS failure, DNS no-addresses, private and loopback destination, connect failure, and signing failure.
- Assert the reason code and correlation ID appear in logs, and that no raw URL, input value, or credential appears.

---

### Corrections applied to the original report

1. **Removed the WXO bearer-token logging claim.** No `Validating authentication header` string exists in this repo. Plugins moved to external `cpex-*` packages (CHANGELOG, PR #3965). File that against the plugin repo.
2. **Replaced `403` for SSRF rejection with `422` plus a reason code.** `403` is already the authorization denial on this endpoint, and the repo's existing URI policy rejection carries a `reason_code` instead. Changing `422` to `403` breaks the current consumer contract.
3. **Corrected the log-attribution claim.** `correlation_id` is already emitted. `user_email` is emitted when identity resolves. Only `team_id` is never passed.
4. **Dropped the "Request cancelled: client disconnected" item.** It is a `logger.debug` in [`mcpgateway/middleware/client_disconnect.py:189`](mcpgateway/middleware/client_disconnect.py), emitted when the disconnect event is set. It is expected disconnect detection, not an error.
5. **Narrowed the title and summary.** One status is wrong (`422` for CA signing). The `422`-versus-`502` split is a classification inconsistency, not a wrong status: both are defensible for their own call site.
6. **Marked the already-correct rows** in the expected-status table, so the fix scope is the two real defects.
7. **Added the async lifecycle caveat** to reproduction step 7. The `502` observation depends on `GATEWAY_ASYNC_LIFECYCLE_ENABLED=false`.
