# Keycloak OIDC Setup Tutorial

This tutorial walks you through setting up Keycloak Single Sign-On (SSO) authentication for ContextForge, enabling enterprise identity management with the popular open-source identity and access management solution.

## Quick Start (Docker Compose)

Use the preconfigured local SSO stack to test Keycloak end-to-end without external IdP setup:

```bash
make compose-sso
make sso-test-login
```

Or run directly with compose:

```bash
docker compose -f docker-compose.yml -f docker-compose.sso.yml --profile sso up -d
```

Preconfigured local endpoints and credentials:

- Gateway UI: `http://localhost:8080/admin/login`
- Keycloak admin console: `http://localhost:8180` (`admin` / `changeme`)
- Keycloak realm: `mcp-gateway`
- Keycloak client: `mcp-gateway`
- Callback URL: `http://localhost:8080/auth/sso/callback/keycloak`
- Compose wiring: internal Keycloak URL `http://keycloak:8080`, browser URL `http://localhost:8180`
- Test users (all password `changeme`):
  - `admin@example.com`
  - `developer@example.com`
  - `viewer@example.com`
  - `newuser@example.com`

## Prerequisites

- ContextForge installed and running
- Keycloak instance with admin access (self-hosted or cloud)
- Keycloak admin console access with appropriate permissions
- Access to your gateway's environment configuration

## Step 1: Access Keycloak Admin Console

### 1.1 Log into Keycloak

1. Navigate to your Keycloak admin console (typically at `https://keycloak.yourcompany.com/admin`)
2. Log in with your administrator credentials
3. Select the realm you want to use (or create a new one)

   - Default realm: `master`
   - For production, consider creating a dedicated realm

### 1.2 Create or Select Realm

**Creating a New Realm** (Optional):

1. Hover over the realm dropdown in the top-left corner
2. Click **Create Realm**
3. Enter realm details:

   - **Realm name**: `mcp-gateway` (or your preferred name)
   - **Enabled**: Yes

4. Click **Create**

**Using Existing Realm**:

- If using the default `master` realm or an existing realm, simply select it from the dropdown

## Step 2: Create Client in Keycloak

### 2.1 Navigate to Clients

1. In the left sidebar, click **Clients**
2. Click **Create client** button
3. You'll configure the client in the following steps

### 2.2 Configure Client Settings - General Settings

On the **General Settings** page:

**Client type**: `OpenID Connect`

**Client ID**: `mcp-gateway`
- This is your `SSO_KEYCLOAK_CLIENT_ID`
- Use a descriptive name for your organization

Click **Next**

### 2.3 Configure Client Settings - Capability Config

On the **Capability config** page:

**Client authentication**: `On` (required for confidential clients)

**Authorization**: `Off` (not needed for basic SSO)

**Authentication flow**: Select the following:

- ✅ **Standard flow** - Enables authorization code flow (required)
- ✅ **Direct access grants** - Enables direct access (optional, for API access)
- ❌ **Implicit flow** - Leave unchecked (deprecated)
- ❌ **Service accounts roles** - Leave unchecked (unless needed)

Click **Next**

### 2.4 Configure Client Settings - Login Settings

On the **Login settings** page:

**Root URL**: `https://gateway.yourcompany.com`
- For development: `http://localhost:8000`

**Home URL**: `https://gateway.yourcompany.com`

**Valid redirect URIs**: `https://gateway.yourcompany.com/auth/sso/callback/keycloak`
- For development, add: `http://localhost:8000/auth/sso/callback/keycloak`
- You can add multiple redirect URIs (one per line)

**Valid post logout redirect URIs**: `https://gateway.yourcompany.com/admin/login`
- Redirects users after logout

**Web origins**: `https://gateway.yourcompany.com`
- For CORS support
- Use `+` to allow all valid redirect URIs

Click **Save**

### 2.5 Note Client Credentials

After creating the client:

1. Navigate to the **Credentials** tab
2. Copy the **Client secret** value - This is your `SSO_KEYCLOAK_CLIENT_SECRET`
3. **IMPORTANT**: Store this secret securely (use a password manager or vault)
4. The Client ID is visible in the **Settings** tab

## Step 3: Configure Client Scopes and Mappers

### 3.1 Configure Client Scopes

Keycloak includes default scopes for OpenID Connect. Verify these are enabled:

