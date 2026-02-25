# Securing ContextForge

This guide provides essential security configurations and best practices for deploying ContextForge in production environments.

## ⚠️ Critical Security Notice

**ContextForge is currently in beta (v1.0.0-RC-1)** and requires careful security configuration for production use:

- The **Admin UI is development-only** and must be disabled in production
- Expect **breaking changes** between versions until 1.0 release
- Do not use it with insecure MCP servers.

## 🚨 Production Security Checklist

### 1. Disable Development Features

```bash
# Required for production - disable all admin interfaces
MCPGATEWAY_UI_ENABLED=false
MCPGATEWAY_ADMIN_API_ENABLED=false

# Optional: turn off auxiliary systems you do not need
MCPGATEWAY_BULK_IMPORT_ENABLED=false
MCPGATEWAY_A2A_ENABLED=false
```

Use RBAC policies to revoke access to prompts, resources, or tools you do not
intend to expose—these surfaces are always mounted but can be hidden from end
users by removing the corresponding permissions.

### 2. Enable Authentication & Security

```bash
# Configure strong authentication
AUTH_REQUIRED=true

# Basic auth is DISABLED by default (recommended for security)
# API_ALLOW_BASIC_AUTH=false    # Default - use JWT tokens instead
# DOCS_ALLOW_BASIC_AUTH=false   # Default - use JWT tokens instead

# If you MUST use Basic auth (legacy compatibility only):
# API_ALLOW_BASIC_AUTH=true
# BASIC_AUTH_USER=custom-username       # Change from default
# BASIC_AUTH_PASSWORD=strong-password-here  # Use secrets manager

# Platform admin user (auto-created during bootstrap)
PLATFORM_ADMIN_EMAIL=admin@yourcompany.com  # Change from default
PLATFORM_ADMIN_PASSWORD=secure-admin-password  # Use secrets manager

# JWT Configuration - Choose based on deployment architecture
JWT_ALGORITHM=RS256                        # Recommended for production (asymmetric)
JWT_PUBLIC_KEY_PATH=jwt/public.pem         # Path to public key file
JWT_PRIVATE_KEY_PATH=jwt/private.pem       # Path to private key file (secure location)
JWT_AUDIENCE_VERIFICATION=true             # Enable audience validation
JWT_ISSUER_VERIFICATION=true               # Enable issuer validation
JWT_ISSUER=your-company-name               # Set to your organization identifier

# Set environment for security defaults
ENVIRONMENT=production

# Configure domain for CORS
APP_DOMAIN=yourdomain.com

# Ensure secure cookies (automatic in production)
SECURE_COOKIES=true
COOKIE_SAMESITE=strict

# Configure CORS (auto-configured based on APP_DOMAIN in production)
CORS_ALLOW_CREDENTIALS=true
```

#### Platform Admin Security Notes

The platform admin user (`PLATFORM_ADMIN_EMAIL`) is automatically created during database bootstrap with full administrative privileges. This user:

- Has access to all RBAC-protected endpoints
- Can manage users, teams, and system configuration
- Is recognized by both database-persisted and virtual authentication flows
- Should use a strong, unique email and password in production

#### JWT Security Configuration

ContextForge supports both symmetric (HMAC) and asymmetric (RSA/ECDSA) JWT algorithms. **Asymmetric algorithms are strongly recommended for production** due to enhanced security properties.

##### Production JWT Security (Recommended)

```bash
# Use asymmetric algorithm for production
JWT_ALGORITHM=RS256                        # or RS384, RS512, ES256, ES384, ES512
JWT_PUBLIC_KEY_PATH=/secure/path/jwt/public.pem
JWT_PRIVATE_KEY_PATH=/secure/path/jwt/private.pem
JWT_AUDIENCE=your-api-identifier
JWT_ISSUER=your-organization
JWT_AUDIENCE_VERIFICATION=true
JWT_ISSUER_VERIFICATION=true
REQUIRE_TOKEN_EXPIRATION=true              # Reject tokens without exp claim
REQUIRE_JTI=true                           # Require JWT ID for token tracking/revocation
```

