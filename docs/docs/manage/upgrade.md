# Upgrading ContextForge and Managing Database Migrations

This guide provides step-by-step instructions for upgrading ContextForge and handling associated database migrations to ensure a smooth transition with minimal downtime.

---

## 🔄 Upgrade Overview

ContextForge is under active development, and while we strive for backward compatibility, it's essential to review version changes carefully when upgrading. Due to rapid iterations, documentation updates may sometimes lag. If you encounter issues, consult our [GitHub repository](https://github.com/ibm/mcp-context-forge) or reach out via GitHub Issues.

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
