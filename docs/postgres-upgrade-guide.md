# PostgreSQL 17 to 18 Upgrade Guide

This document describes the process for upgrading PostgreSQL from version 17 to 18 in the MCP Context Forge Helm chart with automated backup and restore functionality.

## Overview

The upgrade process involves:

1. **Backup Phase**: Taking a backup of PostgreSQL 17 data and storing it in MinIO
2. **Upgrade Phase**: Deploying PostgreSQL 18 with data restored from the backup
3. **Verification Phase**: Checking that PostgreSQL 18 is working correctly

## Configuration

To enable the PostgreSQL upgrade process, set the following values in your `values.yaml` or `my-values.yaml`:

```yaml
postgres:
  upgrade:
    enabled: true              # Enable the upgrade process
    targetVersion: "18"        # Target version for upgrade
    backupCompleted: false     # Set to true after initial backup (prevents re-running backup)

minio:
  enabled: true                # Required for backup storage
```

## Process Flow

### 1. Pre-Upgrade Hook: Backup Job

When `postgres.upgrade.enabled` is `true` and `postgres.upgrade.targetVersion` is "18", the following happens during upgrade:

- A pre-upgrade hook job named `<release-name>-postgres-backup` is executed
- This job connects to the existing PostgreSQL 17 database
- It performs a `pg_dump` to create a SQL backup
- The backup is uploaded to MinIO at the path `postgres-backups/`
- The job runs with Helm hook annotations:
  - `helm.sh/hook: pre-upgrade`
  - `helm.sh/hook-weight: "-5"`
  - `helm.sh/hook-delete-policy: before-hook-creation,hook-succeeded`

### 2. PostgreSQL Deployment Update

- The PostgreSQL deployment is updated to use PostgreSQL 18 image
- An init container is added that downloads the backup from MinIO
- The init container places the backup in `/docker-entrypoint-initdb.d/`
- PostgreSQL 18 starts and automatically applies the SQL dump from initdb directory

### 3. Post-Upgrade Verification

- A post-upgrade hook job named `<release-name>-postgres-migration-check` verifies the upgrade
- This job connects to PostgreSQL 18 and runs a simple query to ensure functionality
- Success is logged if the database is accessible

## Files Created

The following files were added/modified to support PostgreSQL upgrade:

- `templates/job-postgres-backup.yaml` - Backup job
- `templates/job-postgres-backup.yaml` - Backup job
- `templates/job-postgres-migration-check.yaml` - Verification job
- `templates/configmap-postgres-upgrade-status.yaml` - Status tracking
- `values.yaml` - Added upgrade configuration section

## Upgrade Steps

To perform the PostgreSQL 17 to 18 upgrade:

1. **Prepare Configuration**:
   - Ensure `postgres.upgrade.enabled: true` in your values
   - Ensure `postgres.upgrade.targetVersion: "18"` in your values
   - Ensure `minio.enabled: true` in your values

2. **Run Helm Upgrade**:
   ```bash
   helm upgrade --install mcp-stack ./charts/mcp-stack \
     --namespace mcp \
     -f my-values.yaml \
     --wait --timeout 30m
   ```

3. **Monitor the Process**:
   ```bash
   kubectl get pods -n mcp
   kubectl logs -l app.kubernetes.io/component=postgres-backup -n mcp
   kubectl logs -l app.kubernetes.io/component=postgres -n mcp
   ```

4. **Verify Completion**:
   - Check that the PostgreSQL pod is running with PostgreSQL 18
   - Verify the data has been restored by connecting to the database
   - Set `postgres.upgrade.backupCompleted: true` in your values for future upgrades

## Important Notes

- **Backup Safety**: The backup job will only run if `postgres.upgrade.backupCompleted` is false
- **Data Preservation**: The existing PVC is preserved during the upgrade process
- **Rollback**: To rollback, set `postgres.upgrade.targetVersion` back to "17"
- **Testing**: Always test the upgrade process in a non-production environment first
- **Downtime**: Expect brief downtime during the upgrade process

## Troubleshooting

### Backup Job Fails
Check the logs:
```bash
kubectl logs -l app.kubernetes.io/component=postgres-backup -n mcp
```

### PostgreSQL 18 Doesn't Start
Check the PostgreSQL logs:
```bash
kubectl logs -l app=RELEASE_NAME-mcp-stack-postgres -n mcp
```

### Data Not Restored
Verify the MinIO backup exists and is accessible:
```bash
kubectl port-forward svc/RELEASE_NAME-mcp-stack-minio 9001:9001 -n mcp
```
Then access the MinIO UI at http://localhost:9001 with the MinIO credentials.

## Rollback Procedure

If the upgrade fails and you need to rollback:

1. Set `postgres.image.tag: "17"` and `postgres.upgrade.enabled: false` in your values
2. Run the Helm upgrade command again
3. The deployment will revert to PostgreSQL 17