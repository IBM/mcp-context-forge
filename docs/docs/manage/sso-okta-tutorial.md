# Okta OIDC Setup Tutorial

This tutorial walks you through setting up Okta Single Sign-On (SSO) authentication for MCP Gateway, enabling enterprise identity management with Okta's comprehensive platform.

## Prerequisites

- MCP Gateway installed and running
- Okta account with admin access (Developer or Enterprise edition)
- Access to your gateway's environment configuration

## Step 1: Create Okta Application Integration

### 1.1 Access Okta Admin Console

1. Navigate to your Okta admin console

   - URL format: `https://[org-name].okta.com` or `https://[org-name].oktapreview.com`

2. Log in with your administrator credentials
3. Go to **Applications** → **Applications** in the left sidebar

### 1.2 Create New App Integration

1. Click **Create App Integration**
2. Choose **OIDC - OpenID Connect** as the sign-in method
3. Choose **Web Application** as the application type
4. Click **Next**

### 1.3 Configure General Settings

**App integration name**: `MCP Gateway`

**App logo**: Upload your organization's logo (optional)

**Grant type**: Select **Authorization Code** (should be pre-selected)

### 1.4 Configure Sign-in Settings

**Sign-in redirect URIs**: **Critical - must be exact**

- Production: `https://gateway.yourcompany.com/auth/sso/callback/okta`
- Development: `http://localhost:8000/auth/sso/callback/okta`
- Click **Add URI** if you need both

**Sign-out redirect URIs** (optional):

- Production: `https://gateway.yourcompany.com/admin/login`
- Development: `http://localhost:8000/admin/login`

**Controlled access**: Choose appropriate option:

- **Allow everyone in your organization to access** (most common)
- **Limit access to selected groups** (recommended for production)
- **Skip group assignment for now** (development only)

### 1.5 Save and Obtain Credentials

1. Click **Save**
2. After creation, you'll see the **Client Credentials**:

   - **Client ID**: Copy this value
   - **Client secret**: Copy this value (click to reveal)

3. Note your **Okta domain** (e.g., `https://dev-12345.okta.com`)

## Step 2: Configure Okta Application Settings

### 2.1 Configure Token Settings (Optional)

1. In your application, go to the **General** tab
2. Scroll to **General Settings** → **Edit**
3. Configure token lifetimes:

   - **Access token lifetime**: 1 hour (default)
   - **Refresh token lifetime**: 90 days (default)
   - **ID token lifetime**: 1 hour (default)

### 2.2 Configure Claims (Advanced)

1. Go to the **Sign On** tab
2. Scroll to **OpenID Connect ID Token**
3. Configure claims if you need custom user attributes:

   - `groups` - User's group memberships
   - `department` - User's department
   - `title` - User's job title

Example custom claim configuration:

- **Name**: `groups`
- **Include in token type**: ID Token, Always
- **Value type**: Groups
- **Filter**: Matches regex `.*` (for all groups)

## Step 3: Configure User and Group Access

### 3.1 Assign Users to Application

1. Go to the **Assignments** tab in your application
2. Click **Assign** → **Assign to People**
3. Select users who should have access
4. Click **Assign** for each user
5. Click **Save and Go Back**

### 3.2 Assign Groups to Application (Recommended)

1. Click **Assign** → **Assign to Groups**
2. Select groups that should have access:

   - `Everyone` - All users (not recommended for production)
   - `MCP Gateway Users` - Custom group for gateway access
   - `IT Admins` - Administrative access

3. For each group, you can set a custom **Application username**
4. Click **Assign** and **Done**

### 3.3 Create Custom Groups (Optional)

If you want specific groups for MCP Gateway:

1. Go to **Directory** → **Groups**
2. Click **Add Group**
3. Create groups like:

   - **Name**: `MCP Gateway Users`
   - **Description**: `Users with access to MCP Gateway`

4. Add appropriate users to these groups

## Step 4: Configure MCP Gateway Environment

### 4.1 Update Environment Variables

Add these variables to your `.env` file:

```bash
# Enable SSO System
SSO_ENABLED=true

# Okta OIDC Configuration
SSO_OKTA_ENABLED=true
SSO_OKTA_CLIENT_ID=0oa1b2c3d4e5f6g7h8i9
SSO_OKTA_CLIENT_SECRET=AbCdEfGhIjKlMnOpQrStUvWxYz1234567890abcdef
SSO_OKTA_ISSUER=https://dev-12345.okta.com

# Optional: Auto-create users on first login
SSO_AUTO_CREATE_USERS=true

# Optional: Restrict to corporate email domains
SSO_TRUSTED_DOMAINS=["yourcompany.com"]

# Optional: Preserve local admin authentication
SSO_PRESERVE_ADMIN_AUTH=true
```

### 4.2 Example Production Configuration

