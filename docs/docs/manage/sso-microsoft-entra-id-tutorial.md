# Microsoft Entra ID OIDC Setup Tutorial

This tutorial walks you through setting up Microsoft Entra ID (formerly Azure AD) Single Sign-On (SSO) authentication for MCP Gateway, enabling enterprise identity management with Microsoft's cloud identity platform.

## Prerequisites

- MCP Gateway installed and running
- Microsoft Entra ID tenant with admin access
- Azure portal access with appropriate permissions
- Access to your gateway's environment configuration

## Step 1: Register Application in Azure Portal

### 1.1 Access Azure Portal

1. Navigate to the [Azure Portal](https://portal.azure.com)
2. Log in with your administrator credentials
3. Search for **Microsoft Entra ID** in the top search bar
4. Select **Microsoft Entra ID** from the results

### 1.2 Create New App Registration

1. In the left sidebar, click **App registrations**
2. Click **+ New registration**
3. Fill in the application details:

**Name**: `MCP Gateway`

**Supported account types**: Choose the appropriate option:

- **Accounts in this organizational directory only (Single tenant)** - Most common for enterprise
- **Accounts in any organizational directory (Multi-tenant)** - For multi-organization access
- **Accounts in any organizational directory and personal Microsoft accounts** - Public access (not recommended)

**Redirect URI**:

- Platform: **Web**
- URI: `https://gateway.yourcompany.com/auth/sso/callback/entra`
- For development, you can add: `http://localhost:8000/auth/sso/callback/entra`

4. Click **Register**

### 1.3 Note Application Credentials

After registration, you'll see the **Overview** page:

1. **Copy Application (client) ID**: This is your `SSO_ENTRA_CLIENT_ID`
2. **Copy Directory (tenant) ID**: This is your `SSO_ENTRA_TENANT_ID`
3. Keep this page open - you'll need these values later

## Step 2: Create Client Secret

### 2.1 Generate Client Secret

1. In your app registration, go to **Certificates & secrets** in the left sidebar
2. Click the **Client secrets** tab
3. Click **+ New client secret**
4. Add a description: `MCP Gateway Client Secret`
5. Choose an expiration period:
   - **Recommended for production**: 180 days (6 months) or 365 days (1 year)
   - **Important**: Set a reminder to rotate secrets before expiration
6. Click **Add**

### 2.2 Copy Secret Value

**CRITICAL**: Copy the secret value immediately:

- The **Value** column shows the secret (not the Secret ID)
- This value is only shown once - you cannot retrieve it later
- This is your `SSO_ENTRA_CLIENT_SECRET`
- Store it securely (use a password manager or vault)

## Step 3: Configure API Permissions

### 3.1 Add Microsoft Graph Permissions

1. In your app registration, go to **API permissions**
2. Click **+ Add a permission**
3. Select **Microsoft Graph**
4. Choose **Delegated permissions**
5. Add these permissions:
   - ✅ **OpenId permissions** → `openid`
   - ✅ **OpenId permissions** → `profile`
   - ✅ **OpenId permissions** → `email`
   - ✅ **User** → `User.Read` (basic profile information)
6. Click **Add permissions**

### 3.2 Grant Admin Consent (if required)

If your organization requires admin consent for permissions:

1. Click **Grant admin consent for [Your Organization]**
2. Click **Yes** in the confirmation dialog
3. Verify all permissions show **Granted for [Your Organization]** in green

## Step 4: Configure Authentication Settings

### 4.1 Configure Token Settings

1. Go to **Token configuration** in the left sidebar
2. Click **+ Add optional claim**
3. Select **ID** token type
4. Add these optional claims:
   - ✅ `email` - Email address
   - ✅ `family_name` - Last name
   - ✅ `given_name` - First name
   - ✅ `preferred_username` - Username
5. Click **Add**

### 4.2 Configure Authentication Settings

1. Go to **Authentication** in the left sidebar
2. Under **Platform configurations** → **Web**, verify:
   - ✅ Redirect URIs are correct
   - ✅ **ID tokens** checkbox is checked (required for OIDC)
3. Under **Advanced settings**:
   - **Allow public client flows**: No (keep default)
   - **Live SDK support**: No (keep default)
4. Click **Save** if you made changes

### 4.3 Configure Front-channel Logout (Optional)

1. Under **Authentication** → **Front-channel logout URL**:
   - Set to: `https://gateway.yourcompany.com/admin/login`
2. This enables proper logout redirection

## Step 5: Configure MCP Gateway Environment

### 5.1 Update Environment Variables

Add these variables to your `.env` file:

```bash
# Enable SSO System
SSO_ENABLED=true

# Microsoft Entra ID OIDC Configuration
SSO_ENTRA_ENABLED=true
SSO_ENTRA_CLIENT_ID=12345678-1234-1234-1234-123456789012
SSO_ENTRA_CLIENT_SECRET=your~secret~value~from~azure~portal
SSO_ENTRA_TENANT_ID=87654321-4321-4321-4321-210987654321

# Optional: Auto-create users on first login
SSO_AUTO_CREATE_USERS=true

# Optional: Restrict to corporate email domains
SSO_TRUSTED_DOMAINS=["yourcompany.com"]

# Optional: Preserve local admin authentication
SSO_PRESERVE_ADMIN_AUTH=true
```

### 5.2 Example Production Configuration

```bash
# Production Entra ID SSO Setup
SSO_ENABLED=true
SSO_ENTRA_ENABLED=true
SSO_ENTRA_CLIENT_ID=12345678-1234-1234-1234-123456789012
SSO_ENTRA_CLIENT_SECRET=AbC~dEf1GhI2jKl3MnO4pQr5StU6vWx7YzA8bcD9efG0
SSO_ENTRA_TENANT_ID=87654321-4321-4321-4321-210987654321

# Enterprise security settings
SSO_AUTO_CREATE_USERS=true
SSO_TRUSTED_DOMAINS=["acmecorp.com"]
SSO_PRESERVE_ADMIN_AUTH=true
```

### 5.3 Development Configuration

```bash
# Development Entra ID SSO Setup
SSO_ENABLED=true
SSO_ENTRA_ENABLED=true
SSO_ENTRA_CLIENT_ID=dev-client-id-guid
SSO_ENTRA_CLIENT_SECRET=dev-client-secret-value
SSO_ENTRA_TENANT_ID=dev-tenant-id-guid

# More permissive for testing
SSO_AUTO_CREATE_USERS=true
SSO_PRESERVE_ADMIN_AUTH=true
```

### 5.4 Multi-Environment Configuration

For organizations with multiple environments:

```bash
# Staging Environment
SSO_ENTRA_CLIENT_ID=staging-client-id
SSO_ENTRA_TENANT_ID=your-tenant-id  # Same tenant, different app
# Redirect: https://gateway-staging.yourcompany.com/auth/sso/callback/entra

# Production Environment
SSO_ENTRA_CLIENT_ID=prod-client-id
SSO_ENTRA_TENANT_ID=your-tenant-id  # Same tenant, different app
# Redirect: https://gateway.yourcompany.com/auth/sso/callback/entra
```

## Step 6: Restart and Verify Gateway

### 6.1 Restart the Gateway

```bash
# Development
make dev

# Or directly with uvicorn
uvicorn mcpgateway.main:app --reload --host 0.0.0.0 --port 8000

# Production
make serve
```

### 6.2 Verify Entra ID SSO is Enabled

Test that Microsoft Entra ID appears in SSO providers:

```bash
# Check if Entra ID is listed
curl -X GET http://localhost:8000/auth/sso/providers

# Should return Entra ID in the list:
[
  {
    "id": "entra",
    "name": "entra",
    "display_name": "Microsoft Entra ID"
  }
]
```

### 6.3 Check Startup Logs

Verify no errors in the logs:

```bash
# Look for SSO initialization messages
tail -f logs/gateway.log | grep -i entra

# Should see:
# INFO: SSO provider 'entra' initialized successfully
```

## Step 7: Test Microsoft Entra ID SSO Login

### 7.1 Access Login Page

1. Navigate to your gateway's login page:
   - Development: `http://localhost:8000/admin/login`
   - Production: `https://gateway.yourcompany.com/admin/login`

2. You should see a "Microsoft" or "Microsoft Entra ID" button

### 7.2 Test Authentication Flow

1. Click **Continue with Microsoft** (or **Microsoft Entra ID**)
2. You'll be redirected to Microsoft's sign-in page
3. Enter your organizational Microsoft credentials
4. Complete multi-factor authentication if configured
5. Grant consent for the application if prompted (first-time users)
6. You'll be redirected back to the gateway admin panel
7. You should be logged in successfully

### 7.3 Verify User Creation

Check that a user was created in the gateway:

```bash
# Using the admin API (requires admin token)
curl -H "Authorization: Bearer YOUR_ADMIN_TOKEN" \
  http://localhost:8000/auth/users

# Look for your Microsoft email in the user list
```

### 7.4 Verify User Profile

Check that user attributes were imported correctly:

```bash
# Get user details
curl -H "Authorization: Bearer YOUR_ADMIN_TOKEN" \
  http://localhost:8000/auth/users/{user_id}

# Verify fields are populated:
# - email: your@company.com
# - full_name: First Last
# - provider: entra
# - provider_id: unique-microsoft-id
```

## Step 8: Configure Enterprise Features

### 8.1 Conditional Access Policies

Configure Conditional Access in Azure:

1. Go to **Microsoft Entra ID** → **Security** → **Conditional Access**
2. Click **+ New policy**
3. Configure conditions:
   - **Users**: Select specific users or groups
   - **Cloud apps**: Select your MCP Gateway app
   - **Conditions**: Device platform, location, sign-in risk
   - **Grant**: Require MFA, require compliant device, etc.
4. Enable policy and test

### 8.2 Multi-Factor Authentication (MFA)

Configure MFA enforcement:

1. Go to **Microsoft Entra ID** → **Security** → **MFA**
2. Configure MFA settings:
   - **Service settings**: Enable MFA methods (Authenticator app, SMS, etc.)
   - **Users**: Enable MFA per-user or via Conditional Access
3. Test MFA during login to MCP Gateway

### 8.3 User Assignment and Access Control

Control who can access the application:

1. Go to your app registration → **Enterprise applications**
2. Find your MCP Gateway application
3. Go to **Users and groups**
4. Click **+ Add user/group**
5. Select users or security groups who should have access
6. Assign appropriate roles

### 8.4 Group Claims Configuration

To include group memberships in tokens:

1. In your app registration, go to **Token configuration**
2. Click **+ Add groups claim**
3. Select group types to include:
   - Security groups
   - Microsoft 365 groups
   - Distribution groups
4. Choose **Group ID** or **sAMAccountName** format
5. Select token types (ID, Access, SAML)
6. Click **Add**

## Step 9: Advanced Configuration

### 9.1 Custom Branding

Customize the Microsoft sign-in experience:

1. Go to **Microsoft Entra ID** → **Company branding**
2. Click **Configure**
3. Upload logo, banner, background
4. Configure text and colors
5. Users will see your branding on the Microsoft login page

### 9.2 App Roles for RBAC

Define custom application roles:

1. In your app registration, go to **App roles**
2. Click **+ Create app role**
3. Define roles:
   - **Display name**: `MCP Gateway Admin`
   - **Allowed member types**: Users/Groups
   - **Value**: `gateway.admin`
   - **Description**: Administrator role for MCP Gateway
4. Assign roles to users in **Enterprise applications** → **Users and groups**

### 9.3 Certificate-Based Authentication

For enhanced security, use certificates instead of client secrets:

1. In **Certificates & secrets** → **Certificates** tab
2. Click **Upload certificate**
3. Upload .cer, .pem, or .crt file
4. Configure gateway to use certificate authentication
5. More secure than client secrets (no expiration concerns)

### 9.4 Admin Consent Workflow

For organizations requiring admin approval:

1. Go to **Microsoft Entra ID** → **Enterprise applications** → **Admin consent requests**
2. Enable admin consent workflow
3. Configure reviewers
4. Users will request access, admins approve/deny

## Step 10: Production Deployment Checklist

### 10.1 Security Requirements

- [ ] HTTPS enforced for all redirect URIs
- [ ] Client secrets stored securely (Azure Key Vault recommended)
- [ ] MFA enabled for all users or via Conditional Access
- [ ] Conditional Access policies configured
- [ ] Password policies enforced
- [ ] Session timeout configured appropriately

### 10.2 Azure Configuration

- [ ] App registration created with correct settings
- [ ] Client ID, client secret, and tenant ID documented
- [ ] Redirect URIs match production URLs exactly
- [ ] API permissions granted and consented
- [ ] Token configuration includes required claims
- [ ] Appropriate users/groups assigned access
- [ ] Certificate uploaded (if using certificate auth)

### 10.3 Gateway Configuration

- [ ] Environment variables configured correctly
- [ ] Trusted domains configured
- [ ] SSO_AUTO_CREATE_USERS set appropriately
- [ ] SSO_PRESERVE_ADMIN_AUTH enabled (recommended)
- [ ] Logs configured for audit trail

### 10.4 Monitoring and Compliance

- [ ] Azure AD sign-in logs monitoring enabled
- [ ] Audit logs reviewed regularly
- [ ] Conditional Access policy reports enabled
- [ ] Security alerts configured
- [ ] Regular access reviews scheduled
- [ ] Compliance reporting set up (if required)

## Troubleshooting

### Error: "SSO authentication is disabled"

**Problem**: SSO endpoints return 404
**Solution**: Set `SSO_ENABLED=true` and `SSO_ENTRA_ENABLED=true`, then restart gateway

```bash
# Verify SSO is enabled
curl -I http://localhost:8000/auth/sso/providers
# Should return 200 OK
```

### Error: "invalid_client"

**Problem**: Wrong client ID or client secret
**Solution**: Verify credentials from Azure portal match exactly

```bash
# Double-check these values from Azure portal Overview page
SSO_ENTRA_CLIENT_ID=your-actual-client-id  # Application (client) ID
SSO_ENTRA_TENANT_ID=your-actual-tenant-id  # Directory (tenant) ID
SSO_ENTRA_CLIENT_SECRET=your-actual-secret # From Certificates & secrets
```

### Error: "redirect_uri_mismatch"

**Problem**: Azure redirect URI doesn't match
**Solution**: Verify exact URL match in Azure app registration

```bash
# Azure redirect URI must exactly match:
https://your-domain.com/auth/sso/callback/entra

# Common mistakes:
https://your-domain.com/auth/sso/callback/entra/  # Extra slash
http://your-domain.com/auth/sso/callback/entra   # HTTP instead of HTTPS
https://your-domain.com/auth/sso/callback/azure  # Wrong provider ID
```

To fix:

1. Go to Azure Portal → App registrations → Your app
2. Click **Authentication**
3. Add/correct the redirect URI under **Web**
4. Click **Save**

### Error: "AADSTS50105: User not assigned to application"

**Problem**: User doesn't have access to the application
**Solution**: Assign user to the application

1. Go to **Microsoft Entra ID** → **Enterprise applications**
2. Find your MCP Gateway app
3. Go to **Users and groups**
4. Click **+ Add user/group**
5. Select the user and click **Assign**

### Error: "AADSTS65001: User or administrator has not consented"

**Problem**: Application permissions not consented
**Solution**: Grant admin consent for permissions

1. Go to your app registration → **API permissions**
2. Click **Grant admin consent for [Organization]**
3. Click **Yes** to confirm
4. Verify all permissions show **Granted** status

### Error: "AADSTS700016: Application not found in the directory"

**Problem**: Wrong tenant ID or application deleted
**Solution**: Verify tenant ID and application existence

```bash
# Check tenant ID in Azure portal
# Microsoft Entra ID → Overview → Tenant ID
SSO_ENTRA_TENANT_ID=correct-tenant-id-here
```

### Secret Expiration Issues

**Problem**: Client secret expired
**Solution**: Create new secret and update configuration

1. Go to app registration → **Certificates & secrets**
2. Delete expired secret (optional)
3. Create new client secret
4. Update `SSO_ENTRA_CLIENT_SECRET` in your environment
5. Restart gateway

### Token Validation Errors

**Problem**: JWT tokens failing validation
**Solution**: Check token configuration and issuer

```bash
# Verify the correct issuer format
# Should be: https://login.microsoftonline.com/{tenant-id}/v2.0
# Gateway constructs this automatically from tenant ID
```

### MFA Not Prompting

**Problem**: MFA not enforced during login
**Solution**: Check Conditional Access policies

1. Verify MFA is enabled for the user
2. Check Conditional Access policies apply to your app
3. Ensure policy is enabled (not in "Report-only" mode)

## Testing Checklist

- [ ] App registration created in Azure portal
- [ ] Client ID, secret, and tenant ID copied
- [ ] Redirect URIs configured correctly
- [ ] API permissions granted
- [ ] Admin consent granted (if required)
- [ ] Users assigned to application
- [ ] Environment variables configured
- [ ] Gateway restarted with new config
- [ ] `/auth/sso/providers` returns Entra ID provider
- [ ] Login page shows Microsoft/Entra ID button
- [ ] Authentication flow completes successfully
- [ ] User created in gateway user list
- [ ] User profile populated with correct data
- [ ] MFA working (if configured)
- [ ] Conditional Access policies enforced (if configured)
- [ ] Group claims included in tokens (if configured)

## Security Best Practices

### Secret Management

**DO**:

- ✅ Store client secrets in Azure Key Vault
- ✅ Rotate secrets regularly (every 90-180 days)
- ✅ Use separate app registrations for dev/staging/prod
- ✅ Set secret expiration reminders

**DON'T**:

- ❌ Store secrets in source control
- ❌ Share secrets via email or chat
- ❌ Use the same secret across environments
- ❌ Use secrets without expiration

### Access Control

1. **Principle of Least Privilege**: Only grant necessary permissions
2. **User Assignment**: Enable user assignment required
3. **Group-based Access**: Use security groups instead of individual users
4. **Regular Reviews**: Audit user access quarterly

### Monitoring

1. Enable **Sign-in logs** in Azure AD
2. Configure **Diagnostic settings** to send logs to Log Analytics
3. Set up **Alerts** for suspicious sign-ins
4. Review **Audit logs** for configuration changes

## Next Steps

After Microsoft Entra ID SSO is working:

1. **Configure Conditional Access** for enhanced security
2. **Enable MFA** for all users (if not already enabled)
3. **Set up app roles** for RBAC integration
4. **Configure group claims** for automatic team assignment
5. **Implement certificate authentication** for higher security
6. **Set up monitoring and alerting** for security events
7. **Document your configuration** for team reference

## Related Documentation

- [Complete SSO Guide](sso.md) - Full SSO documentation
- [GitHub SSO Tutorial](sso-github-tutorial.md) - GitHub setup guide
- [Google SSO Tutorial](sso-google-tutorial.md) - Google setup guide
- [IBM Security Verify Tutorial](sso-ibm-tutorial.md) - IBM setup guide
- [Okta SSO Tutorial](sso-okta-tutorial.md) - Okta setup guide
- [Team Management](teams.md) - Managing teams and roles
- [RBAC Configuration](rbac.md) - Role-based access control

## Support and Resources

### Microsoft Documentation

- [Microsoft identity platform documentation](https://learn.microsoft.com/en-us/azure/active-directory/develop/)
- [Microsoft Entra ID authentication scenarios](https://learn.microsoft.com/en-us/azure/active-directory/develop/authentication-scenarios)
- [OAuth 2.0 and OpenID Connect protocols](https://learn.microsoft.com/en-us/azure/active-directory/develop/active-directory-v2-protocols)

### Troubleshooting Resources

1. **Azure AD Sign-in Logs**: Real-time authentication debugging
2. **Error code lookup**: [Azure AD error codes](https://learn.microsoft.com/en-us/azure/active-directory/develop/reference-aadsts-error-codes)
3. **Gateway logs**: Enable `LOG_LEVEL=DEBUG` for detailed SSO flow logging
4. **Microsoft Q&A**: Community support forum

### Getting Help

If you encounter issues:

1. Check Azure AD sign-in logs for detailed error messages
2. Enable debug logging in gateway: `LOG_LEVEL=DEBUG`
3. Review gateway logs for Entra ID-specific errors
4. Verify all Azure settings match tutorial exactly
5. Consult Microsoft documentation and support forums
6. Check [MCP Gateway issue tracker](https://github.com/IBM/mcp-context-forge/issues)
