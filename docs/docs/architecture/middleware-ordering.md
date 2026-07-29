# Middleware Execution Ordering

ContextForge uses Starlette's ASGI middleware stack to handle cross-cutting concerns like authentication, CSRF protection, logging, and observability. Understanding the execution order is critical when adding new middleware, especially when middleware depends on request state populated by other middleware.

## Reverse Registration Rule

**Starlette/FastAPI executes middleware in *reverse* registration order.** The last `app.add_middleware()` call registers middleware that runs *outermost* (processes requests first, responses last). The first `add_middleware()` call registers middleware that runs *innermost* (processes requests last, responses first).

### Worked Example

Suppose your code registers middleware like this:

```python
app.add_middleware(First)    # Registered first
app.add_middleware(Second)   # Registered second
app.add_middleware(Third)    # Registered third (last)
```

The execution order on an inbound request is:

```
Request  → Third → Second → First → Handler → First → Second → Third → Response
          (runs)  (runs)  (runs)             (done)  (done)  (done)
```

`Third` runs first on the request path (outermost), and `First` runs last (innermost, closest to the handler). On the response path, the order reverses.

This reverse-registration rule is a Starlette/FastAPI design decision. When a middleware reads `request.state` values set by another middleware, you must register the *producer* middleware **after** the *consumer* middleware so that the producer runs before (earlier on the request path than) the consumer.

## Current Middleware Stack

The middleware stack in `mcpgateway/main.py` (lines ~3265–3501) includes ~26 middleware, plus one outlier registered after route setup. The table below shows them in **registration order** (top = registered first, bottom = registered last):

| Registration Order | Middleware | Execution Order | Purpose | Conditional |
|---|---|---|---|---|
| 1 | `CORSMiddleware` | Outermost | Handles CORS preflight and cross-origin policy | Always |
| 2 | `SSEAwareCompressMiddleware` | ... | Compresses responses (Brotli/Zstd/GZip), excludes SSE/MCP streams | `compression_enabled` |
| 3 | `SecurityHeadersMiddleware` | ... | Adds CSP, X-Frame-Options, HSTS, strips Server headers | Always |
| 4 | `HeaderSizeMiddleware` | ... | Validates request header count/size (RFC 6585 §5) | `header_size_validation_enabled` |
| 5 | `RateLimitMiddleware` | ... | Rate-limiting enforcement per IP/user tier | `rate_limiting_enabled` |
| 6 | `ValidationMiddleware` | ... | Input validation and output sanitization | `validation_middleware_enabled` |
| 7 | `MCPProtocolVersionMiddleware` | ... | Validates `MCP-Protocol-Version` header on MCP routes | Always |
| 8 | `BaseHTTPMiddleware` (token scoping) | ... | Applies token scoping for email-auth users (data filtering) | `email_auth_enabled` |
| 9 | `MCPPathRewriteMiddleware` (token scoped) | ... | Streamable HTTP for MCP routes with token scoping | `email_auth_enabled` |
| 10 | `MCPPathRewriteMiddleware` | ... | Streamable HTTP for MCP routes (no scoping) | `NOT email_auth_enabled` |
| 11 | `HttpAuthMiddleware` | ... | Plugin hook for HTTP auth (e.g., OAuth/OIDC) | Always |
| 12 | `RequestLoggingMiddleware` | ... | Gateway boundary and detailed request/response logging | Always |
| 13 | `DocsAuthMiddleware` | ... | Restricts `/docs` and `/redoc` to authenticated users | Always |
| 14 | `AdminAuthMiddleware` | ... | Requires admin privilege for `/admin/*` routes | Always |
| 15 | `ForwardedHostMiddleware` | ... | Rewrites `Host` from `X-Forwarded-Host` (proxy support) | Always |
| 16 | `ProxyHeadersMiddleware` | ... | Trusts `X-Forwarded-*` headers (scheme, IP) | Always |
| 17 | `CorrelationIDMiddleware` | ... | Attaches request correlation ID for tracing | `correlation_id_enabled` |
| 18 | `CSRFMiddleware` | ... | CSRF token validation (state-changing requests) | `csrf_enabled` |
| 19 | `PasswordChangeEnforcementMiddleware` | ... | Redirects users requiring password change (admin-only) | `password_change_enforcement_enabled` |
| 20 | `AuthContextMiddleware` | Innermost* | Extracts and validates JWT/session, sets `request.state.user` | `security_logging_enabled` OR `siem_export_enabled` with "auth" events OR `mcpgateway_admin_api_enabled` OR `password_change_enforcement_enabled` |
| 21 | `TokenUsageMiddleware` | (varies) | Logs token usage for analytics/audit | `token_usage_logging_enabled` |
| 22 | `ObservabilityMiddleware` | (varies) | Traces request spans for observability | `observability_enabled` |
| 23 | `OpenTelemetryRequestMiddleware` | (varies) | OTEL request root span | `otel_tracing_enabled()` |
| 24 | `BaggageMiddleware` | (varies) | OTEL baggage extraction from headers | `otel_baggage_enabled` AND `otel_tracing_enabled()` |
| 25 | `DBQueryLoggingMiddleware` | (varies) | Logs database queries for N+1 detection | `db_query_log_enabled` |
| 26 | `ClientDisconnectMiddleware` | (varies) | Cancels in-flight handlers on client disconnect | `client_disconnect_middleware_enabled` |
| **27 (outlier)** | **`DeprecationHeadersMiddleware`** | **Outermost** | **Adds RFC 8594 Sunset/Link headers to legacy routes** | **`legacy_api_enabled`** |

