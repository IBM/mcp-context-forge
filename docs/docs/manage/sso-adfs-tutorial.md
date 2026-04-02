# ADFS SSO Integration Testing Guide

This document provides testing instructions and curl commands for the ADFS SSO integration in MCP Context Forge.

## Overview

The ADFS integration extracts user information directly from the ID token instead of calling the userinfo endpoint, which is the standard approach for ADFS since it doesn't support GET requests on the userinfo endpoint.

## Configuration

### Environment Variables

Set the following environment variables in your `.env` file or Kubernetes deployment:

```bash
# Enable SSO and ADFS
SSO_ENABLED=true
SSO_ADFS_ENABLED=true

# ADFS Configuration
SSO_ADFS_CLIENT_ID=your-adfs-client-id
SSO_ADFS_CLIENT_SECRET=your-adfs-client-secret  # pragma: allowlist secret
SSO_ADFS_AUTHORIZATION_URL=https://adfs.ds.example.net/adfs/oauth2/authorize/
SSO_ADFS_TOKEN_URL=https://adfs.ds.example.net/adfs/oauth2/token/
SSO_ADFS_ISSUER=https://adfs.ds.example.net/adfs
SSO_ADFS_SCOPE=openid profile email
SSO_ADFS_DISPLAY_NAME=ADFS Login

# Common SSO Settings
SSO_AUTO_CREATE_USERS=true
SSO_PRESERVE_ADMIN_AUTH=true
```

### Helm Chart Configuration

Update `charts/mcp-stack/values.yaml`:

```yaml
mcpContextForge:
  env:
    SSO_ENABLED: "true"
    SSO_ADFS_ENABLED: "true"
    SSO_ADFS_CLIENT_ID: "your-adfs-client-id"
    SSO_ADFS_CLIENT_SECRET: "your-adfs-client-secret"  # pragma: allowlist secret
    SSO_ADFS_AUTHORIZATION_URL: "https://adfs.ds.example.net/adfs/oauth2/authorize/"
    SSO_ADFS_TOKEN_URL: "https://adfs.ds.example.net/adfs/oauth2/token/"
    SSO_ADFS_ISSUER: "https://adfs.ds.example.net/adfs"
    SSO_ADFS_SCOPE: "openid profile email"
    SSO_ADFS_DISPLAY_NAME: "ADFS Login"
```

## Testing Steps

### 1. Verify ADFS Provider Registration

Check that the ADFS provider is registered in the database:

```bash
# Get JWT token for admin access
export MCPGATEWAY_BEARER_TOKEN=$(python -m mcpgateway.utils.create_jwt_token \
  --username admin@example.com \
  --exp 10080 \
  --secret YOUR_JWT_SECRET_KEY)

# List all SSO providers (admin endpoint)
curl -X GET "https://mcpgateway-dev.example.net/auth/sso/admin/providers" \
  -H "Authorization: Bearer ${MCPGATEWAY_BEARER_TOKEN}" \
  -H "Content-Type: application/json" | jq .
```

Expected response should include an ADFS provider (returns a bare list):

```json
[
  {
    "id": "adfs",
    "name": "adfs",
    "display_name": "ADFS Login",
    "provider_type": "oidc",
    "is_enabled": true,
    "authorization_url": "https://adfs.ds.example.net/adfs/oauth2/authorize/",
    "token_url": "https://adfs.ds.example.net/adfs/oauth2/token/",
    "issuer": "https://adfs.ds.example.net/adfs"
  }
]
```

### 2. Test ADFS Login Flow

#### Step 2.1: Initiate Login

Use curl to get the authorization URL (the endpoint returns JSON, not a redirect):

```bash
curl -s "https://mcpgateway-dev.example.net/auth/sso/login/adfs?redirect_uri=https://mcpgateway-dev.example.net/auth/sso/callback/adfs" | jq .
```

Expected response:

```json
{
  "authorization_url": "https://adfs.ds.example.net/adfs/oauth2/authorize/?client_id=...&state=...&code_challenge=...",
  "state": "adfs.xxxxxxxx"
}
```

Open the `authorization_url` in your browser to start the ADFS login flow.

#### Step 2.2: Complete ADFS Authentication

1. Enter your ADFS credentials on the ADFS login page
2. Approve the OAuth consent (if prompted)
3. You will be redirected back to the callback URL with an authorization code

#### Step 2.3: Verify Callback Processing

The callback endpoint will:
1. Exchange the authorization code for tokens (access_token and id_token)
2. Extract user information from the ID token (not from userinfo endpoint)
3. Create or update the user in the database
4. Set authentication cookies
5. Redirect to the application

### 3. Manual Token Exchange Testing

If you have an authorization code from ADFS, you can manually test the token exchange:

