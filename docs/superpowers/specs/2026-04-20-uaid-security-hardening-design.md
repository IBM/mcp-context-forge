# UAID Cross-Gateway Security Hardening - Design Document

**Issue:** #4236
**Date:** 2026-04-20
**Status:** Approved
**Timeline:** Production ready in 1 week
**PR Strategy:** PR #1 (Critical Security Fixes) - this document covers auth forwarding + fail-closed default. Observability (#4236 section 3) deferred to future PR.

## Overview

Harden security for UAID cross-gateway routing (introduced in #4125) by implementing bearer token forwarding and changing domain allowlist to fail-closed by default. These changes address critical security gaps that block production deployment at scale.

### Security Gaps Addressed

1. **Cross-Gateway Authentication Gap (Critical)**: Remote gateways receive unauthenticated requests, bypassing RBAC and user-level access controls
2. **Domain Allowlist Fail-Open Default (High)**: Empty allowlist permits routing to ANY domain, creating SSRF vulnerability

### Out of Scope (Future Work)

- Observability metrics for cross-gateway calls (nice-to-have, deferred)
- Per-domain rate limiting (nice-to-have, deferred)
- Mutual TLS (mTLS) gateway authentication (future migration path)
- Gateway registry with public key verification (long-term)

## Architecture

### Current State (PR #4125)

```
User → Gateway A (authenticated) → Gateway B (no auth) → Agent
         ↓                              ↓
    Validates RBAC              Public access only
                                (security gap)
```

**Problems:**
- Gateway B receives no authentication context
- User identity and permissions lost across gateway hop
- No audit trail of original user on remote gateway
- SSRF risk: empty `UAID_ALLOWED_DOMAINS` allows routing to any domain

### Proposed Architecture

```
User → Gateway A (authenticated) → Gateway B (validates token) → Agent
         ↓                              ↓
    Extract bearer token          Validate + enforce RBAC
    Add audit headers             (user context preserved)
```

**Security Layers:**
1. **Fail-closed domain allowlist**: Empty config = deny all (explicit opt-in required)
2. **Token forwarding**: Bearer token propagated via `Authorization` header
3. **Audit trail**: `X-Contextforge-Source-Gateway`, `X-Contextforge-Correlation-ID` headers
4. **Shared trust**: Both gateways trust same JWT issuer (shared secret or federated SSO)

## Component Design

### 1. Fail-Closed Domain Allowlist

#### Configuration Changes (`mcpgateway/config.py`)

**New field:**
```python
uaid_allow_all_domains: bool = Field(
    default=False,
    description="DANGEROUS: Allow UAID cross-gateway routing to any domain. Dev-only."
)
```

**Modified behavior of existing field:**
```python
uaid_allowed_domains: List[str] = Field(
    default_factory=list,
    description=(
        "Domain allowlist for UAID cross-gateway routing. When not empty, only UAIDs with endpoints "
        "ending in these domains will be allowed for cross-gateway routing. "
        "Empty list = DENY all cross-gateway routing (fail-closed, secure default)."
    ),
)
```

#### Runtime Enforcement Logic

**Location:** `mcpgateway/services/a2a_service.py:_invoke_remote_agent()`

**Before existing domain validation (line ~2164), add fail-closed gate:**

```python
# Security: Fail-closed if allowlist not configured
allowed_domains = getattr(settings, "uaid_allowed_domains", [])
allow_all = getattr(settings, "uaid_allow_all_domains", False)

if not allowed_domains and not allow_all:
    raise ValueError(
        f"Cross-gateway routing to {endpoint!r} blocked: UAID_ALLOWED_DOMAINS not configured. "
        "Configure UAID_ALLOWED_DOMAINS with trusted domains or set UAID_ALLOW_ALL_DOMAINS=true (unsafe for production)."
    )

# If allow_all flag is true, skip domain validation entirely (dev mode)
if allow_all:
    logger.warning(
        f"⚠️  SECURITY: Cross-gateway routing to {endpoint!r} allowed via UAID_ALLOW_ALL_DOMAINS=true. "
        "This bypasses domain allowlist validation and should NEVER be used in production."
    )
else:
    # Existing domain allowlist validation continues here...
    if allowed_domains:
        # ... existing subdomain matching logic ...
```

#### Startup Validation (`mcpgateway/main.py`)

**Add validation after app initialization:**

```python
# UAID security validation
if settings.a2a_enabled:
    if not settings.uaid_allowed_domains and not settings.uaid_allow_all_domains:
        logger.error(
            "🚨 SECURITY: UAID cross-gateway routing is DISABLED. "
            "Configure UAID_ALLOWED_DOMAINS with trusted domains or set UAID_ALLOW_ALL_DOMAINS=true (unsafe for production). "
            "Cross-gateway UAID calls will fail until allowlist is configured."
        )
```

### 2. Bearer Token Forwarding

#### Request State Enhancement

**Assumption:** Bearer token already extracted by auth middleware and stored in `request.state.bearer_token`.

**Verification needed:** Check `mcpgateway/middleware/` for existing token extraction. If not present, add extraction in auth middleware.

#### Service Layer Changes (`mcpgateway/services/a2a_service.py`)

**Method signature update for `_invoke_remote_agent`:**

```python
async def _invoke_remote_agent(
    self,
    uaid: str,
    parameters: Dict[str, Any],
    interaction_type: str = "query",
    *,
    bearer_token: Optional[str] = None,  # NEW: forwarded auth token
    user_id: Optional[str] = None,
    user_email: Optional[str] = None,
    token_teams: Optional[List[str]] = None,
    hop_count: int = 0,
) -> Dict[str, Any]:
```

**Token extraction in `invoke_agent` method (line ~1700):**

```python
# Extract bearer token from request if available
bearer_token = None
if hasattr(request, "state") and hasattr(request.state, "bearer_token"):
    bearer_token = request.state.bearer_token

# When routing to remote gateway via UAID
if uaid_utils.is_uaid(agent_identifier):
    return await self._invoke_remote_agent(
        uaid=agent_identifier,
        parameters=parameters,
        interaction_type=interaction_type,
        bearer_token=bearer_token,  # NEW: forward token
        user_id=user_id,
        user_email=user_email,
        token_teams=token_teams,
        hop_count=hop_count,
    )
```

**Outbound request headers (in `_invoke_remote_agent`, line ~2200+):**

```python
headers = {
    "Content-Type": "application/json",
    "X-Contextforge-Correlation-ID": correlation_id or str(uuid.uuid4()),
}

# Forward authentication for RBAC enforcement on remote gateway
if bearer_token:
    headers["Authorization"] = f"Bearer {bearer_token}"
    logger.debug("Cross-gateway call: forwarding bearer token for authentication")
else:
    # Backward compatibility: proceed without token but log warning
    logger.warning(
        f"Cross-gateway call to {endpoint} proceeding without authentication token. "
        "Remote gateway will process request as unauthenticated (public access only). "
        "Ensure remote gateway enforces AUTH_REQUIRED=true for security."
    )

# Add audit trail headers for cross-gateway requests
headers["X-Contextforge-Source-Gateway"] = getattr(settings, "app_name", "contextforge")
if user_email:
    # Include originating user for audit purposes (non-sensitive header)
    headers["X-Contextforge-Source-User"] = user_email
```

**Configuration field (`mcpgateway/config.py`):**

```python
uaid_forward_auth: bool = Field(
    default=True,
    description="Forward bearer tokens in cross-gateway UAID calls for RBAC enforcement on remote gateways"
)
```

**Conditional forwarding (only if operator wants it disabled):**

```python
if bearer_token and getattr(settings, "uaid_forward_auth", True):
    headers["Authorization"] = f"Bearer {bearer_token}"
```

#### Error Handling

**Remote gateway returns 401/403:**

```python
# In _invoke_remote_agent, after HTTP response handling
if status_code in (401, 403):
    raise A2AAgentError(
        agent_name=uaid,
        message=f"Cross-gateway authentication failed: remote gateway returned {status_code}. "
                f"Verify both gateways trust the same JWT issuer (shared JWT_SECRET_KEY or federated SSO). "
                f"Endpoint: {endpoint}",
        status_code=status_code,
    )
```

### 3. Trust Model

**JWT-Based Trust (Week 1 Implementation):**

- Both gateways must trust the same JWT issuer
- Options:
  - **Shared Secret**: Both gateways use same `JWT_SECRET_KEY`
  - **Federated SSO**: Both gateways validate tokens from same IdP (Google, GitHub, Entra)
- Remote gateway validates token via existing auth middleware (no code changes needed)
- User's RBAC context preserved automatically via standard token validation

**Validation Flow:**

```
1. Gateway A: User authenticated → token extracted → forwarded in Authorization header
2. Gateway B: Receives request → auth middleware validates token → RBAC checks applied → agent invoked
3. Gateway B: Returns response with user's permissions enforced
```

**Configuration Requirements:**

Operators must ensure:
- Both gateways have `AUTH_REQUIRED=true`
- Both gateways trust same JWT issuer (shared key or federated SSO)
- Token expiration allows for cross-gateway latency (recommend 1+ hour expiration)

**Future Migration Path (Week 4+):**

Migration to mTLS for cryptographic gateway identity:
- Add `UAID_GATEWAY_CERT_PATH` and `UAID_GATEWAY_KEY_PATH` config
- Use `httpx` with client certificates for cross-gateway calls
- Document certificate setup for operators
- Aligns with industry best practices (Kong, Apigee, Istio)

## Testing Strategy

### Unit Tests (`tests/unit/mcpgateway/services/test_a2a_service.py`)

**Fail-Closed Allowlist Tests (3 tests):**

1. **`test_cross_gateway_routing_blocked_when_allowlist_empty_and_flag_false`**
   - Setup: `UAID_ALLOWED_DOMAINS=[]`, `UAID_ALLOW_ALL_DOMAINS=false`
   - Action: Invoke UAID agent
   - Assert: `ValueError` raised with message about allowlist configuration

2. **`test_cross_gateway_routing_allowed_when_flag_true`**
   - Setup: `UAID_ALLOWED_DOMAINS=[]`, `UAID_ALLOW_ALL_DOMAINS=true`
   - Action: Invoke UAID agent
   - Assert: Call proceeds, warning logged

3. **`test_cross_gateway_routing_allowed_when_allowlist_configured`**
   - Setup: `UAID_ALLOWED_DOMAINS=["trusted.example.com"]`
   - Action: Invoke UAID agent with endpoint `agent.trusted.example.com`
   - Assert: Call proceeds (existing behavior unchanged)

**Authentication Forwarding Tests (5 tests):**

1. **`test_cross_gateway_call_forwards_bearer_token`**
   - Setup: Mock request with `request.state.bearer_token = "test-token-123"`
   - Action: Invoke UAID agent
   - Assert: Outbound HTTP request includes `Authorization: Bearer test-token-123`

2. **`test_cross_gateway_call_with_no_token_logs_warning`**
   - Setup: Request without bearer token
   - Action: Invoke UAID agent
   - Assert: Call proceeds, warning logged, no Authorization header

3. **`test_cross_gateway_call_401_raises_clear_error`**
   - Setup: Mock remote gateway returns 401
   - Action: Invoke UAID agent
   - Assert: `A2AAgentError` raised with auth failure message

4. **`test_cross_gateway_call_includes_source_gateway_header`**
   - Setup: `APP_NAME=gateway-primary`
   - Action: Invoke UAID agent
   - Assert: `X-Contextforge-Source-Gateway: gateway-primary` in headers

5. **`test_cross_gateway_call_preserves_correlation_id`**
   - Setup: Request with correlation ID
   - Action: Invoke UAID agent
   - Assert: `X-Contextforge-Correlation-ID` forwarded to remote gateway

**Configuration Tests (`tests/unit/mcpgateway/test_config.py`):**

1. **`test_uaid_allow_all_domains_defaults_false`**
   - Assert: `settings.uaid_allow_all_domains == False`

2. **`test_uaid_forward_auth_defaults_true`**
   - Assert: `settings.uaid_forward_auth == True`

**Startup Validation Tests (`tests/unit/mcpgateway/test_main.py`):**

1. **`test_startup_warns_when_allowlist_empty`**
   - Setup: `A2A_ENABLED=true`, `UAID_ALLOWED_DOMAINS=[]`, `UAID_ALLOW_ALL_DOMAINS=false`
   - Action: Start app
   - Assert: ERROR log contains "UAID cross-gateway routing is DISABLED"

### Integration Tests (Optional, if time permits)

**Two-Gateway Scenario:**
- Gateway A and B both running locally
- Gateway A has UAID agent pointing to Gateway B
- Verify token validation and RBAC enforcement end-to-end

## Migration & Backward Compatibility

### Breaking Change

Cross-gateway UAID routing will **stop working by default** for operators who have not configured `UAID_ALLOWED_DOMAINS`.

**Impact:**
- Existing deployments with UAID agents will see cross-gateway calls fail with clear error
- Error message directs operators to configuration
- UUID-based agents unaffected (continue working as before)

### Migration Path

**Pre-Upgrade (Operator Action Required):**

```bash
# Add to .env before upgrading
UAID_ALLOWED_DOMAINS=["gateway1.example.com", "gateway2.example.com"]
```

**Upgrade Process:**

1. Deploy new version
2. Startup logs ERROR if allowlist empty and A2A enabled
3. Existing UAID calls fail with message: "Configure UAID_ALLOWED_DOMAINS..."
4. Operators add domains to allowlist

**Temporary Bypass (Dev/Testing Only):**

```bash
# UNSAFE: Only for development/testing
UAID_ALLOW_ALL_DOMAINS=true
```

### Graceful Degradation

- `A2A_ENABLED=false` → no impact (UAID not used)
- No UAID agents registered → no impact (UUID-only agents work)
- `uaid_allowed_domains` configured → existing behavior unchanged (with token forwarding added)

### Release Notes Template

```markdown
## ⚠️ BREAKING CHANGE: UAID Security Hardening

Cross-gateway UAID routing now requires explicit domain allowlist configuration and forwards bearer tokens for RBAC enforcement.

### Action Required Before Upgrade

Add to your `.env`:

```bash
# Required: Domain allowlist for UAID cross-gateway routing
UAID_ALLOWED_DOMAINS=["gateway1.example.com", "gateway2.example.com"]

# Optional: Enable auth forwarding (default: true)
UAID_FORWARD_AUTH=true

# UNSAFE: Only for dev/testing (bypasses allowlist)
# UAID_ALLOW_ALL_DOMAINS=true
```

### What Changed

1. **Fail-Closed Default**: Empty `UAID_ALLOWED_DOMAINS` now DENIES all cross-gateway routing (was: allow all domains)
2. **Auth Forwarding**: Bearer tokens forwarded to remote gateways for RBAC enforcement
3. **Startup Validation**: Logs ERROR if A2A enabled but allowlist not configured

### Why This Change

Previous default allowed routing to ANY domain (SSRF risk) and did not forward authentication (bypassed RBAC). New defaults are secure by default.

### Migration Guide

See `docs/security/uaid-cross-gateway-auth.md` for:
- Multi-gateway trust configuration
- Federated SSO setup
- Troubleshooting auth failures
- Future mTLS migration path
```

## Documentation Updates

### 1. `.env.example`

Add new configuration section:

```bash
################################################################################
# UAID Cross-Gateway Routing Security
################################################################################

# Domain allowlist for UAID cross-gateway routing (REQUIRED for production)
# Empty list = DENY all cross-gateway routing (fail-closed, secure default)
# Example: UAID_ALLOWED_DOMAINS=["gateway1.example.com", "gateway2.example.com"]
UAID_ALLOWED_DOMAINS=[]

# DANGEROUS: Allow UAID routing to ANY domain (dev-only)
# ⚠️  WARNING: Setting this to true bypasses domain allowlist validation
# ⚠️  NEVER use in production - creates SSRF vulnerability
UAID_ALLOW_ALL_DOMAINS=false

# Forward bearer tokens in cross-gateway UAID calls for RBAC enforcement
# Requires both gateways to trust the same JWT issuer (shared secret or federated SSO)
UAID_FORWARD_AUTH=true
```

### 2. `README.md` Updates

Add to UAID section:

```markdown
### UAID Security Configuration

**Production Requirements:**
- Configure `UAID_ALLOWED_DOMAINS` with trusted gateway domains
- Ensure all gateways share JWT trust (same `JWT_SECRET_KEY` or federated SSO)
- Enable `AUTH_REQUIRED=true` on all gateways

**Authentication Flow:**
Cross-gateway calls forward the user's bearer token for RBAC enforcement.
Remote gateways validate tokens via existing auth middleware.

**Example Configuration:**
```bash
UAID_ALLOWED_DOMAINS=["gateway1.example.com", "gateway2.example.com"]
JWT_SECRET_KEY=shared-secret-across-all-gateways
AUTH_REQUIRED=true
```
```

### 3. New Security Documentation

**File:** `docs/security/uaid-cross-gateway-auth.md`

**Contents:**
- Architecture diagram showing token flow
- Trust model explanation (shared JWT vs federated SSO)
- Configuration examples for different topologies:
  - Single trust domain (shared secret)
  - Federated SSO (Google, GitHub, Entra)
  - Hybrid (mixed auth systems)
- Threat model and mitigations
- Troubleshooting guide:
  - 401/403 errors from remote gateway
  - Token expiration issues
  - Allowlist misconfiguration
- Future migration path to mTLS
- Security best practices

### 4. `CLAUDE.md` Updates

Add to Security Invariants section:

```markdown
### UAID Cross-Gateway Security

- UAID cross-gateway routing requires explicit domain allowlist (fail-closed default)
- Empty `UAID_ALLOWED_DOMAINS` blocks all cross-gateway routing unless `UAID_ALLOW_ALL_DOMAINS=true`
- Cross-gateway calls forward bearer tokens for RBAC enforcement on remote gateways
- Both gateways must trust the same JWT issuer (shared secret or federated SSO)
- `UAID_ALLOW_ALL_DOMAINS=true` is unsafe for production (bypasses allowlist validation)
```

## Implementation Checklist

### Core Implementation

- [ ] Add `uaid_allow_all_domains` field to `mcpgateway/config.py`
- [ ] Add `uaid_forward_auth` field to `mcpgateway/config.py`
- [ ] Update `uaid_allowed_domains` description for fail-closed behavior
- [ ] Add fail-closed gate in `_invoke_remote_agent` (before domain validation)
- [ ] Add `bearer_token` parameter to `_invoke_remote_agent` signature
- [ ] Extract bearer token in `invoke_agent` method
- [ ] Add `Authorization` header forwarding in `_invoke_remote_agent`
- [ ] Add audit headers (`X-Contextforge-Source-Gateway`, `X-Contextforge-Source-User`)
- [ ] Add 401/403 error handling with clear auth failure message
- [ ] Add startup validation in `mcpgateway/main.py`

### Testing

- [ ] Unit test: fail-closed with empty allowlist
- [ ] Unit test: bypass with `UAID_ALLOW_ALL_DOMAINS=true`
- [ ] Unit test: existing allowlist behavior unchanged
- [ ] Unit test: bearer token forwarded in headers
- [ ] Unit test: no token logs warning
- [ ] Unit test: 401 raises clear error
- [ ] Unit test: source gateway header included
- [ ] Unit test: correlation ID preserved
- [ ] Config test: `uaid_allow_all_domains` defaults false
- [ ] Config test: `uaid_forward_auth` defaults true
- [ ] Startup test: ERROR logged when allowlist empty
- [ ] Run full test suite (ensure 147 A2A tests still pass)

### Documentation

- [ ] Update `.env.example` with new config fields
- [ ] Update `README.md` UAID section with security requirements
- [ ] Create `docs/security/uaid-cross-gateway-auth.md`
- [ ] Update `CLAUDE.md` Security Invariants section
- [ ] Draft release notes with breaking change warning

### Code Quality

- [ ] Run `make autoflake isort black pre-commit`
- [ ] Run `make ruff bandit interrogate pylint verify`
- [ ] Verify no new security warnings from bandit
- [ ] Verify 10.00/10 pylint score maintained

### Review & Merge

- [ ] Create PR with title: `[SECURITY][ENHANCEMENT]: UAID Cross-Gateway Security Hardening - Auth Forwarding & Fail-Closed Allowlist`
- [ ] Link to issue #4236 in PR description
- [ ] Include migration guide in PR description
- [ ] Request review from security-conscious team members
- [ ] Address review feedback
- [ ] Merge to main

## Success Criteria

### Functional Requirements

✅ **Empty allowlist blocks cross-gateway routing by default**
- Clear error message directs operators to configuration
- `UAID_ALLOW_ALL_DOMAINS=true` provides explicit bypass for dev/testing

✅ **Bearer tokens forwarded to remote gateways**
- `Authorization` header present in cross-gateway HTTP calls
- Remote gateways validate tokens via existing auth middleware
- User RBAC context preserved across gateway hops

✅ **Backward compatibility maintained**
- UUID-based agents work unchanged
- Existing allowlist behavior unchanged (when configured)
- Graceful degradation when token unavailable (logs warning)

✅ **Audit trail established**
- `X-Contextforge-Source-Gateway` identifies source
- `X-Contextforge-Source-User` tracks original user
- Correlation IDs propagate across hops

### Non-Functional Requirements

✅ **Security hardened**
- Fail-closed default prevents accidental SSRF
- RBAC enforced across gateway federation
- Clear error messages prevent misconfigurations

✅ **Operator experience**
- Startup validation catches misconfiguration early
- Error messages provide actionable guidance
- Migration path documented clearly

✅ **Production ready in 1 week**
- Implementation: 3-4 days
- Testing: 1-2 days
- Documentation: 1 day
- Buffer: 1-2 days for review/polish

## Future Work (Not in This PR)

### Observability & Monitoring (Issue #4236, Section 3)

- Metrics for cross-gateway calls (count, latency, errors by domain)
- Alerts for cross-gateway calls to non-allowlisted domains
- Dashboard for cross-gateway routing patterns
- Distributed tracing enhancements

### Enhanced Gateway Trust (Week 4+)

- Mutual TLS (mTLS) with certificate-based gateway identity
- Gateway trust token with HMAC signature validation
- Certificate rotation support
- PKI infrastructure documentation

### Gateway Registry (Long-term)

- Trusted gateway registry with public key verification
- HCS-14 compliant gateway discovery
- Automatic allowlist population from registry
- Gateway capability negotiation

### Rate Limiting

- Per-domain rate limiting for cross-gateway calls
- Per-user rate limiting across gateway federation
- Burst protection for remote gateway protection

## Risks & Mitigations

### Risk: Breaking Change Impact

**Risk:** Operators upgrade without configuring allowlist, UAID routing breaks

**Mitigation:**
- Clear ERROR log at startup
- Clear error message on runtime failures
- Prominent documentation in release notes
- Migration guide with examples
- Escape hatch (`UAID_ALLOW_ALL_DOMAINS=true`) for emergency rollback

### Risk: Token Expiration

**Risk:** Long cross-gateway call chains hit token expiration

**Mitigation:**
- Document recommended token expiration (1+ hour)
- Error message on 401 includes token expiration guidance
- Future: Token refresh mechanism for long-running operations

### Risk: Mixed Auth Systems

**Risk:** Gateway A and B use different auth systems (can't validate tokens)

**Mitigation:**
- Document JWT trust requirements clearly
- Error message on 401 mentions trust validation
- Future: Gateway trust token (Option 2) for mixed auth environments

### Risk: Performance Impact

**Risk:** Token forwarding adds latency/overhead

**Mitigation:**
- Headers add negligible overhead (<1ms)
- Token already in request state (no extraction overhead)
- Can disable via `UAID_FORWARD_AUTH=false` if needed (not recommended)

## Appendix: Alternative Approaches Considered

### Alternative 1: Gateway Trust Token (Shared Secret)

Add shared secret header for gateway-to-gateway trust.

**Pros:**
- Works with different user auth systems
- Simpler trust establishment

**Cons:**
- Shared secrets don't scale
- Hard to rotate
- No per-gateway identity
- Not industry best practice

**Decision:** Rejected for Week 1. JWT forwarding is simpler and more aligned with microservice patterns.

### Alternative 2: Mutual TLS (mTLS)

Use certificate-based gateway authentication.

**Pros:**
- Industry gold standard
- Cryptographic identity proof
- Certificate rotation
- No shared secrets

**Cons:**
- Complex implementation (PKI infrastructure)
- Operator setup overhead
- Longer timeline (3-4 weeks)

**Decision:** Future migration path. Document in security guide for Week 4+ implementation.

### Alternative 3: OAuth Token Exchange

Use OAuth 2.0 Token Exchange (RFC 8693) for cross-gateway tokens.

**Pros:**
- Standards-based
- Supports scope narrowing
- Clear security model

**Cons:**
- Requires OAuth infrastructure
- Complex implementation
- Overkill for initial deployment

**Decision:** Deferred to long-term roadmap. JWT forwarding sufficient for initial trust model.

## Conclusion

This design implements critical security hardening for UAID cross-gateway routing with a 1-week timeline. The fail-closed allowlist default prevents SSRF, and bearer token forwarding enables RBAC enforcement across gateway federation. The implementation is backward compatible, well-tested, and provides a clear migration path for operators. Future work includes observability, mTLS migration, and gateway registry integration.