\* *`AuthContextMiddleware` is registered when certain conditions are met (security logging enabled, SIEM export with "auth" events enabled, admin API enabled, or password change enforcement enabled). When registered, it is registered LAST in the main block, making it the innermost of the three auth-related middleware (rows 18–20) but not necessarily innermost overall if other middleware (rows 21–26) are enabled.*

### The Outlier: `DeprecationHeadersMiddleware`

**Key point:** `DeprecationHeadersMiddleware` is registered **outside the main middleware block**, after `app.include_router(legacy_router)` (line ~12882). Because it is registered last, it runs **outermost** — ahead of everything in the main 3265–3501 registration block, including `CORSMiddleware`.

If you are adding middleware that depends on early request processing (e.g., extracting headers or setting flags), remember that `DeprecationHeadersMiddleware` may already have run if `legacy_api_enabled=true`. Conversely, if you add middleware after `DeprecationHeadersMiddleware`, it will run *before* `DeprecationHeadersMiddleware`, which is usually not desired.

## State Dependencies: The CSRF + Auth Middleware Ordering Bug

**Critical constraint:** `CSRFMiddleware` must be registered *before* `AuthContextMiddleware` so that CSRF runs *after* auth and `request.state.user` is already populated.

### The Bug (Issue #5780)

`CSRFMiddleware` validates HMAC-bound CSRF tokens using `request.state.user.email`:

```python
# mcpgateway/middleware/csrf_middleware.py:143–146
if hasattr(request.state, "user") and request.state.user:
    user = request.state.user
    user_id = user.email if hasattr(user, "email") else str(user.id)
```

`AuthContextMiddleware` populates `request.state.user` for all authenticated requests:

```python
# mcpgateway/middleware/auth_middleware.py:189
request.state.user = user
```

**If the middleware registration order is reversed** (CSRF registered after auth), then CSRF runs *before* auth on the request path, and `request.state.user` is unset. The CSRF middleware then silently falls back to extracting identity from the raw JWT `sub` claim (the user's ID, not email). But `admin.py` binds CSRF tokens to the user's *email*, not ID — resulting in universal 403 "CSRF Token Invalid" errors on all Admin UI writes.

**Solution:** In `main.py`, register `CSRFMiddleware` (line ~3403) *before* `AuthContextMiddleware` (line ~3427) so that the reverse-order execution makes auth run first on requests.

## Same-Shape Constraint: `PasswordChangeEnforcementMiddleware`

`PasswordChangeEnforcementMiddleware` has an identical dependency structure to `CSRFMiddleware`: it reads `request.state.user` to check the `password_change_required` flag (line ~96 in `password_change_enforcement.py`):

```python
user: Optional[EmailUser] = getattr(request.state, "user", None)
if not user:
    return await call_next(request)
```

For the same reason, `PasswordChangeEnforcementMiddleware` must be registered *before* `AuthContextMiddleware`. In the current codebase, both CSRF and PasswordChangeEnforcement are registered in the same order-dependent block (lines ~3403–3427), with both registered before auth.

If you add another middleware that reads `request.state` values set by `AuthContextMiddleware`, ensure it is registered *before* `AuthContextMiddleware` to preserve execution order.

## Guidance for Adding New Middleware

1. **Identify producers and consumers.** List the `request.state` attributes your middleware reads and writes. Identify which other middleware or dependencies populate those attributes.

2. **Register consumers *before* producers.** Middleware that reads `request.state.user`, `request.state.jti`, or other auth context must be registered *before* (earlier in the registration list than) `AuthContextMiddleware`.

3. **Add a regression test.** Write a test similar to `test_csrf_middleware_runs_after_auth_context_middleware` (in `tests/unit/mcpgateway/middleware/test_admin_csrf_binding.py:325`) to verify your middleware runs in the expected order:

   ```python
   def test_my_middleware_runs_after_auth_context_middleware():
       from mcpgateway.main import app
       from mcpgateway.middleware.auth_middleware import AuthContextMiddleware
       from mcpgateway.middleware.my_new_middleware import MyNewMiddleware
       
       middleware_classes = [m.cls for m in app.user_middleware]
       assert AuthContextMiddleware in middleware_classes
       assert MyNewMiddleware in middleware_classes
       
       auth_index = middleware_classes.index(AuthContextMiddleware)
       my_index = middleware_classes.index(MyNewMiddleware)
       
       # AuthContextMiddleware must run BEFORE MyNewMiddleware
       # (lower index means earlier in request processing)
       assert auth_index < my_index
   ```

4. **Consider the reverse-registration rule.** When reading the code, remember that `add_middleware()` calls at the *end* register middleware that runs *first* on requests. Use this link to this page ([../architecture/middleware-ordering.md](middleware-ordering.md)) to document your ordering rationale in comments.

5. **Avoid brittle line-number references.** When documenting middleware order in code or docs, reference the middleware class name and its high-level purpose (e.g., "registered before AuthContextMiddleware") rather than specific line numbers, since the codebase evolves.

---

**See also:**
- [Security Features](security-features.md) — overview of ContextForge's security model
- [Configuration: CSRF Protection](../manage/configuration.md#csrf-protection) — CSRF-specific settings and cookie synchronization risks
