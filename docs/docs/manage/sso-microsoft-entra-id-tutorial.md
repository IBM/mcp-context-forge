# Microsoft Entra ID OIDC Setup Tutorial

This tutorial walks you through setting up Microsoft Entra ID (formerly Azure AD) Single Sign-On (SSO) authentication for MCP Gateway, enabling enterprise identity management with Microsoft's cloud identity platform.

## Prerequisites

- Context Forge installed and running
- Microsoft Entra ID tenant with admin access (see below for free options)
- Azure portal access with appropriate permissions
- Access to your gateway's environment configuration

## Getting a Free Microsoft Entra ID Account

If you don't have access to Microsoft Entra ID, you can get a free developer account.

### Option A: Microsoft 365 Developer Program (Recommended)

This provides a full E5 sandbox with **Microsoft Entra ID P2** licenses (25 users).

1. Go to [Microsoft 365 Developer Program](https://developer.microsoft.com/microsoft-365/dev-program)
2. Click **Join now** and sign in with your Microsoft account
3. Fill in the signup form (email, country, company)
4. Accept terms and click **Join**
5. Click **Set up E5 subscription** on your dashboard
6. Choose **Instant sandbox** (recommended)
7. Create your admin account:
   - Username: e.g., `admin`
   - Domain: e.g., `yourname.onmicrosoft.com`
   - Password: Create a strong password
8. Complete phone verification
9. Wait for provisioning (~1 minute)

**Result**: You now have a Microsoft 365 E5 tenant with Entra ID P2 at `admin@yourname.onmicrosoft.com`.

### Option B: Free Azure Account

For basic Entra ID features:

1. Go to [Azure Free Account](https://azure.microsoft.com/free/)
2. Click **Start free** and complete verification
3. You get Entra ID Free tier included

### Option C: Use Existing Organization Tenant

Contact your IT administrator to request access to create App Registrations.

---

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
3. Under **Implicit grant and hybrid flows**:
   - Leave checkboxes **unchecked** (Context Forge uses authorization code flow, not implicit)
4. Under **Advanced settings**:
   - **Allow public client flows**: No (keep default)
   - **Live SDK support**: No (keep default)
5. Click **Save** if you made changes

### 4.3 Configure Front-channel Logout (Optional)

Front-channel logout enables automatic session clearing when users log out from Microsoft Entra ID.

1. Under **Authentication** → **Front-channel logout URL**:
   - Production: `https://gateway.yourcompany.com/admin/logout`
   - Development: `http://localhost:8000/admin/logout`
2. When users log out from Microsoft, Entra ID sends a GET request to this URL
3. Context Forge clears the session cookie and returns HTTP 200

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

# Role Mapping Configuration (New Feature)
# Map EntraID groups to Context Forge roles
SSO_ENTRA_GROUPS_CLAIM=groups
# Optional: Default role for users without group mappings (default: None - no role)
# SSO_ENTRA_DEFAULT_ROLE=viewer
SSO_ENTRA_SYNC_ROLES_ON_LOGIN=true

# Admin Groups (Object IDs or App Role names)
SSO_ENTRA_ADMIN_GROUPS=["a1b2c3d4-1234-5678-90ab-cdef12345678"]

# Group to Role Mapping (JSON format)
# Format: {"group_id_or_name": "role_name"}
SSO_ENTRA_ROLE_MAPPINGS={"e5f6g7h8-1234-5678-90ab-cdef12345678":"developer","i9j0k1l2-1234-5678-90ab-cdef12345678":"team_admin"}
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

# Role Mapping (automatically assign roles based on groups)
SSO_ENTRA_GROUPS_CLAIM=groups
SSO_ENTRA_DEFAULT_ROLE=viewer
SSO_ENTRA_ADMIN_GROUPS=["a1b2c3d4-1234-5678-90ab-cdef12345678"]
SSO_ENTRA_ROLE_MAPPINGS={"e5f6g7h8-1234-5678-90ab-cdef12345678":"developer"}
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

# Role Mapping (optional for development)
SSO_ENTRA_DEFAULT_ROLE=developer
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

Verify SSO provider was created during startup. Check the startup output for:

```
✅ Created SSO provider: Microsoft Entra ID
```

Or if updating an existing provider:

```
🔄 Updated SSO provider: Microsoft Entra ID (ID: entra)
```

**For Docker deployments:**
```bash
docker-compose logs mcpgateway | grep -i "SSO provider"
```

**For systemd deployments:**
```bash
journalctl -u mcpgateway | grep -i "SSO provider"
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
  http://localhost:8000/auth/email/admin/users

# Look for your Microsoft email in the user list
```

### 7.4 Verify User Profile

Check that user attributes were imported correctly:

```bash
# Get user details
curl -H "Authorization: Bearer YOUR_ADMIN_TOKEN" \
  http://localhost:8000/auth/email/admin/users/your@company.com

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

### 8.4 Group Claims Configuration (Required for Role Mapping)

**IMPORTANT**: This step is required to enable automatic role assignment based on group memberships.

> **Critical**: You MUST select **ID** token type when adding group claims. Microsoft's OIDC userinfo endpoint
> does not return group claims. Context Forge extracts groups from the ID token, not the userinfo response.

To include group memberships in tokens:

1. In your app registration, go to **Token configuration**
2. Click **+ Add groups claim**
3. Select group types to include:
   - **Security groups** (recommended)
   - Microsoft 365 groups (if needed)
   - Distribution groups (if needed)
4. Choose **Group ID** format (recommended for stability)
   - **Group ID**: Returns Object IDs (stable, won't change)
   - **sAMAccountName**: Returns group names (readable but can change)
5. **Select token types** (CRITICAL):
   - **ID** - **REQUIRED** for role mapping to work
   - Access (optional, for API authorization)
   - SAML (if using SAML federation)
6. Click **Add**

**Note**: Groups will appear in the `groups` claim in the ID token. You can configure role mappings in Step 8.5 below.

### 8.5 Configure Role Mapping

### Overview

MCP Gateway now supports automatic role assignment based on EntraID group memberships. Users are automatically assigned Context Forge RBAC roles based on their groups, eliminating manual role management.

### Available Roles

Context Forge includes these default roles:

1. **`platform_admin`** (global scope) - Full platform access with all permissions
2. **`team_admin`** (team scope) - Team management, tools, resources, prompts
3. **`developer`** (team scope) - Tool execution and resource access
4. **`viewer`** (team scope) - Read-only access

### 8.5.1 Prerequisites

Ensure you have completed **Step 8.4 Group Claims Configuration** above - groups must be included in ID tokens for role mapping to work.

### 8.5.2 Identify Group Object IDs

Find your security group Object IDs in Azure:

1. Go to **Microsoft Entra ID** → **Groups**
2. Click on a group (e.g., "Developers")
3. Copy the **Object ID** from the Overview page
4. Repeat for all groups you want to map

Example groups:
- Admins: `a1b2c3d4-1234-5678-90ab-cdef12345678`
- Developers: `e5f6g7h8-1234-5678-90ab-cdef12345678`
- Team Admins: `i9j0k1l2-1234-5678-90ab-cdef12345678`
- Viewers: `m3n4o5p6-1234-5678-90ab-cdef12345678`

### 8.5.3 Configure Role Mappings

Add these environment variables to your `.env` file:

```bash
# Role Mapping Configuration
SSO_ENTRA_GROUPS_CLAIM=groups
SSO_ENTRA_DEFAULT_ROLE=viewer
SSO_ENTRA_SYNC_ROLES_ON_LOGIN=true

# Admin Groups (grants platform_admin role)
SSO_ENTRA_ADMIN_GROUPS=["a1b2c3d4-1234-5678-90ab-cdef12345678"]

# Group to Role Mapping (single-line JSON required for .env files)
SSO_ENTRA_ROLE_MAPPINGS={"e5f6g7h8-1234-5678-90ab-cdef12345678":"developer","i9j0k1l2-1234-5678-90ab-cdef12345678":"team_admin","m3n4o5p6-1234-5678-90ab-cdef12345678":"viewer"}
```

**Configuration Options:**

- `SSO_ENTRA_GROUPS_CLAIM`: JWT claim containing groups (default: "groups")
- `SSO_ENTRA_ADMIN_GROUPS`: Groups that grant platform_admin role
- `SSO_ENTRA_ROLE_MAPPINGS`: Map group IDs to role names
- `SSO_ENTRA_DEFAULT_ROLE`: Role assigned if no groups match (default: None - no automatic role assignment)
- `SSO_ENTRA_SYNC_ROLES_ON_LOGIN`: Sync roles on each login (default: true)

**Security Note:** `SSO_ENTRA_DEFAULT_ROLE` defaults to `None` (not "viewer") to prevent automatic access grants. Set this explicitly only if you want all EntraID users to receive a default role when they don't match any group mappings.

### 8.5.4 Using App Roles (Recommended Alternative)

Instead of Security Groups, you can use App Roles for more semantic mappings:

**Step 1: Create App Roles in Azure**

1. In your app registration, go to **App roles**
2. Click **+ Create app role**
3. Create roles:

```
Display name: Admin
Value: Admin
Description: Platform administrators
Allowed member types: Users/Groups

Display name: Developer
Value: Developer
Description: Developers with tool access
Allowed member types: Users/Groups

Display name: TeamAdmin
Value: TeamAdmin
Description: Team administrators
Allowed member types: Users/Groups

Display name: Viewer
Value: Viewer
Description: Read-only users
Allowed member types: Users/Groups
```

**Step 2: Assign Users to App Roles**

1. Go to **Enterprise applications** → Your app
2. Click **Users and groups**
3. Click **+ Add user/group**
4. Select user and assign appropriate role

**Step 3: Configure Role Mappings**

```bash
# Use 'roles' claim instead of 'groups'
SSO_ENTRA_GROUPS_CLAIM=roles

# Map App Role values to Context Forge roles
SSO_ENTRA_ADMIN_GROUPS=["Admin"]
SSO_ENTRA_ROLE_MAPPINGS={"Developer":"developer","TeamAdmin":"team_admin","Viewer":"viewer"}
```

**Benefits of App Roles:**
- ✅ Semantic names (readable)
- ✅ Stable (won't change)
- ✅ No Object ID lookups needed
- ✅ Easier to manage

### 8.5.5 Verify Role Assignment

After configuration, test role assignment:

**Step 1: Login with Test User**

1. Assign a test user to a group/role in Azure
2. Login to MCP Gateway via EntraID SSO
3. Check assigned roles

**Step 2: Verify via API**

```bash
# Get current user's roles
curl -H "Authorization: Bearer YOUR_TOKEN" \
  http://localhost:8000/rbac/my/roles

# Should return assigned roles:
[
  {
    "role_name": "developer",
    "scope": "team",
    "granted_by": "sso_system"
  }
]
```

**Step 3: Check Logs**

```bash
# Look for role assignment messages
tail -f logs/gateway.log | grep "Assigned SSO role"

# Should see:
# INFO: Assigned SSO role 'developer' to user@company.com
# INFO: Mapped EntraID group 'e5f6g7h8-...' to role 'developer'
```

### 8.5.6 Role Synchronization

Roles are automatically synchronized:

**On User Creation:**
- Groups extracted from token
- Roles mapped and assigned
- User created with appropriate permissions

**On User Login (if `SSO_ENTRA_SYNC_ROLES_ON_LOGIN=true`):**
- Current groups extracted
- Old SSO-granted roles revoked if no longer in groups
- New roles assigned based on current groups
- Manually assigned roles preserved

**Manual Role Management:**
- Admins can manually assign additional roles via Admin UI
- Manually assigned roles are preserved during sync
- Only SSO-granted roles (granted_by='sso_system') are synchronized

### 8.5.7 Troubleshooting Role Mapping

**Issue: Users not getting roles**

Check:
1. Groups claim is included in token (Step 8.4)
2. `SSO_ENTRA_GROUPS_CLAIM` matches claim name in token
3. Group IDs in `SSO_ENTRA_ROLE_MAPPINGS` match exactly
4. Roles exist in Context Forge (check Admin UI → RBAC)

Debug:
```bash
# Enable debug logging
LOG_LEVEL=DEBUG

# Check what groups are in the token
# Look for: "Extracted groups from EntraID token"
tail -f logs/gateway.log | grep "groups"
```

**Issue: Admin users not getting admin access**

Check:
1. User's group is in `SSO_ENTRA_ADMIN_GROUPS`
2. Group ID/name matches exactly (case-insensitive)
3. User's `is_admin` flag is set

Debug:
```bash
# Check user's admin status
curl -H "Authorization: Bearer ADMIN_TOKEN" \
  http://localhost:8000/auth/email/admin/users/user@company.com

# Look for: "is_admin": true
```

**Issue: Roles not syncing on login**

Check:
1. `SSO_ENTRA_SYNC_ROLES_ON_LOGIN=true`
2. User has groups in token
3. No errors in logs

Debug:
```bash
# Check for sync messages
tail -f logs/gateway.log | grep "sync"

# Should see:
# INFO: Assigned SSO role 'developer' to user@company.com
# INFO: Revoked SSO role 'old_role' from user@company.com
```

### 8.5.8 Example Configurations

**Example 1: Using Security Groups (Object IDs)**

```bash
SSO_ENTRA_GROUPS_CLAIM=groups
SSO_ENTRA_ADMIN_GROUPS=["a1b2c3d4-1234-5678-90ab-cdef12345678"]
SSO_ENTRA_ROLE_MAPPINGS={"e5f6g7h8-1234-5678-90ab-cdef12345678":"developer","i9j0k1l2-1234-5678-90ab-cdef12345678":"team_admin","m3n4o5p6-1234-5678-90ab-cdef12345678":"viewer"}
SSO_ENTRA_DEFAULT_ROLE=viewer
```

**Example 2: Using App Roles (Recommended)**

```bash
SSO_ENTRA_GROUPS_CLAIM=roles
SSO_ENTRA_ADMIN_GROUPS=["Admin"]
SSO_ENTRA_ROLE_MAPPINGS={"Developer":"developer","TeamAdmin":"team_admin","Viewer":"viewer"}
SSO_ENTRA_DEFAULT_ROLE=viewer
```

**Example 3: Mixed Approach**

```bash
SSO_ENTRA_GROUPS_CLAIM=groups
SSO_ENTRA_ADMIN_GROUPS=["Admin","a1b2c3d4-1234-5678-90ab-cdef12345678"]
SSO_ENTRA_ROLE_MAPPINGS={"Developer":"developer","e5f6g7h8-1234-5678-90ab-cdef12345678":"team_admin"}
```

### 8.5.9 Provider-Level Sync Control

For fine-grained control over role synchronization, you can disable sync at the provider level using the Admin API:

```bash
# Disable role sync for a specific provider
curl -X PUT "http://localhost:8000/auth/sso/admin/providers/entra" \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "provider_metadata": {
      "sync_roles": false,
      "groups_claim": "groups"
    }
  }'
```

This is useful when:
- Provider doesn't emit group claims
- You want to manage roles manually for specific providers
- Migrating from manual to automatic role management

### 8.5.10 Best Practices

**Security:**
- ✅ Leave `SSO_ENTRA_DEFAULT_ROLE` unset unless you want automatic access for all users
- ✅ Use App Roles for stable, semantic mappings
- ✅ Limit admin groups to minimum necessary users
- ✅ Enable role sync to keep permissions current
- ✅ Audit role assignments regularly

**Management:**
- ✅ Document group-to-role mappings
- ✅ Use descriptive App Role names
- ✅ Test with non-admin users first
- ✅ Monitor logs for role assignment issues

**Scalability:**
- ✅ Use groups instead of individual user assignments
- ✅ Leverage Azure group nesting if needed
- ✅ Consider token size limits (~200 groups)
- ✅ Use App Roles for large organizations

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

### 9.3 Certificate-Based Authentication (Future)

> **Note**: Certificate-based authentication is not currently supported by Context Forge. Use client secrets for now. This section documents the Azure configuration for future reference.

For enhanced security, certificates can be used instead of client secrets:

1. In **Certificates & secrets** → **Certificates** tab
2. Click **Upload certificate**
3. Upload .cer, .pem, or .crt file
4. Benefits: No expiration concerns, more secure than secrets

**Current limitation**: Context Forge uses client secrets (`SSO_ENTRA_CLIENT_SECRET`). Certificate authentication support is planned for a future release.

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

### Context Forge Documentation

- [EntraID Role Mapping Feature Guide](sso-entra-role-mapping.md) - Detailed role mapping configuration
- [ADR-034: SSO Admin Sync & Config Precedence](../architecture/adr/034-sso-admin-sync-config-precedence.md) - Design decisions

### Microsoft Documentation

- [Microsoft 365 Developer Program](https://developer.microsoft.com/microsoft-365/dev-program) - Free developer tenant
- [Microsoft identity platform documentation](https://learn.microsoft.com/en-us/azure/active-directory/develop/)
- [Microsoft Entra ID authentication scenarios](https://learn.microsoft.com/en-us/azure/active-directory/develop/authentication-scenarios)
- [OAuth 2.0 and OpenID Connect protocols](https://learn.microsoft.com/en-us/azure/active-directory/develop/active-directory-v2-protocols)
- [Configure optional claims](https://learn.microsoft.com/en-us/entra/identity-platform/optional-claims) - Group limits and token configuration
- [ID token claims reference](https://learn.microsoft.com/en-us/entra/identity-platform/id-token-claims-reference) - Groups overage claim details

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
