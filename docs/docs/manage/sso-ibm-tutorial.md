# IBM Security Verify Setup Tutorial

This tutorial walks you through setting up IBM Security Verify (formerly IBM Cloud Identity) SSO authentication for MCP Gateway, enabling enterprise-grade identity management.

## Prerequisites

- MCP Gateway installed and running
- IBM Security Verify tenant with admin access
- Access to your gateway's environment configuration

## Step 1: Configure IBM Security Verify Application

### 1.1 Access IBM Security Verify Admin Console

1. Navigate to your IBM Security Verify admin console
   - URL format: `https://[tenant-name].verify.ibm.com`
2. Log in with your administrator credentials
3. Go to **Applications** in the left sidebar

### 1.2 Create New Application

1. Click **Add application**
2. Choose **Custom Application**
3. Select **OpenID Connect** as the sign-on method

### 1.3 Configure Application Settings

**General Settings**:

- **Application name**: `MCP Gateway`
- **Description**: `Model Context Protocol Gateway SSO Authentication`
- **Application URL**: Your gateway's public URL
  - Example: `https://gateway.yourcompany.com`

**Sign-on Settings**:

- **Application type**: `Web`
- **Grant types**: Select `Authorization Code`
- **Redirect URIs**: **Critical - must be exact**
  - Production: `https://gateway.yourcompany.com/auth/sso/callback/ibm_verify`
  - Development: `http://localhost:8000/auth/sso/callback/ibm_verify`

### 1.4 Configure Advanced Settings

**Token Settings**:

- **Access token lifetime**: 3600 seconds (1 hour)
- **Refresh token lifetime**: 86400 seconds (24 hours)
- **ID token lifetime**: 3600 seconds (1 hour)

**Scopes**:

- Select `openid` (required)
- Select `profile` (recommended)
- Select `email` (required)

### 1.5 Obtain Client Credentials

After saving the application:

1. Go to the **Sign-on** tab
2. Note the **Client ID**
3. Click **Generate secret** to create a client secret
4. **Important**: Copy the client secret immediately - you won't see it again
5. Note the **Discovery endpoint** URL (usually `https://[tenant].verify.ibm.com/oidc/endpoint/default/.well-known/openid_configuration`)

## Step 2: Configure MCP Gateway Environment

### 2.1 Find Your IBM Security Verify Endpoints

Before configuring, you need your tenant's OIDC endpoints:

```bash
# Replace [tenant-name] with your actual tenant name
curl https://[tenant-name].verify.ibm.com/oidc/endpoint/default/.well-known/openid-configuration

# This returns endpoint URLs you'll need
```

### 2.2 Update Environment Variables

Add these variables to your `.env` file:

```bash
# Enable SSO System
SSO_ENABLED=true

# IBM Security Verify OIDC Configuration
SSO_IBM_VERIFY_ENABLED=true
SSO_IBM_VERIFY_CLIENT_ID=your-client-id-from-ibm-verify
SSO_IBM_VERIFY_CLIENT_SECRET=your-client-secret-from-ibm-verify
SSO_IBM_VERIFY_ISSUER=https://[tenant-name].verify.ibm.com/oidc/endpoint/default

# Optional: Auto-create users on first login
SSO_AUTO_CREATE_USERS=true

# Optional: Restrict to corporate email domains
SSO_TRUSTED_DOMAINS=["yourcompany.com"]

# Optional: Preserve local admin authentication
SSO_PRESERVE_ADMIN_AUTH=true
```

### 2.3 Example Production Configuration

```bash
# Production IBM Security Verify SSO Setup
SSO_ENABLED=true
SSO_IBM_VERIFY_ENABLED=true
SSO_IBM_VERIFY_CLIENT_ID=12345678-abcd-1234-efgh-123456789012
SSO_IBM_VERIFY_CLIENT_SECRET=AbCdEfGhIjKlMnOpQrStUvWxYz123456
SSO_IBM_VERIFY_ISSUER=https://acmecorp.verify.ibm.com/oidc/endpoint/default

# Enterprise security settings
SSO_AUTO_CREATE_USERS=true
SSO_TRUSTED_DOMAINS=["acmecorp.com"]
SSO_PRESERVE_ADMIN_AUTH=true

# Optional: Custom scopes for additional user attributes
SSO_IBM_VERIFY_SCOPE="openid profile email"
```

### 2.4 Development Configuration