1. In your client's settings, go to **Client scopes** tab
2. Verify these **Assigned default client scopes**:

   - ✅ `email` - Email address scope
   - ✅ `profile` - Basic profile information
   - ✅ `roles` - User roles
   - ✅ `web-origins` - CORS origins

If any are missing, click **Add client scope** and select them from the **Default** type.

### 3.2 Add Custom Mappers (Optional)

To include additional claims in tokens:

1. Go to **Client scopes** → Select a scope (e.g., `profile`)
2. Go to **Mappers** tab
3. Click **Add mapper** → **By configuration**
4. Choose mapper type based on what you need:

**Group Membership Mapper**:

- **Name**: `groups`
- **Mapper Type**: `Group Membership`
- **Token Claim Name**: `groups`
- **Full group path**: Off (for simple group names)
- **Add to ID token**: On
- **Add to access token**: On
- **Add to userinfo**: On

**User Attribute Mapper** (for custom attributes):

- **Name**: `department`
- **Mapper Type**: `User Attribute`
- **User Attribute**: `department`
- **Token Claim Name**: `department`
- **Claim JSON Type**: `String`
- **Add to ID token**: On
- **Add to access token**: On
- **Add to userinfo**: On

## Step 4: Configure Realm and Client Roles

### 4.1 Create Realm Roles

Realm roles apply across all clients in the realm:

1. In the left sidebar, click **Realm roles**
2. Click **Create role**
3. Create roles for your organization:

**Example roles**:

- **Role name**: `gateway-admin`
- **Description**: Administrator role for ContextForge
- Click **Save**

Repeat for additional roles:

- `gateway-user` - Standard user
- `gateway-developer` - Developer access
- `gateway-viewer` - Read-only access

### 4.2 Create Client Roles (Optional)

Client roles are specific to ContextForge client:

1. Navigate to **Clients** → Select your `mcp-gateway` client
2. Go to **Roles** tab
3. Click **Create role**
4. Create client-specific roles:

**Example roles**:

- `admin` - Client admin
- `member` - Client member
- `viewer` - Client viewer

### 4.3 Assign Roles to Users

1. Go to **Users** in the left sidebar
2. Find and select a user
3. Go to **Role mapping** tab
4. Click **Assign role**
5. Select roles to assign:

   - Filter by **Realm roles** or client name
   - Check desired roles
   - Click **Assign**

### 4.4 Configure Role Mappers

To include roles in JWT tokens:

1. Go to **Client scopes** → **roles**
2. Go to **Mappers** tab
3. Verify these mappers exist:

**realm roles**:

- Maps realm roles to `realm_access.roles` claim
- Should be enabled by default

**client roles**:

- Maps client roles to `resource_access.{client_id}.roles` claim
- Should be enabled by default

If missing, create them manually using **Add mapper** → **By configuration** → **User Realm Role** or **User Client Role**.

## Step 5: Configure User Attributes and Groups

### 5.1 Create Groups (Optional)

Groups provide hierarchical organization:

1. In the left sidebar, click **Groups**
2. Click **Create group**
3. Enter group details:

   - **Name**: `Developers`
   - Click **Create**

Create additional groups as needed:

- `Administrators`
- `Operations`
- `Support`

### 5.2 Assign Users to Groups

1. Go to **Users** → Select a user
2. Go to **Groups** tab
3. Click **Join Group**
4. Select desired groups
5. Click **Join**

### 5.3 Add Group Mappers

To include group membership in tokens:

1. Go to **Client scopes** → **profile** (or create custom scope)
2. Go to **Mappers** tab
3. Verify or create **Group Membership** mapper (see Step 3.2)

## Step 6: Configure ContextForge Environment

### 6.1 Keycloak Auto-Discovery Feature

Keycloak provides OpenID Connect auto-discovery, which **reduces configuration from 10 environment variables to just 6**:

- **No need to specify**: Authorization URL, Token URL, Userinfo URL, JWKS URI
- **Only specify**: Base URL, Realm, Client ID, Client Secret

The gateway automatically discovers endpoints from:
```
https://your-keycloak.com/realms/{realm}/.well-known/openid-configuration
```

### 6.2 Update Environment Variables

Add these variables to your `.env` file:

