# A2A protocol compliance harness

Black-box A2A protocol tests driven by the official `a2a-sdk` client
(with raw `httpx` where wire-level precision matters). The same test
bodies run against multiple **targets** — `reference` (direct to the
bundled `a2a_echo_agent`), `gateway_proxy`, `gateway_virtual` — so
behavioral drift surfaces as a concrete test failure rather than a
manual log diff.

Mirrors `tests/live_gateway/protocol_compliance/` (the MCP harness) in
shape and gap-tracking discipline. Per-version test bodies live under
`v<X>_<Y>_<Z>/`. Phase 1 covers **A2A 1.0.0** only; the v0.3.0 overlay
arrives in Phase 2.

## Run

```bash
make test-protocol-compliance-a2a            # full matrix
make test-protocol-compliance-a2a-v1-0-0     # A2A 1.0.0 only
make test-protocol-compliance-a2a-reference  # reference target across all versions
```

Direct pytest invocation:

```bash
uv run pytest tests/live_gateway/a2a_compliance -v --tb=short
```

## Setup preconditions

The harness drives a live `a2a_echo_agent` process. Defaults match the
docker-compose `testing` profile (`make testing-up`):

| Env var | Default | Purpose |
|---------|---------|---------|
| `A2A_ECHO_BASE_URL` | `http://127.0.0.1:9100` | Echo agent URL. Use 127.0.0.1, not localhost — the project's autouse DNS stub falls through to the real resolver, which can return IPv6 first; the compose port-forward binds IPv4. |
| `A2A_ECHO_PROTOCOL_VERSION` | `1.0.0` | What the echo agent advertises in its card. Set to `0.3.0` for legacy-overlay tests (Phase 2). |

The agent is brought up by:

```bash
make testing-up
```

which starts the compose `testing` profile (gateway + nginx + echo
agent on port 9100). Confirm with:

```bash
docker compose ps a2a_echo_agent
curl http://127.0.0.1:9100/health
```

## Known compliance gaps

Tracked in [`COMPLIANCE_GAPS.md`](./COMPLIANCE_GAPS.md). One entry per
gap (ID, affected targets, tests, spec section, observed vs. expected,
remediation). Gaps are wired into the affected tests via
`xfail_on(request, ...)` so pytest reports `XFAIL` rather than `FAIL`;
a fix surfaces as `XPASS` and signals the gap is closing on that cell.

**A2A-GAP-001** currently xfails the entire `gateway_proxy` and
`gateway_virtual` columns — ContextForge does not yet expose a native
A2A passthrough endpoint. The reference column is the only live
column today.

## Layout

```
conftest.py              Parametrized (target, transport) -> connected Client fixture
COMPLIANCE_GAPS.md       A2A-GAP-NNN tracker
targets/
  base.py                A2AComplianceTarget ABC + Transport literal
  reference.py           A2AReferenceTarget (direct to a2a_echo_agent)
  gateway_proxy.py       Placeholder (A2A-GAP-001)
  gateway_virtual.py     Placeholder (A2A-GAP-001)
fixtures/
  echo_agent.py          Live-agent reachability probe + base URL + card URL
helpers/
  compliance.py          current_target + xfail_on (gap tracking)
  drift.py               Cross-target normalization stubs
v1_0_0/
  test_agent_card.py
  test_well_known.py
  test_jsonrpc_methods.py
  test_error_handling.py
  test_messages_artifacts.py
  test_security.py
  test_version_negotiation.py
```

## Adding a target

1. Subclass `A2AComplianceTarget` in `targets/<name>.py`. Set `name`
   and `supported_transports` (a non-empty `frozenset[Transport]`).
2. Implement `_open_client(transport, **kwargs)` as an
   `asynccontextmanager` yielding a connected `a2a.client.Client`.
3. Register the target in `conftest.py`'s `_CASES` list. The
   parametrize matrix will pick it up automatically.

## Adding a version

1. Create `v<X>_<Y>_<Z>/` mirroring the `v1_0_0/` layout.
2. If the SDK's `ClientFactory` doesn't auto-negotiate the version
   (today it routes via `is_legacy_version` for v0.3.x), set
   `A2A_ECHO_PROTOCOL_VERSION` in a session-scoped fixture so the
   echo agent advertises the right card.
3. Add per-version Makefile targets following the existing naming.
