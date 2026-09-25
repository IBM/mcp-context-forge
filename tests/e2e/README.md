# tests/e2e/ — End-to-End Tests

End-to-end tests that exercise ContextForge across component boundaries,
often requiring running services.

## MCP Protocol and RBAC E2E

**File:** `tests/live_gateway/e2e/test_e2e.py`

Exercises the MCP protocol against a live ContextForge instance using the
official `mcp` SDK (`ClientSession` over Streamable HTTP) and Playwright API
setup for RBAC coverage — no `mcp-cli` binary or `mcpgateway.wrapper`
subprocess. No LLM provider or API key is required.

### Prerequisites

```bash
# Start ContextForge (docker-compose)
docker compose up -d          # gateway on :8080 via nginx
```

(The `mcp` package is a core dependency of the gateway.)

### Running

```bash
# Default — tests against http://localhost:8080
make test-e2e

# Override gateway URL
MCP_CLI_BASE_URL=http://localhost:4444 make test-e2e

# Run directly with pytest
pytest tests/live_gateway/e2e/test_e2e.py -v
```

`make test-mcp-cli` and `make test-mcp-rbac` are aliases for the consolidated
target. `make test-mcp-protocol-e2e` is a deprecated alias. It sunsets on
2026-12-29.

### Environment Variables

| Variable | Default | Description |
|---|---|---|
| `MCP_CLI_BASE_URL` | `http://localhost:8080` | Gateway URL (nginx proxy or direct) |
| `JWT_SECRET_KEY` | `my-test-key-but-now-longer-than-32-bytes` | JWT signing secret (must match gateway) |
| `PLATFORM_ADMIN_EMAIL` | `admin@example.com` | Admin email for JWT token |
| `MCP_CLI_TOKEN_EXPIRY` | `60` | JWT token lifetime in minutes |
| `MCP_E2E_REVOCATION_DELAY` | `1.0` | Seconds to wait for a revoke to reach every replica |

### What's Tested

16 classes across two coverage areas.

**MCP protocol (async MCP SDK)** — `TestConnectivity`, `TestTools`,
`TestDiscovery`, `TestToolCalls`, plus raw-HTTP probes (`TestRawJsonRpc`,
`TestRawHttpTransportParity`):

- Connectivity: `ping`, `initialize` fields, core-capability advertisement,
  multi-call-in-one-session.
- Tools: `tools/list` fields, gateway-prefixed name discovery, inputSchema
  validation.
- Resources / prompts: `resources/list`, `prompts/list`.
- Tool invocation: `get-system-time`, `echo`, `convert-time`, `get-stats`,
  `nonexistent-tool` (error path), plus the `outputSchema` regression guard
  and positive control for [#4202](https://github.com/IBM/mcp-context-forge/issues/4202).
- Raw-HTTP probes: invalid-method error envelope, Rust-runtime header parity
  on `initialize` + `DELETE` (skipped when the Rust transport isn't mounted).

**RBAC (Playwright `APIRequestContext` + sync MCP helpers)** —
`TestServerVisibilityViaAPI`, `TestMcpToolsVisibilityByRole`,
`TestMcpResourcesPromptsByRole`, `TestMcpToolCallByRole`,
`TestMcpScopedTokenPermissions`, `TestMcpStreamableHttpTransport`,
`TestMcpPerServerEndpoint`, `TestDenyPaths`, `TestTokenLifecycle`,
`TestCrossTransportConsistency`:

- Server visibility: REST API scoping of servers by team/public.
- Tool/resource/prompt visibility by role: admin, developer, team admin,
  outsider.
- Role-gated tool execution: which roles can call vs. only list tools.
- Scoped-token permissions: `tools.read`/`tools.execute` combinations and
  `servers.use` auto-injection.
- Streamable HTTP transport and per-server MCP endpoint routing.
- Deny paths: unauthenticated and cross-team access rejected.
- Token lifecycle: create a token, find it in the catalog, authenticate REST
  and MCP with it, revoke it, and confirm a `tools.read` scope blocks execute.
- Cross-transport consistency: same visibility/behavior across transports.

### Architecture

```
pytest
  ├── MCP SDK ClientSession (async, Streamable HTTP)
  │     └── Authorization: Bearer <jwt>
  │           └── HTTP → ContextForge gateway /mcp (MCP_CLI_BASE_URL)
  └── Playwright APIRequestContext (sync, via _run_async thread-pool)
        └── Authorization: Bearer <jwt>
              └── HTTP → ContextForge gateway /mcp, /servers, /tokens (MCP_CLI_BASE_URL)
```

No subprocess, no settle delays, no stdin-close plumbing. Async sessions are
established by the `streamablehttp_client` / `ClientSession` async context
managers; RBAC classes drive the sync Playwright API client from the same
pytest-asyncio module via a thread-pool helper (`_run_async`).
