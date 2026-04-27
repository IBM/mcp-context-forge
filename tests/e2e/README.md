# tests/e2e/ — End-to-End Tests

End-to-end tests that exercise ContextForge across component boundaries,
often requiring running services.

## MCP Protocol E2E (FastMCP client)

**File:** `test_mcp_protocol_e2e.py`

Exercises the MCP protocol against a live ContextForge instance using the
`fastmcp.client.Client` — no `mcp-cli` binary, no `mcpgateway.wrapper`
subprocess. All tests are async and run in-pytest. No LLM provider or API key
is required.

### Prerequisites

```bash
# Start ContextForge (docker-compose)
docker compose up -d          # gateway on :8080 via nginx
```

(The `fastmcp` package is already installed via the dev dependency group.)

### Running

```bash
# Default — tests against http://localhost:8080
make test-mcp-protocol-e2e

# Override gateway URL
MCP_CLI_BASE_URL=http://localhost:4444 make test-mcp-protocol-e2e

# Run directly with pytest
pytest tests/e2e/test_mcp_protocol_e2e.py -v
```

The legacy `make test-mcp-cli` target is retained as a deprecation alias and
invokes the new target.

### Environment Variables

| Variable | Default | Description |
|---|---|---|
| `MCP_CLI_BASE_URL` | `http://localhost:8080` | Gateway URL (nginx proxy or direct) |
| `JWT_SECRET_KEY` | `my-test-key-but-now-longer-than-32-bytes` | JWT signing secret (must match gateway) |
| `PLATFORM_ADMIN_EMAIL` | `admin@example.com` | Admin email for JWT token |
| `MCP_CLI_TOKEN_EXPIRY` | `60` | JWT token lifetime in minutes |

### What's Tested

Organized into five classes — `TestConnectivity`, `TestTools`, `TestDiscovery`,
`TestToolCalls`, plus raw-HTTP probes (`TestRawJsonRpc`,
`TestRawHttpTransportParity`). Coverage includes:

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

### Architecture

```
pytest
  └── FastMCP Client (async)
        └── Authorization: Bearer <jwt>
              └── HTTP → ContextForge gateway /mcp (MCP_CLI_BASE_URL)
```

No subprocess, no settle delays, no stdin-close plumbing. Sessions are
established by the Client's `__aenter__` and torn down on `__aexit__`.
