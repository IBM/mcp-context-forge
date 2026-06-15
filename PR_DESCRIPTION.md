# Exempt the trusted-internal dispatch from edge middleware

Stacked on top of #5212 (`fix/session-affinity-auth-context`). Open this PR against that branch so the diff shows only the work below.

## Summary

The session-affinity and Rust runtime paths re-enter the gateway through an in-process / loopback dispatch to `/_internal/mcp/rpc` (and `/_internal/a2a/*`). Because that dispatch goes back through the ASGI stack, the edge middleware that already ran for the originating request runs a second time on the internal hop: token scoping, rate limiting, token-usage logging, and HTTP auth plugin hooks.

This PR routes the trusted-internal hop around that middleware. Every skip is gated on a single shared trust check, so the exemption is contingent on the full trust boundary and never on a URL prefix alone.

It lands in two commits:

| Commit | Scope |
|---|---|
| `consolidate the internal-runtime trust gate into one helper` | One trust gate; callers delegate to it |
| `exempt trusted-internal dispatch from edge middleware` | Per-middleware exemptions + CSRF config change |

## The trust gate

Three near-duplicate trust checks (in `main`, `token_scoping`, and the HMAC helper) are replaced by one gate in `auth_context`:

```
is_trusted_internal_runtime_request(request, *, allowed_prefixes, require_auth_context, path=None)
is_trusted_internal_mcp_request(request, *, path=None)   # MCP/A2A wrapper
```

A request is trusted only when all of the following hold:

```
path matches an allowed internal prefix      (/_internal/mcp or /_internal/a2a)
x-contextforge-mcp-runtime  in {rust, affinity}     (runtime marker)
x-contextforge-mcp-runtime-auth  is a valid HMAC    (the trust boundary)
x-contextforge-auth-context  present                (required for every route except */authenticate)
request.client.host  is loopback                    (127.0.0.1 / ::1, defense in depth)
```

Notes:

- The HMAC plus the encoded auth context are the trust boundary. The loopback check is defense in depth, because `ProxyHeaders(trusted_hosts="*")` makes `request.client.host` influenced by `X-Forwarded-For` for genuinely external requests.
- Auth context is path-aware: `*/authenticate` creates the context, so it is the only internal route that does not require the header.
- The A2A feature guard is retained: `/_internal/a2a/*` is never trusted when A2A is disabled.
- `token_scoping` previously trusted only the `rust` marker. It now delegates to the shared gate and so also trusts the `affinity` marker, closing the gap where the in-process affinity dispatch was still token-scoped.

## Middleware exemptions

| Middleware | Behavior on a trusted hop | Why it matters |
|---|---|---|
| TokenScoping | skipped (delegates to the gate) | the internal hop is not re-scoped |
| RateLimit | skipped | the edge request was already counted; no double count |
| TokenUsage | skipped | no duplicate usage row for the in-process replay |
| HttpAuth | skipped | HTTP auth plugin hooks already ran; they do not re-fire |
| CSRF | skipped via the gate | see below |

### CSRF change

`/_internal/mcp/` is removed from the default `csrf_exempt_paths`. The skip is now contingent on the full trust gate rather than a static path prefix. This is strictly tighter: a path-only exemption left a CSRF-free URL reachable by any client, whereas the gate-based skip requires a valid HMAC from a loopback client. The legit loopback forward still skips CSRF; a forged external request to the same path now hits CSRF enforcement.

## Loopback passthrough hardening

`_LOOPBACK_SKIP_HEADERS` is broadened to strip forwarded and client-IP headers (`forwarded`, `x-forwarded-*`, `x-real-ip`, `cf-connecting-ip`, `true-client-ip`) so the in-process replay cannot carry a spoofable client address into the internal hop.

## What is intentionally NOT exempted

Route-level enforcement is unchanged and still runs on every internal request: the route-level trust check, the forwarded-user build, the internal-request authorization, the server-scope enforcement, method authorization, the HMAC verification, and the auth-context decode. The middleware exemptions remove duplicated edge work; they do not relax the route's own authorization.

## Testing

### Unit

- New `test_internal_runtime_trust.py`: allow and deny for the gate (including the HMAC-is-the-boundary and `X-Forwarded-For` cases), the affinity marker, A2A enable/disable, the prefix allowlist, `token_scoping` trusting affinity, and the forwarded-header stripping.
- Per middleware (RateLimit, TokenUsage, HttpAuth, CSRF): an allow test (trusted hop is exempted) and a deny test (a forged HMAC fails the gate and the normal enforcement path runs).

### Live verification (3 replicas x 24 workers, affinity on)

| Test | Result |
|---|---|
| Isolation: 12 increments on one session through the load balancer | strictly monotonic `[1..12]`, single pool owner; per-session isolation preserved |
| Worker kill: SIGKILL the owning worker mid-session | stale session returns a clean `404 Session not found`; a fresh initialize recovers cleanly |
| Exemption is gated: external POST to the internal endpoints | all rejected (`403`), including forged trust headers, a valid bearer without the HMAC, and `/_internal/a2a/*`. The forged-no-bearer case is rejected by CSRF, confirming the path is no longer blanket-exempt |

The legit loopback forward and the forged external request take the same `/_internal/mcp/rpc` path with opposite outcomes (200 vs 403), decided only by the trust gate.

### Throughput

Tools-only benchmark (125 users, 60s) over three runs: hundreds of requests per second with zero failures across roughly 69,500 forwarded requests, well above the broken-affinity baseline. The exemptions only remove work on the internal hop, so they do not regress throughput.

## Compatibility

- No new configuration. The CSRF behavior for the internal dispatch moves from a static path entry to the gate-based skip; the net effect for a legit loopback forward is unchanged.
- No change to external request handling: a request that does not satisfy the full trust gate goes through the normal middleware exactly as before.
