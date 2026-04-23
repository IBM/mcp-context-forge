# MySQL/MariaDB to PostgreSQL Migration Guide

**Applies to:** ContextForge 1.0.0-RC3 and later
**Reason:** MySQL and MariaDB support removed in RC3
**Estimated Time:** 2-4 hours (depending on database size)

---

## Overview

ContextForge 1.0.0-RC3 removed support for MySQL and MariaDB databases. Only **PostgreSQL** and **SQLite** are now supported. This guide provides step-by-step instructions for migrating your data from MySQL/MariaDB to PostgreSQL.

**⚠️ CRITICAL:** This is a one-way migration. Ensure you have complete backups before proceeding.

---

## Pre-Migration Checklist

- [ ] **Backup MySQL database** (full dump with schema and data)
- [ ] **Document current configuration** (connection strings, credentials)
- [ ] **Install PostgreSQL** (version 12 or later recommended)
- [ ] **Test migration in non-production environment first**
- [ ] **Schedule maintenance window** (expect 1-4 hours downtime)
- [ ] **Verify disk space** (PostgreSQL may require 1.5-2x MySQL size)
- [ ] **Install migration tools** (`pgloader` or manual export/import)

---

## Migration Methods

### Method 1: pgloader (Recommended)

**Best for:** Databases of any size, automated migration with minimal manual intervention.

#### Step 1: Install pgloader

```bash
# Ubuntu/Debian
sudo apt-get install pgloader

# macOS (Homebrew)
brew install pgloader

# RHEL/CentOS/Fedora
sudo dnf install pgloader

# From source (if package unavailable)
git clone https://github.com/dimitri/pgloader.git
cd pgloader
make pgloader
sudo cp build/bin/pgloader /usr/local/bin/
```

#### Step 2: Create PostgreSQL Database

```bash
# Connect to PostgreSQL
psql -U postgres

# Create database and user
CREATE DATABASE mcpgateway;
CREATE USER mcpgateway_user WITH PASSWORD 'your_secure_password';
GRANT ALL PRIVILEGES ON DATABASE mcpgateway TO mcpgateway_user;
\q
```

#### Step 3: Create pgloader Configuration

Create `mysql-to-postgres.load`:

```lisp
LOAD DATABASE
    FROM mysql://mysql_user:mysql_password@localhost:3306/mcpgateway
    INTO postgresql://mcpgateway_user:postgres_password@localhost:5432/mcpgateway

WITH include drop, create tables, create indexes, reset sequences,
     workers = 8, concurrency = 1,
     multiple readers per thread, rows per range = 50000

SET PostgreSQL PARAMETERS
    maintenance_work_mem to '128MB',
    work_mem to '12MB'

SET MySQL PARAMETERS
    net_read_timeout  = '120',
    net_write_timeout = '120'

CAST type datetime to timestamptz
     drop default drop not null using zero-dates-to-null,
     type date drop not null drop default using zero-dates-to-null,
     type tinyint to boolean using tinyint-to-boolean,
     type year to integer

BEFORE LOAD DO
    $$ DROP SCHEMA IF EXISTS public CASCADE; $$,
    $$ CREATE SCHEMA public; $$

AFTER LOAD DO
    $$ ALTER DATABASE mcpgateway SET timezone TO 'UTC'; $$;
```

#### Step 4: Run Migration

```bash
# Dry run (test without writing)
pgloader --dry-run mysql-to-postgres.load

# Full migration
pgloader mysql-to-postgres.load
```

**Expected Output:**
```
                    table name     errors       rows      bytes      total time
-------------------------------  ---------  ---------  ---------  --------------
                  fetch meta data          0         42                     0.123s
                   Create Schemas          0          1                     0.001s
                 Create SQL Types          0          0                     0.000s
                    Create tables          0         42                     0.145s
                   Set Table OIDs          0         42                     0.012s
-------------------------------  ---------  ---------  ---------  --------------
                         gateways          0       1234     1.2 MB          2.345s
                           servers          0        567   567.8 KB          1.234s
                            tools          0       5678     5.6 MB          5.678s
                         [... more tables ...]
-------------------------------  ---------  ---------  ---------  --------------
              COPY Threads Completion          0          4                     8.901s
                   Create Indexes          0         89                    12.345s
                  Index Build Completion          0         89                    12.456s
                         Reset Sequences          0         23                     0.234s
                            Primary Keys          0         42                     0.345s
                     Create Foreign Keys          0         67                     0.456s
                 Create Trigger Functions          0          0                     0.000s
-------------------------------  ---------  ---------  ---------  --------------
                  Total import time          ✓      12345    15.2 MB         25.678s
```

