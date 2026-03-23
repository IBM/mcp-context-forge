# Google OAuth/OIDC Setup Tutorial

This tutorial walks you through setting up Google Single Sign-On (SSO) authentication for ContextForge, allowing users to log in with their Google accounts.

## Prerequisites

- ContextForge installed and running
- Google account with access to Google Cloud Console
- Access to your gateway's environment configuration

## Step 1: Create Google OAuth Application

### 1.1 Access Google Cloud Console

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Select or create a project for your ContextForge
3. In the left sidebar, navigate to **APIs & Services** → **Credentials**

### 1.2 Enable Required APIs

Before creating credentials, enable the necessary APIs:

1. Go to **APIs & Services** → **Library**
2. Search for and enable:

   - **Google Identity Service** (for user authentication)
   - **Google People API** (for user profile information)
   - **Google Identity and Access Management (IAM) API** (optional, for advanced features)

### 1.3 Configure OAuth Consent Screen

1. Go to **APIs & Services** → **OAuth consent screen**
2. Choose **External** (for general use) or **Internal** (for Google Workspace)
3. Fill out the required fields:

**App name**: `ContextForge - [Your Organization]`

**User support email**: Your support email

**Application home page**: Your gateway URL

- Example: `https://gateway.yourcompany.com`

**Authorized domains**: Add your domain

- Example: `yourcompany.com`

**Developer contact information**: Your email

4. Click **Save and Continue**
5. Add scopes (optional for basic auth):

   - `userinfo.email`
   - `userinfo.profile`
   - `openid`

### 1.4 Create OAuth Client ID

1. Go to **APIs & Services** → **Credentials**
2. Click **Create Credentials** → **OAuth client ID**
3. Choose **Web application**
4. Configure the client:

**Name**: `ContextForge OAuth Client`

**Authorized JavaScript origins**: Your gateway domain

- Production: `https://gateway.yourcompany.com`
- Development: `http://localhost:8000`

**Authorized redirect URIs**: **Critical - must be exact**

- Production: `https://gateway.yourcompany.com/auth/sso/callback/google`
- Development: `http://localhost:8000/auth/sso/callback/google`
5. Click **Create**
6. **Important**: Copy the Client ID and Client Secret immediately

## Step 2: Configure ContextForge Environment

### 2.1 Update Environment Variables

Add these variables to your `.env` file:

```bash
# Enable SSO System
SSO_ENABLED=true

# Google OAuth Configuration
SSO_GOOGLE_ENABLED=true
SSO_GOOGLE_CLIENT_ID=123456789012-abcdefghijklmnopqrstuvwxyz123456.apps.googleusercontent.com
SSO_GOOGLE_CLIENT_SECRET=GOCSPX-1234567890abcdefghijklmnop

# Optional: Auto-create users on first login
SSO_AUTO_CREATE_USERS=true

# Optional: Restrict to Google Workspace domain
SSO_TRUSTED_DOMAINS=["yourcompany.com"]

# Optional: Preserve local admin authentication
SSO_PRESERVE_ADMIN_AUTH=true
```

### 2.2 Example Production Configuration

```bash
# Production Google SSO Setup
SSO_ENABLED=true
SSO_GOOGLE_ENABLED=true
SSO_GOOGLE_CLIENT_ID=123456789012-realclientid.apps.googleusercontent.com
SSO_GOOGLE_CLIENT_SECRET=GOCSPX-realsecretfromgoogle

# Security settings for Google Workspace
SSO_AUTO_CREATE_USERS=true
SSO_TRUSTED_DOMAINS=["yourcompany.com"]  # Only company emails
SSO_PRESERVE_ADMIN_AUTH=true

# Optional: Custom OAuth scopes
SSO_GOOGLE_SCOPE="openid profile email"
```

### 2.3 Development Configuration