```bash
# Development IBM Security Verify SSO Setup
SSO_ENABLED=true
SSO_IBM_VERIFY_ENABLED=true
SSO_IBM_VERIFY_CLIENT_ID=dev-client-id
SSO_IBM_VERIFY_CLIENT_SECRET=dev-client-secret
SSO_IBM_VERIFY_ISSUER=https://dev-tenant.verify.ibm.com/oidc/endpoint/default

# More permissive for testing
SSO_AUTO_CREATE_USERS=true
SSO_PRESERVE_ADMIN_AUTH=true
```

### 2.5 Advanced Configuration Options

```bash
# Custom OAuth scopes for enterprise features
SSO_IBM_VERIFY_SCOPE="openid profile email groups"

# Custom user attribute mappings (if needed)
IBM_VERIFY_USER_MAPPING={"preferred_username": "username", "family_name": "last_name"}

# Group/role mapping for automatic team assignment
IBM_VERIFY_GROUP_MAPPING={"CN=Developers,OU=Groups": "dev-team-uuid", "CN=Administrators,OU=Groups": "admin-team-uuid"}
```

## Step 3: Configure User Access in IBM Security Verify

### 3.1 Assign Users to Application

1. In IBM Security Verify admin console, go to **Applications**
2. Find your MCP Gateway application
3. Go to **Access** tab
4. Click **Assign access**
5. Choose assignment method:
   - **Users**: Assign specific users
   - **Groups**: Assign entire groups (recommended)
   - **Everyone**: Allow all users (not recommended for production)

### 3.2 Configure Group-Based Access (Recommended)

1. Create or use existing groups in IBM Security Verify
2. Assign the application to appropriate groups:
   - `MCP_Gateway_Users` - Regular users
   - `MCP_Gateway_Admins` - Administrative users
3. Add users to these groups as needed

## Step 4: Restart and Verify Gateway

### 4.1 Restart the Gateway

```bash
# Development
make dev

# Or directly with uvicorn
uvicorn mcpgateway.main:app --reload --host 0.0.0.0 --port 8000

# Production
make serve
```

### 4.2 Verify IBM Security Verify SSO is Enabled

Test that IBM Security Verify appears in SSO providers:

```bash
# Check if IBM Security Verify is listed
curl -X GET http://localhost:8000/auth/sso/providers

# Should return IBM Security Verify in the list:
[
  {
    "id": "ibm_verify",
    "name": "ibm_verify",
    "display_name": "IBM Security Verify"
  }
]
```

## Step 5: Test IBM Security Verify SSO Login

### 5.1 Access Login Page

1. Navigate to your gateway's login page:
   - Development: `http://localhost:8000/admin/login`
   - Production: `https://gateway.yourcompany.com/admin/login`

2. You should see a "Continue with IBM Security Verify" button

### 5.2 Test Authentication Flow

1. Click **Continue with IBM Security Verify**
2. You'll be redirected to IBM Security Verify's login page
3. Enter your corporate credentials
4. Complete any multi-factor authentication if required
5. Grant consent if prompted
6. You'll be redirected back to the gateway admin panel
7. You should be logged in successfully

### 5.3 Verify User Creation

Check that a user was created:

```bash
# Using the admin API (requires admin token)
curl -H "Authorization: Bearer YOUR_ADMIN_TOKEN" \
  http://localhost:8000/auth/users

# Look for your IBM Security Verify email in the user list
```

## Step 6: Enterprise Features (Advanced)

### 6.1 Multi-Factor Authentication (MFA)

IBM Security Verify MFA is handled automatically:

1. Configure MFA policies in IBM Security Verify admin console
2. Go to **Security** → **Multi-factor authentication**
3. Set up policies for your MCP Gateway application
4. Users will be prompted for MFA during login

### 6.2 Conditional Access

Configure access policies based on conditions:

1. In IBM Security Verify, go to **Security** → **Access policies**
2. Create policies for your MCP Gateway application
3. Configure conditions:
   - Device compliance
   - Location-based access
   - Risk-based authentication
   - Time-based restrictions

### 6.3 User Lifecycle Management

Configure automatic user provisioning:

1. Set up SCIM provisioning (if supported)
2. Configure user attribute synchronization
3. Set up automatic de-provisioning for terminated users

### 6.4 Audit and Compliance

Enable comprehensive audit logging:

1. In IBM Security Verify, configure audit settings
2. Enable logging for:
   - Authentication events
   - Authorization decisions
   - User provisioning actions
   - Administrative changes

## Step 7: Production Deployment Checklist

### 7.1 Security Requirements

- [ ] HTTPS enforced for all redirect URIs
- [ ] Client secrets stored in secure vault
- [ ] MFA policies configured
- [ ] Conditional access policies set
- [ ] Audit logging enabled
- [ ] Regular security reviews scheduled

