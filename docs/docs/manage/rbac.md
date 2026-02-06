# RBAC Configuration

Role-based access control (RBAC) defines which actions users or teams can perform in MCP Gateway. This document covers the two-layer security model, token scoping semantics, permission system, and best practices for access control.

---

## Overview

MCP Gateway implements a **two-layer security model**:

1. **Token Scoping (Layer 1)**: Controls what resources a user CAN SEE (data filtering)
2. **RBAC (Layer 2)**: Controls what actions a user CAN DO (action authorization)

Both layers must pass for an operation to succeed.

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                      Two-Layer Security Model                               │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│   Request → Authentication → Token Scoping → RBAC Check → Operation        │
│                              (Can See?)       (Can Do?)                     │
│                                                                             │
│   ┌──────────┐   ┌──────────┐   ┌──────────┐   ┌──────────┐   ┌──────────┐ │
│   │   JWT    │   │  User    │   │ Resource │   │Permission│   │ Execute  │ │
│   │  Token   │──▶│ Identity │──▶│  Access  │──▶│  Check   │──▶│ Operation│ │
│   │          │   │          │   │          │   │          │   │          │ │
│   └──────────┘   └──────────┘   └──────────┘   └──────────┘   └──────────┘ │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Authentication Methods

| Method | Priority | Description |
|--------|----------|-------------|
| JWT Token | 1 (Primary) | Signature verified, supports teams/scopes claims |
| Plugin Auth | 0 (Before JWT) | `HTTP_AUTH_RESOLVE_USER` hook can provide custom auth |
| API Token (DB) | 2 (Fallback) | Legacy database-stored tokens |
| Proxy Header | 3 | When `MCP_CLIENT_AUTH_ENABLED=false` AND `TRUST_PROXY_AUTH=true` |
| Anonymous | 4 | When `AUTH_REQUIRED=false` (development only) |

---

## Core Concepts

### Subjects
Users authenticated via:

- JWT tokens (session or API)
- SSO providers (OAuth 2.0/OIDC)
- Basic authentication (development only)

### Teams
Logical groups that:

- Organize users for access boundaries
- Own resources (tools, prompts, resources)
- Map from external identity providers (SSO groups)

### Built-in RBAC Roles

| Role | Scope | Permissions |
|------|-------|-------------|
| `platform_admin` | global | `["*"]` (all permissions) |
| `team_admin` | team | teams.read, teams.update, teams.join, teams.manage_members, tools.read, tools.execute, resources.read, prompts.read, admin.dashboard,gateways.read,servers.read |
| `developer` | team | teams.join, tools.read, tools.execute, resources.read, prompts.read, admin.dashboard,gateways.read,servers.read |
| `viewer` | team | teams.join, tools.read, resources.read, prompts.read, admin.dashboard,gateways.read,servers.read |

!!! info "Default Role Assignment"
    **New users automatically receive default roles upon creation:**
    
    - **Admin users** (`is_admin: true`): Assigned the `platform_admin` role with global scope
    - **Non-admin users** (`is_admin: false`) with team scope: Assigned the `viewer` role with team scope
    
    This ensures all users have appropriate baseline access to the Admin UI and resources. The `granted_by` field tracks which admin created the user for audit purposes.

!!! note "Existing Users"
    An Alembic migration ensures that existing users without roles receive appropriate default role assignments:
    
    - Admin users without roles are assigned the `platform_admin` role with global scope
    - Non-admin users with team scope but without roles are assigned the `viewer` role with team scope
   
### Resources
Protected entities:

- Servers (MCP gateways and virtual servers)
- Tools, Prompts, Resources (MCP primitives)
- System configuration and audit logs

---

## Token Scoping Model

Token scoping controls what resources a token can access based on the `teams` claim in the JWT payload. The `normalize_token_teams()` function is the **single source of truth** for interpreting JWT team claims across all enforcement points.

### Token Scoping Contract