##### Development JWT Security

```bash
# HMAC acceptable for development/testing only
JWT_ALGORITHM=HS256
JWT_SECRET_KEY=your-strong-secret-key-here  # Minimum 32 characters
JWT_AUDIENCE=mcpgateway-api
JWT_ISSUER=mcpgateway
JWT_AUDIENCE_VERIFICATION=true
JWT_ISSUER_VERIFICATION=true
REQUIRE_TOKEN_EXPIRATION=true              # Reject tokens without exp claim
REQUIRE_JTI=true                           # Require JWT ID for token tracking/revocation
```

##### JWT Key Management Best Practices

**RSA Key Generation:**
```bash
# Option 1: Use Makefile (Recommended for development/local)
make certs-jwt                   # Generates ./certs/jwt/{private,public}.pem with secure permissions

# Option 2: Manual generation (Production with custom paths)
mkdir -p /secure/certs/jwt
openssl genrsa -out /secure/certs/jwt/private.pem 4096
openssl rsa -in /secure/certs/jwt/private.pem -pubout -out /secure/certs/jwt/public.pem
chmod 600 /secure/certs/jwt/private.pem  # Private key: owner read/write only
chmod 644 /secure/certs/jwt/public.pem   # Public key: world readable
chown mcpgateway:mcpgateway /secure/certs/jwt/*.pem
```

**ECDSA Key Generation (Alternative):**
```bash
# Option 1: Use Makefile (Recommended for development/local)
make certs-jwt-ecdsa             # Generates ./certs/jwt/{ec_private,ec_public}.pem with secure permissions

# Option 2: Manual generation (Production with custom paths)
mkdir -p /secure/certs/jwt
openssl ecparam -genkey -name prime256v1 -noout -out /secure/certs/jwt/ec_private.pem
openssl ec -in /secure/certs/jwt/ec_private.pem -pubout -out /secure/certs/jwt/ec_public.pem
chmod 600 /secure/certs/jwt/ec_private.pem
chmod 644 /secure/certs/jwt/ec_public.pem
```

**Combined Generation (SSL + JWT):**
```bash
make certs-all                   # Generates both TLS certificates and JWT RSA keys
```

**Security Requirements:**

- [ ] **Never commit private keys** to version control
- [ ] **Store private keys** in secure, encrypted storage
- [ ] **Use strong file permissions** (600) on private keys
- [ ] **Implement key rotation** procedures (recommend 90-day rotation)
- [ ] **Monitor key access** in system audit logs
- [ ] **Use Hardware Security Modules (HSMs)** for high-security environments
- [ ] **Separate key storage** from application deployment

**Container Security for JWT Keys:**
```bash
# Mount keys as read-only secrets (Kubernetes example)
apiVersion: v1
kind: Secret
metadata:
  name: jwt-keys
type: Opaque
data:
  private.pem: <base64-encoded-private-key>
  public.pem: <base64-encoded-public-key>

# In pod spec:
volumes:

  - name: jwt-keys
    secret:
      secretName: jwt-keys
      defaultMode: 0600
```

#### Environment Isolation

When deploying ContextForge across multiple environments (DEV, UAT, PROD), you must configure unique JWT settings per environment to prevent tokens from one environment being accepted in another.

**Required per-environment configuration:**

| Setting | DEV | UAT | PROD |
|---------|-----|-----|------|
| `JWT_SECRET_KEY` (or keypair) | Unique | Unique | Unique |
| `JWT_ISSUER` | `mcpgateway-dev` | `mcpgateway-uat` | `mcpgateway-prod` |
| `JWT_AUDIENCE` | `mcpgateway-api-dev` | `mcpgateway-api-uat` | `mcpgateway-api-prod` |

**Example production configuration:**