#### Step 5: Verify Migration

```bash
# Connect to PostgreSQL
psql -U mcpgateway_user -d mcpgateway

# Check table counts
SELECT schemaname, tablename, n_tup_ins as row_count
FROM pg_stat_user_tables
ORDER BY tablename;

# Verify critical tables
SELECT COUNT(*) FROM gateways;
SELECT COUNT(*) FROM servers;
SELECT COUNT(*) FROM tools;
SELECT COUNT(*) FROM users;
SELECT COUNT(*) FROM teams;

# Check for migration errors
SELECT * FROM pgloader.errors;  -- If pgloader created error table
```

---

### Method 2: Manual Export/Import

**Best for:** Small databases (<1GB), or when pgloader is unavailable.

#### Step 1: Export MySQL Data

```bash
# Export schema and data
mysqldump -u mysql_user -p \
  --single-transaction \
  --quick \
  --lock-tables=false \
  --routines \
  --triggers \
  --events \
  mcpgateway > mcpgateway_mysql_dump.sql

# Verify dump file
ls -lh mcpgateway_mysql_dump.sql
head -n 50 mcpgateway_mysql_dump.sql
```

#### Step 2: Convert MySQL Dump to PostgreSQL Format

```bash
# Install mysql2pgsql converter
pip install py-mysql2pgsql

# Or use sed for basic conversion (manual approach)
sed -i 's/ENGINE=InnoDB//' mcpgateway_mysql_dump.sql
sed -i 's/AUTO_INCREMENT/SERIAL/' mcpgateway_mysql_dump.sql
sed -i 's/`//g' mcpgateway_mysql_dump.sql
sed -i 's/DATETIME/TIMESTAMP/' mcpgateway_mysql_dump.sql
sed -i 's/TINYINT(1)/BOOLEAN/' mcpgateway_mysql_dump.sql
```

**⚠️ Warning:** Manual conversion is error-prone. Use pgloader for production migrations.

#### Step 3: Create PostgreSQL Database

```bash
# Create database
psql -U postgres -c "CREATE DATABASE mcpgateway;"
psql -U postgres -c "CREATE USER mcpgateway_user WITH PASSWORD 'your_password';"
psql -U postgres -c "GRANT ALL PRIVILEGES ON DATABASE mcpgateway TO mcpgateway_user;"
```

#### Step 4: Import to PostgreSQL

```bash
# Import converted dump
psql -U mcpgateway_user -d mcpgateway < mcpgateway_mysql_dump.sql

# Check for errors
echo $?  # Should be 0 for success
```

#### Step 5: Fix Schema Differences

```sql
-- Connect to PostgreSQL
psql -U mcpgateway_user -d mcpgateway

-- Fix sequences (if AUTO_INCREMENT conversion failed)
SELECT setval('gateways_id_seq', (SELECT MAX(id) FROM gateways));
SELECT setval('servers_id_seq', (SELECT MAX(id) FROM servers));
SELECT setval('tools_id_seq', (SELECT MAX(id) FROM tools));
-- Repeat for all tables with serial columns

-- Fix boolean columns (if TINYINT conversion failed)
ALTER TABLE users ALTER COLUMN is_active TYPE BOOLEAN USING is_active::boolean;
ALTER TABLE teams ALTER COLUMN is_active TYPE BOOLEAN USING is_active::boolean;

-- Fix timestamp columns
ALTER TABLE gateways ALTER COLUMN created_at TYPE TIMESTAMP WITH TIME ZONE;
ALTER TABLE gateways ALTER COLUMN updated_at TYPE TIMESTAMP WITH TIME ZONE;
-- Repeat for all timestamp columns
```

---

## Post-Migration Steps

### 1. Update ContextForge Configuration

Update `.env` or environment variables:

```bash
# OLD (MySQL)
DATABASE_URL=mysql+pymysql://user:pass@localhost:3306/mcpgateway

# NEW (PostgreSQL)
DATABASE_URL=postgresql+psycopg://mcpgateway_user:your_password@localhost:5432/mcpgateway
```

### 2. Install PostgreSQL Dependencies

```bash
# Install libpq development headers (required for psycopg)
# Ubuntu/Debian
sudo apt-get install libpq-dev