```bash
# Production Okta SSO Setup
SSO_ENABLED=true
SSO_OKTA_ENABLED=true
SSO_OKTA_CLIENT_ID=0oa1b2c3d4e5f6g7h8i9
SSO_OKTA_CLIENT_SECRET=AbCdEfGhIjKlMnOpQrStUvWxYz1234567890abcdef
SSO_OKTA_ISSUER=https://acmecorp.okta.com

# Enterprise security settings
SSO_AUTO_CREATE_USERS=true
SSO_TRUSTED_DOMAINS=["acmecorp.com"]
SSO_PRESERVE_ADMIN_AUTH=true

# Optional: Custom scopes for additional user attributes
SSO_OKTA_SCOPE="openid profile email groups"
```

### 4.3 Development Configuration

```bash
# Development Okta SSO Setup
SSO_ENABLED=true
SSO_OKTA_ENABLED=true
SSO_OKTA_CLIENT_ID=0oa_dev_client_id
SSO_OKTA_CLIENT_SECRET=dev_client_secret
SSO_OKTA_ISSUER=https://dev-12345.oktapreview.com

# More permissive for testing
SSO_AUTO_CREATE_USERS=true
SSO_PRESERVE_ADMIN_AUTH=true
```

### 4.4 Advanced Configuration Options

```bash
# Custom OAuth scopes for enhanced user data
SSO_OKTA_SCOPE="openid profile email groups address phone"

# Group mapping for automatic team assignment
OKTA_GROUP_MAPPING={"MCP Gateway Admins": "admin-team-uuid", "MCP Gateway Users": "user-team-uuid"}

# Custom authorization server (if using custom Okta authorization server)
SSO_OKTA_ISSUER=https://dev-12345.okta.com/oauth2/custom-auth-server-id
```

## Step 5: Restart and Verify Gateway

### 5.1 Restart the Gateway

```bash
# Development
make dev

# Or directly with uvicorn
uvicorn mcpgateway.main:app --reload --host 0.0.0.0 --port 8000

# Production
make serve
```

### 5.2 Verify Okta SSO is Enabled

Test that Okta appears in SSO providers:

```bash
# Check if Okta is listed
curl -X GET http://localhost:8000/auth/sso/providers

# Should return Okta in the list:
[
  {
    "id": "okta",
    "name": "okta",
    "display_name": "Okta"
  }
]
```

## Step 6: Test Okta SSO Login

### 6.1 Access Login Page

1. Navigate to your gateway's login page:

   - Development: `http://localhost:8000/admin/login`
   - Production: `https://gateway.yourcompany.com/admin/login`

2. You should see a "Continue with Okta" button

### 6.2 Test Authentication Flow

1. Click **Continue with Okta**
2. You'll be redirected to Okta's sign-in page
3. Enter your Okta credentials
4. Complete any multi-factor authentication if required
5. Grant consent for the application if prompted
6. You'll be redirected back to the gateway admin panel
7. You should be logged in successfully

### 6.3 Verify User Creation

Check that a user was created:

```bash
# Using the admin API (requires admin token)
curl -H "Authorization: Bearer YOUR_ADMIN_TOKEN" \
  http://localhost:8000/auth/users

# Look for your Okta email in the user list
```

## Step 7: Okta Advanced Features (Enterprise)

### 7.1 Multi-Factor Authentication (MFA)

Configure MFA policies in Okta:

1. Go to **Security** → **Multifactor**
2. Set up MFA policies for your MCP Gateway application
3. Configure factors (SMS, Email, Okta Verify app, etc.)
4. Users will be prompted for MFA during login

### 7.2 Adaptive Authentication

Configure risk-based authentication:

1. Go to **Security** → **Authentication** → **Sign On**
2. Create policies with conditions:

   - Device trust
   - Network location
   - User risk level
   - Time-based restrictions

### 7.3 Universal Directory Integration

Sync user attributes from external directories:

1. Go to **Directory** → **Directory Integrations**
2. Configure integration with:

   - Active Directory
   - LDAP
   - HR systems (Workday, BambooHR, etc.)

3. Map attributes for automatic user provisioning

### 7.4 API Access Management

For programmatic API access:

1. Create a custom authorization server
2. Configure API scopes and claims
3. Issue API tokens for service-to-service authentication

## Step 8: Production Deployment Checklist

### 8.1 Security Requirements

- [ ] HTTPS enforced for all redirect URIs
- [ ] Client secrets stored securely (vault/secret management)
- [ ] MFA policies configured appropriately
- [ ] Adaptive authentication policies set
- [ ] Password policies enforced
- [ ] Session management configured

### 8.2 Okta Configuration

- [ ] Application created with correct settings
- [ ] Appropriate users/groups assigned access
- [ ] Custom claims configured if needed
- [ ] Token lifetimes set appropriately
- [ ] Sign-out redirect URIs configured

