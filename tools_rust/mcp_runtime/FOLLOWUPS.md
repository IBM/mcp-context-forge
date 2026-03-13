# Rust MCP Follow-Ups

This file tracks issues discovered while validating the Rust MCP runtime that should be investigated or resolved in a separate PR, or after the core Rust MCP work is finished.

## Recommended Scope

These items are intentionally separated from the main Rust MCP runtime work because they are either:

- broader test-suite stability issues
- admin/UI problems not specific to the Rust MCP path
- brittle test assumptions that should be cleaned up independently

## Current Follow-Ups

### 1. Playwright admin JWT login instability

Status:
- Needs investigation

Observed behavior:
- In larger Playwright file runs, the admin JWT-cookie login helper can intermittently remain on `/admin/login`.
- Gateway logs show matching `401 Invalid token` errors during some of these failures.

Why this matters:
- This affects admin/UI suite reliability.
- It is not currently proven to be a Rust MCP runtime issue.

Likely area:
- [`tests/playwright/conftest.py`](../../../tests/playwright/conftest.py)
- admin JWT cookie seeding / validation path
- admin auth middleware / login redirect handling

Recommended next step:
- Add targeted instrumentation around `_ensure_admin_logged_in(...)` and capture redirect/response traces when JWT-cookie login falls back to `/admin/login`.

### 2. Circuit breaker unit test timing flake

Status:
- Likely brittle test

Observed behavior:
- [`test_circuit_resets_after_timeout`](../../../tests/unit/mcpgateway/services/test_mcp_session_pool.py) failed in the full suite, but passed in isolation and repeated reruns.

Why this matters:
- Creates noise in `make test`.

Likely cause:
- Fixed `asyncio.sleep(...)` timing in the test versus wall-clock timing in the circuit-breaker implementation.

Recommended next step:
- Rewrite the test to poll until reset rather than relying on a fixed sleep margin.

### 3. Gateway delete Playwright assertion is too strict

Status:
- Likely brittle test

Observed behavior:
- [`test_delete_button_with_confirmation`](../../../tests/playwright/test_gateways.py) waits for a gateway row to exist after deletion.
- That fails if the deleted gateway was the last visible row.

Why this matters:
- Produces false negatives in the UI suite.

Recommended next step:
- Verify deletion by name or empty-state handling instead of requiring at least one remaining row.

### 4. Gateway edit modal file-scope instability

Status:
- Needs investigation

Observed behavior:
- [`test_edit_modal_transport_options`](../../../tests/playwright/entities/test_gateways_extended.py) can fail at file scope with the edit modal not opening, while passing in single-test isolation.

Why this matters:
- Suggests residual UI/file-state coupling.

Recommended next step:
- Reproduce on a fresh stack with focused instrumentation around modal open requests and Alpine/HTMX state changes.

### 5. Prompt/admin page file-scope login failures

Status:
- Needs investigation

Observed behavior:
- Some prompt/admin-oriented Playwright files fail at fixture setup because the admin page remains on `/admin/login`.

Why this matters:
- Same likely root as the admin JWT-cookie instability, but worth tracking explicitly because it impacts multiple UI areas.

Recommended next step:
- Treat as part of the admin login fixture investigation rather than fixing prompt-specific tests first.

### 6. `register_fast_time_sse` sync quirk

Status:
- Needs investigation

Observed behavior:
- On clean startup, `register_fast_time_sse` can still create its SSE virtual server with zero associated tools even though related tooling can later appear reachable.

Why this matters:
- Compose test ergonomics and fixture predictability.

Recommended next step:
- Inspect server sync timing and transport filtering on the SSE registration path separately from the `register_fast_time` auth/startup race that was already fixed.

## Not In Scope Here

These items are not currently believed to be blocking the main Rust MCP runtime work:

- core MCP protocol parity
- Rust MCP session isolation correctness
- Rust MCP performance benchmarking

Those are tracked in:

- [`README.md`](./README.md)
- [`STATUS.md`](./STATUS.md)
- [`TESTING-DESIGN.md`](./TESTING-DESIGN.md)
