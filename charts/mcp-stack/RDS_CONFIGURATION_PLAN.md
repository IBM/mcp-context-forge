# RDS Configuration Plan for MCP Stack Helm Chart

## Overview

This document outlines the approach to enable external RDS database configuration in the MCP Stack Helm chart, allowing users to provide a full `DATABASE_URL` connection string instead of using the in-cluster PostgreSQL deployment.

## Current Architecture Analysis

### Current PostgreSQL Setup

1. **In-cluster PostgreSQL Deployment** ([`deployment-postgres.yaml`](charts/mcp-stack/templates/deployment-postgres.yaml:18))
   - Conditionally deployed when `postgres.enabled: true`
   - Uses auto-generated service name: `<release>-mcp-stack-postgres`
   - Credentials stored in Secret: `postgres-secret` (or `postgres.existingSecret`)

2. **Database Connection in Gateway** ([`deployment-mcpgateway.yaml`](charts/mcp-stack/templates/deployment-mcpgateway.yaml:54-99))
   - Individual env vars: `POSTGRES_HOST`, `POSTGRES_PORT`, `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD`
   - `DATABASE_URL` constructed at runtime using shell variable expansion: `postgresql://$(POSTGRES_USER):$(POSTGRES_PASSWORD)@$(POSTGRES_HOST):$(POSTGRES_PORT)/$(POSTGRES_DB)`

3. **Migration Job** ([`job-migration.yaml`](charts/mcp-stack/templates/job-migration.yaml:47-66))
   - Uses same pattern as gateway deployment
   - Runs as Helm hook: `post-install,pre-upgrade`

## Proposed Solution

### Design Principles

1. **Backward Compatibility**: Existing configurations continue to work without changes
2. **Simplicity**: Single `DATABASE_URL` for external databases
3. **Security**: Sensitive connection strings stored in Kubernetes Secrets
4. **Flexibility**: Support both in-cluster and external databases

### Configuration Structure

Add new section to [`values.yaml`](charts/mcp-stack/values.yaml:619):

```yaml
postgres:
  enabled: true                    # Set to false when using external database
  
  # External database configuration (RDS, Cloud SQL, etc.)
  external:
    enabled: false                 # Set to true to use external database
    databaseUrl: ""                # Full connection string (stored in secret)
    # Example: "postgresql://user:pass@my-rds.us-east-1.rds.amazonaws.com:5432/mydb"
    
  # Existing in-cluster configuration (unchanged)
  image:
    repository: postgres
    tag: "17"
  # ... rest of existing config
```

### Implementation Changes

#### 1. Update [`deployment-mcpgateway.yaml`](charts/mcp-stack/templates/deployment-mcpgateway.yaml:52-99)

**Current Approach:**
```yaml
env:
  - name: POSTGRES_HOST
    value: {{ printf "%s-postgres" (include "mcp-stack.fullname" .) }}
  # ... other POSTGRES_* vars
  - name: DATABASE_URL
    value: >-
      postgresql://$(POSTGRES_USER):$(POSTGRES_PASSWORD)@$(POSTGRES_HOST):$(POSTGRES_PORT)/$(POSTGRES_DB)
```

**New Approach (with conditional logic):**
```yaml
env:
  {{- if .Values.postgres.external.enabled }}
  # External database: use provided DATABASE_URL directly
  - name: DATABASE_URL
    valueFrom:
      secretKeyRef:
        name: {{ include "mcp-stack.fullname" . }}-external-db-secret
        key: DATABASE_URL
  {{- else }}
  # In-cluster database: construct DATABASE_URL from components
  - name: POSTGRES_HOST
    value: {{ printf "%s-postgres" (include "mcp-stack.fullname" .) }}
  - name: POSTGRES_PORT
    value: "{{ .Values.mcpContextForge.env.postgres.port }}"
  - name: POSTGRES_DB
    value: "{{ .Values.mcpContextForge.env.postgres.db }}"
  - name: POSTGRES_USER
    valueFrom:
      secretKeyRef:
        name: {{ include "mcp-stack.postgresSecretName" . | trim }}
        key: POSTGRES_USER
  - name: POSTGRES_PASSWORD
    valueFrom:
      secretKeyRef:
        name: {{ include "mcp-stack.postgresSecretName" . | trim }}
        key: POSTGRES_PASSWORD
  - name: DATABASE_URL
    value: >-
      postgresql://$(POSTGRES_USER):$(POSTGRES_PASSWORD)@$(POSTGRES_HOST):$(POSTGRES_PORT)/$(POSTGRES_DB)
  {{- end }}
```

