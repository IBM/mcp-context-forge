# Migration Guide: Upgrading to Multi-Tenancy (v0.6.0 to v0.7.0)

This guide walks you through upgrading from MCP Gateway v0.6.0 to v0.7.0 that implements comprehensive multi-tenancy, team management, and RBAC.

## Overview

Version 0.7.0 introduces major architectural changes:
- **Multi-tenant architecture** with team-based resource isolation
- **Email-based authentication** alongside existing basic auth
- **Personal teams** automatically created for each user
- **Role-Based Access Control (RBAC)** with granular permissions
- **Team visibility controls** (private/public teams, private/team/public resources)
- **SSO integration** with GitHub, Google, and generic OIDC providers

## 🛠️ Migration Tools

This migration includes **2 essential scripts** to help you:

### `scripts/verify_multitenancy_0_7_0_migration.py`
- **Purpose**: Verify v0.6.0 → v0.7.0 migration completed successfully
- **Checks**: Admin user, personal team, resource assignments, visibility settings
- **When**: Run after migration to confirm everything worked

### `scripts/fix_multitenancy_0_7_0_resources.py`
- **Purpose**: Fix resources missing team assignments after v0.6.0 → v0.7.0 upgrade
- **Fixes**: Assigns orphaned servers/tools/resources to admin's personal team
- **When**: Use if verification shows unassigned resources

## Pre-Migration Checklist

### 1. Backup Your Database & Configuration
**⚠️ CRITICAL: Always backup your database AND configuration before upgrading**

#### Database Backup
```bash
# For SQLite (default)
cp mcp.db mcp.db.backup.$(date +%Y%m%d_%H%M%S)

# For PostgreSQL
pg_dump -h localhost -U postgres -d mcp > mcp_backup_$(date +%Y%m%d_%H%M%S).sql

# For MySQL
mysqldump -u mysql -p mcp > mcp_backup_$(date +%Y%m%d_%H%M%S).sql
```

#### Configuration Export (Recommended)
**💡 Export your current configuration via the Admin UI before migration:**

```bash
# 1. Start your current MCP Gateway
make dev  # or however you normally run it

# 2. Access the admin UI
open http://localhost:4444/admin

# 3. Navigate to Export/Import section
# 4. Click "Export Configuration"
# 5. Save the JSON file (contains servers, tools, resources, etc.)

# Or use direct API call (if you have a bearer token):
curl -H "Authorization: Bearer YOUR_TOKEN" \
     "http://localhost:4444/admin/export/configuration" \
     -o mcp_config_backup_$(date +%Y%m%d_%H%M%S).json

# Or with basic auth:
curl -u admin:changeme \
     "http://localhost:4444/admin/export/configuration" \
     -o mcp_config_backup_$(date +%Y%m%d_%H%M%S).json
```

**✅ Benefits**:
- Preserves all your servers, tools, resources, and settings
- Can be imported after migration if needed
- Human-readable JSON format

### 2. Setup Environment Configuration

**⚠️ CRITICAL: You must setup your `.env` file before running the migration**

The migration uses your `.env` configuration to create the platform admin user.

#### If you don't have a `.env` file:
```bash
# Copy the example file
cp .env.example .env

# Edit .env to set your admin credentials
nano .env  # or your preferred editor
```

#### If you already have a `.env` file:
```bash
# Backup your current .env
cp .env .env.backup.$(date +%Y%m%d_%H%M%S)

# Check if you have the required settings
grep -E "PLATFORM_ADMIN_EMAIL|PLATFORM_ADMIN_PASSWORD|EMAIL_AUTH_ENABLED" .env

# If missing, add them or merge from .env.example
```

### 3. Configure Required Settings

**⚠️ REQUIRED: Configure these settings in your `.env` file before migration**