The `teams` claim in JWT tokens determines resource visibility. The system follows a **secure-first design**: when in doubt, access is denied.

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                        Token Teams Claim Handling                           │
├─────────────────────────────────────────────────────────────────────────────┤
│  JWT Claim State          │  is_admin: true       │  is_admin: false        │
├───────────────────────────┼───────────────────────┼─────────────────────────┤
│  No "teams" key           │  PUBLIC-ONLY []       │  PUBLIC-ONLY []         │
│  teams: null              │  ADMIN BYPASS (None)  │  PUBLIC-ONLY []         │
│  teams: []                │  PUBLIC-ONLY []       │  PUBLIC-ONLY []         │
│  teams: ["team-id"]       │  Team + Public        │  Team + Public          │
│  teams: ["t1", "t2"]      │  Both Teams + Public  │  Both Teams + Public    │
└───────────────────────────┴───────────────────────┴─────────────────────────┘
```

!!! warning "Admin Bypass Requirements"
    Admin bypass (unrestricted access) requires **BOTH** conditions:

    1. `teams: null` (explicit null, not missing key)
    2. `is_admin: true`

    A missing `teams` key always results in public-only access, even for admins.
    An empty `teams: []` also results in public-only access, even for admins.

### Return Value Semantics

| Return Value | Meaning | Query Behavior |
|--------------|---------|----------------|
| `None` | Admin bypass | Skip ALL team filtering |
| `[]` (empty list) | Public-only | Filter to `visibility='public'` ONLY |
| `["t1", "t2"]` | Team-scoped | Filter to team resources + public |

### Security Design Principles

1. **Secure-First Defaults**

   - Missing `teams` key always returns `[]` (public-only access)
   - This prevents accidental exposure when tokens are misconfigured

2. **Explicit Admin Bypass**

   - Admin bypass requires explicit `teams: null` AND `is_admin: true`
   - Empty teams `[]` disables bypass even for admins

3. **Scoped Automation Tokens**

   - Tokens with `teams: []` are intentionally restricted to public resources
   - Use case: CI/CD pipelines, monitoring systems, public API clients

### Token Scoping Flow

```
                                 ┌──────────────────┐
                                 │   JWT Token      │
                                 │   Received       │
                                 └────────┬─────────┘
                                          │
                                          ▼
                              ┌───────────────────────┐
                              │  Extract "teams"      │
                              │  claim from JWT       │
                              └───────────┬───────────┘
                                          │
                          ┌───────────────┴───────────────┐
                          │                               │
                          ▼                               ▼
               ┌─────────────────────┐       ┌─────────────────────┐
               │ "teams" key EXISTS  │       │ "teams" key MISSING │
               └──────────┬──────────┘       └──────────┬──────────┘
                          │                             │
                          ▼                             ▼
               ┌─────────────────────┐       ┌─────────────────────┐
               │ Check teams value   │       │ Return []           │
               └──────────┬──────────┘       │ PUBLIC-ONLY         │
                          │                  │ (secure default)    │
          ┌───────────────┼───────────────┐  └─────────────────────┘
          │               │               │
          ▼               ▼               ▼
  ┌───────────────┐ ┌───────────┐ ┌───────────────┐
  │ teams: null   │ │ teams: [] │ │ teams: [...]  │
  └───────┬───────┘ └─────┬─────┘ └───────┬───────┘
          │               │               │
          ▼               │               ▼
  ┌───────────────┐       │       ┌───────────────┐
  │ Check is_admin│       │       │ Return [...]  │
  └───────┬───────┘       │       │ TEAM-SCOPED   │
          │               │       └───────────────┘
    ┌─────┴─────┐         │
    │           │         │
    ▼           ▼         ▼