#### 2. Update [`job-migration.yaml`](charts/mcp-stack/templates/job-migration.yaml:45-66)

Apply the same conditional logic as the gateway deployment:

```yaml
env:
  {{- if .Values.postgres.external.enabled }}
  # External database
  - name: DATABASE_URL
    valueFrom:
      secretKeyRef:
        name: {{ include "mcp-stack.fullname" . }}-external-db-secret
        key: DATABASE_URL
  {{- else }}
  # In-cluster database (existing logic)
  - name: POSTGRES_HOST
    value: {{ printf "%s-postgres" (include "mcp-stack.fullname" .) }}
  # ... rest of existing env vars
  {{- end }}
```

#### 3. Create New Secret Template: `secret-external-db.yaml`

```yaml
{{- if .Values.postgres.external.enabled }}
apiVersion: v1
kind: Secret
metadata:
  name: {{ include "mcp-stack.fullname" . }}-external-db-secret
  labels:
    {{- include "mcp-stack.labels" . | nindent 4 }}
type: Opaque
stringData:
  DATABASE_URL: {{ .Values.postgres.external.databaseUrl | quote }}
{{- end }}
```

#### 4. Update [`deployment-postgres.yaml`](charts/mcp-stack/templates/deployment-postgres.yaml:18)

Ensure PostgreSQL deployment is skipped when using external database:

```yaml
{{- if and .Values.postgres.enabled (not .Values.postgres.external.enabled) }}
# ... existing PostgreSQL deployment
{{- end }}
```

#### 5. Update [`secret-postgres.yaml`](charts/mcp-stack/templates/secret-postgres.yaml:2)

Update condition to skip when using external database:

```yaml
{{- if and .Values.postgres.enabled (not .Values.postgres.external.enabled) (not .Values.postgres.existingSecret) }}
# ... existing secret
{{- end }}
```

## Usage Examples

### Example 1: Using AWS RDS

```yaml
# my-rds-values.yaml
postgres:
  enabled: false                   # Disable in-cluster PostgreSQL
  external:
    enabled: true
    databaseUrl: "postgresql://admin:MySecurePass123@my-app.abc123.us-east-1.rds.amazonaws.com:5432/mcpgateway"

mcpContextForge:
  replicaCount: 3
  # ... other gateway config
```

Deploy with:
```bash
helm install my-release ./charts/mcp-stack -f my-rds-values.yaml
```

### Example 2: Using Google Cloud SQL

```yaml
postgres:
  enabled: false
  external:
    enabled: true
    databaseUrl: "postgresql://postgres:password@10.1.2.3:5432/mcpdb?sslmode=require"
```

### Example 3: Keep In-Cluster PostgreSQL (No Changes)

```yaml
# Existing configuration continues to work
postgres:
  enabled: true
  credentials:
    database: postgresdb
    user: admin
    password: changeme
```

## Security Considerations

1. **Secret Management**: The `DATABASE_URL` is stored in a Kubernetes Secret, not in plain text
2. **SSL/TLS**: Users should include SSL parameters in the connection string (e.g., `?sslmode=require`)
3. **Credential Rotation**: Update the secret and restart pods to rotate credentials
4. **Network Security**: Ensure proper network policies and security groups allow pod-to-RDS communication