```bash
# Enable SSO System
SSO_ENABLED=true

# Keycloak OIDC Configuration
SSO_KEYCLOAK_ENABLED=true
SSO_KEYCLOAK_BASE_URL=https://keycloak.yourcompany.com
SSO_KEYCLOAK_REALM=master
SSO_KEYCLOAK_CLIENT_ID=mcp-gateway
SSO_KEYCLOAK_CLIENT_SECRET=your-client-secret-from-keycloak

# Optional: Role mapping configuration
SSO_KEYCLOAK_MAP_REALM_ROLES=true
SSO_KEYCLOAK_MAP_CLIENT_ROLES=false

# Optional: Custom JWT claim mapping
SSO_KEYCLOAK_USERNAME_CLAIM=preferred_username
SSO_KEYCLOAK_EMAIL_CLAIM=email
SSO_KEYCLOAK_GROUPS_CLAIM=groups

# Optional: Auto-create users on first login
SSO_AUTO_CREATE_USERS=true

# Optional: Restrict to corporate email domains
SSO_TRUSTED_DOMAINS=["yourcompany.com"]

# Optional: Preserve local admin authentication
SSO_PRESERVE_ADMIN_AUTH=true
```

### 6.3 Example Production Configuration

```bash
# Production Keycloak SSO Setup
SSO_ENABLED=true
SSO_KEYCLOAK_ENABLED=true
SSO_KEYCLOAK_BASE_URL=https://keycloak.acmecorp.com
SSO_KEYCLOAK_REALM=production
SSO_KEYCLOAK_CLIENT_ID=mcp-gateway-prod
SSO_KEYCLOAK_CLIENT_SECRET=AbC~dEf1GhI2jKl3MnO4pQr5StU6vWx7YzA8bcD9efG0

# Role mapping - include realm roles, exclude client roles
SSO_KEYCLOAK_MAP_REALM_ROLES=true
SSO_KEYCLOAK_MAP_CLIENT_ROLES=false

# Custom claims for enterprise directory
SSO_KEYCLOAK_USERNAME_CLAIM=preferred_username
SSO_KEYCLOAK_EMAIL_CLAIM=email
SSO_KEYCLOAK_GROUPS_CLAIM=groups

# Enterprise security settings
SSO_AUTO_CREATE_USERS=true
SSO_TRUSTED_DOMAINS=["acmecorp.com"]
SSO_PRESERVE_ADMIN_AUTH=true
```

### 6.4 Development Configuration

```bash
# Development Keycloak SSO Setup
SSO_ENABLED=true
SSO_KEYCLOAK_ENABLED=true
SSO_KEYCLOAK_BASE_URL=http://localhost:8080
SSO_KEYCLOAK_REALM=master
SSO_KEYCLOAK_CLIENT_ID=mcp-gateway-dev
SSO_KEYCLOAK_CLIENT_SECRET=dev-client-secret-value

# More permissive for testing
SSO_KEYCLOAK_MAP_REALM_ROLES=true
SSO_KEYCLOAK_MAP_CLIENT_ROLES=true
SSO_AUTO_CREATE_USERS=true
SSO_PRESERVE_ADMIN_AUTH=true
```

### 6.5 Multi-Realm Configuration

For organizations with multiple realms:

```bash
# Development Realm
SSO_KEYCLOAK_REALM=development
SSO_KEYCLOAK_CLIENT_ID=mcp-gateway-dev
# Redirect: https://gateway-dev.yourcompany.com/auth/sso/callback/keycloak

# Staging Realm
SSO_KEYCLOAK_REALM=staging
SSO_KEYCLOAK_CLIENT_ID=mcp-gateway-staging
# Redirect: https://gateway-staging.yourcompany.com/auth/sso/callback/keycloak

# Production Realm
SSO_KEYCLOAK_REALM=production
SSO_KEYCLOAK_CLIENT_ID=mcp-gateway-prod
# Redirect: https://gateway.yourcompany.com/auth/sso/callback/keycloak
```

