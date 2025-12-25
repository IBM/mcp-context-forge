# PostgreSQL Schema Configuration Support

## Overview

MCP Gateway now supports custom PostgreSQL schema configuration via the `search_path` parameter. This feature addresses [Issue #1535](https://github.com/IBM/mcp-context-forge/issues/1535) and enables deployment in enterprise PostgreSQL environments where access to the `public` schema is restricted.

## Problem Statement

Enterprise PostgreSQL environments often restrict access to the `public` schema for security reasons. Previously, MCP Gateway could only use the default `public` schema, preventing deployment in such environments without database-level workarounds.

## Solution

Users can now specify a custom PostgreSQL schema by including the `options` query parameter in the `DATABASE_URL` environment variable. The schema must exist before deploying MCP Gateway.

## Configuration

### Basic Usage

Set the `DATABASE_URL` environment variable with the `options` parameter:

```bash
# Single custom schema
export DATABASE_URL="postgresql+psycopg://user:password@host:5432/dbname?options=-c%20search_path=mcp_gateway"

# Multiple schemas in search path (searches mcp_gateway first, then public)
export DATABASE_URL="postgresql+psycopg://user:password@host:5432/dbname?options=-c%20search_path=mcp_gateway,public"
```

### URL Encoding

The `options` parameter must be URL-encoded:
- Space (` `) → `%20`
- Comma (`,`) → `%2C` (optional, usually works without encoding)

### Docker/Docker Compose

```yaml
version: '3.8'
services:
  mcpgateway:
    image: mcpgateway:latest
    environment:
      - DATABASE_URL=postgresql+psycopg://user:password@postgres:5432/mcp?options=-c%20search_path=mcp_gateway
    depends_on:
      - postgres

  postgres:
    image: postgres:15
    environment:
      - POSTGRES_DB=mcp
      - POSTGRES_USER=user
      - POSTGRES_PASSWORD=password
    volumes:
      - ./init-schema.sql:/docker-entrypoint-initdb.d/init-schema.sql
```

### Kubernetes

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: mcpgateway-config
data:
  DATABASE_URL: "postgresql+psycopg://$(DB_USER):$(DB_PASS)@postgres:5432/mcp?options=-c%20search_path=mcp_gateway"
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: mcpgateway
spec:
  template:
    spec:
      containers:
      - name: mcpgateway
        image: mcpgateway:latest
        env:
        - name: DATABASE_URL
          valueFrom:
            configMapKeyRef:
              name: mcpgateway-config
              key: DATABASE_URL
```

## Prerequisites

### 1. Create the Schema

The custom schema must exist before deploying MCP Gateway. Connect to your PostgreSQL database and run:

```sql
-- Create the schema
CREATE SCHEMA IF NOT EXISTS mcp_gateway;

-- Grant necessary permissions to your application user
GRANT ALL PRIVILEGES ON SCHEMA mcp_gateway TO your_app_user;
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA mcp_gateway TO your_app_user;
GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA mcp_gateway TO your_app_user;

-- Set default privileges for future objects
ALTER DEFAULT PRIVILEGES IN SCHEMA mcp_gateway
  GRANT ALL PRIVILEGES ON TABLES TO your_app_user;
ALTER DEFAULT PRIVILEGES IN SCHEMA mcp_gateway
  GRANT ALL PRIVILEGES ON SEQUENCES TO your_app_user;
```

### 2. Verify Schema Access

Test that your user can access the schema:

```sql
-- Connect as your application user
SET search_path TO mcp_gateway;

-- Verify you can create tables
CREATE TABLE test_table (id SERIAL PRIMARY KEY);
DROP TABLE test_table;
```

## Migration from Public Schema

If you're migrating an existing deployment from the `public` schema to a custom schema:

### Option 1: Fresh Installation

1. Create the new schema
2. Update `DATABASE_URL` with the new schema
3. Deploy MCP Gateway (it will create tables in the new schema)
4. Migrate data from old schema if needed

### Option 2: Schema Migration

```sql
-- 1. Create new schema
CREATE SCHEMA mcp_gateway;

-- 2. Move all tables to new schema
DO $$
DECLARE
    row record;
BEGIN
    FOR row IN
        SELECT tablename
        FROM pg_tables
        WHERE schemaname = 'public'
        AND tablename LIKE 'mcp_%'
    LOOP
        EXECUTE 'ALTER TABLE public.' || quote_ident(row.tablename) ||
                ' SET SCHEMA mcp_gateway';
    END LOOP;
END $$;

-- 3. Update DATABASE_URL and restart MCP Gateway
```

## Troubleshooting

### Tables Created in Wrong Schema

**Symptom**: Tables are still being created in `public` schema

**Solution**:
1. Verify the `DATABASE_URL` includes the `options` parameter
2. Check URL encoding is correct (space = `%20`)
3. Restart the application to pick up the new configuration

### Permission Denied Errors

**Symptom**: `ERROR: permission denied for schema mcp_gateway`

**Solution**:
```sql
-- Grant schema usage
GRANT USAGE ON SCHEMA mcp_gateway TO your_app_user;
GRANT CREATE ON SCHEMA mcp_gateway TO your_app_user;

-- Grant permissions on existing objects
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA mcp_gateway TO your_app_user;
GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA mcp_gateway TO your_app_user;
```

### Schema Does Not Exist

**Symptom**: `ERROR: schema "mcp_gateway" does not exist`

**Solution**: Create the schema before deploying:
```sql
CREATE SCHEMA mcp_gateway;
```

### Connection Fails with Options Parameter

**Symptom**: Connection fails when `options` parameter is added

**Solution**:
1. Verify PostgreSQL version supports the `options` parameter (PostgreSQL 9.0+)
2. Check that the psycopg3 driver is being used (not asyncpg)
3. Verify URL encoding is correct

## Technical Details

### How It Works

1. The `DATABASE_URL` is parsed by SQLAlchemy's `make_url()` function
2. The `options` query parameter is extracted from the URL
3. The options are passed to psycopg via the `connect_args` dictionary
4. PostgreSQL applies the `search_path` setting for all connections
5. All table operations use the specified schema

### Supported Databases

- ✅ **PostgreSQL**: Full support via `options` parameter
- ⚠️ **SQLite**: Ignores `options` parameter (no effect)
- ⚠️ **MySQL/MariaDB**: Ignores `options` parameter (use database name instead)

### Alembic Migrations

Alembic migrations automatically respect the `search_path` setting:
- Tables are created in the first schema in `search_path`
- Migrations work seamlessly with custom schemas
- No special configuration needed

## Examples

### Development Environment

```bash
# .env file
DATABASE_URL=postgresql+psycopg://dev:devpass@localhost:5432/mcp_dev?options=-c%20search_path=mcp_gateway
```

### Production Environment

```bash
# Secure production setup with restricted public schema
DATABASE_URL=postgresql+psycopg://mcp_app:${DB_PASSWORD}@db.prod.example.com:5432/mcp_prod?options=-c%20search_path=mcp_gateway&sslmode=require
```

### Multi-Schema Setup

```bash
# Search mcp_gateway first, fall back to shared schema
DATABASE_URL=postgresql+psycopg://user:pass@host:5432/db?options=-c%20search_path=mcp_gateway,shared,public
```

## Security Considerations

1. **Schema Isolation**: Using a custom schema provides logical separation from other applications
2. **Permission Control**: Restrict access to the schema at the database level
3. **Audit Trail**: Schema-level permissions make it easier to audit access
4. **No Public Access**: Eliminates dependency on the `public` schema

## References

- [PostgreSQL search_path Documentation](https://www.postgresql.org/docs/current/ddl-schemas.html#DDL-SCHEMAS-PATH)
- [Psycopg3 Connection Options](https://www.psycopg.org/psycopg3/docs/api/connections.html)
- [GitHub Issue #1535](https://github.com/IBM/mcp-context-forge/issues/1535)

## Support

For issues or questions:
1. Check the troubleshooting section above
2. Review the [GitHub issue](https://github.com/IBM/mcp-context-forge/issues/1535)
3. Open a new issue with details about your setup