```bash
# Development Google SSO Setup
SSO_ENABLED=true
SSO_GOOGLE_ENABLED=true
SSO_GOOGLE_CLIENT_ID=123456789012-devtest.apps.googleusercontent.com
SSO_GOOGLE_CLIENT_SECRET=GOCSPX-devtestsecret

# More permissive for testing
SSO_AUTO_CREATE_USERS=true
SSO_PRESERVE_ADMIN_AUTH=true
# SSO_TRUSTED_DOMAINS=[]  # Allow any email for testing
```

### 2.4 Google Workspace Domain Restriction

For organizations using Google Workspace:

```bash
# Restrict to your organization's domain
SSO_TRUSTED_DOMAINS=["yourcompany.com"]

# Allow multiple domains
SSO_TRUSTED_DOMAINS=["yourcompany.com", "subsidiary.com", "contractor.org"]
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

### 3.2 Verify Google SSO is Enabled

Test that Google appears in SSO providers:

```bash
# For development server (port 8000)
curl -X GET http://localhost:8000/auth/sso/providers

# For production server (port 4444, make serve)
curl -X GET http://localhost:4444/auth/sso/providers

# Should return Google in the list:
[
  {
    "id": "google",
    "name": "google",
    "display_name": "Google",
    "authorization_url": null
  }
]
```

**Troubleshooting**:

- **404 error**: Check that `SSO_ENABLED=true` in your environment and restart gateway
- **Empty array `[]`**: SSO is enabled but Google provider not created - restart gateway to auto-bootstrap

## Step 4: Test Google SSO Login

### 4.1 Access Login Page

1. Navigate to your gateway's login page:

   - Development (port 8000): `http://localhost:8000/admin/login`
   - Development (make serve, port 4444): `http://localhost:4444/admin/login`
   - Production: `https://gateway.yourcompany.com/admin/login`

2. You should see a "Continue with Google" button

### 4.2 Test Authentication Flow

1. Click **Continue with Google**
2. You'll be redirected to Google's sign-in page
3. Enter your Google credentials
4. Grant permissions if prompted
5. You'll be redirected back to the gateway admin panel
6. You should be logged in successfully

### 4.3 Verify User Creation

Check that a user was created:

```bash
# Using the admin API (requires admin token)
curl -H "Authorization: Bearer YOUR_ADMIN_TOKEN" \
  http://localhost:8000/auth/users

# Look for your Google email in the user list
```

## Step 5: Google Workspace Integration (Advanced)

### 5.1 Google Workspace Domain Verification

For Google Workspace organizations:

1. In Google Cloud Console, go to **Domain verification**
2. Verify ownership of your domain
3. This allows stricter domain controls

### 5.2 Google Groups Integration

Map Google Groups to gateway teams:

```bash
# Custom configuration (requires additional API setup)
GOOGLE_GROUPS_MAPPING={"group1@yourcompany.com": "team-uuid-1", "admins@yourcompany.com": "admin-team-uuid"}
```

**Note**: This requires additional Google Groups API setup and custom development.

### 5.3 Advanced OAuth Scopes

Request additional Google permissions:

```bash
# Extended scopes for Google Workspace
SSO_GOOGLE_SCOPE="openid profile email https://www.googleapis.com/auth/admin.directory.group.readonly"
```

Common useful scopes:

- `openid profile email` - Basic user info (default)
- `https://www.googleapis.com/auth/admin.directory.user.readonly` - Read user directory
- `https://www.googleapis.com/auth/admin.directory.group.readonly` - Read group memberships

## Step 6: Production Deployment Checklist

### 6.1 Security Requirements

- [ ] Use HTTPS for all redirect URIs
- [ ] Store client secrets securely (vault/secret management)
- [ ] Set restrictive `SSO_TRUSTED_DOMAINS` for Google Workspace
- [ ] Configure OAuth consent screen properly
- [ ] Regular secret rotation

### 6.2 Google Cloud Configuration

- [ ] OAuth consent screen configured
- [ ] Authorized domains added
- [ ] Required APIs enabled
- [ ] Redirect URIs match exactly
- [ ] Client ID and secret copied securely

### 6.3 DNS and Certificates

- [ ] Gateway accessible from internet
- [ ] HTTPS certificates valid
- [ ] Domain verification completed (for Workspace)