### 6.6 Configuration Variables Reference

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `SSO_KEYCLOAK_ENABLED` | Yes | `false` | Enable Keycloak SSO provider |
| `SSO_KEYCLOAK_BASE_URL` | Yes | - | Base URL of Keycloak instance |
| `SSO_KEYCLOAK_PUBLIC_BASE_URL` | No | _unset_ | Browser-facing Keycloak URL used for authorization redirects when gateway uses an internal URL |
| `SSO_KEYCLOAK_REALM` | Yes | `master` | Keycloak realm name |
| `SSO_KEYCLOAK_CLIENT_ID` | Yes | - | OAuth client ID from Keycloak |
| `SSO_KEYCLOAK_CLIENT_SECRET` | Yes | - | OAuth client secret from Keycloak |
| `SSO_KEYCLOAK_MAP_REALM_ROLES` | No | `true` | Include realm roles in user profile |
| `SSO_KEYCLOAK_MAP_CLIENT_ROLES` | No | `false` | Include client-specific roles |
| `SSO_KEYCLOAK_USERNAME_CLAIM` | No | `preferred_username` | JWT claim for username |
| `SSO_KEYCLOAK_EMAIL_CLAIM` | No | `email` | JWT claim for email |
| `SSO_KEYCLOAK_GROUPS_CLAIM` | No | `groups` | JWT claim for group membership |
| `SSO_KEYCLOAK_ROLE_MAPPINGS` | No | `{}` | JSON map of Keycloak roles/groups to Gateway RBAC roles |
| `SSO_KEYCLOAK_DEFAULT_ROLE` | No | _unset_ | Fallback role when no mapping matches |
| `SSO_KEYCLOAK_RESOLVE_TEAM_SCOPE_TO_PERSONAL_TEAM` | No | `false` | Resolve team-scoped mapped roles to the user's personal team |

## Step 7: Restart and Verify Gateway

### 7.1 Restart the Gateway

```bash
# Development
make dev

# Or directly with uvicorn
uvicorn mcpgateway.main:app --reload --host 0.0.0.0 --port 8000

# Production
make serve
```

### 7.2 Verify Keycloak SSO is Enabled

Test that Keycloak appears in SSO providers:

```bash
# Check if Keycloak is listed
curl -X GET http://localhost:8000/auth/sso/providers

# Should return Keycloak in the list:
[
  {
    "id": "keycloak",
    "name": "keycloak",
    "display_name": "Keycloak"
  }
]
```

### 7.3 Check Startup Logs

Verify no errors in the logs:

```bash
# Look for SSO initialization messages
tail -f logs/gateway.log | grep -i keycloak

# Should see:
# INFO: SSO provider 'keycloak' initialized successfully
# INFO: Keycloak auto-discovery loaded endpoints from https://.../.well-known/openid-configuration
```

### 7.4 Test Auto-Discovery Endpoint

Verify Keycloak's OIDC discovery endpoint is accessible:

```bash
# Test OIDC discovery
curl https://keycloak.yourcompany.com/realms/master/.well-known/openid-configuration

# Should return JSON with endpoints:
{
  "issuer": "https://keycloak.yourcompany.com/realms/master",
  "authorization_endpoint": "https://keycloak.yourcompany.com/realms/master/protocol/openid-connect/auth",
  "token_endpoint": "https://keycloak.yourcompany.com/realms/master/protocol/openid-connect/token",
  "userinfo_endpoint": "https://keycloak.yourcompany.com/realms/master/protocol/openid-connect/userinfo",
  ...
}
```

## Step 8: Test Keycloak SSO Login

### 8.1 Access Login Page

1. Navigate to your gateway's login page:

   - Development: `http://localhost:8000/admin/login`
   - Production: `https://gateway.yourcompany.com/admin/login`

2. You should see a "Keycloak" button with a key icon

### 8.2 Test Authentication Flow

1. Click **Continue with Keycloak**
2. You'll be redirected to Keycloak's sign-in page
3. Enter your Keycloak username and password
4. Complete multi-factor authentication if configured in Keycloak
5. Grant consent for the application if prompted (first-time users)
6. You'll be redirected back to the gateway admin panel
7. You should be logged in successfully

### 8.3 Verify User Creation

Check that a user was created in the gateway:

```bash
# Using the admin API (requires admin token)
curl -H "Authorization: Bearer YOUR_ADMIN_TOKEN" \
  http://localhost:8000/auth/users

# Look for your Keycloak email in the user list
```

### 8.4 Verify User Profile and Roles

Check that user attributes and roles were imported correctly:

```bash
# Get user details
curl -H "Authorization: Bearer YOUR_ADMIN_TOKEN" \
  http://localhost:8000/auth/users/{user_id}

# Verify fields are populated:
# - email: your@company.com
# - full_name: First Last
# - provider: keycloak
# - provider_id: unique-keycloak-id
# - roles: [list of realm/client roles if mapped]
# - groups: [list of groups if mapped]
```