```bash
# Replace with your actual values
ADFS_TOKEN_URL="https://adfs.ds.example.net/adfs/oauth2/token/"
CLIENT_ID="your-adfs-client-id"
CLIENT_SECRET="your-adfs-client-secret"  # pragma: allowlist secret
REDIRECT_URI="https://mcpgateway-dev.example.net/auth/sso/callback/adfs"
AUTH_CODE="your-authorization-code"

# Exchange authorization code for tokens
curl -X POST "${ADFS_TOKEN_URL}" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "grant_type=authorization_code" \
  -d "code=${AUTH_CODE}" \
  -d "client_id=${CLIENT_ID}" \
  -d "client_secret=${CLIENT_SECRET}" \
  -d "redirect_uri=${REDIRECT_URI}" | jq .
```

Expected response:

```json
{
  "access_token": "eyJ0eXAiOiJKV1QiLCJhbGc...",
  "token_type": "Bearer",
  "expires_in": 3600,
  "id_token": "eyJ0eXAiOiJKV1QiLCJhbGc..."
}
```

### 4. Decode and Verify ID Token

You can decode the ID token to verify the claims:

```bash
# Extract the ID token from the response above
ID_TOKEN="eyJ0eXAiOiJKV1QiLCJhbGc..."

# Decode the payload (middle part of JWT)
echo $ID_TOKEN | cut -d'.' -f2 | base64 -d 2>/dev/null | jq .
```

Expected claims in ADFS ID token:

```json
{
  "aud": "your-adfs-client-id",
  "iss": "https://adfs.ds.example.net/adfs",
  "iat": 1234567890,
  "exp": 1234571490,
  "sub": "user-unique-id",
  "upn": "user@example.com",
  "unique_name": "DOMAIN\\username",
  "email": "user@example.com",
  "name": "John Doe",
  "given_name": "John",
  "family_name": "Doe",
  "groups": ["group1", "group2"]
}
```

### 5. Verify User Creation

After successful login, verify the user was created in the database:

```bash
# List users
curl -X GET "https://mcpgateway-dev.example.net/admin/users" \
  -H "Authorization: Bearer ${MCPGATEWAY_BEARER_TOKEN}" \
  -H "Content-Type: application/json" | jq '.users[] | select(.auth_provider == "adfs")'
```

Expected response:

```json
{
  "id": "user-uuid",
  "email": "user@example.com",
  "full_name": "John Doe",
  "auth_provider": "adfs",
  "is_admin": false,
  "is_active": true,
  "created_at": "2026-03-11T12:00:00Z"
}
```

## Troubleshooting

### Issue: "User info request failed for adfs: HTTP 405"

**Cause**: The application is trying to call the userinfo endpoint with GET method, which ADFS doesn't support.

**Solution**: This issue is fixed in the updated code. The application now extracts user info from the ID token instead of calling the userinfo endpoint.

### Issue: "Failed to decode ADFS ID token claims"

**Cause**: The ID token is malformed or not present in the token response.

**Solution**:
1. Verify that ADFS is configured to return an ID token
2. Check that the `openid` scope is included in the authorization request
3. Review ADFS logs for any token generation errors

### Issue: "ADFS provider requires id_token in token_data but it was not provided"

**Cause**: The token exchange response doesn't include an ID token.

**Solution**:
1. Ensure the `openid` scope is included in `SSO_ADFS_SCOPE`
2. Verify ADFS is configured to issue ID tokens for your client application
3. Check ADFS relying party trust settings

### Issue: User email is missing or incorrect

**Cause**: ADFS may use different claim names for email.

**Solution**: The code checks multiple claims in priority order:
1. `email`
2. `preferred_username`
3. `upn` (User Principal Name)
4. `unique_name`

If none of these contain the email, configure ADFS to include the email claim in the ID token.

## Logs to Monitor

When testing, monitor these log entries:

```bash
# Successful token exchange
"Starting token exchange for provider adfs"
"Token exchange successful for provider adfs"

# User info extraction from ID token (debug level)
"ADFS: using decoded id_token claims (keys: [...])"

# User creation
"Created SSO provider: ADFS Login"
```

## Security Considerations

1. **Always use HTTPS** for ADFS endpoints in production
2. **Protect client secrets** - never commit them to version control
3. **Validate redirect URIs** - ensure they match your application's callback URL
4. **Token expiration** - ADFS tokens typically expire after 1 hour
5. **Scope limitations** - only request the scopes your application needs

## Additional Resources

- [ADFS OAuth 2.0 Documentation](https://docs.microsoft.com/en-us/windows-server/identity/ad-fs/overview/ad-fs-openid-connect-oauth-flows-scenarios)
- [MCP Context Forge SSO Documentation](./sso.md)
- [RBAC Configuration](./rbac.md)