### 7.2 IBM Security Verify Configuration

- [ ] Application created with correct settings
- [ ] Redirect URIs match exactly
- [ ] Appropriate users/groups assigned access
- [ ] MFA policies configured
- [ ] Audit logging enabled

### 7.3 Network and Infrastructure

- [ ] Gateway accessible from corporate network
- [ ] IBM Security Verify endpoints reachable
- [ ] HTTPS certificates valid
- [ ] Load balancer configured (if needed)

## Troubleshooting

### Error: "SSO authentication is disabled"

**Problem**: SSO endpoints return 404
**Solution**: Set `SSO_ENABLED=true` and restart gateway

### Error: "invalid_redirect_uri"

**Problem**: IBM Security Verify redirect URI doesn't match
**Solution**: Verify exact URL match in IBM Security Verify application settings

```bash
# IBM Security Verify redirect URI must exactly match:
https://your-domain.com/auth/sso/callback/ibm_verify

# Common mistakes:
https://your-domain.com/auth/sso/callback/ibm_verify/  # Extra slash
http://your-domain.com/auth/sso/callback/ibm_verify   # HTTP instead of HTTPS
https://your-domain.com/auth/sso/callback/ibm-verify  # Wrong provider ID
```

### Error: "invalid_client"

**Problem**: Wrong client ID or client secret
**Solution**: Verify credentials from IBM Security Verify application

```bash
# Double-check these values match IBM Security Verify
SSO_IBM_VERIFY_CLIENT_ID=your-actual-client-id
SSO_IBM_VERIFY_CLIENT_SECRET=your-actual-client-secret
```

### Error: "User not authorized"

**Problem**: User not assigned access to the application
**Solution**: Assign user or their group to the MCP Gateway application

1. In IBM Security Verify admin console, go to Applications
2. Find MCP Gateway application → Access tab
3. Assign access to the user or their group

### Error: "Issuer mismatch"

**Problem**: Wrong issuer URL configured
**Solution**: Verify issuer URL matches your IBM Security Verify tenant

```bash
# Get the correct issuer from the well-known configuration
curl https://[tenant-name].verify.ibm.com/oidc/endpoint/default/.well-known/openid-configuration

# Look for "issuer" field in response
```

### MFA Not Working

**Problem**: Multi-factor authentication not triggered
**Solution**: Check MFA policies in IBM Security Verify

1. Go to Security → Multi-factor authentication
2. Ensure policies are enabled for your application
3. Check user enrollment status
4. Verify policy conditions are met

## Testing Checklist

- [ ] IBM Security Verify application created
- [ ] Client ID and secret generated
- [ ] Redirect URI configured correctly
- [ ] Users/groups assigned access to application
- [ ] Environment variables set correctly
- [ ] Gateway restarted with new config
- [ ] `/auth/sso/providers` returns IBM Security Verify provider
- [ ] Login page shows "Continue with IBM Security Verify" button
- [ ] Authentication flow completes successfully
- [ ] User appears in gateway user list
- [ ] MFA working (if configured)

## Enterprise Integration

### Active Directory Integration

If IBM Security Verify is connected to Active Directory:

1. User attributes sync automatically
2. Group memberships are available
3. Configure group-based access in IBM Security Verify
4. Map AD groups to gateway teams

### SAML Federation (Alternative)

For environments preferring SAML over OIDC:

1. Configure SAML application in IBM Security Verify
2. Use custom SAML integration (requires additional development)
3. Configure SAML assertions and attribute mapping

## Next Steps

After IBM Security Verify SSO is working:

1. **Configure MFA policies** for enhanced security
2. **Set up conditional access** based on risk factors
3. **Integrate with existing AD/LDAP** if needed
4. **Configure audit logging** for compliance
5. **Train users** on the new login process
6. **Set up monitoring** for authentication failures

## Related Documentation

- [Complete SSO Guide](sso.md) - Full SSO documentation
- [GitHub SSO Tutorial](sso-github-tutorial.md) - GitHub setup guide
- [Google SSO Tutorial](sso-google-tutorial.md) - Google setup guide
- [Team Management](teams.md) - Managing teams and roles
- [RBAC Configuration](rbac.md) - Role-based access control

## Support

If you encounter issues:

1. Check IBM Security Verify admin console for error messages
2. Enable debug logging: `LOG_LEVEL=DEBUG`
3. Review gateway logs for IBM Security Verify errors
4. Verify all IBM Security Verify settings match tutorial
5. Contact IBM Security Verify support for tenant-specific issues