### 8.5 Test Role Mapping

If `SSO_KEYCLOAK_MAP_REALM_ROLES=true`, verify roles are included:

```bash
# Decode JWT token to inspect claims
# Use https://jwt.io or a JWT decoding library

# Expected claims:
{
  "realm_access": {
    "roles": ["gateway-admin", "gateway-user"]
  },
  "resource_access": {
    "mcp-gateway": {
      "roles": ["admin", "member"]  # If MAP_CLIENT_ROLES=true
    }
  },
  "groups": ["/Developers", "/Administrators"]
}
```

## Step 9: Configure Advanced Features

### 9.1 Multi-Factor Authentication (MFA)

Configure MFA in Keycloak for enhanced security:

1. Go to **Authentication** in the left sidebar
2. Select **Flows** tab
3. Configure **Browser** flow:

   - Add **OTP Form** execution
   - Set to **Required**

4. Go to **Required Actions** tab
5. Enable **Configure OTP** for first-time setup

Users will be prompted to configure OTP (Google Authenticator, etc.) on first login.

### 9.2 Conditional Authentication

Create custom authentication flows:

1. Go to **Authentication** → **Flows**
2. Click **Create flow**
3. Add conditional logic:

   - **Condition - User Role**: Check if user has specific role
   - **Condition - User Attribute**: Check custom attributes
   - **OTP Form**: Require MFA for admins only

### 9.3 Identity Brokering

Connect Keycloak to external identity providers:

1. Go to **Identity Providers** in the left sidebar
2. Click **Add provider**
3. Select provider type:

   - **GitHub** - Social login
   - **Google** - Google Workspace
   - **Microsoft** - Azure AD/Entra ID
   - **SAML v2.0** - Enterprise SAML providers
   - **OpenID Connect** - Generic OIDC providers

Configure the provider and users can login through Keycloak using external accounts.

### 9.4 User Federation

Sync users from LDAP/Active Directory:

1. Go to **User federation** in the left sidebar
2. Click **Add LDAP providers** (or Kerberos)
3. Configure connection:

   - **Connection URL**: `ldap://ldap.company.com:389`
   - **Bind DN**: Service account DN
   - **Bind Credential**: Service account password

4. Configure user mapping:

   - **User Object Classes**: `person, organizationalPerson, user`
   - **Username LDAP attribute**: `sAMAccountName`
   - **RDN LDAP attribute**: `cn`
   - **UUID LDAP attribute**: `objectGUID`

5. Click **Test connection** and **Test authentication**
6. Click **Save**
7. Click **Synchronize all users** to import LDAP users

### 9.5 Custom Themes and Branding

Customize Keycloak's login page appearance:

1. Go to **Realm settings** → **Themes** tab
2. Configure themes:

   - **Login theme**: Custom branded login page
   - **Account theme**: Custom account management UI
   - **Email theme**: Branded email templates

3. Or create custom theme:

   - Place theme files in `themes/{theme-name}/` directory
   - Update realm theme settings
   - Restart Keycloak

### 9.6 Events and Monitoring

Configure audit logging:

1. Go to **Realm settings** → **Events** tab
2. **Login events settings**:

   - Enable **Save Events**: Yes
   - Set **Expiration**: 7 days (or longer for compliance)
   - Select events to log (Login, Logout, Register, etc.)

3. **Admin events settings**:

   - Enable **Save Events**: Yes
   - Enable **Include Representation**: Yes (for detailed audit)

View events:

- **Events** → **Login events**: User authentication events
- **Events** → **Admin events**: Configuration changes

## Step 10: Production Deployment Checklist

### 10.1 Security Requirements

- [ ] HTTPS enforced for all redirect URIs
- [ ] Client secrets stored securely (HashiCorp Vault, Kubernetes Secrets)
- [ ] MFA enabled for administrators
- [ ] MFA recommended or required for all users
- [ ] Strong password policies configured
- [ ] Session timeout configured appropriately
- [ ] Brute force detection enabled

### 10.2 Keycloak Configuration

- [ ] Client created with correct settings
- [ ] Client ID and client secret documented securely
- [ ] Redirect URIs match production URLs exactly
- [ ] Client scopes configured (email, profile, roles, groups)
- [ ] Required mappers added for custom claims
- [ ] Realm roles defined and assigned
- [ ] Client roles defined (if needed)
- [ ] Users assigned to appropriate roles
- [ ] Groups configured (if using group-based access)