## Migration Path

### From In-Cluster to RDS

1. **Backup existing data** from in-cluster PostgreSQL
2. **Create RDS instance** and restore data
3. **Update values.yaml**:
   ```yaml
   postgres:
     enabled: false
     external:
       enabled: true
       databaseUrl: "postgresql://..."
   ```
4. **Upgrade Helm release**: `helm upgrade my-release ./charts/mcp-stack -f values.yaml`
5. **Verify migration job** completes successfully
6. **Test application** connectivity

### From RDS to In-Cluster (Rollback)

1. **Backup RDS data**
2. **Update values.yaml**:
   ```yaml
   postgres:
     enabled: true
     external:
       enabled: false
   ```
3. **Upgrade Helm release**
4. **Restore data** to in-cluster PostgreSQL

## Testing Checklist

- [ ] Deploy with in-cluster PostgreSQL (existing behavior)
- [ ] Deploy with external RDS using full `DATABASE_URL`
- [ ] Verify migration job runs successfully with external database
- [ ] Test gateway connectivity to external database
- [ ] Verify backward compatibility with existing configurations
- [ ] Test upgrade path from in-cluster to external
- [ ] Test rollback from external to in-cluster
- [ ] Validate secret creation and mounting
- [ ] Check that PostgreSQL deployment is skipped when `external.enabled: true`

## Files to Modify

1. [`charts/mcp-stack/values.yaml`](charts/mcp-stack/values.yaml:619) - Add `postgres.external` section
2. [`charts/mcp-stack/templates/deployment-mcpgateway.yaml`](charts/mcp-stack/templates/deployment-mcpgateway.yaml:52) - Add conditional DATABASE_URL logic
3. [`charts/mcp-stack/templates/job-migration.yaml`](charts/mcp-stack/templates/job-migration.yaml:45) - Add conditional DATABASE_URL logic
4. [`charts/mcp-stack/templates/deployment-postgres.yaml`](charts/mcp-stack/templates/deployment-postgres.yaml:18) - Update condition
5. [`charts/mcp-stack/templates/secret-postgres.yaml`](charts/mcp-stack/templates/secret-postgres.yaml:2) - Update condition
6. **NEW**: `charts/mcp-stack/templates/secret-external-db.yaml` - Create new secret template

## Alternative Approaches Considered

### Alternative 1: Override in `mcpContextForge.secret`

**Approach**: Allow users to set `DATABASE_URL` directly in [`mcpContextForge.secret`](charts/mcp-stack/values.yaml:571):
```yaml
mcpContextForge:
  secret:
    DATABASE_URL: "postgresql://user:pass@rds-host:5432/db"
```

**Pros**: 
- Simpler, no new configuration section
- Already documented in values.yaml comments

**Cons**:
- Still need to disable PostgreSQL deployment manually
- Less explicit about external database usage
- Doesn't prevent construction of unused POSTGRES_* env vars

**Decision**: Rejected in favor of explicit `postgres.external` section for clarity

### Alternative 2: Separate DATABASE_URL from POSTGRES_* vars

**Approach**: Always check for `DATABASE_URL` first, fall back to constructed URL

**Cons**:
- More complex template logic
- Harder to understand which configuration is active

**Decision**: Rejected in favor of clear conditional logic

## Conclusion

The proposed solution provides a clean, secure, and backward-compatible way to use external RDS databases with the MCP Stack Helm chart. The key changes are:

1. Add `postgres.external.enabled` and `postgres.external.databaseUrl` to values.yaml
2. Use conditional logic in deployment templates to choose between external and in-cluster database
3. Create a new secret template for external database credentials
4. Ensure PostgreSQL deployment is skipped when using external database

This approach maintains full backward compatibility while providing a straightforward path for users who want to use managed database services like AWS RDS, Google Cloud SQL, or Azure Database for PostgreSQL.