# UAID Cross-Gateway Authentication & Security

This document describes the security architecture, trust model, and configuration for UAID cross-gateway routing.

## Overview

UAID (Universal Agent ID) enables zero-config cross-gateway routing by embedding endpoint and protocol information in the agent identifier. This document covers the security controls that protect cross-gateway communications.

## Security Layers

### Layer 1: Fail-Closed Domain Allowlist

**Purpose:** Prevent SSRF attacks by restricting which domains can be reached via cross-gateway routing.

**Configuration:**

```bash
# Required for production
UAID_ALLOWED_DOMAINS=["gateway1.example.com", "gateway2.example.com"]

# Default behavior (empty list)
UAID_ALLOWED_DOMAINS=[]  # DENIES all cross-gateway routing (fail-closed)

# Unsafe bypass (dev/testing only)
UAID_ALLOW_ALL_DOMAINS=true  # Allows routing to ANY domain
```

**Enforcement:**

1. **Startup Validation:** Logs ERROR if allowlist empty when A2A enabled
2. **Runtime Check:** Rejects cross-gateway calls if allowlist not configured
3. **Subdomain Matching:** Supports wildcard matching (e.g., `example.com` matches `agent.example.com`)

**Error Messages:**

```
Cross-gateway routing to 'agent.untrusted.com' blocked: UAID_ALLOWED_DOMAINS not configured.
Configure UAID_ALLOWED_DOMAINS with trusted domains or set UAID_ALLOW_ALL_DOMAINS=true (unsafe for production).
```

### Layer 2: Bearer Token Forwarding

**Purpose:** Preserve user authentication and RBAC context across gateway hops.

**Configuration:**

```bash
# Enable token forwarding (default: true)
UAID_FORWARD_AUTH=true

# Disable if using alternative auth mechanism
UAID_FORWARD_AUTH=false
```

**Authentication Flow:**

```
1. User authenticates to Gateway A → receives JWT token
2. User invokes UAID agent → Gateway A extracts token from request.state.bearer_token
3. Gateway A makes cross-gateway call → includes Authorization: Bearer <token>
4. Gateway B receives request → validates token via auth middleware
5. Gateway B enforces user's RBAC permissions → invokes agent
6. Response returns through Gateway A → forwarded to user
```

**Headers:**

```http
Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...
X-Contextforge-Source-Gateway: gateway-primary
X-Contextforge-Source-User: user@example.com
X-Contextforge-Correlation-ID: corr-abc-123-xyz
```

## Trust Model

### Shared JWT Secret (Simple)

Both gateways use the same `JWT_SECRET_KEY`:

```bash
# Gateway A .env
JWT_SECRET_KEY=shared-secret-value-xyz

# Gateway B .env
JWT_SECRET_KEY=shared-secret-value-xyz
```

**Pros:**
- Simple to configure
- Works immediately
- No external dependencies

**Cons:**
- Key rotation requires coordination
- Single key compromise affects all gateways
- Not suitable for untrusted gateway federation

### Federated SSO (Recommended for Production)

Both gateways validate tokens from the same identity provider:

**Google Workspace:**
```bash
# Both gateways
SSO_GOOGLE_CLIENT_ID=your-client-id.apps.googleusercontent.com
SSO_GOOGLE_CLIENT_SECRET=your-secret
```

**GitHub:**
```bash
# Both gateways
SSO_GITHUB_CLIENT_ID=your-github-client-id
SSO_GITHUB_CLIENT_SECRET=your-github-secret
```

**Microsoft Entra ID (Azure AD):**
```bash
# Both gateways
SSO_ENTRA_CLIENT_ID=your-app-client-id
SSO_ENTRA_TENANT_ID=your-tenant-id
SSO_ENTRA_CLIENT_SECRET=your-secret
```

**Pros:**
- Centralized identity management
- Key rotation handled by IdP
- Works across organizational boundaries
- Supports conditional access policies

**Cons:**
- Requires IdP setup
- External dependency
- Token expiration considerations

## Configuration Examples

### Single Trust Domain (Shared Secret)

```bash
# Gateway A (gateway-primary.example.com)
A2A_ENABLED=true
AUTH_REQUIRED=true
JWT_SECRET_KEY=shared-secret-xyz-789
UAID_ALLOWED_DOMAINS=["gateway-secondary.example.com"]
UAID_FORWARD_AUTH=true

# Gateway B (gateway-secondary.example.com)
A2A_ENABLED=true
AUTH_REQUIRED=true
JWT_SECRET_KEY=shared-secret-xyz-789
UAID_ALLOWED_DOMAINS=["gateway-primary.example.com"]
UAID_FORWARD_AUTH=true
```

### Federated SSO (Google)

```bash
# Gateway A
A2A_ENABLED=true
AUTH_REQUIRED=true
SSO_GOOGLE_CLIENT_ID=your-client-id.apps.googleusercontent.com
SSO_GOOGLE_CLIENT_SECRET=your-google-secret
UAID_ALLOWED_DOMAINS=["gateway-b.partner.com"]
UAID_FORWARD_AUTH=true

# Gateway B (partner organization)
A2A_ENABLED=true
AUTH_REQUIRED=true
SSO_GOOGLE_CLIENT_ID=your-client-id.apps.googleusercontent.com
SSO_GOOGLE_CLIENT_SECRET=your-google-secret
UAID_ALLOWED_DOMAINS=["gateway-a.yourorg.com"]
UAID_FORWARD_AUTH=true
```

