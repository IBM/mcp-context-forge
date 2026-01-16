# ADR-0004: Combine JWT & Basic Auth

- *Status:* Accepted
- *Date:* 2025-02-01
- *Deciders:* Core Engineering Team

## Context

The gateway needs to support two types of clients:

- **Browser-based users** using the Admin UI
- **Headless clients** such as scripts, services, and tools

These use cases require different authentication workflows:

- Browsers prefer form-based login and session cookies.
- Automation prefers stateless, token-based access.

The current config exposes both:

- `BASIC_AUTH_USER` and `BASIC_AUTH_PASSWORD`
- `JWT_SECRET_KEY`, `JWT_EXPIRY_SECONDS`, and cookie settings

## Decision

We will combine both authentication modes as follows:

- **Basic Auth** secures access to `/admin`. Upon success, a short-lived **JWT cookie** is issued.
- **JWT Bearer token** (via header or cookie) is required for all API, WebSocket, and SSE requests.
- Tokens are signed using the shared `JWT_SECRET_KEY` and include standard claims (sub, exp, scopes).
- When `AUTH_REQUIRED=false`, the gateway allows unauthenticated access (dev only).

## Consequences

- ✅ Developers can log in once via browser and obtain an authenticated session.
- ✅ Scripts can use a generated JWT directly, with no credential storage.
- ❌ Tokens must be signed, rotated, and verified securely (TLS required).
- 🔄 JWTs expire and must be refreshed periodically by clients.

## Alternatives Considered

| Option | Why Not |
|--------|---------|
| **JWT only** | CLI tools need a pre-acquired token; not friendly for interactive login. |
| **Basic only** | Password sent on every request; cannot easily revoke or expire credentials. |
| **OAuth2 / OpenID Connect** | Too complex for self-hosted setups; requires external identity provider. |
| **mTLS client auth** | Secure but heavy; not usable in browsers or simple HTTP clients. |

## Status

This combined authentication mechanism is implemented and enabled by default in the gateway.

---

## Update: Asymmetric JWT Algorithm Support

- *Date:* 2025-01-13
- *Status:* Extended
- *Enhancement By:* Core Engineering Team

### Enhancement Overview

JWT authentication has been extended to support both symmetric (HMAC) and asymmetric (RSA/ECDSA) algorithms, significantly expanding the gateway's authentication capabilities for enterprise and distributed environments.

### Supported Algorithms

| Category | Algorithms | Use Case | Key Management |
|----------|------------|----------|----------------|
| **HMAC (Symmetric)** | HS256, HS384, HS512 | Single-service, simple deployments | Shared secret (`JWT_SECRET_KEY`) |
| **RSA (Asymmetric)** | RS256, RS384, RS512 | Multi-service, enterprise | Public/private key pair |
| **ECDSA (Asymmetric)** | ES256, ES384, ES512 | High-performance, modern crypto | Public/private key pair |

### Configuration

**Symmetric (HMAC) - Default:**
```bash
JWT_ALGORITHM=HS256
JWT_SECRET_KEY=your-secret-key
```

**Asymmetric (RSA/ECDSA) - New:**
```bash
JWT_ALGORITHM=RS256
JWT_PUBLIC_KEY_PATH=jwt/public.pem
JWT_PRIVATE_KEY_PATH=jwt/private.pem
JWT_AUDIENCE_VERIFICATION=true
JWT_ISSUER_VERIFICATION=true
```

### Benefits of Asymmetric Support

✅ **Enhanced Security**

- Private key never leaves the signing service
- Public key can be safely distributed for verification
- Eliminates shared secret management challenges

✅ **Scalability & Federation**

- Multiple services can verify tokens independently
- No need to distribute signing secrets
- Supports microservices and distributed architectures

✅ **Enterprise Compliance**

- Meets enterprise security standards (SOC2, ISO 27001)
- Supports Hardware Security Module (HSM) integration
- Enables proper key lifecycle management

✅ **Future-Proof Architecture**

- Foundation for advanced features like key rotation
- Compatible with industry-standard JWT libraries
- Supports Dynamic Client Registration scenarios

### Implementation Notes

- **Backward Compatibility**: All existing HMAC configurations continue to work unchanged
- **Runtime Configuration**: Algorithm and keys are validated at startup
- **Error Handling**: Clear error messages for misconfigured keys or missing files
- **Performance**: Minimal overhead for asymmetric operations in typical workloads

### Security Considerations

- **Key Storage**: Private keys must be secured and never committed to version control
- **Key Rotation**: Implement regular key rotation procedures for asymmetric keys
- **Algorithm Selection**: Choose algorithm based on security requirements and performance needs
- **Audience Verification**: Can be disabled for Dynamic Client Registration (DCR) scenarios

---

## Update: MCP Endpoint Authentication Configuration

- *Date:* 2025-01-16
- *Status:* Extended
- *Enhancement By:* Core Engineering Team

### Enhancement Overview

A new `MCP_REQUIRE_AUTH` configuration option provides fine-grained control over authentication requirements for MCP protocol endpoints (`/mcp/*`), independent of the global `AUTH_REQUIRED` setting.

### Configuration

| Setting | Default | Description |
|---------|---------|-------------|
| `MCP_REQUIRE_AUTH` | `false` | When `true`, all `/mcp` requests must include a valid Bearer token. When `false`, unauthenticated requests are allowed but can only access public tools, resources, and prompts. |

### Behavior Matrix

| `AUTH_REQUIRED` | `MCP_REQUIRE_AUTH` | REST API | MCP Endpoints |
|-----------------|-------------------|----------|---------------|
| `true` | `false` (default) | Auth required | Public-only access without token |
| `true` | `true` | Auth required | Auth required |
| `false` | `false` | No auth | Public-only access without token |
| `false` | `true` | No auth | Auth required |

### Use Cases

**Default (`MCP_REQUIRE_AUTH=false`):**

- Suitable for public MCP services offering public tools
- Unauthenticated clients can discover and invoke public tools only
- Team-scoped and private tools require authentication

**Strict Mode (`MCP_REQUIRE_AUTH=true`):**

- Recommended for multi-tenant deployments
- All MCP clients must authenticate before any operation
- Prevents anonymous enumeration of available tools

### Security Considerations

- When `MCP_REQUIRE_AUTH=false`, unauthenticated requests receive an empty team list (`teams=[]`), restricting access to `visibility=public` items only
- Private and team-scoped tools, resources, and prompts are never exposed to unauthenticated users
- The service layer enforces access control regardless of this setting

### Configuration Dependencies

Full MCP access control (visibility + team scoping + membership validation) requires:

1. `MCP_CLIENT_AUTH_ENABLED=true` (default) - enables JWT authentication for MCP endpoints
2. Valid Bearer tokens with `teams` claim for team-scoped access
3. Team membership validation runs on each request (60s cache TTL)

When `MCP_CLIENT_AUTH_ENABLED=false`:

- Access control relies on `MCP_REQUIRE_AUTH` + tool/resource visibility only
- Team membership validation is skipped (no JWT to extract teams from)
- Use `TRUST_PROXY_AUTH=true` with a reverse proxy for user identification
