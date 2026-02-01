# GitHub SSO Setup Tutorial

This tutorial walks you through setting up GitHub Single Sign-On (SSO) authentication for MCP Gateway, allowing users to log in with their GitHub accounts.

## Prerequisites

- MCP Gateway installed and running
- GitHub account with admin access to create OAuth apps
- Access to your gateway's environment configuration

## Step 1: Create GitHub OAuth Application

### 1.1 Navigate to GitHub Settings

1. Log into GitHub and go to **Settings** (click your profile picture → Settings)
2. In the left sidebar, click **Developer settings**
3. Click **OAuth Apps**
4. Click **New OAuth App**

### 1.2 Configure OAuth Application

Fill out the OAuth application form:

**Application name**: `MCP Gateway - [Your Organization]`

- Example: `MCP Gateway - Acme Corp`

**Homepage URL**: Your gateway's public URL

- Production: `https://gateway.yourcompany.com`
- Development (port 8000): `http://localhost:8000`
- Development (make serve, port 4444): `http://localhost:4444`

**Application description** (optional):
```
Model Context Protocol Gateway SSO Authentication
```

**Authorization callback URL**: **This is critical - must be exact**
```
# Production
https://gateway.yourcompany.com/auth/sso/callback/github

# Development (port 8000)
http://localhost:8000/auth/sso/callback/github

# Development (make serve, port 4444)
http://localhost:4444/auth/sso/callback/github
```

**Important**: The callback URL must match your gateway's actual port and protocol exactly.

### 1.3 Generate Client Secret

1. Click **Register application**
2. Note the **Client ID** (visible immediately)
3. Click **Generate a new client secret**
4. **Important**: Copy the client secret immediately - you won't see it again
5. Store both Client ID and Client Secret securely

## Step 2: Configure MCP Gateway Environment

### 2.1 Update Environment Variables

Add these variables to your `.env` file:

```bash
# Enable SSO System
SSO_ENABLED=true

# GitHub OAuth Configuration
SSO_GITHUB_ENABLED=true
SSO_GITHUB_CLIENT_ID=Iv1.a1b2c3d4e5f6g7h8
SSO_GITHUB_CLIENT_SECRET=ghp_1234567890abcdef1234567890abcdef12345678

# Optional: Auto-create users on first login
SSO_AUTO_CREATE_USERS=true

# Optional: Restrict to specific email domains
SSO_TRUSTED_DOMAINS=["yourcompany.com", "contractor.org"]

# Optional: Preserve local admin authentication
SSO_PRESERVE_ADMIN_AUTH=true
```

### 2.2 Example Production Configuration

```bash
# Production GitHub SSO Setup
SSO_ENABLED=true
SSO_GITHUB_ENABLED=true
SSO_GITHUB_CLIENT_ID=Iv1.real-client-id-from-github
SSO_GITHUB_CLIENT_SECRET=ghp_real-secret-from-github

# Security settings
SSO_AUTO_CREATE_USERS=true
SSO_TRUSTED_DOMAINS=["yourcompany.com"]
SSO_PRESERVE_ADMIN_AUTH=true

# Optional: GitHub organization team mapping
GITHUB_ORG_TEAM_MAPPING={"your-github-org": "dev-team-uuid"}
```

### 2.3 Development Configuration

```bash
# Development GitHub SSO Setup
SSO_ENABLED=true
SSO_GITHUB_ENABLED=true
SSO_GITHUB_CLIENT_ID=Iv1.dev-client-id
SSO_GITHUB_CLIENT_SECRET=ghp_dev-secret

# More permissive for testing
SSO_AUTO_CREATE_USERS=true
SSO_PRESERVE_ADMIN_AUTH=true
```

## Step 3: Restart and Verify Gateway

### 3.1 Restart the Gateway

```bash
# Development
make dev

# Or directly with uvicorn
uvicorn mcpgateway.main:app --reload --host 0.0.0.0 --port 8000

# Production
make serve
```

### 3.2 Verify SSO is Enabled

Test that SSO endpoints are accessible:

```bash
# For development server (port 8000)
curl -X GET http://localhost:8000/auth/sso/providers

# For production server (port 4444, make serve)
curl -X GET http://localhost:4444/auth/sso/providers

# Should return GitHub provider:
[
  {
    "id": "github",
    "name": "github",
    "display_name": "GitHub",
    "authorization_url": null
  }
]
```

**Troubleshooting**:

- **404 error**: Check that `SSO_ENABLED=true` in your environment and restart gateway
- **Empty array `[]`**: SSO is enabled but GitHub provider not created - restart gateway to auto-bootstrap
- **Connection refused**: Gateway not running or wrong port

## Step 4: Test GitHub SSO Login

### 4.1 Access Login Page

1. Navigate to your gateway's login page:

   - Development (port 8000): `http://localhost:8000/admin/login`
   - Development (make serve, port 4444): `http://localhost:4444/admin/login`
   - Production: `https://gateway.yourcompany.com/admin/login`

2. You should see a "Continue with GitHub" button

### 4.2 Test Authentication Flow

1. Click **Continue with GitHub**
2. You'll be redirected to GitHub's authorization page
3. Click **Authorize** to grant access
4. You'll be redirected back to the gateway admin panel
5. You should be logged in successfully

### 4.3 Verify User Creation

Check that a user was created in the gateway:

```bash
# Using the admin API (requires admin token)
curl -H "Authorization: Bearer YOUR_ADMIN_TOKEN" \
  http://localhost:8000/auth/users

# Look for your GitHub email in the user list
```

## Step 5: Advanced Configuration (Optional)

### 5.1 GitHub Organization Team Mapping

