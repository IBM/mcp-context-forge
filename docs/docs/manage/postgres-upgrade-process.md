# PostgreSQL 17 to 18 Upgrade Guide

This guide explains how to upgrade PostgreSQL from version 17 to 18 in ContextForge Helm chart with automated backup and restore to MinIO.

## Prerequisites

Before proceeding with the upgrade, ensure:

- You have a running installation with PostgreSQL 17
- You have `kubectl` and `helm` access to your cluster
- You have sufficient disk space for backup operations
- You can accept brief downtime during the upgrade process

## Upgrade Safety Rules (Required)

Before any PostgreSQL image/tag upgrade in Kubernetes:

1. Take a backup you can restore from.
2. Ensure Postgres does not run overlapping old/new pods on the same PVC.
3. Ensure graceful shutdown to flush checkpoints/WAL before pod termination.
4. Prefer strict single-pod mounts (`ReadWriteOncePod`) when supported by your storage class.

Example pre-upgrade backup command:

```bash
kubectl exec -n mcp deploy/mcp-stack-postgres -- \
  pg_dump -U admin -d postgresdb > pg-backup-$(date +%Y%m%d-%H%M%S).sql
```

The chart now applies these safety defaults for internal Postgres:

- `Deployment` strategy is always `Recreate` (non-overlapping updates)
- `terminationGracePeriodSeconds=120`
- `lifecycle.preStop` hook runs `pg_ctl ... stop`
- `postgres.persistence.useReadWriteOncePod=true` by default

If your storage class does not support `ReadWriteOncePod`, set:

```yaml
postgres:
  persistence:
    useReadWriteOncePod: false
    accessModes: [ReadWriteOnce]
```

## Upgrade Process

The upgrade process occurs in stages and requires two separate Helm operations:

### Stage 1: Enable MinIO for Backup Storage

`minio.enabled` is `false` by default. Enable MinIO first so backup/restore can run:

```bash
# Update your my-values.yaml to enable MinIO
helm upgrade --install mcp-stack ./charts/mcp-stack \
  --namespace mcp \
  --create-namespace \
  -f my-values.yaml \
  --wait --timeout 30m
```

Or directly set MinIO to enabled:

```bash
helm upgrade --install mcp-stack ./charts/mcp-stack \
  --namespace mcp \
  --create-namespace \
  -f my-values.yaml \
  --set minio.enabled=true \
  --wait --timeout 30m
```

!!! note
    The chart fails at render time if `postgres.upgrade.enabled=true` while `minio.enabled=false`.

### Stage 2: Perform the PostgreSQL Upgrade with Backup

Once MinIO is running, proceed with the actual PostgreSQL upgrade:

1. **Update your values file** to configure the upgrade:

```yaml
# In your my-values.yaml
postgres:
  upgrade:
    enabled: true              # Enable the PostgreSQL upgrade process
    targetVersion: "18"        # Target PostgreSQL version (18)
    backupCompleted: false     # Set to false to initiate backup process
```

2. **Run the upgrade command**:

```bash
helm upgrade --install mcp-stack ./charts/mcp-stack \
  --namespace mcp \
  -f my-values.yaml \
  --wait --timeout 30m
```

This will:

- Run a pre-upgrade hook to backup PostgreSQL 17 data to MinIO
- Upgrade the PostgreSQL deployment to version 18
- Restore data from the backup during PostgreSQL 18 initialization

### Stage 3: Verify the Upgrade

After the upgrade completes, verify that everything is working:

```bash
# Check that all pods are running
kubectl get pods -n mcp

# Check PostgreSQL logs
kubectl logs -n mcp deployment/mcp-stack-postgres

# Verify the PostgreSQL version
kubectl exec -n mcp deployment/mcp-stack-postgres -- psql -U admin -c "SELECT version();"
```

## Rollback Process

If something goes wrong and you need to rollback:

1. Set `postgres.upgrade.enabled: false` and `postgres.upgrade.targetVersion: "17"` in your values file
2. Run `helm upgrade` with the changes
3. The deployment will revert to PostgreSQL 17

## Troubleshooting

### Backup Job Fails
If the backup job fails, check the logs:
```bash
kubectl logs -n mcp -l app.kubernetes.io/component=postgres-backup
```

### PostgreSQL Pod Stuck in CrashLoopBackOff
This usually indicates the data directory compatibility issue. Make sure:

- MinIO is accessible and running
- The backup file exists in MinIO
- The PVC has compatible ownership/perms

### MinIO Not Starting
Ensure your storage class settings match existing PVCs:
```bash
kubectl describe pvc -n mcp
```

### Legacy `1.0.0-BETA-2` Upgrade Fails on MinIO Selector
If your release was originally installed from chart/app `1.0.0-BETA-2`, you may see:
```text
Deployment.apps "<release>-minio" is invalid: spec.selector ... field is immutable
```

One-time workaround:
```bash
kubectl delete deployment -n mcp-private mcp-stack-minio
helm upgrade mcp-stack ./charts/mcp-stack -n mcp-private -f my-values.yaml --wait --timeout 30m
```

## Configuration Reference

### Upgrade Parameters

| Parameter | Description | Default |
|-----------|-------------|---------|
| `postgres.upgrade.enabled` | Enable the PostgreSQL upgrade process | `false` |
| `postgres.upgrade.targetVersion` | Target PostgreSQL version (currently supports "18") | `"18"` |
| `postgres.upgrade.backupCompleted` | Internal flag - set to false to trigger backup | `false` |
| `minio.enabled` | Enable MinIO for backup storage | `false` (set `true` for upgrades) |
| `postgres.terminationGracePeriodSeconds` | Grace period before force-kill on pod shutdown | `120` |
| `postgres.lifecycle.preStop.enabled` | Run clean shutdown hook before container termination | `true` |
| `postgres.persistence.useReadWriteOncePod` | Prefer strict single-pod mount mode | `true` |

### Storage Configuration

When upgrading with existing PVCs, make sure to maintain the same storage class:

```yaml
postgres:
  persistence:
    storageClassName: "same-as-existing-pvc"  # Match existing PVC
    size: "same-as-existing-pvc"              # Match existing PVC
```

## Important Notes

- **Backup Required**: The upgrade process automatically creates a backup before upgrading
- **Data Safety**: Data is preserved during the upgrade process via the backup/restore mechanism
- **Downtime**: Expect brief downtime during the upgrade as PostgreSQL restarts
- **PVC Compatibility**: The PVC will be reused but the data will be migrated through the backup/restore process
- **MinIO Required**: MinIO must be enabled and operational for the upgrade to work
- **Validation Guard**: Chart rendering fails fast if upgrade mode is enabled without MinIO
- **Single Writer Safety**: Chart forces Postgres `Recreate` strategy to avoid overlapping pod mounts on one PVC
- **Graceful Stop**: Chart sets preStop + termination grace period to reduce checkpoint/WAL corruption risk

## Cleanup After Successful Upgrade

Once you've verified the upgrade was successful:

1. Optionally set `postgres.upgrade.backupCompleted: true` to prevent the backup job from running in future upgrades
2. Clean up old backup files from MinIO if needed
3. Update your documentation to reflect the new PostgreSQL version