```bash
# Platform Administrator (will be created by migration)
PLATFORM_ADMIN_EMAIL=your-admin@yourcompany.com
PLATFORM_ADMIN_PASSWORD=your-secure-password
PLATFORM_ADMIN_FULL_NAME="Your Name"

# Enable email authentication (required for multi-tenancy)
EMAIL_AUTH_ENABLED=true

# Personal team settings (recommended defaults)
AUTO_CREATE_PERSONAL_TEAMS=true
PERSONAL_TEAM_PREFIX=personal
```

**💡 Tips**:
- Use a **real email address** for `PLATFORM_ADMIN_EMAIL` (you'll use this to log in)
- Choose a **strong password** (minimum 8 characters)
- Set `EMAIL_AUTH_ENABLED=true` to enable the multitenancy features

**🔍 Verify your configuration**:
```bash
# Check your settings are loaded correctly
python3 -c "
from mcpgateway.config import settings
print(f'Admin email: {settings.platform_admin_email}')
print(f'Email auth: {settings.email_auth_enabled}')
print(f'Personal teams: {settings.auto_create_personal_teams}')
"
```

## Migration Process

> **🚨 IMPORTANT**: Before starting the migration, you **must** have a properly configured `.env` file with `PLATFORM_ADMIN_EMAIL` and other required settings. The migration will use these settings to create your admin user. See the Pre-Migration Checklist above.

### Step 1: Update Codebase

```bash
# Pull the latest changes
git fetch origin main
git checkout main
git pull origin main

# Update dependencies
make install-dev
```

### Step 2: Run Database Migration

The migration process is automated and handles:
- Creating multi-tenancy database schema
- Creating platform admin user and personal team
- **Migrating existing servers** to the admin's personal team
- Setting up default RBAC roles

**⚠️ PREREQUISITE**: Ensure `.env` file is configured with `PLATFORM_ADMIN_EMAIL` etc. (see step 3 above)
**✅ Configuration**: Uses your `.env` settings automatically
**✅ Database Compatibility**: Works with **SQLite**, **PostgreSQL**, and **MySQL**

```bash
# IMPORTANT: Setup .env first (if not already done)
cp .env.example .env  # then edit with your admin credentials

# Run the migration (uses settings from your .env file)
python3 -m mcpgateway.bootstrap_db

# Or using make
make dev  # This runs bootstrap_db automatically

# Verify migration completed successfully
python3 scripts/verify_multitenancy_0_7_0_migration.py
```

### Step 3: Verify Migration Results

After migration, verify the results using our verification script:

```bash
# Run comprehensive verification
python3 scripts/verify_multitenancy_0_7_0_migration.py
```

This will check:
- ✅ Platform admin user creation
- ✅ Personal team creation and membership
- ✅ Resource team assignments
- ✅ Visibility settings
- ✅ Database integrity

**Expected Output**: All checks should pass. If any fail, see the troubleshooting section below.

## Post-Migration Configuration

### 1. Verify Server Visibility

Old servers should now be visible in the Virtual Servers list. They will be:
- **Owned by**: Your platform admin user
- **Assigned to**: Admin's personal team
- **Visibility**: Public (visible to all authenticated users)

### 2. Import Configuration (If Needed)

If you exported your configuration before migration and need to restore specific settings:

```bash
# Access the admin UI
open http://localhost:4444/admin

# Navigate to Export/Import section → Import Configuration
# Upload your backup JSON file from step 1

# Or use API:
curl -X POST "http://localhost:4444/admin/import/configuration" \
     -H "Authorization: Bearer YOUR_TOKEN" \
     -H "Content-Type: application/json" \
     -d @mcp_config_backup_YYYYMMDD_HHMMSS.json

# Or with basic auth:
curl -X POST "http://localhost:4444/admin/import/configuration" \
     -u admin:changeme \
     -H "Content-Type: application/json" \
     -d @mcp_config_backup_YYYYMMDD_HHMMSS.json
```

**📋 Import Options**:
- **Merge**: Adds missing resources without overwriting existing ones
- **Replace**: Overwrites existing resources with backup versions
- **Selective**: Choose specific servers/tools/resources to import

### 2. Configure SSO (Optional)

If you want to enable SSO authentication:

```bash
# In .env file - Example for GitHub
SSO_ENABLED=true
SSO_PROVIDERS=["github"]

# GitHub configuration
GITHUB_CLIENT_ID=your-github-app-id
GITHUB_CLIENT_SECRET=your-github-app-secret

# Admin assignment (optional)
SSO_AUTO_ADMIN_DOMAINS=["yourcompany.com"]
SSO_GITHUB_ADMIN_ORGS=["your-org"]
```

### 3. Create Additional Teams

After migration, you can create organizational teams:

```bash
# Via API (with admin token)
curl -X POST http://localhost:4444/admin/teams \
  -H "Authorization: Bearer YOUR_JWT_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Engineering Team",
    "description": "Development and engineering resources",
    "visibility": "private"
  }'

# Or use the Admin UI at http://localhost:4444/admin
```

## Understanding the Migration

### What Happened to My Old Data?

The consolidated migration automatically handles your existing resources in a single, seamless process:

1. **Schema Creation**: Creates all multitenancy tables (users, teams, roles, token management, SSO, etc.)
2. **Column Addition**: Adds `team_id`, `owner_email`, and `visibility` columns to existing resource tables
3. **Admin User Creation**: Creates platform admin user (from `PLATFORM_ADMIN_EMAIL`)
4. **Personal Team Creation**: Creates personal team for the admin user
5. **Data Population**: **Automatically assigns old resources** to admin's personal team with "public" visibility

### Database Tables Created

The migration creates **15 new tables** for the multitenancy system:

**Core Authentication:**
- `email_users` - User accounts and authentication
- `email_auth_events` - Authentication event logging
- `email_api_tokens` - API token management with scoping
- `token_usage_logs` - **Token usage tracking and analytics**
- `token_revocations` - Token revocation blacklist

**Team Management:**
- `email_teams` - Team definitions and settings
- `email_team_members` - Team membership and roles
- `email_team_invitations` - Team invitation workflow
- `email_team_join_requests` - Public team join requests
- `pending_user_approvals` - SSO user approval workflow

**RBAC System:**
- `roles` - Role definitions and permissions
- `user_roles` - User role assignments
- `permission_audit_log` - Permission access auditing

**SSO Integration:**
- `sso_providers` - OAuth2/OIDC provider configuration
- `sso_auth_sessions` - SSO authentication session tracking

This all happens in the consolidated migration `cfc3d6aa0fb2`, so no additional steps are needed.

### Team Assignment Logic

```
Old Server (pre-migration):
├── team_id: NULL
├── owner_email: NULL
└── visibility: NULL

Migrated Server (post-migration):
├── team_id: "admin-personal-team-id"
├── owner_email: "your-admin@yourcompany.com"
└── visibility: "public"
```

### Why "Public" Visibility?

Old servers are set to "public" visibility to ensure they remain accessible to all users immediately after migration. You can adjust visibility per resource:

- **Private**: Only the owner can access
- **Team**: All team members can access
- **Public**: All authenticated users can access

## Customizing Resource Ownership

### Reassign Resources to Specific Teams

After migration, you may want to move resources to appropriate teams:

```bash
# Example: Move a server to a specific team
curl -X PUT http://localhost:4444/admin/servers/SERVER_ID \
  -H "Authorization: Bearer YOUR_JWT_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "team_id": "target-team-id",
    "visibility": "team"
  }'
```

### Change Resource Visibility

```bash
# Make a resource private (owner only)
curl -X PUT http://localhost:4444/admin/servers/SERVER_ID \
  -H "Authorization: Bearer YOUR_JWT_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"visibility": "private"}'

# Make it visible to team members
curl -X PUT http://localhost:4444/admin/servers/SERVER_ID \
  -H "Authorization: Bearer YOUR_JWT_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"visibility": "team"}'
```

## Troubleshooting

### Issue: Servers Not Visible After Migration

**Problem**: Old servers don't appear in the Virtual Servers list.

**Solution**: This should not happen with the current migration. If it does, check:

```bash
# Check if servers have team assignments
python3 -c "
from mcpgateway.db import SessionLocal, Server
with SessionLocal() as db:
    total_servers = db.query(Server).count()
    servers_without_team = db.query(Server).filter(Server.team_id == None).count()
    print(f'Total servers: {total_servers}')
    print(f'Servers without team: {servers_without_team}')
    if servers_without_team > 0:
        print('ISSUE: Some servers lack team assignment')
        print('Re-run the migration: python3 -m mcpgateway.bootstrap_db')
    else:
        print('✓ All servers have team assignments')
"
```

**Root Cause**: The consolidated migration should handle this automatically. If you still see issues:

1. **First, try the fix script** (recommended):
   ```bash
   python3 scripts/fix_multitenancy_0_7_0_resources.py
   ```

2. **If that doesn't work**, ensure `PLATFORM_ADMIN_EMAIL` is set and re-run migration:
   ```bash
   export PLATFORM_ADMIN_EMAIL="your-admin@company.com"
   python3 -m mcpgateway.bootstrap_db
   ```

### Issue: Migration Uses Wrong Admin Email

**Problem**: Migration created admin user with default email (`admin@example.com`) instead of your configured email.

**Root Cause**: `.env` file not properly configured before migration.

**Solution**:
1. **Check your `.env` configuration**:
   ```bash
   # Verify your settings are loaded
   python3 -c "
   from mcpgateway.config import settings
   print(f'Admin email: {settings.platform_admin_email}')
   print(f'Email auth enabled: {settings.email_auth_enabled}')
   "
   ```

2. **If settings are wrong, update `.env` and re-run**:
   ```bash
   # Edit your .env file
   nano .env  # Set PLATFORM_ADMIN_EMAIL=your-email@company.com

   # Re-run migration
   python3 -m mcpgateway.bootstrap_db
   ```

### Issue: Admin User Not Created

**Problem**: Platform admin user was not created during migration.

**Solution**: Check configuration and re-run:

```bash
# First, verify .env configuration
python3 -c "
from mcpgateway.config import settings
print(f'Admin email: {settings.platform_admin_email}')
print(f'Email auth: {settings.email_auth_enabled}')
"

# If EMAIL_AUTH_ENABLED=false, the admin won't be created
# Set EMAIL_AUTH_ENABLED=true in .env and re-run:
python3 -m mcpgateway.bootstrap_db

# Or manually create using bootstrap function:
python3 -c "
import asyncio
from mcpgateway.bootstrap_db import bootstrap_admin_user
asyncio.run(bootstrap_admin_user())
"
```

### Issue: Personal Team Not Created

**Problem**: Admin user exists but has no personal team.

**Solution**: Create personal team manually:

```bash
python3 -c "
import asyncio
from mcpgateway.db import SessionLocal, EmailUser
from mcpgateway.services.personal_team_service import PersonalTeamService

async def create_admin_team():
    with SessionLocal() as db:
        # Replace with your admin email
        admin_email = 'admin@example.com'
        admin = db.query(EmailUser).filter(EmailUser.email == admin_email).first()
        if admin:
            service = PersonalTeamService(db)
            team = await service.create_personal_team(admin)
            print(f'Created personal team: {team.name} (id: {team.id})')

asyncio.run(create_admin_team())
"
```

### Issue: Migration Fails During Execution

**Problem**: Migration encounters errors during execution.

**Solution**: Check the logs and fix common issues:

```bash
# Check database connectivity
python3 -c "
from mcpgateway.db import engine
try:
    with engine.connect() as conn:
        result = conn.execute('SELECT 1')
        print('Database connection: OK')
except Exception as e:
    print(f'Database error: {e}')
"

# Check required environment variables
python3 -c "
from mcpgateway.config import settings
print(f'Database URL: {settings.database_url}')
print(f'Admin email: {settings.platform_admin_email}')
print(f'Email auth enabled: {settings.email_auth_enabled}')
"

# Run migration with verbose output
export LOG_LEVEL=DEBUG
python3 -m mcpgateway.bootstrap_db
```

## Rollback Procedure

If you need to rollback the migration:

### 1. Restore Database Backup

```bash
# For SQLite
cp mcp.db.backup.YYYYMMDD_HHMMSS mcp.db

# For PostgreSQL
dropdb mcp
createdb mcp
psql -d mcp < mcp_backup_YYYYMMDD_HHMMSS.sql

# For MySQL
mysql -u mysql -p -e "DROP DATABASE mcp; CREATE DATABASE mcp;"
mysql -u mysql -p mcp < mcp_backup_YYYYMMDD_HHMMSS.sql
```

### 2. Revert Environment Configuration

```bash
# Restore previous environment
cp .env.backup.YYYYMMDD_HHMMSS .env

# Disable email auth if you want to go back to basic auth only
EMAIL_AUTH_ENABLED=false
```

### 3. Use Previous Codebase Version

```bash
# Check out the previous version
git checkout v0.6.0  # or your previous version tag

# Reinstall dependencies
make install-dev
```

## Verification Checklist

After completing the migration, verify using the automated verification script:

```bash
# Run comprehensive verification
python3 scripts/verify_multitenancy_0_7_0_migration.py
```

Manual checks (if needed):
- [ ] Database migration completed without errors
- [ ] Platform admin user created successfully
- [ ] Personal team created for admin user
- [ ] Old servers are visible in Virtual Servers list
- [ ] Admin UI accessible at `/admin` endpoint
- [ ] Authentication works (email + password)
- [ ] Basic auth still works (if `AUTH_REQUIRED=true`)
- [ ] API endpoints respond correctly
- [ ] Resource creation works and assigns to teams

**If verification fails**: Use the fix script:
```bash
python3 scripts/fix_multitenancy_0_7_0_resources.py
```

## Getting Help

If you encounter issues during migration:

1. **Check the logs**: Set `LOG_LEVEL=DEBUG` for verbose output
2. **Review troubleshooting section** above for common issues
3. **File an issue**: https://github.com/anthropics/claude-code/issues
4. **Include information**: Database type, error messages, relevant logs

## Next Steps

After successful migration:

1. **Review team structure**: Plan how to organize your teams
2. **Configure SSO**: Set up integration with your identity provider
3. **Set up RBAC**: Configure roles and permissions as needed
4. **Train users**: Introduce team-based workflows
5. **Monitor usage**: Use the new audit logs and metrics

The multi-tenant architecture provides much more flexibility and security for managing resources across teams and users. Take time to explore the new admin UI and team management features.

## Quick Reference

### Essential Commands
```bash
# 1. BACKUP (before migration)
cp mcp.db mcp.db.backup.$(date +%Y%m%d_%H%M%S)
curl -u admin:changeme "http://localhost:4444/admin/export/configuration" -o config_backup.json

# 2. SETUP .ENV (required)
cp .env.example .env  # then edit with your admin credentials

# 3. VERIFY CONFIG
python3 -c "from mcpgateway.config import settings; print(f'Admin: {settings.platform_admin_email}')"

# 4. MIGRATE
python3 -m mcpgateway.bootstrap_db

# 5. VERIFY SUCCESS
python3 scripts/verify_multitenancy_0_7_0_migration.py

# 6. FIX IF NEEDED
python3 scripts/fix_multitenancy_0_7_0_resources.py
```

### Important URLs
- **Admin UI**: http://localhost:4444/admin
- **Export Config**: http://localhost:4444/admin/export/configuration
- **Import Config**: http://localhost:4444/admin/import/configuration