┌────────┐ ┌────────┐ ┌────────┐
│ Admin  │ │Non-Adm │ │ Empty  │
│ true   │ │ false  │ │ list   │
├────────┤ ├────────┤ ├────────┤
│ Return │ │ Return │ │ Return │
│ None   │ │ []     │ │ []     │
│ BYPASS │ │ PUBLIC │ │ PUBLIC │
└────────┘ └────────┘ └────────┘
```

!!! note "Key Insight"
    The difference between `teams: null` and missing `teams` key is critical:

    - **Missing key**: Always `[]` (public-only) - secure default
    - **Explicit null**: Admin bypass when `is_admin: true`, otherwise `[]`

### Visibility Levels

Resources in MCP Gateway have three visibility levels:

| Visibility | Description | Who Can See |
|------------|-------------|-------------|
| `public` | Accessible to all authenticated users | Everyone with valid token |
| `team` | Accessible to team members only | Team members + admins (with bypass) |
| `private` | Accessible to owner only | Resource owner + admins (with bypass) |

### Access Matrix by Token Type

| Token Type | Public Resources | Team Resources | Private Resources |
|------------|-----------------|----------------|-------------------|
| Admin Bypass (`teams=null`, `is_admin=true`) | ✅ | ✅ (all teams) | ✅ (all) |
| Team-Scoped (`teams=["t1"]`) | ✅ | ✅ (own team) | ✅ (own only) |
| Public-Only (`teams=[]`) | ✅ | ❌ | ❌ |

!!! warning "Public-Only Token Limitations"
    **Public-only tokens (`teams=[]`) cannot access private resources, even if the resource is owned by the token's user.**

    This is intentional security behavior - public-only tokens are designed for limited-scope access to public resources only. To access private resources, users must use a team-scoped token that includes their personal team.

    ```
    # Public-only token behavior:
    # ✅ Can access: visibility='public' resources
    # ❌ Cannot access: visibility='team' resources (any team)
    # ❌ Cannot access: visibility='private' resources (even if owned by user)
    ```

### Enforcement Points

Token scoping is enforced consistently across all access paths:

| Location | Token Scoping | RBAC | Description |
|----------|--------------|------|-------------|
| Token Scoping Middleware | ✅ | N/A | Request-level data filtering |
| REST API Endpoints | ✅ | ✅ | `@require_permission` decorators |
| RPC Handler (`/rpc`) | ✅ | Varies | Method-specific permission checks |
| Admin UI | ✅ | ✅ | Permission-based UI rendering |
| Service Layer | ✅ | N/A | Database query filtering |
| WebSocket | ✅ | ✅ | Forwards auth to /rpc |
| MCP Transport | ✅ | N/A | Streamable HTTP protocol filtering |

---

## Token Types and Use Cases

### Session Tokens (UI Login)

Generated when users log in via the Admin UI:

```json
{
  "sub": "admin@example.com",
  "is_admin": true,
  "teams": null,
  "iss": "mcpgateway",
  "aud": "mcpgateway-api",
  "exp": 1234567890
}
```

**Behavior**: Admin session tokens should set `teams: null` (explicit null) combined with `is_admin: true` to enable admin bypass (unrestricted access to all resources).

### API Tokens (Programmatic Access)

Generated via the Admin UI or API for automation:

```json
{
  "sub": "service-account@example.com",
  "is_admin": false,
  "teams": ["team-uuid-1", "team-uuid-2"],
  "iss": "mcpgateway",
  "aud": "mcpgateway-api",
  "exp": 1234567890
}
```

**Behavior**: Access restricted to public resources plus resources owned by specified teams.

### Scoped Automation Tokens

For CI/CD, monitoring, or public API access:

```json
{
  "sub": "ci-pipeline@example.com",
  "is_admin": true,
  "teams": [],  // Explicitly empty = public-only
  "iss": "mcpgateway",
  "aud": "mcpgateway-api",
  "exp": 1234567890
}
```

**Behavior**: Even admin tokens with `teams: []` are restricted to public resources only. This enables creating limited-scope tokens for automation that shouldn't access team-internal resources.

---

## Generating Scoped Tokens

### Using the CLI Tool

```bash
# Unrestricted admin token (no teams key)
python3 -m mcpgateway.utils.create_jwt_token \
  --username admin@example.com \
  --exp 60 \
  --secret $JWT_SECRET_KEY

# Team-scoped token
python3 -m mcpgateway.utils.create_jwt_token \
  --username user@example.com \
  --exp 60 \
  --secret $JWT_SECRET_KEY \
  --teams '["team-uuid-1"]'

# Public-only scoped token (for automation)
python3 -m mcpgateway.utils.create_jwt_token \
  --username ci@example.com \
  --exp 60 \
  --secret $JWT_SECRET_KEY \
  --teams '[]'