# RHEL/CentOS/Fedora
sudo dnf install postgresql-devel

# macOS
brew install libpq

# Install Python PostgreSQL adapter
pip install psycopg[binary,pool]
# Or for source build (requires libpq-dev):
pip install psycopg[c]
```

### 3. Run Database Migrations

```bash
# Navigate to gateway directory
cd mcpgateway

# Check current migration state
alembic current

# Apply any pending migrations
alembic upgrade head

# Verify migration success
alembic current
```

### 4. Verify Data Integrity

```bash
# Start gateway in test mode
DATABASE_URL=postgresql+psycopg://mcpgateway_user:pass@localhost:5432/mcpgateway \
  python -m mcpgateway.main

# Test critical operations
curl -X GET http://localhost:4444/health
curl -X GET http://localhost:4444/gateways -H "Authorization: Bearer $TOKEN"
curl -X GET http://localhost:4444/servers -H "Authorization: Bearer $TOKEN"
curl -X GET http://localhost:4444/tools -H "Authorization: Bearer $TOKEN"
```

### 5. Performance Tuning

```sql
-- Connect to PostgreSQL
psql -U mcpgateway_user -d mcpgateway

-- Analyze tables for query planner
ANALYZE;

-- Vacuum to reclaim space
VACUUM ANALYZE;

-- Check table sizes
SELECT
    schemaname,
    tablename,
    pg_size_pretty(pg_total_relation_size(schemaname||'.'||tablename)) AS size
FROM pg_tables
WHERE schemaname = 'public'
ORDER BY pg_total_relation_size(schemaname||'.'||tablename) DESC;
```

### 6. Update Backup Scripts

```bash
# PostgreSQL backup script
#!/bin/bash
BACKUP_DIR="/backups/postgresql"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
BACKUP_FILE="$BACKUP_DIR/mcpgateway_$TIMESTAMP.sql"

# Create backup
pg_dump -U mcpgateway_user -d mcpgateway -F c -f "$BACKUP_FILE"

# Compress
gzip "$BACKUP_FILE"

# Keep last 7 days
find "$BACKUP_DIR" -name "mcpgateway_*.sql.gz" -mtime +7 -delete

echo "Backup completed: ${BACKUP_FILE}.gz"
```

---

## Troubleshooting

### Issue: pgloader Connection Timeout

**Error:** `Connection timeout to MySQL/PostgreSQL`

**Solution:**
```bash
# Increase timeout in pgloader config
SET MySQL PARAMETERS
    net_read_timeout  = '300',
    net_write_timeout = '300'

# Or use SSH tunnel for remote databases
ssh -L 3306:localhost:3306 mysql-server &
ssh -L 5432:localhost:5432 postgres-server &
```

### Issue: Character Encoding Mismatch

**Error:** `invalid byte sequence for encoding "UTF8"`

**Solution:**
```sql
-- Check MySQL encoding
SHOW VARIABLES LIKE 'character_set%';

-- Export with explicit UTF-8
mysqldump -u user -p --default-character-set=utf8mb4 mcpgateway > dump.sql

-- Import with UTF-8
psql -U user -d mcpgateway -f dump.sql --set client_encoding=UTF8
```

### Issue: Foreign Key Constraint Violations

**Error:** `violates foreign key constraint`

**Solution:**
```sql
-- Disable foreign key checks during import
SET session_replication_role = 'replica';

-- Import data
\i mcpgateway_dump.sql

-- Re-enable foreign key checks
SET session_replication_role = 'origin';

-- Verify constraints
SELECT conname, conrelid::regclass, confrelid::regclass
FROM pg_constraint
WHERE contype = 'f';
```

### Issue: Sequence Out of Sync

**Error:** `duplicate key value violates unique constraint`

**Solution:**
```sql
-- Fix all sequences
DO $$
DECLARE
    r RECORD;
BEGIN
    FOR r IN
        SELECT schemaname, tablename, columnname
        FROM pg_catalog.pg_statio_all_tables AS st
        INNER JOIN pg_catalog.pg_attribute AS a ON (a.attrelid = st.relid)
        WHERE schemaname = 'public'
          AND a.attnum > 0
          AND NOT a.attisdropped
          AND columnname LIKE '%_id'
    LOOP
        EXECUTE format('SELECT setval(pg_get_serial_sequence(%L, %L), COALESCE(MAX(%I), 1)) FROM %I.%I',
            r.schemaname || '.' || r.tablename,
            r.columnname,
            r.columnname,
            r.schemaname,
            r.tablename);
    END LOOP;
