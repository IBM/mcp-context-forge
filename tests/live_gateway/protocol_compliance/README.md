# Protocol compliance harness

Black-box MCP protocol tests driven by the FastMCP `Client`. The same test
bodies run against multiple **targets** (reference server, gateway proxy,
gateway virtual server) and multiple **transports** (stdio, SSE, Streamable
HTTP) so behavioral drift across them surfaces as a concrete test failure
rather than a manual log diff.

## Run

```bash
make test-protocol-compliance           # full matrix (phase-dependent)
pytest tests/protocol_compliance -v     # direct invocation
```

## Current coverage (Phase 4a, live-gateway)

| Target | stdio | SSE | HTTP |
|--------|:-----:|:---:|:----:|
| `ReferenceTarget` | ✅ | ⏳ | ⏳ |
| `GatewayProxyTarget` | n/a | ⏳ | ✅ (with documented gaps) |
| `GatewayVirtualServerTarget` | n/a | ⏳ | ✅ (with documented gaps) |

**Steady-state run**: 36 passed, 8 failed, 28 skipped. The 8 failures are
real gateway-compliance gaps the harness exists to surface; per Phase 4c
policy, they stay loud and the gateway-target Make target is non-required.

### Setup preconditions (live gateway)

The harness runs against a live ContextForge gateway. Defaults match the
``docker-compose`` setup, with these env-var overrides supported:

| Env var | Default | Purpose |
|---------|---------|---------|
| `MCP_CLI_BASE_URL` | `http://127.0.0.1:8080` | Gateway URL. **Use 127.0.0.1, not localhost** — the project's autouse DNS stub falls through to the real resolver, which returns IPv6 first; docker-compose binds IPv4 only. |
| `JWT_SECRET_KEY` | `my-test-key-but-now-longer-than-32-bytes` | Must match the gateway's signing secret. |
| `PLATFORM_ADMIN_EMAIL` | `admin@example.com` | Bootstrap admin user the harness mints JWT for. |
| `MCP_REFERENCE_UPSTREAM_HOST` | `host.docker.internal` | Hostname the dockerized gateway uses to reach the reference server running on the host. Linux users override (e.g. `172.17.0.1`). |

**Gateway config**: the bundled ``docker-compose.yml`` already defaults
``SSRF_ALLOW_LOCALHOST=true`` and ``SSRF_ALLOW_PRIVATE_NETWORKS=true``
(lines 250–251) which is what the harness needs to register the
``host.docker.internal`` reference-server URL. No extra setup required.
If your environment overrides those vars to ``false``, the harness will
skip gateway-target rows with the SSRF reason.

### Known gateway-compliance gaps

Tracked in [`COMPLIANCE_GAPS.md`](./COMPLIANCE_GAPS.md) with one entry
per gap (ID, affected targets, tests, spec section, observed vs.
expected, remediation). The gaps themselves are wired into the affected
tests via `xfail_on(...)` so pytest reports `XFAIL` rather than
`FAILED` — the XPASS sidecar (see `conftest.pytest_runtest_logreport`)
catches any that start passing so closures get noticed even when nobody
is reading the gap file. When a gap closes, remove the `xfail_on` line
and move the entry to the "Closed gaps" section at the bottom of that
file.

## Scope boundary: Authorization

This harness covers:

| Surface | Where tested |
|---|---|
| Bearer accepted on `/mcp/` | `test_mcp_protocol_e2e.py` (live) |
| Missing/malformed bearer rejected (401 + WWW-Authenticate) | `test_security_best_practices.py`, `test_oauth_authorization.py` |
| RFC 9728 Protected Resource Metadata endpoint routed | `test_oauth_authorization.py` (tier 1) |
| OAuth 2.1 `client_credentials` grant round-trip via Keycloak | `test_oauth_authorization.py` (tier 2 — needs Keycloak) |
| JWT-signature validation (tampered tokens rejected) | `test_oauth_authorization.py` (tier 2) |
| OAuth 2.1 code+PKCE flow, DCR, introspection, full PRM payload | `tests/compliance/mcp_2025_11_25/authorization/` (separate suite) |
| Token scoping and RBAC for admin routes | `tests/live_gateway/mcp/test_mcp_rbac_transport.py` |

### Starting Keycloak for tier 2 tests

```bash
docker compose --profile sso up -d keycloak
# Keycloak: http://localhost:8180   realm: mcp-gateway   client: mcp-gateway
```

Tier-2 tests skip with a readable reason if Keycloak isn't reachable.
Override via ``KEYCLOAK_BASE_URL``, ``KEYCLOAK_REALM``,
``KEYCLOAK_CLIENT_ID``, ``KEYCLOAK_CLIENT_SECRET`` env vars.

## Layout

```
targets/
  base.py                ComplianceTarget ABC + Transport literal
  reference.py           ReferenceTarget (stdio via in-process Client(mcp))
conftest.py              Parametrized (target, transport) -> connected Client fixture
test_lifecycle.py        initialize / ping
test_tools.py            tools/list, tools/call (incl. error path)
test_resources.py        resources/list, resources/read, templates
test_prompts.py          prompts/list, prompts/get with arguments
```

## Adding a target

1. Subclass `ComplianceTarget` in `targets/<name>.py`.
2. Populate `name`, `supported_transports`, and implement `client(transport)`.
3. Append an instance to `TARGETS` in `conftest.py`.

The existing tests will automatically parametrize over the new target for
every transport it declares supported.
