# RBAC Configuration

Role-based access control (RBAC) defines which actions users or teams can perform in MCP Gateway. This document covers the security model, token scoping semantics, and best practices for access control.

---

## Overview

MCP Gateway implements a multi-layered access control system:

1. **Authentication**: Verify user identity via JWT, SSO, or API tokens
2. **Team Membership**: Group users for collective access policies
3. **Token Scoping**: Restrict token capabilities to specific resources
4. **Visibility Filtering**: Control which resources users can discover

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         Access Control Layers                               │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│   Request → Authentication → Team Resolution → Token Scoping → Visibility  │
│                                                                             │
│   ┌──────────┐   ┌──────────┐   ┌──────────┐   ┌──────────┐   ┌──────────┐ │
│   │   JWT    │   │  User    │   │  Token   │   │ Resource │   │ Filtered │ │
│   │  Token   │──▶│ Identity │──▶│  Teams   │──▶│  Access  │──▶│  Results │ │
│   │          │   │          │   │          │   │          │   │          │ │
│   └──────────┘   └──────────┘   └──────────┘   └──────────┘   └──────────┘ │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

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

### Roles
Current role types:
- **Admin**: Full management access, can bypass team restrictions
- **Maintainer**: Manage servers, tools, prompts, configurations
- **Viewer**: Read-only access and metrics

### Resources
Protected entities:
- Servers (MCP gateways and virtual servers)
- Tools, Prompts, Resources (MCP primitives)
- System configuration and audit logs

---

## Token Scoping Model

Token scoping controls what resources a token can access based on the `teams` claim in the JWT payload. This provides fine-grained access control for automation tokens, service accounts, and restricted user sessions.

### Teams Claim Semantics

The `teams` claim in JWT tokens determines resource visibility:

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                        Token Teams Claim Handling                           │
├─────────────────────────────────────────────────────────────────────────────┤
│  JWT Claim State          │  Admin User           │  Non-Admin User         │
├───────────────────────────┼───────────────────────┼─────────────────────────┤
│  No "teams" key           │  UNRESTRICTED         │  PUBLIC-ONLY (secure)   │
│  teams: null              │  UNRESTRICTED         │  PUBLIC-ONLY (secure)   │
│  teams: []                │  PUBLIC-ONLY          │  PUBLIC-ONLY            │
│  teams: ["team-id"]       │  Team + Public        │  Team + Public          │
│  teams: ["t1", "t2"]      │  Both Teams + Public  │  Both Teams + Public    │
└───────────────────────────┴───────────────────────┴─────────────────────────┘
```

### Security Design Principles

1. **Principle of Least Privilege**
   - Non-admin tokens without explicit team scope default to public-only access
   - This prevents accidental exposure of team resources

2. **Scoped Automation Tokens**
   - Admin tokens with `teams: []` are intentionally restricted to public resources
   - Use case: CI/CD pipelines, monitoring systems, public API clients

3. **Backward Compatible Admin Access**
   - Admin session tokens (from UI login) omit the teams claim entirely
   - This grants unrestricted access for administrative operations

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
               │ "teams" key exists  │       │ "teams" key missing │
               │ with non-null value │       │ OR teams: null      │
               └──────────┬──────────┘       └──────────┬──────────┘
                          │                             │
                          ▼                             ▼
               ┌─────────────────────┐       ┌─────────────────────┐
               │ Use explicit scope  │       │ Check is_admin flag │
               │ teams = [...] or [] │       └──────────┬──────────┘
               └──────────┬──────────┘                  │
                          │                 ┌───────────┴───────────┐
                          │                 │                       │
                          │                 ▼                       ▼
                          │      ┌──────────────────┐   ┌──────────────────┐
                          │      │ Admin: teams =   │   │ Non-Admin:       │
                          │      │ None (bypass)    │   │ teams = []       │
                          │      │ UNRESTRICTED     │   │ PUBLIC-ONLY      │
                          │      └────────┬─────────┘   └────────┬─────────┘
                          │               │                      │
                          └───────────────┴──────────────────────┘
                                          │
                                          ▼
                              ┌───────────────────────┐
                              │   Apply visibility    │
                              │   filter to query     │
                              └───────────────────────┘
```

### Visibility Levels

Resources in MCP Gateway have three visibility levels:

| Visibility | Description | Who Can See |
|------------|-------------|-------------|
| `public` | Accessible to all authenticated users | Everyone with valid token |
| `team` | Accessible to team members only | Team members + admins (unrestricted) |
| `private` | Accessible to owner only | Resource owner + admins (unrestricted) |

### Enforcement Points

Token scoping is enforced consistently across all access paths:

| Layer | Location | Description |
|-------|----------|-------------|
| Middleware | `token_scoping.py` | Request-level access control |
| REST API | `main.py` | `/tools`, `/resources`, `/prompts` endpoints |
| RPC Handler | `main.py` | `tools/list`, `resources/list`, `prompts/list` |
| MCP Transport | `streamablehttp_transport.py` | Streamable HTTP protocol filtering |
| Service Layer | `*_service.py` | Database query filtering |

---

## Token Types and Use Cases

### Session Tokens (UI Login)

Generated when users log in via the Admin UI:

```json
{
  "sub": "user@example.com",
  "is_admin": true,
  "iss": "mcpgateway",
  "aud": "mcpgateway-api",
  "exp": 1234567890
  // Note: No "teams" key for admin users = unrestricted access
}
```

**Behavior**: Admin session tokens omit the `teams` claim, granting unrestricted access to all resources.

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
| Admin UI access | Session token (no teams key) |
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

## Related Documentation

- [Team Management](teams.md) - Setting up teams and SSO mapping
- [Security Features](securing.md) - Comprehensive security configuration
- [Configuration Reference](configuration.md) - Environment variables
- [API Usage](api-usage.md) - Token usage in API calls
