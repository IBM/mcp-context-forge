# Generic OIDC Provider Setup Tutorial

This tutorial walks you through setting up generic OpenID Connect (OIDC) Single Sign-On (SSO) authentication for MCP Gateway, enabling integration with any OIDC-compliant identity provider including Keycloak, Auth0, Authentik, and others.

## Overview

The Generic OIDC provider support allows you to integrate MCP Gateway with any standards-compliant OpenID Connect provider. This flexibility enables you to use your existing identity infrastructure regardless of the vendor.

**Supported Providers** (non-exhaustive):

- Keycloak
- Auth0
- Authentik
- Authelia
- Ory Hydra
- GitLab (as OIDC provider)
- Casdoor
- FusionAuth
- Any other OIDC-compliant provider

## Prerequisites

- MCP Gateway installed and running
- Access to your OIDC provider's admin console
- Ability to create OAuth/OIDC applications in your provider
- Access to your gateway's environment configuration
- HTTPS enabled on your gateway (recommended for production)

## Understanding OIDC Discovery

Most OIDC providers support automatic discovery via the `.well-known/openid-configuration` endpoint:

```bash
# Example discovery endpoints
https://keycloak.company.com/auth/realms/master/.well-known/openid-configuration
https://your-tenant.auth0.com/.well-known/openid-configuration
https://authentik.company.com/application/o/app-name/.well-known/openid-configuration
```

This endpoint returns all necessary URLs for OIDC integration. You can use `curl` or a browser to view it:

```bash
curl https://your-provider.com/.well-known/openid-configuration | jq .
```

Look for these key fields:

- `authorization_endpoint` → `SSO_GENERIC_AUTHORIZATION_URL`
- `token_endpoint` → `SSO_GENERIC_TOKEN_URL`
- `userinfo_endpoint` → `SSO_GENERIC_USERINFO_URL`
- `issuer` → `SSO_GENERIC_ISSUER`

## Step 1: Choose Your Provider ID

Select a unique identifier for your provider. This will be used in URLs and configuration.

**Guidelines**:

- Use lowercase alphanumeric characters and hyphens
- Common choices: `keycloak`, `auth0`, `authentik`, `gitlab`, `custom-sso`
- Avoid: `github`, `google`, `okta`, `entra`, `ibm_verify` (reserved for built-in providers)

**Example**: If using Keycloak, you might choose `keycloak` or `company-sso`

This becomes your callback URL:
```
https://gateway.yourcompany.com/auth/sso/callback/{provider_id}
```

## Step 2: Configure Your OIDC Provider

Choose your provider below for specific setup instructions:

### Option A: Keycloak Setup

#### 2A.1 Create Client Application

1. Log in to **Keycloak Admin Console**
2. Select your realm (e.g., `master` or custom realm)
3. Go to **Clients** → **Create client**

**Settings**:

- **Client type**: `OpenID Connect`
- **Client ID**: `mcp-gateway` (or your choice)
- **Client authentication**: `ON` (confidential client)
- **Authorization**: `OFF` (not needed for SSO)

#### 2A.2 Configure Client Settings

**Access Settings**:

- **Root URL**: `https://gateway.yourcompany.com`
- **Home URL**: `https://gateway.yourcompany.com/admin`
- **Valid redirect URIs**: `https://gateway.yourcompany.com/auth/sso/callback/keycloak`
- **Valid post logout redirect URIs**: `https://gateway.yourcompany.com/admin/login`
- **Web origins**: `https://gateway.yourcompany.com`

**Advanced Settings**:

- **Access Token Lifespan**: 5 minutes (default is fine)
- **Client authentication**: ON
- **Standard flow**: Enabled (Authorization Code Flow)
- **Direct access grants**: Disabled (not needed)

#### 2A.3 Get Client Credentials

1. Go to **Clients** → Select your client → **Credentials** tab
2. Copy the **Client secret**
3. Note your realm name from the URL

**Your endpoints will be**:
```bash
# For realm "master" on keycloak.company.com:
Authorization: https://keycloak.company.com/auth/realms/master/protocol/openid-connect/auth
Token:         https://keycloak.company.com/auth/realms/master/protocol/openid-connect/token
Userinfo:      https://keycloak.company.com/auth/realms/master/protocol/openid-connect/userinfo
Issuer:        https://keycloak.company.com/auth/realms/master
```

