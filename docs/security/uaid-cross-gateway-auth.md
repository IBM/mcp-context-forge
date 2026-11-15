# UAID Cross-Gateway Authentication and Security

Universal Agent ID (UAID) enables cross-gateway routing by embedding endpoint and protocol details in the agent identifier.
This document describes security controls, trust models, and configuration for UAID routing.

## Security Controls

### Domain Allowlist (SSRF Protection)

The gateway uses a fail-closed domain allowlist to prevent Server-Side Request Forgery (SSRF) attacks.

```bash
# Production configuration
UAID_ALLOWED_DOMAINS=["gateway1.example.com", "gateway2.example.com"]

# Default behavior (empty list denies all cross-gateway routing)
UAID_ALLOWED_DOMAINS=[]

# Development bypass only (unsafe for production)
UAID_ALLOW_ALL_DOMAINS=true
```

Allowlist rules:

- **Startup check:** The gateway logs an error when `MCPGATEWAY_A2A_ENABLED` is `true` and `UAID_ALLOWED_DOMAINS` is empty. Set `UAID_REQUIRE_ALLOWLIST_ON_STARTUP=true` to abort startup instead.
- **Runtime validation:** The gateway checks the destination endpoint against `UAID_ALLOWED_DOMAINS`.
- **Subdomain support:** A domain entry matches its subdomains (for example, `example.com` matches `agent.example.com`).

### Bearer Token Forwarding

The gateway forwards user bearer tokens across hops to preserve authentication and RBAC context.

```bash
# Enable token forwarding (default)
UAID_FORWARD_AUTH=true

# Disable token forwarding
UAID_FORWARD_AUTH=false <!-- pragma: allowlist secret -->
```

Authentication flow:

1. User authenticates to Gateway A and receives a JWT.
2. User invokes a UAID agent.
3. Gateway A extracts the bearer token from the request context.
4. Gateway A sends the request to Gateway B with an `Authorization: Bearer <token>` header.
5. Gateway B checks the token and enforces RBAC permissions.
6. Gateway B invokes the agent and returns the response through Gateway A.

Forwarded request headers:

```http
Authorization: Bearer <token>
X-Contextforge-Source-Gateway: gateway-primary
X-Contextforge-Source-User: user@example.com
X-Contextforge-Correlation-ID: corr-abc-123-xyz
```

### Hop Limit (Loop Prevention)

The gateway sets `UAID_MAX_FEDERATION_HOPS` (default `5`) to stop routing loops.
Each outbound hop increments the `X-Contextforge-UAID-Hop` header.
Inbound requests that meet or exceed the limit return a `404` status code.

## Trust Models

Cross-gateway token forwarding requires both gateways to accept the forwarded JWT.

### Shared JWT Secret

Both gateways use the same `JWT_SECRET_KEY`:

```bash
# Gateway A and Gateway B
JWT_SECRET_KEY=shared-secret-value-xyz <!-- pragma: allowlist secret -->
```

Characteristics:

- Fast setup with no external dependencies.
- Key rotation requires coordinated updates across all gateways.
- Key compromise affects all gateways that share the key.

### Federated SSO

Both gateways accept tokens from a shared identity provider:

```bash
# Google Workspace
SSO_GOOGLE_CLIENT_ID=your-client-id.apps.googleusercontent.com
SSO_GOOGLE_CLIENT_SECRET=your-secret <!-- pragma: allowlist secret -->

# GitHub
SSO_GITHUB_CLIENT_ID=your-github-client-id
SSO_GITHUB_CLIENT_SECRET=your-github-secret <!-- pragma: allowlist secret -->

# Microsoft Entra ID
SSO_ENTRA_CLIENT_ID=your-app-client-id
SSO_ENTRA_TENANT_ID=your-tenant-id
SSO_ENTRA_CLIENT_SECRET=your-secret <!-- pragma: allowlist secret -->
```

Characteristics:

- Central identity management across organizations.
- Identity provider manages key rotation.
- Requires external identity provider configuration.

## Configuration Examples

### Shared Secret Setup

```bash
# Gateway A (gateway-a.example.com)
MCPGATEWAY_A2A_ENABLED=true
AUTH_REQUIRED=true <!-- pragma: allowlist secret -->
JWT_SECRET_KEY=shared-secret-xyz-789 <!-- pragma: allowlist secret -->
UAID_ALLOWED_DOMAINS=["gateway-b.example.com"]
UAID_FORWARD_AUTH=true <!-- pragma: allowlist secret -->

# Gateway B (gateway-b.example.com)
MCPGATEWAY_A2A_ENABLED=true
AUTH_REQUIRED=true <!-- pragma: allowlist secret -->
JWT_SECRET_KEY=shared-secret-xyz-789 <!-- pragma: allowlist secret -->
UAID_ALLOWED_DOMAINS=["gateway-a.example.com"]
UAID_FORWARD_AUTH=true <!-- pragma: allowlist secret -->
```

### Development Setup (Unsafe)

```bash
# Development and testing only
MCPGATEWAY_A2A_ENABLED=true
AUTH_REQUIRED=false <!-- pragma: allowlist secret -->
UAID_ALLOW_ALL_DOMAINS=true
UAID_FORWARD_AUTH=false <!-- pragma: allowlist secret -->
```

## Troubleshooting

### Allowlist Rejection

**Problem:** Cross-gateway calls fail with `UAID_ALLOWED_DOMAINS not configured` or `endpoint not in allowlist`.

**Solution:**

1. Add the destination domain to `UAID_ALLOWED_DOMAINS`.
2. Check that the UAID native endpoint matches the allowed domain.

### Remote Gateway Returns 401

**Problem:** The target gateway rejects the cross-gateway call with HTTP `401 Unauthorized`.

**Solution:**

1. **Check JWT trust:** Ensure both gateways use the same `JWT_SECRET_KEY` or the same SSO identity provider.
2. **Check token expiration:** Ensure the token does not expire during long operations.
3. **Check token forwarding:** Check that `UAID_FORWARD_AUTH` is `true` on the source gateway.
4. **Inspect remote auth configuration:** Check logs on the target gateway for validation errors.

### Missing Bearer Token Warning

**Problem:** Logs display `proceeding without authentication token`.

**Solution:**

1. Authenticate the initial client request with a bearer token.
2. Ensure authentication middleware sets `request.state.bearer_token`.

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

## Related Documentation

- [Multi-Tenancy Architecture](../docs/architecture/multitenancy.md)
- [RBAC Configuration](../docs/manage/rbac.md)
- [SSO Configuration](../docs/manage/sso.md)