```bash
# Each environment MUST use different values
JWT_SECRET_KEY="$(openssl rand -base64 32)"  # Or use separate keypairs
JWT_ISSUER=mcpgateway-prod
JWT_AUDIENCE=mcpgateway-api-prod
JWT_ISSUER_VERIFICATION=true
JWT_AUDIENCE_VERIFICATION=true
ENVIRONMENT=production
```

!!! warning "Cross-Environment Token Acceptance"
    If environments share the same JWT signing key and issuer/audience values, tokens created in DEV will be accepted in PROD. The gateway logs warnings at startup when default `JWT_ISSUER` or `JWT_AUDIENCE` values are detected in non-development environments.

**Optional: Environment claim validation**

For additional defense-in-depth, you can embed and validate an environment claim in tokens:

```bash
EMBED_ENVIRONMENT_IN_TOKENS=true   # Adds "env" claim to gateway-issued tokens
VALIDATE_TOKEN_ENVIRONMENT=true    # Rejects tokens with mismatched "env" claim
```

This rejects tokens created for a different environment even if signing keys are accidentally shared. Tokens without an `env` claim are allowed for backward compatibility with existing tokens and external IdP tokens.

### 3. Token Scoping Security

The gateway supports fine-grained token scoping to restrict token access to specific servers, permissions, IP ranges, and time windows. This provides defense-in-depth security for API access.

!!! tip "Detailed RBAC Documentation"
    For comprehensive documentation on token scoping semantics, team-based access control, and visibility filtering, see the [RBAC Configuration Guide](rbac.md).

#### Team-Based Token Scoping

Tokens can be scoped to specific teams using the `teams` JWT claim:

| Token Configuration | Admin User | Non-Admin User |
|---------------------|------------|----------------|
| No `teams` key | Unrestricted | Public-only |
| `teams: null` | Unrestricted | Public-only |
| `teams: []` | Public-only | Public-only |
| `teams: ["team-id"]` | Team + Public | Team + Public |

**Security Default**: Non-admin tokens without explicit team scope default to public-only access (principle of least privilege).

#### Server-Scoped Tokens

Server-scoped tokens are restricted to specific MCP servers and cannot access admin endpoints:

!!! danger "CLI Token Security Warning"
    The examples below use CLI token generation for demonstration. The CLI bypasses all security validations (team membership, permission containment, audit logging). **For production**, use the `/tokens` API endpoint which enforces proper security controls.

```bash
# Generate server-scoped token (DEV/TEST ONLY)
python3 -m mcpgateway.utils.create_jwt_token \
  --username user@example.com \
  --scopes '{"server_id": "my-specific-server"}' \
  --secret my-test-key
```

**Security Features:**

- Server-scoped tokens **cannot access `/admin`** endpoints (security hardening)
- Only truly public endpoints (`/health`, `/ready`) bypass server restrictions
- Documentation endpoints (`/docs`, `/redoc`, `/openapi.json`) are exempt from server scoping but still require auth by default
- RBAC permission checks still apply to all endpoints

#### Permission-Scoped Tokens

Tokens can be restricted to specific permission sets:

```bash
# Generate permission-scoped token (DEV/TEST ONLY)
python3 -m mcpgateway.utils.create_jwt_token \
  --username user@example.com \
  --scopes '{"permissions": ["tools.read", "resources.read"]}' \
  --secret my-test-key
```

**Canonical Permissions Used:**

- `tools.create`, `tools.read`, `tools.update`, `tools.delete`, `tools.execute`
- `resources.create`, `resources.read`, `resources.update`, `resources.delete`
- `admin.system_config`, `admin.user_management`, `admin.security_audit`

### 4. Token Lifecycle Management

ContextForge provides token lifecycle controls including revocation and validation requirements.

#### Token Revocation

Tokens with a `jti` (JWT ID) claim are tracked and can be revoked before expiration:

- Revoked tokens are normally rejected immediately on all endpoints
- Token revocation is checked against the `token_revocations` database table
- Administrators can revoke tokens via the Admin UI or API
- Auth dependencies (`require_auth`, `require_admin_auth`) and MCP transport auth all enforce revocation and active-user checks on the normal path.
- Availability trade-off: when revocation/user lookups fail due to a database outage, these checks currently fail open to preserve availability.