### 10.3 Gateway Configuration

- [ ] Environment variables configured correctly
- [ ] Trusted domains configured for email restrictions
- [ ] `SSO_AUTO_CREATE_USERS` set appropriately
- [ ] `SSO_PRESERVE_ADMIN_AUTH` enabled (recommended)
- [ ] Role mapping settings configured (`MAP_REALM_ROLES`, `MAP_CLIENT_ROLES`)
- [ ] Custom claim mapping configured (username, email, groups)
- [ ] Logs configured for audit trail
- [ ] Auto-discovery endpoint accessible from gateway

### 10.4 Keycloak Hardening

- [ ] Keycloak database secured (TLS, strong passwords)
- [ ] Keycloak admin console access restricted (IP allowlist)
- [ ] Keycloak running behind reverse proxy (HTTPS termination)
- [ ] Keycloak realm settings reviewed for security
- [ ] Password policies enforced (complexity, history, expiration)
- [ ] Brute force detection enabled (failed login lockout)
- [ ] Events logging enabled for audit compliance
- [ ] LDAP/AD integration secured (if applicable)
- [ ] Regular Keycloak updates applied

### 10.5 Monitoring and Compliance

- [ ] Keycloak login events monitoring enabled
- [ ] Keycloak admin events monitoring enabled
- [ ] Gateway SSO logs reviewed regularly
- [ ] Alerting configured for authentication failures
- [ ] Regular access reviews scheduled
- [ ] Compliance reporting configured (if required)

## Troubleshooting

### Error: "SSO authentication is disabled"

**Problem**: SSO endpoints return 404
**Solution**: Set `SSO_ENABLED=true` and `SSO_KEYCLOAK_ENABLED=true`, then restart gateway

```bash
# Verify SSO is enabled
curl -I http://localhost:8000/auth/sso/providers
# Should return 200 OK
```

### Error: "Invalid client credentials"

**Problem**: Wrong client ID or client secret
**Solution**: Verify credentials from Keycloak admin console match exactly

```bash
# Double-check these values from Keycloak client settings
SSO_KEYCLOAK_CLIENT_ID=mcp-gateway  # From client General Settings
SSO_KEYCLOAK_CLIENT_SECRET=your-actual-secret  # From client Credentials tab
SSO_KEYCLOAK_REALM=master  # Realm name (case-sensitive)
```

Verify in Keycloak:

1. Go to **Clients** → Select your client
2. **Settings** tab: Verify Client ID
3. **Credentials** tab: Regenerate secret if needed

### Error: "redirect_uri_mismatch"

**Problem**: Keycloak redirect URI doesn't match
**Solution**: Verify exact URL match in Keycloak client configuration

```bash
# Keycloak redirect URI must exactly match:
https://your-domain.com/auth/sso/callback/keycloak

# Common mistakes:
https://your-domain.com/auth/sso/callback/keycloak/  # Extra slash
http://your-domain.com/auth/sso/callback/keycloak   # HTTP instead of HTTPS
https://your-domain.com/auth/sso/callback/generic   # Wrong provider ID
```

To fix:

1. Go to Keycloak Admin Console → **Clients** → Your client
2. Go to **Settings** tab
3. Update **Valid redirect URIs** field
4. Add exact callback URL (one per line)
5. Click **Save**

### Error: "User not found" or "Email not verified"

**Problem**: User email not verified in Keycloak
**Solution**: Verify user's email in Keycloak

1. Go to **Users** → Find user
2. Go to **Details** tab
3. Check **Email verified**: Set to **On**
4. Click **Save**

Or configure Keycloak to skip email verification:

1. Go to **Realm settings** → **Login** tab
2. Disable **Verify email**

### Error: "Failed to discover OIDC endpoints"

**Problem**: Auto-discovery endpoint not accessible
**Solution**: Verify Keycloak base URL and realm are correct

```bash
# Test discovery endpoint manually
curl https://keycloak.yourcompany.com/realms/master/.well-known/openid-configuration

# Should return JSON with OIDC endpoints
# If this fails, check:
# - Base URL is correct and accessible from gateway
# - Realm name is spelled correctly (case-sensitive)
# - Keycloak is running and healthy
# - Network/firewall rules allow access
```

