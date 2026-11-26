# Supported Databases

ContextForge supports two database backends: **SQLite** for development and **PostgreSQL** for production.

## Database Support Matrix

| Database    | Support Level | Production Ready | Connection String Example                                    | Notes                          |
|-------------|---------------|------------------|--------------------------------------------------------------|--------------------------------|
| SQLite      | ✅ Full       | ⚠️ Dev only      | `sqlite:///./mcp.db`                                        | Default, file-based            |
| PostgreSQL  | ✅ Full       | ✅ Yes           | `postgresql+psycopg://postgres:changeme@localhost:5432/mcp` | Recommended for production     |

## PostgreSQL Configuration

### Connection String Format

```bash
DATABASE_URL=postgresql+psycopg://[username]:[password]@[host]:[port]/[database]

# Examples:
DATABASE_URL=postgresql+psycopg://postgres:changeme@localhost:5432/mcp
DATABASE_URL=postgresql+psycopg://mcpuser:secret123@pg.example.com:5432/mcpgateway
```

### Version Requirements

- **PostgreSQL**: 14+ (recommended)

### Driver Requirements

The `psycopg` driver is used for PostgreSQL connections:

```bash
# Install with PostgreSQL support
pip install mcp-contextforge-gateway[postgres]
```

## Known Limitations

### General Database Limitations

1. **SQLite Connection Limits**

   - SQLite is limited to 50 connections in pool (vs 200 for other databases)
   - **Recommendation**: Use PostgreSQL for high-concurrency deployments

2. **SQLite Write Concurrency**

   - SQLite uses file-level locking, limiting concurrent writes
   - **Recommendation**: Use PostgreSQL for multi-worker or multi-instance deployments

## Performance Considerations

### PostgreSQL Optimization

```bash
# Recommended connection pool settings for PostgreSQL
DB_POOL_SIZE=200              # Maximum persistent connections
DB_MAX_OVERFLOW=20            # Additional connections beyond pool_size
DB_POOL_TIMEOUT=30            # Seconds to wait for connection
DB_POOL_RECYCLE=3600          # Seconds before recreating connection
```

### Index Optimization

PostgreSQL benefits from these additional indexes for large deployments:

```sql
-- Recommended indexes for high-performance deployments
CREATE INDEX idx_tools_team_created ON tools(team_id, created_at);
CREATE INDEX idx_resources_owner_uri ON resources(owner_email, uri);
CREATE INDEX idx_prompts_team_name ON prompts(team_id, name);
```

## Migration Between Databases

### SQLite to PostgreSQL Migration

```bash
# 1. Export SQLite data
sqlite3 mcp.db .dump > mcp_backup.sql

# 2. Update your DATABASE_URL
DATABASE_URL=postgresql+psycopg://postgres:changeme@localhost:5432/mcp

# 3. Start ContextForge with the new database URL
# The gateway will automatically handle schema creation and migrations
```

## Aggregate Audit Migration

Migration `4a7d9e2c6b18` permits NULL values in `audit_trails.resource_id`.
An aggregate audit represents multiple resources and has no individual resource ID.
Team stamping uses the existing `team_id` column and needs no new column.

Before upgrading an existing deployment:

1. Back up the database and verify that you can restore it.
2. Stop application writers and schedule a maintenance window for SQLite databases.
3. Run `alembic upgrade head` from `mcpgateway/` with the deployment's database configuration.
4. Start the upgraded application only after the migration succeeds.

On historical SQLite schemas, Alembic copies the audit table to change column nullability.
Allow temporary disk space for that copy and expect write locking during the migration.
Already-nullable audit columns need no alteration.

!!! warning "Downgrade restriction"
    Downgrade restores NOT NULL only when every audit row has a resource ID.
    If any NULL resource IDs exist, the migration refuses the downgrade before changing the schema.
    Keep the compatible schema revision and preserve those audit records.
    Do not delete aggregate audits or invent resource IDs to force a downgrade.
    Application-only rollback leaves the nullable schema in place; check the older application's compatibility separately.

## Troubleshooting

### Common PostgreSQL Issues

1. **Connection Refused**
   ```bash
   # Check PostgreSQL service status
   sudo systemctl status postgresql

   # Verify port is open
   netstat -tlnp | grep 5432
   ```

2. **Authentication Failures**
   ```bash
   # Check pg_hba.conf for allowed authentication methods
   sudo -u postgres psql -c "SHOW hba_file;"
   ```

3. **Permission Denied**
   ```bash
   # Grant privileges
   sudo -u postgres psql -c "GRANT ALL PRIVILEGES ON DATABASE mcp TO your_user;"
   ```

## Related Documentation

- [Configuration Reference](configuration.md) - Complete database configuration options
- [Docker Compose Deployment](../deployment/compose.md) - PostgreSQL container setup
- [Kubernetes Deployment](../deployment/kubernetes.md) - PostgreSQL in Kubernetes
- [Performance Tuning](tuning.md) - Database optimization guidelines