```bash
# Enable token tracking (required for revocation)
REQUIRE_JTI=true
```

#### Token Validation Settings

| Setting | Default | Description |
|---------|---------|-------------|
| `REQUIRE_TOKEN_EXPIRATION` | `true` | Reject tokens without `exp` claim |
| `REQUIRE_JTI` | `true` | Require `jti` claim for token tracking |

These settings are enabled by default for security. For backward compatibility with existing tokens that lack these claims, you can disable them (not recommended for production).

### 5. Admin Route Authentication

The Admin UI (`/admin/*`) enforces additional authentication checks beyond standard API authentication:

#### Authentication Requirements

- **Valid JWT token** with admin privileges, OR
- **Proxy authentication** when `TRUST_PROXY_AUTH=true` (for deployments behind OAuth2 Proxy, Authelia, etc.)

#### Validation Checks

Admin routes perform the following validations:

1. **Token revocation**: Tokens are checked against the revocation list
2. **Account status**: Disabled accounts (`is_active=false`) are blocked
3. **Admin privilege**: User must have `is_admin=true` in their profile

#### Proxy Authentication

For deployments using an authentication proxy:

```bash
# Enable proxy header authentication
TRUST_PROXY_AUTH=true
PROXY_USER_HEADER=X-Forwarded-User    # Header containing authenticated username

# Important: Only enable when ContextForge is behind a trusted proxy
# that properly sets and validates this header
```

### 6. Session Management

The reverse proxy session management (`/reverse-proxy/sessions`) implements access controls:

#### Session Access Rules

| User Type | Access Level |
|-----------|--------------|
| Admin | View all active sessions |
| Regular User | View only their own sessions |
| Unauthenticated | No access (401) |

#### Session Security Features

- **Server-side ID generation**: Session IDs are generated server-side using UUIDs
- **Ownership tracking**: Sessions are associated with the creating user
- **No client-supplied IDs**: Client-provided session ID headers are ignored

### 7. User Registration

Control whether users can self-register accounts:

```bash
# Disable public registration (recommended for production)
PUBLIC_REGISTRATION_ENABLED=false
```

When disabled, only administrators can create user accounts via the Admin UI or API.

### 8. Network Security

- [ ] Configure TLS/HTTPS with valid certificates
- [ ] Implement firewall rules and network policies
- [ ] Use internal-only endpoints where possible
- [ ] Configure appropriate CORS policies (auto-configured by ENVIRONMENT setting)
- [ ] Set up rate limiting per endpoint/client
- [ ] Verify security headers are present (automatically added by SecurityHeadersMiddleware)
- [ ] Configure iframe embedding policy (X_FRAME_OPTIONS=DENY by default, change to SAMEORIGIN if needed)
- [ ] Verify Subresource Integrity (SRI) hashes for CDN resources (automatically verified in CI)

#### Subresource Integrity (SRI)

MCP Gateway implements Subresource Integrity for all external CDN resources to cryptographically verify that fetched resources have not been tampered with. This protects against:

- **CDN Compromise**: Malicious code injection if a CDN is compromised
- **MITM Attacks**: Content modification during transit
- **DNS Hijacking**: Redirection to malicious CDN servers
- **Version Drift**: Unexpected changes to CDN content

**Protected Resources** (15 total):

- HTMX (1.9.10) - Dynamic interactions
- Alpine.js (3.14.1) - Reactive framework
- Chart.js (4.4.1) - Data visualization
- Marked (11.1.1) - Markdown parser
- DOMPurify (3.0.6) - XSS sanitizer
- CodeMirror (5.65.18) - Code editor (7 files)
- Font Awesome (6.4.0) - Icon library

**Verification**:

```bash
# Verify all SRI hashes match current CDN content
make sri-verify

# Regenerate hashes (after updating CDN library versions)
make sri-generate
```

