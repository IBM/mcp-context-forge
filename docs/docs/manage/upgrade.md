# Upgrading ContextForge and Managing Database Migrations

This guide provides step-by-step instructions for upgrading ContextForge and handling associated database migrations to ensure a smooth transition with minimal downtime.

---

## 🔄 Upgrade Overview

ContextForge is under active development, and while we strive for backward compatibility, it's essential to review version changes carefully when upgrading. Due to rapid iterations, documentation updates may sometimes lag. If you encounter issues, consult our [GitHub repository](https://github.com/ibm/mcp-context-forge) or reach out via GitHub Issues.

---

## 📋 Version-Specific Upgrade Guides

**⚠️ IMPORTANT:** Before upgrading, review the version-specific migration guide for your target version:

- **[Upgrading to 1.0.0-RC3](upgrade-to-1.0.0-rc3.md)** - Comprehensive guide covering 8 breaking changes with step-by-step migration instructions

Each version-specific guide includes:
- Detailed breaking change descriptions
- Configuration update procedures
- Data migration steps
- Validation and testing instructions
- Rollback procedures
- Estimated migration time

---

## 🆕 Tool Lifecycle Management

**What Changed:**

- New `sunset_date` column added to `tools` table (timezone-aware DateTime)
- Tool lifecycle states introduced: **Active → Deprecated → Sunset**
- `sunsetDate` field now **required** when setting `deprecated=true` via API
- Automated sunset scheduler service runs every 60 minutes by default

**Migration Impact:**

- ✅ **Backwards Compatible**: Existing tools continue working unchanged
- ✅ **No Data Loss**: All existing tool data preserved
- ✅ **Non-Breaking**: Existing deprecated tools (without sunset dates) remain executable indefinitely
- ⚠️ **API Change**: New deprecation requests must include `sunsetDate` field

### Database Migration

The migration adds the `sunset_date` column with these characteristics:

```sql
ALTER TABLE tools ADD COLUMN sunset_date TIMESTAMP WITH TIME ZONE;
CREATE INDEX idx_tools_sunset_date ON tools(sunset_date);
```

**Migration Details:**

- **File**: `mcpgateway/alembic/versions/15a7b5f1e41a_add_sunset_date_to_tools.py`
- **Idempotent**: Safe to run multiple times
- **Default Value**: `NULL` for all existing tools
- **Index**: Added for efficient scheduler queries

### Upgrade Steps

```bash
# 1. Backup database (recommended)
pg_dump -h localhost -U postgres mcp > mcp_backup_$(date +%Y%m%d).sql

# 2. Stop gateway (optional, migration is safe while running)
docker-compose down

# 3. Run migration
cd mcpgateway
alembic upgrade head

# 4. Restart gateway
docker-compose up -d

# 5. Verify migration
docker-compose logs -f mcpgateway | grep "sunset_scheduler"
# Expected output: "Sunset scheduler started with interval: 60 minutes"
```

### Behavior Changes

| Scenario | Before | After |
|----------|--------|-------|
| Create deprecated tool | ✅ `deprecated=true` (no sunset date) | ❌ Requires `sunsetDate` field |
| Existing deprecated tools | ✅ Executable indefinitely | ✅ Executable indefinitely (backwards compatible) |
| Update to `deprecated=false` | ✅ Clears deprecation | ✅ Clears deprecation + `sunset_date` |
| Tool past sunset date | N/A | ⚠️ Automatically disabled by scheduler |

### Configuration

New environment variable:

```bash
# .env or environment
SUNSET_SCHEDULER_INTERVAL_MINUTES=60  # Default: 60 minutes
```

**Recommendation:** Keep the default 60-minute interval for production. Sunset dates are typically set days/weeks in advance, so shorter intervals provide minimal benefit while increasing database load.

### Existing Deployments

**Option 1: No Action Required** (Default)

- Existing deprecated tools keep working without sunset dates
- Tools show `lifecycleState="deprecated"` in API responses
- No forced migration timeline

**Option 2: Add Sunset Dates to Existing Deprecated Tools**

```bash
# List existing deprecated tools
curl -H "Authorization: Bearer $TOKEN" \
  http://localhost:4444/tools | \
  jq '.tools[] | select(.deprecated == true and .sunsetDate == null)'

# Add sunset dates (example: 90 days from now)
SUNSET_DATE=$(date -u -d "+90 days" +"%Y-%m-%dT%H:%M:%SZ")
curl -X PUT -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d "{\"deprecated\": true, \"sunsetDate\": \"$SUNSET_DATE\"}" \
  http://localhost:4444/tools/{tool_id}
```

### Rollback Procedure

If issues arise, roll back the migration:

```bash
# 1. Stop gateway
docker-compose down

# 2. Rollback migration
cd mcpgateway
alembic downgrade -1

# 3. Restore from backup (if needed)
psql -h localhost -U postgres mcp < mcp_backup_YYYYMMDD.sql

# 4. Restart gateway
docker-compose up -d
```

### Validation

```bash
# 1. Verify sunset_date column exists
psql -h localhost -U postgres mcp -c "\d tools" | grep sunset_date

# 2. Check scheduler is running
docker-compose logs mcpgateway | grep "Sunset scheduler"

# 3. Test API lifecycle fields
curl -H "Authorization: Bearer $TOKEN" \
  http://localhost:4444/tools/{tool_id} | \
  jq '{lifecycleState, daysUntilSunset, isExecutable}'
```

### Documentation

- [Tool Lifecycle Management](./tool-lifecycle.md) - Complete feature guide
- [API Usage - Lifecycle Fields](./api-usage.md#tool-lifecycle-management) - API examples
- [Configuration - Scheduler Settings](./configuration.md#tools) - Environment variables

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

### 3. Update ContextForge

Depending on your deployment method: podman, docker, kubernetes, etc.

!!! note "Helm chart specific notes"
    - Chart `charts/mcp-stack` now defaults `minio.enabled=false`
    - PostgreSQL major upgrade workflow requires `minio.enabled=true` with `postgres.upgrade.enabled=true`
    - Internal PostgreSQL now forces `Deployment.strategy.type=Recreate` to prevent overlapping old/new DB pods on the same PVC during upgrades
    - Internal PostgreSQL now defaults `postgres.terminationGracePeriodSeconds=120` and `postgres.lifecycle.preStop.enabled=true` for cleaner shutdown
    - Internal PostgreSQL now defaults `postgres.persistence.useReadWriteOncePod=true` (set it to `false` and use `ReadWriteOnce` if your storage class does not support RWOP)
    - Releases originally installed from chart/app `1.0.0-BETA-2` may require one-time MinIO Deployment recreation before upgrade:
      `kubectl delete deployment -n <namespace> <release>-minio`

### 4. Apply Database Migrations

If the new version includes database schema changes:

* **Migration Scripts**: Execute any provided migration scripts.
* **Manual Migrations**: If no scripts are provided, consult the release notes for manual migration instructions.

### 5. Verify the Upgrade

Post-upgrade, ensure:

* **Service Availability**: ContextForge is running and accessible.
* **Functionality**: All features and integrations are working as expected.
* **Logs**: Check logs for any errors or warnings.

---

## 🧪 Testing and Validation

* **Staging Environment**: Test the upgrade process in a staging environment before applying to production.
* **Automated Tests**: Run your test suite to catch any regressions.
* **User Acceptance Testing (UAT)**: Engage end-users to validate critical workflows.

---

## 📚 Additional Resources

* [ContextForge GitHub Repository](https://github.com/ibm/mcp-context-forge)
* [ContextForge Documentation](../index.md)

---