### Error: "Invalid issuer in JWT token"

**Problem**: JWT issuer doesn't match expected value
**Solution**: Verify realm and base URL configuration

```bash
# Expected issuer format:
https://keycloak.yourcompany.com/realms/{realm}

# Common issues:
# - Base URL includes "/auth" path for older Keycloak versions (pre-17)
# - Realm name mismatch (case-sensitive)
# - Base URL with trailing slash

# For Keycloak < 17.0, use:
SSO_KEYCLOAK_BASE_URL=https://keycloak.yourcompany.com/auth

# For Keycloak >= 17.0, use:
SSO_KEYCLOAK_BASE_URL=https://keycloak.yourcompany.com
```

### Roles Not Appearing in JWT

**Problem**: User roles not included in JWT token
**Solution**: Configure role mappers and enable role mapping

1. Verify role mappers exist:

   - Go to **Client scopes** → **roles** → **Mappers**
   - Ensure **realm roles** and **client roles** mappers exist

2. Enable role mapping in gateway:
```bash
SSO_KEYCLOAK_MAP_REALM_ROLES=true
SSO_KEYCLOAK_MAP_CLIENT_ROLES=true
```

3. Assign roles to user:

   - Go to **Users** → Select user → **Role mapping**
   - Assign appropriate roles

### Groups Not Appearing in JWT

**Problem**: User groups not included in JWT token
**Solution**: Add group membership mapper

1. Go to **Client scopes** → **profile** (or custom scope)
2. Go to **Mappers** tab
3. Click **Add mapper** → **By configuration**
4. Select **Group Membership**:

   - **Name**: `groups`
   - **Token Claim Name**: `groups`
   - **Full group path**: Off
   - **Add to ID token**: On
   - **Add to userinfo**: On

5. Click **Save**

Update gateway configuration:
```bash
SSO_KEYCLOAK_GROUPS_CLAIM=groups
```

### Keycloak Admin Console Not Accessible

**Problem**: Cannot access Keycloak admin console
**Solution**: Check Keycloak configuration and network

1. Verify Keycloak is running:
```bash
# For containerized Keycloak
docker ps | grep keycloak

# Check Keycloak logs
docker logs keycloak-container
```

2. Check network and firewall rules
3. Verify admin user credentials
4. Reset admin password if needed:
```bash
# Inside Keycloak container
cd /opt/keycloak/bin
./kcadm.sh config credentials --server http://localhost:8080 --realm master --user admin
./kcadm.sh update realms/master -s enabled=true
```

## Testing Checklist

- [ ] Client created in Keycloak admin console
- [ ] Client ID and secret copied securely
- [ ] Redirect URIs configured correctly
- [ ] Client scopes assigned (email, profile, roles)
- [ ] Mappers configured for custom claims
- [ ] Realm roles created and assigned
- [ ] Users assigned to appropriate roles
- [ ] Groups configured (if applicable)
- [ ] Environment variables configured in gateway
- [ ] Gateway restarted with new config
- [ ] `/auth/sso/providers` returns Keycloak provider
- [ ] Login page shows Keycloak button
- [ ] Authentication flow completes successfully
- [ ] User created in gateway user list
- [ ] User profile populated with correct data
- [ ] Roles included in JWT (if `MAP_REALM_ROLES=true`)
- [ ] Groups included in JWT (if groups mapper configured)
- [ ] MFA working (if configured)
- [ ] LDAP sync working (if configured)

## Security Best Practices

### Secret Management

**DO**:

- ✅ Store client secrets in secure vault (HashiCorp Vault, Kubernetes Secrets)
- ✅ Rotate secrets regularly (every 90-180 days)
- ✅ Use separate clients for dev/staging/prod
- ✅ Use separate realms for environment isolation

**DON'T**:

- ❌ Store secrets in source control
- ❌ Share secrets via email or chat
- ❌ Use the same secret across environments
- ❌ Reuse secrets after exposure

### Access Control

1. **Principle of Least Privilege**: Only grant necessary roles
2. **Role-Based Access**: Use realm roles for broad access, client roles for specific permissions
3. **Group-Based Management**: Manage users via groups for easier administration
4. **Regular Reviews**: Audit user access quarterly
5. **Time-Limited Sessions**: Configure appropriate session timeouts

### Keycloak Hardening