### 8.3 Monitoring and Compliance

- [ ] System Log monitoring enabled
- [ ] Audit trail configured
- [ ] Compliance reporting set up (if required)
- [ ] Regular access reviews scheduled

## Troubleshooting

### Error: "SSO authentication is disabled"

**Problem**: SSO endpoints return 404
**Solution**: Set `SSO_ENABLED=true` and restart gateway

### Error: "invalid_client"

**Problem**: Wrong client ID or client secret
**Solution**: Verify credentials from Okta application settings

```bash
# Double-check these values match your Okta application
SSO_OKTA_CLIENT_ID=your-actual-client-id
SSO_OKTA_CLIENT_SECRET=your-actual-client-secret
```

### Error: "redirect_uri_mismatch"

**Problem**: Okta redirect URI doesn't match
**Solution**: Verify exact URL match in Okta application settings

```bash
# Okta redirect URI must exactly match:
https://your-domain.com/auth/sso/callback/okta

# Common mistakes:
https://your-domain.com/auth/sso/callback/okta/  # Extra slash
http://your-domain.com/auth/sso/callback/okta   # HTTP instead of HTTPS
https://your-domain.com/auth/sso/callback/oauth # Wrong provider ID
```

### Error: "User is not assigned to the client application"

**Problem**: User doesn't have access to the application
**Solution**: Assign user to the application

1. In Okta admin console, go to Applications → [Your App]
2. Go to Assignments tab
3. Assign the user or their group to the application

### Error: "The issuer specified in the request is invalid"

**Problem**: Wrong Okta domain or issuer URL
**Solution**: Verify issuer URL matches your Okta domain

```bash
# Get the correct issuer from Okta's well-known configuration
curl https://[your-okta-domain].okta.com/.well-known/openid_configuration

# Use the "issuer" field value
```

### MFA Bypass Issues

**Problem**: Users not prompted for MFA
**Solution**: Check MFA policies and user enrollment

1. Verify MFA policies are active for your application
2. Check user MFA enrollment status
3. Ensure policy conditions are met (device, location, etc.)

### Token Validation Errors

**Problem**: JWT tokens failing validation
**Solution**: Check token configuration and clock sync

1. Verify token lifetime settings
2. Check server clock synchronization
3. Validate JWT signature verification

## Testing Checklist

- [ ] Okta application integration created
- [ ] Client ID and secret configured
- [ ] Redirect URIs set correctly
- [ ] Users/groups assigned to application
- [ ] Environment variables configured
- [ ] Gateway restarted with new config
- [ ] `/auth/sso/providers` returns Okta provider
- [ ] Login page shows "Continue with Okta" button
- [ ] Authentication flow completes successfully
- [ ] User appears in gateway user list
- [ ] MFA working (if configured)
- [ ] Group claims included in tokens (if configured)

## Okta API Integration (Advanced)

### Programmatic User Management

Use Okta APIs for advanced user management:

```python
# Example: Sync Okta groups with Gateway teams
import requests

def sync_okta_groups():
    okta_token = "your-okta-api-token"
    okta_domain = "https://dev-12345.okta.com"

    # Get user's groups from Okta
    response = requests.get(
        f"{okta_domain}/api/v1/users/{user_id}/groups",
        headers={"Authorization": f"SSWS {okta_token}"}
    )

    groups = response.json()
    return [group['profile']['name'] for group in groups]
```

### Custom Authorization Server

For advanced API access patterns:

1. Create custom authorization server in Okta
2. Define custom scopes for MCP Gateway APIs
3. Configure audience restrictions
4. Use for service-to-service authentication

## Next Steps

After Okta SSO is working:

1. **Configure MFA policies** for enhanced security
2. **Set up adaptive authentication** based on risk
3. **Integrate with existing directories** (AD/LDAP)
4. **Configure custom user attributes** and claims
5. **Set up automated user provisioning/deprovisioning**
6. **Monitor authentication patterns** for security insights

## Related Documentation

- [Complete SSO Guide](sso.md) - Full SSO documentation
- [GitHub SSO Tutorial](sso-github-tutorial.md) - GitHub setup guide
- [Google SSO Tutorial](sso-google-tutorial.md) - Google setup guide
- [IBM Security Verify Tutorial](sso-ibm-tutorial.md) - IBM setup guide
- [Team Management](teams.md) - Managing teams and roles
- [RBAC Configuration](rbac.md) - Role-based access control

## Support

If you encounter issues:

1. Check Okta System Log for authentication errors
2. Enable debug logging: `LOG_LEVEL=DEBUG`
3. Review gateway logs for Okta-specific errors
4. Verify all Okta settings match tutorial exactly
5. Use Okta's support resources and community forums