```

### Using the Admin UI

1. Navigate to **Admin UI → Tokens**
2. Click **Create Token**
3. Select team scope:

   - **No team selected**: Public resources only (secure default)
   - **Specific team(s)**: Team + public resources

4. Configure additional restrictions (IP, permissions, expiry)

!!! warning "Token Scope Warning"
    Tokens created without selecting a team will have access to **public resources only**.
    This is the secure default to prevent accidental exposure of team resources.

---

## Permission System

### Permission Categories

Permissions are defined in the `Permissions` class and control what actions users can perform:

| Category | Permissions |
|----------|-------------|
| **Users** | users.create, users.read, users.update, users.delete, users.invite |
| **Teams** | teams.create, teams.read, teams.update, teams.delete, teams.join, teams.manage_members |
| **Tools** | tools.create, tools.read, tools.update, tools.delete, tools.execute |
| **Resources** | resources.create, resources.read, resources.update, resources.delete, resources.share |
| **Gateways** | gateways.create, gateways.read, gateways.update, gateways.delete |
| **Prompts** | prompts.create, prompts.read, prompts.update, prompts.delete, prompts.execute |
| **Servers** | servers.create, servers.read, servers.update, servers.delete, servers.manage |
| **Tokens** | tokens.create, tokens.read, tokens.update, tokens.revoke |
| **Admin** | admin.system_config, admin.user_management, admin.security_audit, admin.overview, admin.dashboard, admin.events, admin.grpc, admin.plugins |
| **A2A** | a2a.create, a2a.read, a2a.update, a2a.delete, a2a.invoke |
| **Tags** | tags.read, tags.create, tags.update, tags.delete |
| **Wildcard** | `*` (all permissions) |

### Permission Checking Flow

```
@require_permission("resource.action")
    │
    ▼
┌─────────────────────────────┐
│ Extract user_context        │ ← From request/kwargs
└─────────────────────────────┘
    │
    ▼
┌─────────────────────────────┐
│ Plugin Permission Hook      │ ← HTTP_AUTH_CHECK_PERMISSION can override
└─────────────────────────────┘
    │ (no plugin decision)
    ▼
┌─────────────────────────────┐
│ Admin Bypass Check          │ ← If allow_admin_bypass=True AND user.is_admin
└─────────────────────────────┘
    │ (not admin or bypass disabled)
    ▼
┌─────────────────────────────┐
│ Role Collection             │ ← Get all active roles for user
│ - Global scope roles        │
│ - Personal scope roles      │
│ - Team scope roles          │
└─────────────────────────────┘
    │
    ▼
┌─────────────────────────────┐
│ Permission Aggregation      │ ← Collect permissions from roles
│ - Include inherited perms   │   (role inheritance supported)
│ - Check for wildcard (*)    │
└─────────────────────────────┘
    │
    ▼
┌─────────────────────────────┐
│ Fallback Permission Check   │ ← Implicit permissions (see below)
└─────────────────────────────┘
    │
    ▼
  GRANT or DENY