**Updating CDN Libraries**:

When updating a CDN library version:

1. Update the URL in `scripts/cdn_resources.py`
2. Run `make sri-generate` to calculate new hash
3. Update the URL in templates (admin.html, login.html, etc.)
4. Run `make sri-verify` to confirm hash matches
5. Commit both `mcpgateway/sri_hashes.json` and template changes

The CI pipeline automatically verifies SRI hashes on every build to detect unexpected changes.

**Security Checklist**:

- [x] All CDN resources have SRI integrity attributes
- [x] All CDN URLs use exact version numbers (no `@latest`)
- [x] CI verifies hashes match CDN content
- [x] Hashes use SHA-384 algorithm (W3C recommended)
- [ ] Review SRI hashes after any CDN library updates

### 9. Container Security

```bash
# Run containers with security constraints
docker run \
  --read-only \
  --user 1001:1001 \
  --cap-drop ALL \
  --security-opt no-new-privileges \
  mcpgateway:latest
```

- [ ] Use minimal base images (UBI Micro)
- [ ] Run as non-root user
- [ ] Enable read-only filesystem
- [ ] Set resource limits (CPU, memory)
- [ ] Scan images for vulnerabilities

### 10. Secrets Management

- [ ] **Never store secrets in environment variables directly**
- [ ] Use a secrets management system (Vault, AWS Secrets Manager, etc.)
- [ ] Rotate credentials regularly
- [ ] Restrict container access to secrets
- [ ] Never commit `.env` files to version control

### 11. MCP Server Validation

Before connecting any MCP server:

- [ ] Verify server authenticity and source code
- [ ] Review server permissions and data access
- [ ] Test in isolated environment first
- [ ] Monitor server behavior for anomalies
- [ ] Implement rate limiting for untrusted servers

### 12. Database Security

- [ ] Use TLS for database connections
- [ ] Configure strong passwords
- [ ] Restrict database access by IP/network
- [ ] Enable audit logging
- [ ] Regular backups with encryption

### 13. Monitoring & Logging

- [ ] Set up structured logging without sensitive data
- [ ] Configure log rotation and secure storage
- [ ] Implement monitoring and alerting
- [ ] Set up anomaly detection
- [ ] Create incident response procedures

### 14. Integration Security

ContextForge should be integrated with:

- [ ] API Gateway for auth and rate limiting
- [ ] Web Application Firewall (WAF)
- [ ] Identity and Access Management (IAM)
- [ ] SIEM for security monitoring
- [ ] Load balancer with TLS termination

### 15. Well-Known URI Security

Configure well-known URIs appropriately for your deployment:

```bash
# For private APIs (default) - blocks all crawlers
WELL_KNOWN_ENABLED=true
WELL_KNOWN_ROBOTS_TXT="User-agent: *\nDisallow: /"

# For public APIs - allow health checks, block sensitive endpoints
# WELL_KNOWN_ROBOTS_TXT="User-agent: *\nAllow: /health\nAllow: /docs\nDisallow: /admin\nDisallow: /tools"

# Security contact information (RFC 9116)
WELL_KNOWN_SECURITY_TXT="Contact: mailto:security@example.com\nExpires: 2025-12-31T23:59:59Z\nPreferred-Languages: en"
```

Security considerations:

- [ ] Configure security.txt with current contact information
- [ ] Review robots.txt to prevent unauthorized crawler access
- [ ] Monitor well-known endpoint access in logs
- [ ] Update security.txt Expires field before expiration
- [ ] Consider custom well-known files only if necessary

### 16. Downstream Application Security

Applications consuming ContextForge data must:

- [ ] Validate all inputs from the gateway
- [ ] Implement context-appropriate sanitization
- [ ] Use Content Security Policy (CSP) headers
- [ ] Escape data for output context (HTML, JS, SQL)
- [ ] Implement their own authentication/authorization

## 🔐 Environment Variables Reference

### Security-Critical Settings