## Troubleshooting

### Error: "SSO authentication is disabled"

**Problem**: SSO endpoints return 404
**Solution**: Set `SSO_ENABLED=true` and restart gateway

### Error: "redirect_uri_mismatch"

**Problem**: Google OAuth redirect URI doesn't match
**Solution**: Verify exact URL match in Google Cloud Console

```bash
# Google Cloud Console authorized redirect URIs must exactly match:
https://your-domain.com/auth/sso/callback/google

# Common mistakes:
https://your-domain.com/auth/sso/callback/google/  # Extra slash
http://your-domain.com/auth/sso/callback/google   # HTTP instead of HTTPS
https://www.your-domain.com/auth/sso/callback/google  # Wrong subdomain
```

### Error: "Access blocked: This app's request is invalid"

**Problem**: OAuth consent screen not configured properly
**Solution**: Complete OAuth consent screen configuration

1. Go to Google Cloud Console → OAuth consent screen
2. Fill in all required fields
3. Add your domain to authorized domains
4. Publish the app (for external users)

### Error: "User creation failed"

**Problem**: User's email domain not in trusted domains
**Solution**: Add domain to trusted domains or remove restriction

```bash
# For Google Workspace - add your domain
SSO_TRUSTED_DOMAINS=["yourcompany.com"]

# For consumer Google accounts - remove restriction
SSO_TRUSTED_DOMAINS=[]
```

### Google Sign-in Shows "This app isn't verified"

**Problem**: App verification required for production use
**Solution**: For internal use, users can click "Advanced" → "Go to [App Name] (unsafe)"

For production apps with external users:

1. Go through Google's app verification process
2. Or limit to internal users only (Google Workspace)

### Error: "invalid_client"

**Problem**: Wrong client ID or secret
**Solution**: Verify credentials from Google Cloud Console

```bash
# Double-check these values match Google Cloud Console
SSO_GOOGLE_CLIENT_ID=your-actual-client-id.apps.googleusercontent.com
SSO_GOOGLE_CLIENT_SECRET=GOCSPX-your-actual-client-secret
```

## Testing Checklist

- [ ] Google Cloud project created
- [ ] OAuth consent screen configured
- [ ] OAuth client ID created with correct redirect URI
- [ ] Client ID and secret added to environment
- [ ] Gateway restarted with new config
- [ ] `/auth/sso/providers` returns Google provider
- [ ] Login page shows "Continue with Google" button
- [ ] Clicking Google button redirects to Google sign-in
- [ ] Google sign-in redirects back successfully
- [ ] User is logged into gateway admin panel
- [ ] User appears in gateway user list

## Google Workspace Specific Setup

### Admin Console Configuration

If using Google Workspace:

1. Go to [Google Admin Console](https://admin.google.com)
2. Navigate to **Security** → **API controls**
3. Click **MANAGE THIRD-PARTY APP ACCESS**
4. Configure app access for your ContextForge OAuth app

### Domain-Wide Delegation (Advanced)

For service account access (advanced use cases):

1. Create a service account in Google Cloud Console
2. Enable domain-wide delegation
3. In Google Admin Console, configure API scopes
4. Use service account for server-to-server authentication

## Next Steps

After Google SSO is working:

1. **Test with different user types** (admin, regular users)
2. **Set up team mappings** for automatic role assignment
3. **Configure additional SSO providers** for redundancy
4. **Monitor authentication logs** for issues
5. **Document user onboarding** process

## Related Documentation

- [Complete SSO Guide](sso.md) - Full SSO documentation
- [GitHub SSO Tutorial](sso-github-tutorial.md) - GitHub setup guide
- [Team Management](teams.md) - Managing teams and roles
- [RBAC Configuration](rbac.md) - Role-based access control

## Support

If you encounter issues:

1. Check Google Cloud Console for error messages
2. Enable debug logging: `LOG_LEVEL=DEBUG`
3. Review gateway logs for Google OAuth errors
4. Verify all Google Cloud Console settings match tutorial
5. Test with a simple curl command to isolate issues