1. **Admin Console Access**: Restrict to specific IPs or VPN
2. **Database Security**: Use TLS for database connections, strong passwords
3. **HTTPS Only**: Never run Keycloak on HTTP in production
4. **Brute Force Protection**: Enable lockout after failed login attempts
5. **Password Policies**: Enforce strong passwords (length, complexity, history)
6. **Regular Updates**: Keep Keycloak updated with latest security patches

### Monitoring

1. Enable **Login events** in Keycloak for authentication audit trail
2. Enable **Admin events** for configuration change tracking
3. Configure **Alerts** for suspicious authentication patterns
4. Review **Event logs** regularly for security incidents
5. Export logs to SIEM for centralized monitoring

## Benefits of Keycloak SSO

### Simplified Configuration

Keycloak's auto-discovery reduces configuration by **40%** compared to generic OIDC:

**Generic OIDC requires**:

- Authorization URL
- Token URL
- Userinfo URL
- Issuer URL
- JWKS URI (sometimes)

**Keycloak requires only**:

- Base URL
- Realm name
- Client ID
- Client secret

The gateway automatically discovers all endpoints from the well-known configuration.

### Enterprise Features

- **User Federation**: LDAP/Active Directory synchronization
- **Identity Brokering**: Connect to external IdPs (Google, GitHub, SAML)
- **Multi-Factor Authentication**: Built-in OTP and WebAuthn support
- **Fine-Grained Authorization**: Realm and client roles, group-based access
- **Customizable UI**: Branded login pages and themes
- **Events and Audit**: Comprehensive logging for compliance

### Open Source Advantages

- **Self-Hosted**: Full control over identity data
- **No Vendor Lock-In**: Standards-based OIDC/OAuth 2.0
- **Active Community**: Large ecosystem and plugin support
- **Cost-Effective**: No per-user licensing fees
- **Extensible**: Custom authenticators, mappers, and providers

## Next Steps

After Keycloak SSO is working:

1. **Configure MFA** for enhanced security
2. **Set up user federation** with LDAP/AD (if applicable)
3. **Configure identity brokering** for social login options
4. **Implement fine-grained authorization** with custom roles
5. **Customize login themes** for brand consistency
6. **Set up event logging** for audit compliance
7. **Configure session management** and timeout policies
8. **Implement group-based team mapping** in ContextForge
9. **Document your configuration** for team reference

## Related Documentation

- [Complete SSO Guide](sso.md) - Full SSO documentation
- [GitHub SSO Tutorial](sso-github-tutorial.md) - GitHub setup guide
- [Google SSO Tutorial](sso-google-tutorial.md) - Google setup guide
- [IBM Security Verify Tutorial](sso-ibm-tutorial.md) - IBM setup guide
- [Microsoft Entra ID Tutorial](sso-microsoft-entra-id-tutorial.md) - Microsoft Entra ID setup guide
- [Okta SSO Tutorial](sso-okta-tutorial.md) - Okta setup guide
- [Generic OIDC Tutorial](sso-generic-oidc-tutorial.md) - Generic OIDC providers
- [Team Management](teams.md) - Managing teams and roles
- [RBAC Configuration](rbac.md) - Role-based access control

## Support and Resources

### Keycloak Documentation

- [Keycloak Official Documentation](https://www.keycloak.org/documentation)
- [Server Administration Guide](https://www.keycloak.org/docs/latest/server_admin/)
- [Securing Applications Guide](https://www.keycloak.org/docs/latest/securing_apps/)
- [Authorization Services Guide](https://www.keycloak.org/docs/latest/authorization_services/)

### Troubleshooting Resources

1. **Keycloak Server Logs**: Check Keycloak logs for detailed authentication errors
2. **Gateway logs**: Enable `LOG_LEVEL=DEBUG` for detailed SSO flow logging
3. **OIDC Discovery**: Test `.well-known/openid-configuration` endpoint
4. **Keycloak Community**: Active community forums and mailing lists

### Getting Help

If you encounter issues:

1. Check Keycloak server logs for error messages
2. Verify OIDC discovery endpoint is accessible
3. Enable debug logging in gateway: `LOG_LEVEL=DEBUG`
4. Review gateway logs for Keycloak-specific errors
5. Test JWT token claims at [jwt.io](https://jwt.io)
6. Consult Keycloak documentation and community forums
7. Check [ContextForge issue tracker](https://github.com/IBM/mcp-context-forge/issues)