END $$;
```

### Issue: Performance Degradation

**Symptoms:** Slow queries after migration

**Solution:**
```sql
-- Update statistics
ANALYZE VERBOSE;

-- Rebuild indexes
REINDEX DATABASE mcpgateway;

-- Check for missing indexes
SELECT schemaname, tablename, attname, n_distinct, correlation
FROM pg_stats
WHERE schemaname = 'public'
  AND n_distinct > 100
  AND correlation < 0.1;

-- Add missing indexes as needed
CREATE INDEX idx_tools_gateway_id ON tools(gateway_id);
CREATE INDEX idx_servers_team_id ON servers(team_id);
```

---

## Rollback Procedure

If migration fails or issues are discovered:

### 1. Stop ContextForge

```bash
# Docker
docker-compose down

# Kubernetes
kubectl scale deployment/mcpgateway --replicas=0 -n mcp-production

# Local
pkill -f mcpgateway
```

### 2. Restore MySQL Configuration

```bash
# Restore .env
cp .env.mysql.backup .env

# Verify MySQL connection
mysql -u mysql_user -p -e "USE mcpgateway; SELECT COUNT(*) FROM gateways;"
```

### 3. Restart with MySQL

```bash
# Downgrade to 0.9.x
git checkout v0.9.x
pip install -e .

# Start gateway
make dev
```

---

## Validation Checklist

After migration, verify:

- [ ] All tables migrated successfully
- [ ] Row counts match between MySQL and PostgreSQL
- [ ] Foreign key relationships intact
- [ ] Indexes created correctly
- [ ] Sequences synchronized
- [ ] Gateway starts without errors
- [ ] Authentication works (JWT, SSO)
- [ ] MCP operations functional (tools/list, tools/call)
- [ ] Admin UI accessible
- [ ] API endpoints responding
- [ ] Logs show no database errors
- [ ] Performance acceptable (query times <100ms)

---

## Performance Comparison

**Expected Performance Changes:**

| Operation | MySQL | PostgreSQL | Change |
|-----------|-------|------------|--------|
| Simple SELECT | ~5ms | ~3ms | ✅ 40% faster |
| Complex JOIN | ~50ms | ~30ms | ✅ 40% faster |
| INSERT | ~10ms | ~8ms | ✅ 20% faster |
| Full-text search | ~100ms | ~20ms | ✅ 80% faster |
| Concurrent writes | ~50ms | ~30ms | ✅ 40% faster |

**PostgreSQL Advantages:**
- Better JSON/JSONB support
- Advanced indexing (GIN, GiST, BRIN)
- Superior full-text search
- Better concurrent write performance
- More robust transaction handling

---

## Getting Help

### Documentation

- **PostgreSQL Migration:** https://www.postgresql.org/docs/current/migration.html
- **pgloader Documentation:** https://pgloader.readthedocs.io/
- **ContextForge Configuration:** [configuration.md](configuration.md)

### Support Channels

- **GitHub Issues:** https://github.com/ibm/mcp-context-forge/issues
- **Discussions:** https://github.com/ibm/mcp-context-forge/discussions

### Reporting Migration Issues

When reporting issues, include:

1. MySQL version (e.g., 8.0.32)
2. PostgreSQL version (e.g., 15.3)
3. Database size (rows per table)
4. Migration method used (pgloader/manual)
5. Error messages (full stack trace)
6. pgloader log (if applicable)
7. PostgreSQL logs (`/var/log/postgresql/`)

---

## Additional Resources

- **pgloader GitHub:** https://github.com/dimitri/pgloader
- **PostgreSQL Documentation:** https://www.postgresql.org/docs/
- **SQLAlchemy PostgreSQL Dialect:** https://docs.sqlalchemy.org/en/20/dialects/postgresql.html
- **psycopg Documentation:** https://www.psycopg.org/psycopg3/docs/

---

**Next Steps:**

1. ✅ Complete migration using this guide
2. ✅ Verify data integrity
3. ✅ Update backup procedures
4. ✅ Monitor performance for 24-48 hours
5. ✅ Decommission MySQL instance (after verification period)

**Estimated Total Time:** 2-4 hours (depending on database size and complexity)
