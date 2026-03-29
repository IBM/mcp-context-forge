# Nginx `/mcp` Fronting Regression in Python Runtime

## Summary

The Python MCP transport was not the thing that broke.

The regression was in the nginx `/mcp` front-door routing logic after the
dynamic backend change in commit `c1734f1bb` (`feat: complete rust observability parity`).

That change made nginx prefer the Rust public MCP listener on `gateway:8787`
for `/mcp`, with a fallback to the Python transport on `gateway:4444`.

That overall idea is valid, but the fallback implementation became unsafe for
POST requests because it combined:

- `proxy_pass $mcp_transport_backend_url` where the primary backend is `http://gateway:8787`
- `error_page 502 503 504 = @mcp_transport_fallback`
- `proxy_request_buffering off`

In Python runtime mode, nothing is listening on `:8787`, so nginx must fall back
to `:4444`. With request buffering disabled, nginx does not reliably have the
full POST body available to replay to the fallback upstream. The result was
intermittent hangs and timeouts on `/mcp` POSTs.

## Expected Runtime Model

This is the intended model:

- Python mode:
  - app/API/MCP transport served by Python on `:4444`
  - no public Rust MCP listener on `:8787`
- Rust edge/full mode:
  - app/API still exists on `:4444`
  - public MCP transport is exposed by Rust on `:8787`
  - nginx fronts `/mcp` to `:8787`

The Rust listener behavior is visible in [docker-entrypoint.sh](../docker-entrypoint.sh):

- `MCP_RUST_LISTEN_HTTP` defaults to `127.0.0.1:8787`
- `MCP_RUST_PUBLIC_LISTEN_HTTP` is set to `0.0.0.0:8787` only when the managed Rust runtime is enabled for the public transport path

So yes: in plain Python mode, there should be nothing listening on `gateway:8787`.

## What Changed

Before `c1734f1bb`, nginx used an upstream block with a backup server model for
the MCP transport path:

- primary: `gateway:8787`
- backup: `gateway:4444`

After `c1734f1bb`, nginx switched to resolver-backed variables:

- [infra/nginx/nginx.conf](../infra/nginx/nginx.conf)
  - `$mcp_transport_backend_url` -> `http://gateway:8787`
  - `$mcp_transport_fallback_url` -> `http://gateway:4444`
- `/mcp` now uses a named fallback location with `error_page 502 503 504 = @mcp_transport_fallback`

That change was made for a good reason: Docker DNS re-resolution across gateway
container churn. The problem was not the dynamic URL approach itself. The problem
was the interaction with unbuffered POST request bodies.

## Symptoms

Observed on a Python runtime stack (`/health` reported `x-contextforge-mcp-runtime-mode: python`
and `x-contextforge-mcp-transport-mounted: python`):

- `make test-mcp-cli` failed
- `make test-mcp-rbac` failed or became flaky
- `mcp-cli ping` hung
- async `httpx` POSTs to `http://localhost:8080/mcp/` intermittently timed out
- direct async POSTs to individual gateway replicas on `:4444` were stable
- repeated `curl` requests to `/mcp/` often succeeded, which made the issue look
  misleadingly intermittent

Gateway logs showed secondary fallout such as:

- `starlette.requests.ClientDisconnect`
- `mcp.server.streamable_http_manager - ERROR - Stateless session crashed`
- `anyio.ClosedResourceError`

Those were consequences of the client timing out/disconnecting, not the root cause.

## Root Cause

The root cause was:

1. nginx tried `gateway:8787` first for `/mcp`
2. in Python mode, `:8787` was not listening
3. nginx attempted fallback to `gateway:4444`
4. `proxy_request_buffering off` meant nginx did not reliably retain the POST body
   for replay to the fallback location
5. some requests stalled or timed out instead of reaching Python cleanly

This was especially visible with async MCP clients and stdio-wrapper-driven flows,
which is why `mcp-cli` and the RBAC transport tests exposed it.

## Fix Applied

The narrow fix was in [infra/nginx/nginx.conf](../infra/nginx/nginx.conf):

- keep `proxy_buffering off`
  - response streaming behavior still matters for SSE/streamable HTTP
- change `proxy_request_buffering` to `on` for:
  - the `/mcp` location
  - the named fallback location

This preserves streaming responses while allowing nginx to replay POST request
bodies safely when it has to fall back from `:8787` to `:4444`.

## Why This Fix Makes Sense

The actual failure mode was not "nginx should never front `/mcp` with Rust".

The failure mode was:

- "nginx fronted `/mcp` with Rust"
- "the Rust listener was absent"
- "fallback existed"
- "POST body replay to fallback was unreliable because request buffering was disabled"

So the fix was intentionally minimal:

- do not change Python MCP code
- do not remove the Rust-first idea
- do not collapse everything back to a single backend
- only make fallback replay safe

## Validation

After the nginx change:

- repeated async `POST http://127.0.0.1:8080/mcp/` initialize probes became stable
- direct replica probes on `:4444` remained stable
- `make test-mcp-cli` passed: `22 passed, 1 skipped`
- `make test-mcp-rbac` passed: `40 passed`
- `uv run pytest tests/unit/mcpgateway/test_wrapper.py -q` passed

This strongly indicates the regression was in nginx’s `/mcp` routing/fallback behavior,
not in the Python MCP transport implementation.

## Long-Term Improvement

The current design still has an architectural smell:

- nginx always tries `:8787` first for `/mcp`
- that is correct only when the Rust public MCP transport is actually mounted
- in Python mode, nginx already knows from the application health surface that
  the MCP transport is Python-backed

The cleaner long-term design is:

1. Make nginx route `/mcp` conditionally based on active runtime mode.
2. In Python mode, send `/mcp` directly to `:4444`.
3. In Rust edge/full mode, send `/mcp` to `:8787`.
4. Keep fallback only for genuine transient failure, not as the normal Python-mode path.

There are a few possible ways to do that:

- Generate the nginx config differently for Python vs Rust mode at container startup.
- Template only the MCP backend URL at startup based on runtime env.
- Introduce an explicit env contract for nginx, for example "public MCP transport backend is `:4444` or `:8787`".

This would be better than "always probe `:8787` first" because:

- Python mode would stop paying a failed-upstream penalty on every `/mcp` call
- fallback would no longer be part of the steady-state Python path
- the config would more accurately reflect the active transport mount
- behavior would be easier to reason about during incidents

## Recommendation

Short term:

- keep the current fix in place
- it is narrow, correct, and validated

Long term:

- make nginx’s `/mcp` upstream explicitly runtime-aware instead of implicitly
  Rust-first with Python fallback

That would preserve the Rust front-door design while eliminating an unnecessary
failure mode in plain Python deployments.