```bash
# Core Security
MCPGATEWAY_UI_ENABLED=false              # Must be false in production
MCPGATEWAY_ADMIN_API_ENABLED=false       # Must be false in production
AUTH_REQUIRED=true                       # Enforce auth for every request
API_ALLOW_BASIC_AUTH=false               # Keep disabled (use JWT instead)
DOCS_ALLOW_BASIC_AUTH=false              # Keep disabled (use JWT instead)

# Feature Flags (disable unused features)
MCPGATEWAY_BULK_IMPORT_ENABLED=false
MCPGATEWAY_A2A_ENABLED=false
PUBLIC_REGISTRATION_ENABLED=false        # Disable user self-registration

# Token Security
REQUIRE_TOKEN_EXPIRATION=true            # Reject tokens without exp claim
REQUIRE_JTI=true                         # Require JWT ID for revocation support

# Network Security
CORS_ENABLED=true
ALLOWED_ORIGINS=https://your-domain.com
SECURITY_HEADERS_ENABLED=true

# Logging (no sensitive data)
LOG_LEVEL=INFO               # Avoid DEBUG in production
LOG_TO_FILE=false            # Disable file logging unless required
LOG_ROTATION_ENABLED=false   # Enable only when log files are needed
```

> **Rate limiting:** ContextForge does not ship a built-in global rate limiter. Enforce
> request throttling at an upstream ingress (NGINX, Envoy, API gateway) before traffic
> reaches the service.

## 🚀 Deployment Architecture

### Recommended Production Architecture

```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│                 │     │                 │     │                 │
│   WAF/CDN       │────▶│  Load Balancer │────▶│   API Gateway   │
│                 │     │   (TLS Term)    │     │  (Auth/Rate)    │
└─────────────────┘     └─────────────────┘     └────────┬────────┘
                                                          │
                                                          ▼
                                                 ┌─────────────────┐
                                                 │                 │
                                                 │  ContextForge    │
                                                 │  (Internal)     │
                                                 └────────┬────────┘
                                                          │
                              ┌───────────────────────────┼───────────────────────────┐
                              │                           │                           │
                              ▼                           ▼                           ▼
                     ┌─────────────────┐        ┌─────────────────┐        ┌─────────────────┐
                     │                 │        │                 │        │                 │
                     │  Trusted MCP    │        │    Database     │        │     Redis       │
                     │    Servers      │        │   (TLS/Auth)    │        │   (TLS/Auth)    │
                     └─────────────────┘        └─────────────────┘        └─────────────────┘
```

## 🔍 Security Validation

### Pre-Production Checklist

1. **Run Security Scans**
   ```bash
   make security-all        # Run all security tools
   make security-report     # Generate security report
   make trivy              # Scan container vulnerabilities
   ```

2. **Validate Configuration**

   - Review all environment variables
   - Confirm admin features disabled
   - Verify authentication enabled
   - Check TLS configuration
   - Confirm `REQUIRE_JTI=true` for token tracking
   - Confirm `REQUIRE_TOKEN_EXPIRATION=true`
   - Confirm `PUBLIC_REGISTRATION_ENABLED=false`

3. **Test Security Controls**

   - Attempt unauthorized access
   - Verify rate limiting works
   - Test input validation
   - Check error handling

4. **Review Dependencies**
   ```bash
   make pip-audit          # Check Python dependencies
   make sbom              # Generate software bill of materials
   ```

## 📚 Additional Resources

- [Security Policy](https://github.com/IBM/mcp-context-forge/blob/main/SECURITY.md) - Full security documentation
- [Deployment Options](index.md) - Various deployment methods
- [Environment Variables](configuration.md) - Complete configuration reference

## ⚡ Quick Start Security Commands

```bash
# Development (with security checks)
make security-all && make test && make run

# Production build
make docker-prod

# Security audit
make security-report
```

Remember: **Security is a shared responsibility**. ContextForge provides *some* security controls, but you must properly configure and integrate it within a comprehensive security architecture.
