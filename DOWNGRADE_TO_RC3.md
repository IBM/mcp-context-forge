# Alembic Downgrade to 1.0.0-RC3

## Overview

This guide provides instructions for downgrading the database schema from the current HEAD to the 1.0.0-RC3 release state.

## Current State Analysis

- **Current HEAD**: `bb43712cae28` (merge of token_blocklist and audit_identity heads)
- **RC3 Release Date**: April 14-17, 2026
- **Target Migration for RC3**: `43c07ed25a24` (add_oauth_fields_to_servers)

## Migration Timeline

The following migrations were added AFTER RC3 and will be rolled back:

1. `bb43712cae28` - Merge token_blocklist with audit_identity heads (Apr 30, 2026)
2. `cae28b15a507` - Merge token_revocation and uaid heads (Apr 21, 2026)
3. `aa1b2c3d4e5f` - Add token revocation idle timeout fields (Apr 21, 2026)
4. `b2c3d4e5f6g7` - Add identity fields to audit_trails (Feb 17, 2026)
5. `a1b2c3d4e5f6` - Add identity_propagation to gateways (Feb 17, 2026)
6. `d2b501bf4262` - Add UAID field to a2a_agents (Apr 14, 2026)
7. `ffe4494639d3` - Add a2a_task_events table (Apr 21, 2026)
8. Several other migrations between RC3 and current

## ⚠️ CRITICAL WARNINGS

### Data Loss Risk

**The following data will be PERMANENTLY DELETED during downgrade:**

1. **Token Revocation Data**:
   - All token blocklist entries
   - Token idle timeout settings
   - JTI-based revocation records

2. **Identity & Audit Data**:
   - Identity propagation settings on gateways
   - Enhanced audit trail identity fields (JTI, reason, security_event, security_severity)

3. **A2A Agent Data**:
   - UAID (Universal Agent ID) fields
   - A2A task events
   - A2A push notification configs

4. **Tool & Plugin Data**:
   - Tool plugin bindings
   - Plugin reference IDs

5. **Other Features**:
   - Title fields on tools, resources, and prompts
   - Various indexes and performance optimizations

### Breaking Changes After Downgrade

After downgrading to RC3, the following features will NO LONGER WORK:

- JWT token revocation (tokens cannot be revoked until expiry)
- Idle timeout enforcement
- UAID-based A2A agent routing
- Enhanced audit logging with security context
- Identity propagation for OAuth flows
- Per-tool plugin configuration

## Prerequisites

### 1. Backup Your Database

**MANDATORY**: Create a full database backup before proceeding.

```bash
# For SQLite
cp mcp.db mcp.db.backup-$(date +%Y%m%d-%H%M%S)

# For PostgreSQL
pg_dump -U postgres -d mcp > mcp-backup-$(date +%Y%m%d-%H%M%S).sql

# For MariaDB/MySQL
mysqldump -u root -p mcp > mcp-backup-$(date +%Y%m%d-%H%M%S).sql
```

### 2. Stop the Gateway

```bash
# Docker Compose
docker compose down

# Kubernetes
kubectl scale deployment mcpgateway --replicas=0 -n <namespace>

# Systemd
sudo systemctl stop mcpgateway
```

### 3. Verify Current Migration State

```bash
cd mcpgateway
alembic current
# Should show: bb43712cae28 (head)

alembic heads
# Should show: bb43712cae28 (head)
```

## Downgrade Procedure

### Step 1: Perform the Downgrade

```bash
cd mcpgateway

# Downgrade to RC3 (43c07ed25a24)
alembic downgrade 43c07ed25a24
```

**Expected Output:**
```
INFO  [alembic.runtime.migration] Context impl SQLiteImpl.
INFO  [alembic.runtime.migration] Will assume non-transactional DDL.
INFO  [alembic.runtime.migration] Running downgrade bb43712cae28 -> cae28b15a507, b2c3d4e5f6g7
INFO  [alembic.runtime.migration] Running downgrade cae28b15a507 -> aa1b2c3d4e5f, d2b501bf4262
INFO  [alembic.runtime.migration] Running downgrade aa1b2c3d4e5f -> z1a2b3c4d5e6
INFO  [alembic.runtime.migration] Running downgrade d2b501bf4262 -> ffe4494639d3
INFO  [alembic.runtime.migration] Running downgrade ffe4494639d3 -> 8f2e1c9b0d3a
...
INFO  [alembic.runtime.migration] Running downgrade ee288b094280 -> 43c07ed25a24
```