Map GitHub organizations to gateway teams:

```bash
# Environment variable format
GITHUB_ORG_TEAM_MAPPING={"your-github-org": "dev-team-uuid", "admin-org": "admin-team-uuid"}
```

Create teams first using the admin API:

```bash
# Create a team
curl -X POST http://localhost:8000/teams \
  -H "Authorization: Bearer YOUR_ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "GitHub Developers",
    "description": "Users from GitHub organization"
  }'
```

### 5.2 Custom OAuth Scopes

Request additional GitHub permissions:

```bash
# Add to .env
SSO_GITHUB_SCOPE="user:email read:org"
```

### 5.3 Trusted Domains Restriction

Only allow users from specific email domains:

```bash
SSO_TRUSTED_DOMAINS=["yourcompany.com", "contractor.com"]
```

Users with emails from other domains will be blocked.

## Step 6: Production Deployment Checklist

### 6.1 Security Requirements

- [ ] Use HTTPS for all callback URLs
- [ ] Store client secrets in secure vault/secret management
- [ ] Set restrictive `SSO_TRUSTED_DOMAINS`
- [ ] Enable audit logging
- [ ] Regular secret rotation schedule

### 6.2 Callback URL Verification

Ensure callback URLs match exactly:

**GitHub OAuth App**: `https://gateway.yourcompany.com/auth/sso/callback/github`
**Gateway Config**: Gateway must be accessible at `https://gateway.yourcompany.com`

### 6.3 Firewall and Network

- [ ] Gateway accessible from internet (for GitHub callbacks)
- [ ] HTTPS certificates valid and auto-renewing
- [ ] CDN/load balancer configured if needed

## Troubleshooting

### Error: "SSO authentication is disabled"

**Problem**: SSO endpoints return 404
**Solution**: Set `SSO_ENABLED=true` and restart gateway

```bash
# Check environment
echo $SSO_ENABLED

# Should output: true
```

### Error: "The redirect_uri is not associated with this application"

**Problem**: GitHub OAuth app callback URL doesn't match your gateway's actual URL
**Solution**: Update GitHub OAuth app settings to match your gateway's port and protocol

```bash
# For make serve (port 4444):
Homepage URL: http://localhost:4444
Authorization callback URL: http://localhost:4444/auth/sso/callback/github

# For development server (port 8000):
Homepage URL: http://localhost:8000
Authorization callback URL: http://localhost:8000/auth/sso/callback/github

# Common mistakes:
http://localhost:4444/auth/sso/callback/github/  # Extra slash
http://localhost:8000/auth/sso/callback/github  # Wrong port (when using 4444)
https://localhost:4444/auth/sso/callback/github # HTTPS on localhost
```

### Error: Missing query parameters (code, state)

**Problem**: Direct access to callback URL without OAuth flow
**Solution**: Don't navigate directly to `/auth/sso/callback/github` - use the "Continue with GitHub" button

### Error: "User creation failed"

**Problem**: User's email domain not in trusted domains
**Solution**: Add domain to `SSO_TRUSTED_DOMAINS` or remove restriction

```bash
# Add user's domain
SSO_TRUSTED_DOMAINS=["yourcompany.com", "user-domain.com"]

# Or remove restriction entirely
SSO_TRUSTED_DOMAINS=[]
```

### Error: No GitHub button appears

**Problem**: JavaScript fails to load SSO providers
**Solution**: Check browser console and Content Security Policy

```bash
# Check if providers endpoint works
curl http://localhost:8000/auth/sso/providers

# Check browser console for CSP violations
```

### GitHub Authorization Returns Error

**Problem**: GitHub shows "Application suspended" or similar
**Solution**: Check GitHub OAuth app status and limits

1. Go to GitHub Settings → Developer settings → OAuth Apps
2. Check if your app is suspended or has issues
3. Verify callback URL is correct
4. Check if you've exceeded rate limits

### Users Can't Access After Login

**Problem**: User logs in successfully but has no permissions
**Solution**: Assign users to teams or roles

```bash
# List users to find the GitHub user
curl -H "Authorization: Bearer ADMIN_TOKEN" \
  http://localhost:8000/auth/users

# Assign user to a team
curl -X POST http://localhost:8000/teams/TEAM_ID/members \
  -H "Authorization: Bearer ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"user_id": "USER_ID", "role": "member"}'
```

## Testing Checklist

- [ ] GitHub OAuth app created and configured
- [ ] Environment variables set correctly
- [ ] Gateway restarted with new config
- [ ] `/auth/sso/providers` returns GitHub provider
- [ ] Login page shows "Continue with GitHub" button
- [ ] Clicking GitHub button redirects to GitHub
- [ ] GitHub authorization redirects back successfully
- [ ] User is logged into gateway admin panel
- [ ] User appears in gateway user list

## Next Steps

After GitHub SSO is working:

1. **Set up additional providers** (Google, Okta, IBM Verify)
2. **Configure team mappings** for automatic role assignment
3. **Set up monitoring** for authentication failures
4. **Configure backup authentication** methods
5. **Document user onboarding** process for your organization

## Related Documentation

- [Complete SSO Guide](sso.md) - Full SSO documentation
- [Team Management](teams.md) - Managing teams and roles
- [RBAC Configuration](rbac.md) - Role-based access control
- [Security Best Practices](../architecture/security-features.md)

## Support

If you encounter issues:

1. Check the [Troubleshooting section](#troubleshooting) above
2. Enable debug logging: `LOG_LEVEL=DEBUG`
3. Review gateway logs for SSO-related errors
4. Verify GitHub OAuth app configuration matches exactly