### Development/Testing (Unsafe)

```bash
# ⚠️  WARNING: Never use this in production
A2A_ENABLED=true
AUTH_REQUIRED=false  # UNSAFE: Disables auth entirely
UAID_ALLOW_ALL_DOMAINS=true  # UNSAFE: Allows routing to any domain
UAID_FORWARD_AUTH=false  # Optional: Disable if no auth available
```

## Troubleshooting

### Error: "UAID_ALLOWED_DOMAINS not configured"

**Symptom:** Cross-gateway calls fail immediately with configuration error.

**Cause:** Domain allowlist not configured (fail-closed default).

**Solution:**
```bash
# Add trusted domains to .env
UAID_ALLOWED_DOMAINS=["gateway1.example.com", "gateway2.example.com"]

# OR for dev/testing ONLY (unsafe)
UAID_ALLOW_ALL_DOMAINS=true
```

### Error: "Cross-gateway authentication failed: remote gateway returned 401"

**Symptom:** Remote gateway rejects request with 401 Unauthorized.

**Possible Causes:**

1. **JWT trust mismatch:**
   - Gateway A and B use different `JWT_SECRET_KEY`
   - Gateway B not configured for federated SSO
   - IdP configuration mismatch

   **Solution:** Verify both gateways trust same JWT issuer (shared key or SSO)

2. **Token expired:**
   - User token expired before cross-gateway call completed
   - Long-running operations hit token TTL

   **Solution:** Increase JWT expiration or implement token refresh

3. **Token not forwarded:**
   - `UAID_FORWARD_AUTH=false` on source gateway
   - Auth middleware not extracting token to `request.state.bearer_token`

   **Solution:** Enable `UAID_FORWARD_AUTH=true`, verify auth middleware

4. **Remote gateway requires auth:**
   - Gateway B has `AUTH_REQUIRED=true` but token validation fails

   **Solution:** Verify remote gateway auth configuration, check logs

### Warning: "proceeding without authentication token"

**Symptom:** Logged warning on cross-gateway calls, remote gateway receives unauthenticated request.

**Cause:** Source gateway did not extract bearer token from request.

**Solution:**

1. Verify auth middleware extracts token:
   ```python
   # Auth middleware should set:
   request.state.bearer_token = extracted_token
   ```

2. Check request has authentication:
   ```bash
   # User must be authenticated when making request
   curl -H "Authorization: Bearer <token>" ...
   ```

### Error: "Cross-gateway routing blocked: endpoint not in allowlist"

**Symptom:** Call fails with allowlist rejection.

**Cause:** UAID endpoint domain not in `UAID_ALLOWED_DOMAINS`.

**Solution:**
```bash
# Add the domain to allowlist
UAID_ALLOWED_DOMAINS=["trusted.example.com", "another-gateway.example.com"]

# UAID format must match:
# uaid:aid:hash;registry=X;proto=Y;nativeId=agent.trusted.example.com
#                                              ^^^^^ must be in allowlist
```

## Security Best Practices

1. **Always configure allowlist in production:**
   - Never use `UAID_ALLOW_ALL_DOMAINS=true` in production
   - Use specific domain names, not wildcard/CIDR ranges

2. **Use federated SSO when possible:**
   - Preferred over shared secrets for multi-org deployments
   - Enables centralized access control and audit

3. **Set appropriate token expiration:**
   - Minimum 1 hour for cross-gateway routing
   - Consider network latency and operation duration

4. **Monitor authentication failures:**
   - Alert on 401/403 spikes from cross-gateway calls
   - Investigate token validation errors

5. **Rotate shared secrets regularly:**
   - If using shared JWT secret, rotate quarterly
   - Coordinate rotation across all gateways

6. **Enable AUTH_REQUIRED on all gateways:**
   - Never expose gateways without authentication
   - Even "internal" gateways should enforce auth

## Future Enhancements

### Mutual TLS (mTLS)

**Timeline:** Week 4+

**Features:**
- Certificate-based gateway identity
- Cryptographic trust without shared secrets
- Certificate rotation support

**Configuration (planned):**
```bash
UAID_GATEWAY_CERT_PATH=/path/to/gateway.crt
UAID_GATEWAY_KEY_PATH=/path/to/gateway.key
UAID_GATEWAY_CA_PATH=/path/to/ca.crt
```

### Gateway Trust Token

**Timeline:** Future release

**Features:**
- HMAC-signed requests for gateway-to-gateway trust
- Works with mixed auth systems
- Per-gateway secret rotation

**Configuration (planned):**
```bash
UAID_GATEWAY_TRUST_TOKEN=gateway-shared-secret
```

### Gateway Registry

**Timeline:** Long-term roadmap

**Features:**
- Trusted gateway registry with public key verification
- HCS-14 compliant discovery
- Automatic allowlist population

## Related Documentation

- UAID Implementation: PR #4125
- Security Hardening: Issue #4236
- General Authentication: `docs/docs/manage/rbac.md`
- Multi-tenancy: `docs/docs/architecture/multitenancy.md`
