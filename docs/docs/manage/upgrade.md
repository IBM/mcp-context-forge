# Upgrading MCP Gateway and Managing Database Migrations

This guide provides step-by-step instructions for upgrading the MCP Gateway and handling associated database migrations to ensure a smooth transition with minimal downtime.

---

## 🔄 Upgrade Overview

MCP Gateway is under active development, and while we strive for backward compatibility, it's essential to review version changes carefully when upgrading. Due to rapid iterations, documentation updates may sometimes lag. If you encounter issues, consult our [GitHub repository](https://github.com/ibm/mcp-context-forge) or reach out via GitHub Issues.

---

## 🛠 Upgrade Steps

### 1. Backup Current Configuration and Data

Before initiating an upgrade:

- **Export Configuration**: Backup your current configuration files.
- **Database Backup**: Create a full backup of your database to prevent data loss.

### 2. Review Release Notes

Check the [release notes](https://github.com/ibm/mcp-context-forge/releases) for:

- **Breaking Changes**: Identify any changes that might affect your current setup.
- **Migration Scripts**: Look for any provided scripts or instructions for database migrations.

### 3. Update MCP Gateway

Depending on your deployment method: podman, docker, kubernetes, etc.

### 4. Apply Database Migrations

If the new version includes database schema changes:

* **Migration Scripts**: Execute any provided migration scripts.
* **Manual Migrations**: If no scripts are provided, consult the release notes for manual migration instructions.

### 5. Verify the Upgrade

Post-upgrade, ensure:

* **Service Availability**: MCP Gateway is running and accessible.
* **Functionality**: All features and integrations are working as expected.
* **Logs**: Check logs for any errors or warnings.

---

## 🆕 Multi-User System Upgrade (v0.6.0+)

### Overview

Version 0.6.0 introduces a comprehensive multi-user authentication system. The upgrade is **backward compatible** with zero breaking changes.

### Migration Options

#### Option 1: Keep Legacy Mode (No Changes Required)
Your existing deployment continues working unchanged:

```bash
# Explicitly enable legacy mode (optional)
LEGACY_AUTH_MODE=true
MULTI_USER_ENABLED=false

# Your existing settings continue to work
BASIC_AUTH_USER=admin
BASIC_AUTH_PASSWORD=changeme
JWT_SECRET_KEY=my-test-key
```

#### Option 2: Migrate to Multi-User Mode (Recommended)

1. **Enable Multi-User Mode**:
   ```bash
   MULTI_USER_ENABLED=true
   LEGACY_AUTH_MODE=false

   # Enhanced JWT configuration
   JWT_ISSUER=mcpgateway
   JWT_AUDIENCE=mcpgateway-api

   # Keep existing credentials for default admin user
   BASIC_AUTH_USER=admin
   BASIC_AUTH_PASSWORD=changeme
   ```

2. **Apply Database Migration**:
   ```bash
   # The migration runs automatically on startup
   # Or run manually if needed:
   alembic upgrade head
   ```

3. **Login with Existing Credentials**:
   ```bash
   curl -X POST http://localhost:4444/auth/login \
     -H "Content-Type: application/json" \
     -d '{"username": "admin", "password": "changeme"}'
   ```

4. **Create Additional Users** (via API or Admin UI):
   ```bash
   curl -X POST http://localhost:4444/users \
     -H "Authorization: Bearer $ACCESS_TOKEN" \
     -d '{"username": "alice", "password": "SecurePassword123!", "email": "alice@company.com"}'
   ```

5. **Create API Tokens**:
   ```bash
   curl -X POST http://localhost:4444/tokens \
     -H "Authorization: Bearer $ACCESS_TOKEN" \
     -d '{"name": "production-api", "expires_in_days": 90}'
   ```

### New Features Available

- **User Management**: Create, manage, and authenticate individual users
- **API Token Management**: Individual token creation, revocation, and tracking
- **Team Collaboration**: Team creation and membership management
- **Resource Scoping**: Private, team, and global resource visibility
- **Security Features**: Password policies, account lockout, audit logging
- **CSRF Protection**: Enhanced security for web interfaces

### Database Schema Changes

The migration adds these tables:
- `users` - User accounts and profiles
- `user_sessions` - Active user sessions
- `api_tokens` - Individual API tokens with revocation
- `auth_events` - Authentication audit log
- `teams`, `team_members`, `team_invitations` - Team management
- Adds `user_id`, `scope_type`, `scope_team_id` columns to existing resource tables

### Rollback Plan

If you need to rollback to legacy mode:

1. **Set Legacy Mode**:
   ```bash
   LEGACY_AUTH_MODE=true
   MULTI_USER_ENABLED=false
   ```

2. **Rollback Database** (if needed):
   ```bash
   alembic downgrade 733159a4fa74
   ```

### Verification Steps

1. **Check Multi-User Status**:
   ```bash
   curl http://localhost:4444/auth/health
   ```

2. **Test Login**:
   ```bash
   curl -X POST http://localhost:4444/auth/login \
     -d '{"username": "admin", "password": "changeme"}'
   ```

3. **Verify Token Creation**:
   ```bash
   curl -X POST http://localhost:4444/tokens \
     -H "Authorization: Bearer $ACCESS_TOKEN" \
     -d '{"name": "test-token"}'
   ```

---

## 🧪 Testing and Validation

* **Staging Environment**: Test the upgrade process in a staging environment before applying to production.
* **Automated Tests**: Run your test suite to catch any regressions.
* **User Acceptance Testing (UAT)**: Engage end-users to validate critical workflows.

---

## 📚 Additional Resources

* [MCP Gateway GitHub Repository](https://github.com/ibm/mcp-context-forge)
* [MCP Gateway Documentation](../index.md)

---