### Step 2: Verify Downgrade

```bash
alembic current
# Should show: 43c07ed25a24

alembic heads
# Should show: 43c07ed25a24 (head)
```

### Step 3: Checkout RC3 Code

```bash
cd ..
git fetch --all --tags
git checkout tags/v1.0.0-RC3  # Or the appropriate RC3 tag/commit
```

**Note**: If no RC3 tag exists, use the commit hash from the release:
```bash
git checkout c7eab28f0  # Commit used for RC3 deployment
```

### Step 4: Restart the Gateway

```bash
# Docker Compose
docker compose up -d

# Kubernetes
kubectl scale deployment mcpgateway --replicas=1 -n <namespace>

# Systemd
sudo systemctl start mcpgateway
```

### Step 5: Verify Application Health

```bash
# Check health endpoint
curl http://localhost:4444/health

# Check version
curl http://localhost:4444/version

# Check logs for errors
docker compose logs -f mcpgateway  # Docker
kubectl logs -f deployment/mcpgateway -n <namespace>  # Kubernetes
journalctl -u mcpgateway -f  # Systemd
```

## Troubleshooting

### Migration Fails with "Destination X is not a valid downgrade target"

**Cause**: The target revision is not in the downgrade path from current HEAD.

**Solution**: 
1. Check the migration history: `alembic history --verbose`
2. Verify the target revision exists: `ls mcpgateway/alembic/versions/43c07ed25a24*.py`
3. If the revision doesn't exist, you may need to downgrade to an earlier revision

### Foreign Key Constraint Violations

**Cause**: Data dependencies prevent column/table deletion.

**Solution**:
1. Check the error message for the specific constraint
2. Manually delete dependent data if safe to do so
3. Consider using `--sql` to generate SQL and manually edit it

### Application Fails to Start After Downgrade

**Cause**: Code expects newer schema features.

**Solution**:
1. Ensure you checked out the RC3 code: `git log -1`
2. Verify the migration state matches: `alembic current`
3. Check for environment variables that reference removed features

## Rollback Plan

If the downgrade fails or causes issues, restore from backup:

### SQLite
```bash
cp mcp.db.backup-YYYYMMDD-HHMMSS mcp.db
```

### PostgreSQL
```bash
dropdb -U postgres mcp
createdb -U postgres mcp
psql -U postgres -d mcp < mcp-backup-YYYYMMDD-HHMMSS.sql
```

### MariaDB/MySQL
```bash
mysql -u root -p -e "DROP DATABASE mcp; CREATE DATABASE mcp;"
mysql -u root -p mcp < mcp-backup-YYYYMMDD-HHMMSS.sql
```

Then checkout the original code version and restart.

## Alternative: Fresh RC3 Installation

If downgrade is too risky or complex, consider:

1. Export critical data (users, teams, configurations)
2. Deploy a fresh RC3 instance
3. Import the exported data
4. Migrate clients to the new instance

## Post-Downgrade Considerations

### Features to Disable

Update your `.env` file to disable features not available in RC3:

```bash
# Token revocation not available in RC3
TOKEN_IDLE_TIMEOUT=0

# Disable features that depend on removed migrations
# (Check RC3 documentation for available features)
```

### Client Updates

Inform clients that the following features are no longer available:
- Token revocation API endpoints
- UAID-based agent routing
- Enhanced audit logging fields

## Support

If you encounter issues during downgrade:

1. Check the migration logs for specific errors
2. Review the Alembic migration files in `mcpgateway/alembic/versions/`
3. Consult the project documentation
4. Open an issue on GitHub with:
   - Current migration state (`alembic current`)
   - Error messages
   - Database type and version
   - Backup confirmation

## Summary

- **Target Migration**: `43c07ed25a24` (add_oauth_fields_to_servers)
- **Data Loss**: Token revocation, UAID, audit enhancements, and more
- **Backup**: MANDATORY before proceeding
- **Downgrade Command**: `alembic downgrade 43c07ed25a24`
- **Code Checkout**: `git checkout c7eab28f0` or `tags/v1.0.0-RC3`