#### 2A.4 Configure Scopes (Optional)

1. Go to **Client scopes** tab
2. Ensure these scopes are in **Assigned default client scopes**:
   - `openid` (required)
   - `profile` (recommended)
   - `email` (recommended)

#### 2A.5 Map User Attributes (Optional)

To ensure proper user info:

1. Go to **Clients** → Your client → **Client scopes**
2. Click on **profile** scope
3. Verify these mappers exist:
   - `email` → User attribute `email`
   - `given_name` → User attribute `firstName`
   - `family_name` → User attribute `lastName`
   - `preferred_username` → User attribute `username`

### Option B: Auth0 Setup

#### 2B.1 Create Application

1. Log in to [Auth0 Dashboard](https://manage.auth0.com/)
2. Go to **Applications** → **Applications**
3. Click **+ Create Application**

**Settings**:

- **Name**: `MCP Gateway`
- **Application type**: `Regular Web Applications`
- Click **Create**

#### 2B.2 Configure Application Settings

In the application settings:

**Application URIs**:

- **Allowed Callback URLs**: `https://gateway.yourcompany.com/auth/sso/callback/auth0`
- **Allowed Logout URLs**: `https://gateway.yourcompany.com/admin/login`
- **Allowed Web Origins**: `https://gateway.yourcompany.com`

**Advanced Settings** → **Grant Types**:

- ✅ Authorization Code
- ✅ Refresh Token (optional)
- ❌ Implicit (not needed)

Click **Save Changes**

#### 2B.3 Get Client Credentials

In the **Settings** tab:

- Copy **Domain**: `your-tenant.auth0.com`
- Copy **Client ID**
- Copy **Client Secret**

**Your endpoints will be**:
```bash
Authorization: https://your-tenant.auth0.com/authorize
Token:         https://your-tenant.auth0.com/oauth/token
Userinfo:      https://your-tenant.auth0.com/userinfo
Issuer:        https://your-tenant.auth0.com/
```

#### 2B.4 Configure Connection (Optional)

1. Go to **Authentication** → **Database** or **Enterprise**
2. Configure your identity source (Active Directory, LDAP, etc.)
3. Enable the connection for your application

### Option C: Authentik Setup

#### 2C.1 Create Provider

1. Log in to **Authentik Admin Interface**
2. Go to **Applications** → **Providers**
3. Click **Create**

**Provider Settings**:

- **Name**: `MCP Gateway Provider`
- **Type**: `OAuth2/OpenID Provider`
- **Client type**: `Confidential`
- **Client ID**: Auto-generated or custom
- **Client Secret**: Auto-generated (copy this)
- **Redirect URIs**: `https://gateway.yourcompany.com/auth/sso/callback/authentik`

**Advanced Settings**:

- **Scopes**: `openid profile email`
- **Subject mode**: `Based on the User's hashed ID`
- **Include claims in id_token**: Yes

Click **Create**

#### 2C.2 Create Application

1. Go to **Applications** → **Applications**
2. Click **Create**

**Application Settings**:

- **Name**: `MCP Gateway`
- **Slug**: `mcp-gateway`
- **Provider**: Select the provider you just created
- **Launch URL**: `https://gateway.yourcompany.com/admin`

#### 2C.3 Get Configuration

**Your endpoints will be**:
```bash
# Assuming app slug is "mcp-gateway"
Authorization: https://authentik.company.com/application/o/authorize/
Token:         https://authentik.company.com/application/o/token/
Userinfo:      https://authentik.company.com/application/o/userinfo/
Issuer:        https://authentik.company.com/application/o/mcp-gateway/
```

**Note**: Authentik URLs typically include the application slug in the issuer URL.

## Step 3: Configure MCP Gateway

### 3.1 Basic Configuration

Add these variables to your `.env` file:

```bash
# Enable SSO System
SSO_ENABLED=true

# Generic OIDC Provider Configuration
SSO_GENERIC_ENABLED=true
SSO_GENERIC_PROVIDER_ID=keycloak  # Change to your chosen ID
SSO_GENERIC_DISPLAY_NAME=Company SSO  # Display name on login button
SSO_GENERIC_CLIENT_ID=your-client-id
SSO_GENERIC_CLIENT_SECRET=your-client-secret
SSO_GENERIC_AUTHORIZATION_URL=https://your-provider.com/auth
SSO_GENERIC_TOKEN_URL=https://your-provider.com/token
SSO_GENERIC_USERINFO_URL=https://your-provider.com/userinfo
SSO_GENERIC_ISSUER=https://your-provider.com
SSO_GENERIC_SCOPE=openid profile email  # Optional, this is the default

# Optional: Auto-create users on first login
SSO_AUTO_CREATE_USERS=true

# Optional: Restrict to corporate email domains
SSO_TRUSTED_DOMAINS=["yourcompany.com"]

# Optional: Preserve local admin authentication
SSO_PRESERVE_ADMIN_AUTH=true
```

### 3.2 Keycloak Configuration Example

```bash
# Keycloak on keycloak.company.com with realm "master"
SSO_ENABLED=true
SSO_GENERIC_ENABLED=true
SSO_GENERIC_PROVIDER_ID=keycloak
SSO_GENERIC_DISPLAY_NAME=Company SSO
SSO_GENERIC_CLIENT_ID=mcp-gateway
SSO_GENERIC_CLIENT_SECRET=AbC123dEf456GhI789jKl012MnO345pQr678StU901vWx234YzA567
SSO_GENERIC_AUTHORIZATION_URL=https://keycloak.company.com/auth/realms/master/protocol/openid-connect/auth
SSO_GENERIC_TOKEN_URL=https://keycloak.company.com/auth/realms/master/protocol/openid-connect/token
SSO_GENERIC_USERINFO_URL=https://keycloak.company.com/auth/realms/master/protocol/openid-connect/userinfo
SSO_GENERIC_ISSUER=https://keycloak.company.com/auth/realms/master
SSO_AUTO_CREATE_USERS=true
SSO_TRUSTED_DOMAINS=["company.com"]
```

### 3.3 Auth0 Configuration Example

```bash
# Auth0 tenant
SSO_ENABLED=true
SSO_GENERIC_ENABLED=true
SSO_GENERIC_PROVIDER_ID=auth0
SSO_GENERIC_DISPLAY_NAME=Auth0
SSO_GENERIC_CLIENT_ID=AbCdEfGhIjKlMnOpQrStUvWx
SSO_GENERIC_CLIENT_SECRET=1234567890abcdefghijklmnopqrstuvwxyz1234567890ABCDEFG
SSO_GENERIC_AUTHORIZATION_URL=https://your-tenant.auth0.com/authorize
SSO_GENERIC_TOKEN_URL=https://your-tenant.auth0.com/oauth/token
SSO_GENERIC_USERINFO_URL=https://your-tenant.auth0.com/userinfo
SSO_GENERIC_ISSUER=https://your-tenant.auth0.com/
SSO_AUTO_CREATE_USERS=true
SSO_TRUSTED_DOMAINS=["company.com"]
```

### 3.4 Authentik Configuration Example

```bash
# Authentik with application slug "mcp-gateway"
SSO_ENABLED=true
SSO_GENERIC_ENABLED=true
SSO_GENERIC_PROVIDER_ID=authentik
SSO_GENERIC_DISPLAY_NAME=Authentik SSO
SSO_GENERIC_CLIENT_ID=generated-client-id-from-authentik
SSO_GENERIC_CLIENT_SECRET=generated-client-secret-from-authentik
SSO_GENERIC_AUTHORIZATION_URL=https://authentik.company.com/application/o/authorize/
SSO_GENERIC_TOKEN_URL=https://authentik.company.com/application/o/token/
SSO_GENERIC_USERINFO_URL=https://authentik.company.com/application/o/userinfo/
SSO_GENERIC_ISSUER=https://authentik.company.com/application/o/mcp-gateway/
SSO_AUTO_CREATE_USERS=true
SSO_TRUSTED_DOMAINS=["company.com"]
```

### 3.5 Development Configuration

For local testing:

```bash
# Development setup with HTTP (not recommended for production)
SSO_ENABLED=true
SSO_GENERIC_ENABLED=true
SSO_GENERIC_PROVIDER_ID=keycloak-dev
SSO_GENERIC_DISPLAY_NAME=Dev SSO
SSO_GENERIC_CLIENT_ID=dev-client-id
SSO_GENERIC_CLIENT_SECRET=dev-client-secret
SSO_GENERIC_AUTHORIZATION_URL=http://localhost:8080/auth/realms/master/protocol/openid-connect/auth
SSO_GENERIC_TOKEN_URL=http://localhost:8080/auth/realms/master/protocol/openid-connect/token
SSO_GENERIC_USERINFO_URL=http://localhost:8080/auth/realms/master/protocol/openid-connect/userinfo
SSO_GENERIC_ISSUER=http://localhost:8080/auth/realms/master
SSO_AUTO_CREATE_USERS=true
SSO_PRESERVE_ADMIN_AUTH=true

# Note: Update callback URL in provider to:
# http://localhost:4444/auth/sso/callback/keycloak-dev
```

## Step 4: Verify OIDC Endpoints

Before starting the gateway, verify your provider's endpoints are accessible:

```bash
# Test authorization endpoint (should return HTML page or redirect)
curl -I https://your-provider.com/auth

# Test discovery endpoint
curl https://your-provider.com/.well-known/openid-configuration | jq .

# Verify these match your configuration:
# - authorization_endpoint
# - token_endpoint
# - userinfo_endpoint
# - issuer
```

## Step 5: Start and Verify Gateway

### 5.1 Restart the Gateway

```bash
# Development
make dev

# Production
make serve

# Docker
docker-compose restart gateway
```

### 5.2 Verify Generic OIDC Provider is Listed

```bash
# Check if your provider appears in the list
curl -X GET http://localhost:8000/auth/sso/providers

# Should include your provider:
[
  {
    "id": "keycloak",
    "name": "keycloak",
    "display_name": "Company SSO"
  }
]
```

### 5.3 Check Startup Logs

```bash
# Look for SSO initialization messages
tail -f logs/gateway.log | grep -i sso

# Should see:
# ✅ Created SSO provider: Company SSO
# or
# 🔄 Updated SSO provider: Company SSO
```

## Step 6: Test OIDC Login Flow

### 6.1 Access Login Page

1. Navigate to your gateway's login page:
   - Development: `http://localhost:8000/admin/login`
   - Production: `https://gateway.yourcompany.com/admin/login`

2. You should see a button with your configured `SSO_GENERIC_DISPLAY_NAME`

### 6.2 Test Authentication Flow

1. Click the **Company SSO** button (or your display name)
2. You'll be redirected to your OIDC provider's sign-in page
3. Enter your credentials
4. Complete any MFA if configured
5. Grant consent if prompted (first-time users)
6. You'll be redirected back to the gateway
7. You should be logged in successfully

### 6.3 Verify User Creation

Check that a user was created:

```bash
# Using admin API (requires admin token)
curl -H "Authorization: Bearer YOUR_ADMIN_TOKEN" \
  http://localhost:8000/auth/users

# Look for your email in the user list
```

### 6.4 Verify User Profile

```bash
# Get user details
curl -H "Authorization: Bearer YOUR_ADMIN_TOKEN" \
  http://localhost:8000/auth/users/{user_id}

# Verify fields:
# - email: your@company.com
# - full_name: First Last
# - provider: keycloak (or your provider_id)
# - provider_id: unique-user-id-from-provider
```

## Step 7: Advanced Configuration

### 7.1 Custom Scopes

Add additional scopes if your provider supports them:

```bash
# Example: Add group membership scope
SSO_GENERIC_SCOPE=openid profile email groups roles

# Or organization access
SSO_GENERIC_SCOPE=openid profile email read:org
```

Verify your provider supports these scopes in their documentation.

### 7.2 Multiple OIDC Providers

To configure multiple generic providers, use the Admin API:

```bash
# Create additional providers via API
curl -X POST http://localhost:8000/auth/sso/admin/providers \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "id": "gitlab",
    "name": "gitlab",
    "display_name": "GitLab",
    "provider_type": "oidc",
    "client_id": "gitlab-client-id",
    "client_secret": "gitlab-client-secret",
    "authorization_url": "https://gitlab.com/oauth/authorize",
    "token_url": "https://gitlab.com/oauth/token",
    "userinfo_url": "https://gitlab.com/oauth/userinfo",
    "issuer": "https://gitlab.com",
    "scope": "openid profile email",
    "trusted_domains": ["company.com"],
    "auto_create_users": true
  }'
```

### 7.3 Trusted Domains

Restrict access to specific email domains:

```bash
# Single domain
SSO_TRUSTED_DOMAINS=["company.com"]

# Multiple domains
SSO_TRUSTED_DOMAINS=["company.com", "partner.com", "contractor.net"]
```

Users with email addresses outside these domains will be rejected.

### 7.4 Team Mapping (Advanced)

Configure automatic team assignment using the Admin API:

```bash
# Update provider with team mapping
curl -X PUT http://localhost:8000/auth/sso/admin/providers/keycloak \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "team_mapping": {
      "engineering": {
        "team_id": "uuid-of-engineering-team",
        "role": "member"
      },
      "admin": {
        "team_id": "uuid-of-admin-team",
        "role": "owner"
      }
    }
  }'
```

## Troubleshooting

### Error: "SSO authentication is disabled"

**Problem**: SSO endpoints return 404
**Solution**: Verify `SSO_ENABLED=true` and `SSO_GENERIC_ENABLED=true`, then restart

```bash
curl -I http://localhost:8000/auth/sso/providers
# Should return 200 OK
```

### Error: "invalid_client"

**Problem**: Client ID or secret is incorrect
**Solution**: Verify credentials match your provider exactly

```bash
# Double-check these values from your provider
SSO_GENERIC_CLIENT_ID=actual-client-id-from-provider
SSO_GENERIC_CLIENT_SECRET=actual-secret-from-provider
```

### Error: "redirect_uri_mismatch"

**Problem**: Callback URL doesn't match provider configuration
**Solution**: Ensure exact match including protocol and trailing slashes

```bash
# Provider configuration must exactly match:
https://gateway.yourcompany.com/auth/sso/callback/keycloak

# Common mistakes:
https://gateway.yourcompany.com/auth/sso/callback/keycloak/  # Extra slash
http://gateway.yourcompany.com/auth/sso/callback/keycloak   # HTTP vs HTTPS
https://gateway.yourcompany.com/auth/sso/callback/generic   # Wrong provider_id
```

### Error: "invalid_scope"

**Problem**: Requested scope not supported by provider
**Solution**: Check provider documentation for supported scopes

```bash
# Start with minimal scopes
SSO_GENERIC_SCOPE=openid profile email

# Add scopes incrementally after testing
```

### Error: "issuer mismatch"

**Problem**: Token issuer doesn't match configured issuer
**Solution**: Verify issuer URL format matches provider exactly

```bash
# Check discovery endpoint
curl https://your-provider.com/.well-known/openid-configuration | jq '.issuer'

# Ensure SSO_GENERIC_ISSUER matches exactly (including trailing slash)
SSO_GENERIC_ISSUER=https://your-provider.com/  # Note the trailing slash if needed
```

### Token Validation Errors

**Problem**: JWT tokens failing validation
**Solution**: Enable debug logging to see token validation details

```bash
# Enable debug logging
LOG_LEVEL=DEBUG

# Check logs for token validation errors
tail -f logs/gateway.log | grep -i token
```

### User Info Endpoint Issues

**Problem**: User profile incomplete or missing
**Solution**: Verify userinfo endpoint and scope configuration

```bash
# Test userinfo endpoint directly
curl -H "Authorization: Bearer $ACCESS_TOKEN" \
  https://your-provider.com/userinfo

# Should return user profile JSON
# Verify email, name, and preferred_username fields exist
```

### Certificate/SSL Errors

**Problem**: SSL certificate verification failing
**Solution**: For development only, you can skip verification (not recommended for production)

```bash
# Development only - DO NOT use in production
SKIP_SSL_VERIFY=true
```

For production, fix the certificate issue at the provider level.

## Testing Checklist

- [ ] Provider application created with correct settings
- [ ] Client ID and secret obtained
- [ ] Redirect URI configured correctly
- [ ] Required scopes configured
- [ ] Discovery endpoint accessible
- [ ] Environment variables configured
- [ ] Gateway restarted
- [ ] Provider appears in `/auth/sso/providers` list
- [ ] Login page shows provider button
- [ ] Authentication flow completes
- [ ] User created in gateway
- [ ] User profile populated
- [ ] Email domain restriction working (if configured)
- [ ] Logout redirects correctly

## Security Best Practices

### Secret Management

**DO**:

- ✅ Store secrets in environment variables or secret management systems
- ✅ Use strong, randomly generated client secrets
- ✅ Rotate secrets regularly (every 90-180 days)
- ✅ Use separate credentials for dev/staging/prod
- ✅ Enable HTTPS for all redirect URIs

**DON'T**:

- ❌ Store secrets in source control
- ❌ Share secrets via email or chat
- ❌ Use the same credentials across environments
- ❌ Use HTTP in production

### Access Control

1. **Trusted Domains**: Always configure `SSO_TRUSTED_DOMAINS` in production
2. **User Review**: Implement user approval workflows if needed
3. **Scope Minimization**: Only request necessary scopes
4. **Regular Audits**: Review user access quarterly

### Provider Security

1. **Enable MFA** on your OIDC provider
2. **Configure session timeouts** appropriately
3. **Enable audit logging** for all authentication events
4. **Monitor failed login attempts**
5. **Review access logs** regularly

## Next Steps

After Generic OIDC SSO is working:

1. **Configure team mappings** for automatic team assignment
2. **Set up additional providers** via Admin API if needed
3. **Enable MFA** on your OIDC provider
4. **Configure conditional access** policies (provider-specific)
5. **Set up monitoring** for authentication events
6. **Document your configuration** for team reference

## Provider-Specific Resources

### Keycloak
- [Keycloak Documentation](https://www.keycloak.org/documentation)
- [Client Configuration Guide](https://www.keycloak.org/docs/latest/server_admin/#_clients)
- [Client Authentication](https://www.keycloak.org/docs/latest/server_admin/#_client-credentials)

### Auth0
- [Auth0 Documentation](https://auth0.com/docs)
- [Application Settings](https://auth0.com/docs/get-started/applications)
- [Configure OpenID Connect](https://auth0.com/docs/authenticate/protocols/openid-connect-protocol)

### Authentik
- [Authentik Documentation](https://goauthentik.io/docs/)
- [OAuth2/OIDC Provider](https://goauthentik.io/docs/providers/oauth2)
- [Application Configuration](https://goauthentik.io/docs/applications)

## Related Documentation

- [Complete SSO Guide](sso.md) - Full SSO documentation
- [Microsoft Entra ID Tutorial](sso-microsoft-entra-id-tutorial.md) - Entra ID setup
- [GitHub SSO Tutorial](sso-github-tutorial.md) - GitHub setup
- [Google SSO Tutorial](sso-google-tutorial.md) - Google setup
- [Team Management](teams.md) - Managing teams and roles
- [RBAC Configuration](rbac.md) - Role-based access control

## Support

### Getting Help

If you encounter issues:

1. Check provider's authentication logs for error details
2. Enable debug logging: `LOG_LEVEL=DEBUG`
3. Review gateway logs for OIDC-specific errors
4. Test provider endpoints directly with curl
5. Verify all URLs match provider documentation exactly
6. Consult provider-specific documentation
7. Check [MCP Gateway issue tracker](https://github.com/IBM/mcp-context-forge/issues)

### Common OIDC Standards

- [OpenID Connect Core 1.0](https://openid.net/specs/openid-connect-core-1_0.html)
- [OAuth 2.0 Authorization Framework](https://datatracker.ietf.org/doc/html/rfc6749)
- [OpenID Connect Discovery](https://openid.net/specs/openid-connect-discovery-1_0.html)