```

### Fallback Permissions

The system grants implicit permissions without explicit role assignment. These are **not** shown in `/rbac/my/permissions` but are effective:

| User Context | Implicit Permissions |
|--------------|---------------------|
| Any authenticated user | teams.create, teams.read |
| Team member | teams.read (for their teams) |
| Team owner | teams.read, teams.update, teams.delete, teams.manage_members |
| Any authenticated user | tokens.* (for own tokens only) |

!!! info "Why Fallback Permissions Exist"
    Fallback permissions enable basic functionality without requiring explicit role assignment:

    - Users can always create and view teams they belong to
    - Team owners automatically have management rights
    - Users can always manage their own API tokens

### Admin API RBAC

The Admin API enforces **strict RBAC** where even users with `is_admin: true` must have explicit permissions granted. This enables **delegated administration** - granting specific admin capabilities without full superuser access.

**Key behaviors:**

| Aspect | Behavior |
|--------|----------|
| Admin bypass | `allow_admin_bypass=False` on all admin routes |
| `is_admin` flag | Does NOT bypass permission checks |
| UI entry | Requires any `admin.*` permission via `has_admin_permission()` |
| Route protection | All 177 admin routes use `@require_permission` decorators |

**Example: Delegated Server Management**

```json
{
  "role": "server-manager",
  "permissions": [
    "servers.read",
    "servers.create",
    "servers.update",
    "servers.delete"
  ]
}
```

A user with this role can:

- ✅ Access `/admin/servers/*` endpoints
- ✅ View the Admin UI (has `servers.*` which satisfies `has_admin_permission()`)
- ❌ Access `/admin/tools/*` endpoints (no `tools.*` permissions)
- ❌ Access `/admin/gateways/*` endpoints (no `gateways.*` permissions)

!!! warning "Platform Admin Role"
    The built-in `platform_admin` role has `["*"]` (wildcard) permissions, which grants access to all operations. For delegated administration, create custom roles with specific permission sets.

---

## Configuration Safety

### Development vs Production Settings

The following configuration combinations require careful consideration:

| Setting | Value | Impact | Recommended Use |
|---------|-------|--------|-----------------|
| `AUTH_REQUIRED` | `false` | All requests granted admin access | Development only |
| `TRUST_PROXY_AUTH` | `true` + `MCP_CLIENT_AUTH_ENABLED=false` | Trust `X-Forwarded-User` header without verification | Behind trusted reverse proxy only |

### Proxy Authentication Mode

When `MCP_CLIENT_AUTH_ENABLED=false` and `TRUST_PROXY_AUTH=true`:

- The gateway trusts the `X-Forwarded-User` header from upstream proxy
- No JWT validation or database verification is performed
- **Only use** when deployed behind a trusted reverse proxy that handles authentication

!!! danger "Security Warning"
    Proxy authentication mode should only be used in trusted network environments where the reverse proxy is the only entry point to the gateway. Exposing the gateway directly to untrusted networks with this configuration allows header injection attacks.

### Anonymous Mode (AUTH_REQUIRED=false)

When `AUTH_REQUIRED=false`:

- All unauthenticated requests receive platform-admin context
- **Never use in production** - all users have full admin access
- Intended only for local development and testing

!!! danger "Production Warning"
    Setting `AUTH_REQUIRED=false` in production grants administrative access to all requests. This completely bypasses authentication and authorization.

---

## Best Practices

### Token Lifecycle

1. **Use short expiration times** for interactive sessions (hours)
2. **Use longer expiration** for service accounts with IP restrictions
3. **Rotate tokens regularly** (recommended: 90 days for long-lived tokens)
4. **Revoke tokens immediately** when access should be removed

### Team Organization

1. **Create purpose-specific teams**:

   - `platform-admins` - Full administrative access
   - `developers` - Development and testing resources
   - `ci-automation` - CI/CD pipeline access
   - `monitoring` - Read-only observability access

2. **Map SSO groups to teams** for automatic membership management
3. **Use personal teams** for individual resource ownership

### Scoping Strategy

| Use Case | Recommended Token Scope |
|----------|------------------------|
| Admin UI access | Session token (`teams: null` + `is_admin: true`) |
| CI/CD pipeline | `teams: []` (public-only) |
| Service integration | Specific team(s) |
| Developer access | Personal team + project teams |
| Monitoring/alerting | `teams: []` with read permissions |

---

## Troubleshooting

### Token Not Seeing Expected Resources

1. **Check token claims**: Decode the JWT to verify `teams` claim
   ```bash
   # Decode JWT payload (middle section)
   echo "$TOKEN" | cut -d. -f2 | base64 -d | jq .
   ```

2. **Verify resource visibility**: Check the resource's `visibility` and `team_id`
   ```bash
   curl -H "Authorization: Bearer $ADMIN_TOKEN" /tools/{id} | jq '{visibility, teamId}'
   ```

3. **Check user admin status**: Non-admin users without teams get public-only access

### Admin Token Being Restricted

If an admin token is unexpectedly restricted:

1. **Check for explicit `teams` claim**: `teams: []` restricts even admins
2. **Verify `is_admin` flag**: Must be `true` in JWT or database user
3. **Check middleware logs**: Look for "token_teams" in debug output

### Inconsistent Results Between Endpoints

If REST and RPC endpoints return different results:

1. **Check for caching**: REST list endpoints may have cached data
2. **Wait for cache TTL**: Default is 60 seconds for registry cache
3. **Use direct GET**: `/tools/{id}` bypasses list cache

---

## Bootstrap Custom Roles

MCP Gateway allows you to define custom roles that are automatically created during database bootstrap. This is useful for organizations that need to pre-configure roles before deployment.

### Configuration

Enable custom role bootstrapping with these environment variables:

| Variable | Default | Description |
|----------|---------|-------------|
| `MCPGATEWAY_BOOTSTRAP_ROLES_IN_DB_ENABLED` | `false` | Enable loading additional roles from file |
| `MCPGATEWAY_BOOTSTRAP_ROLES_IN_DB_FILE` | `additional_roles_in_db.json` | Path to the JSON file containing role definitions |

### Role Definition Format

Create a JSON file containing an array of role definitions:

```json
[
  {
    "name": "data_analyst",
    "description": "Read-only access for data analysis",
    "scope": "team",
    "permissions": ["tools.read", "resources.read", "prompts.read"],
    "is_system_role": true
  },
  {
    "name": "auditor",
    "description": "Compliance audit access",
    "scope": "global",
    "permissions": ["tools.read", "resources.read", "prompts.read", "servers.read", "gateways.read"],
    "is_system_role": true
  }
]
```

**Required fields:**

- `name` - Unique role name
- `scope` - Either `team` (team-level access) or `global` (system-wide access)
- `permissions` - Array of permission strings (e.g., `tools.read`, `resources.create`)

**Optional fields:**

- `description` - Human-readable description
- `is_system_role` - Set to `true` to prevent users from modifying/deleting the role

### Available Permissions

| Resource | Permissions |
|----------|-------------|
| Tools | `tools.create`, `tools.read`, `tools.update`, `tools.delete`, `tools.execute` |
| Resources | `resources.create`, `resources.read`, `resources.update`, `resources.delete` |
| Prompts | `prompts.create`, `prompts.read`, `prompts.update`, `prompts.delete` |
| Servers | `servers.create`, `servers.read`, `servers.update`, `servers.delete` |
| Gateways | `gateways.create`, `gateways.read`, `gateways.update`, `gateways.delete` |
| Teams | `teams.create`, `teams.read`, `teams.update`, `teams.delete`, `teams.join` |

### Docker Compose Example

```yaml
services:
  gateway:
    environment:
      - MCPGATEWAY_BOOTSTRAP_ROLES_IN_DB_ENABLED=true
      - MCPGATEWAY_BOOTSTRAP_ROLES_IN_DB_FILE=/app/custom_roles.json
    volumes:
      - ./custom_roles.json:/app/custom_roles.json:ro
```

### Kubernetes/Helm Example

```yaml
# values.yaml
mcpContextForge:
  env:
    MCPGATEWAY_BOOTSTRAP_ROLES_IN_DB_ENABLED: "true"
    MCPGATEWAY_BOOTSTRAP_ROLES_IN_DB_FILE: "/config/custom_roles.json"

  # Mount ConfigMap with role definitions
  extraVolumes:
    - name: custom-roles
      configMap:
        name: mcp-gateway-roles
  extraVolumeMounts:
    - name: custom-roles
      mountPath: /config
```

### Error Handling

- **File not found**: Bootstrap continues with default roles only; warning logged
- **Invalid JSON**: Bootstrap continues with default roles only; error logged
- **Malformed entries**: Invalid role entries are skipped with warnings; valid entries are processed

!!! tip "Idempotent Bootstrap"
    Bootstrap is idempotent - running it multiple times won't duplicate roles. Existing roles are detected and skipped.

---

## Related Documentation

- [Team Management](teams.md) - Setting up teams and SSO mapping
- [Security Features](securing.md) - Comprehensive security configuration
- [Configuration Reference](configuration.md) - Environment variables
- [API Usage](api-usage.md) - Token usage in API calls
