# ADR-0027: Migrate from Psycopg2 to Psycopg3

- *Status:* Accepted
- *Date:* 2025-01-15
- *Deciders:* Mihai Criveti

## Context

The MCP Gateway uses PostgreSQL as one of its supported production database backends. Historically, the project used `psycopg2` (via `psycopg2-binary`) as the PostgreSQL adapter. Psycopg2 has been the standard PostgreSQL adapter for Python for over 15 years.

Psycopg3 (the `psycopg` package) is a complete rewrite of the PostgreSQL adapter, offering significant improvements in architecture, performance, and features. SQLAlchemy 2.x provides native support for psycopg3 via the `postgresql+psycopg://` dialect.

Key benefits of psycopg3:

1. **Parameter binding**: Psycopg3 uses server-side parameter binding by default (parameters sent separately from query), improving security
2. **Prepared statements**: Native support for prepared statements, improving performance for repeated queries
3. **Binary protocol**: Support for binary data transfer, reducing parsing overhead
4. **Async support**: First-class async support built into the core library
5. **Connection pooling**: Native connection pool implementation (`psycopg_pool`)
6. **Active maintenance**: Psycopg3 is actively developed; psycopg2 is in maintenance mode

## Decision

We will use `psycopg[binary]` (psycopg3) as the only supported PostgreSQL adapter. Psycopg2 is no longer supported.

### Changes Made

1. **Dependencies** (`pyproject.toml`):
   - Use `psycopg[c,binary]>=3.2.0` for the `postgres` extra (C extension + pre-compiled libpq)

2. **Driver Detection** (`mcpgateway/db.py`):
   - Only psycopg3 driver is supported: `driver in ("psycopg", "default", "")`
   - Keep-alive parameters work via libpq

3. **Connection URLs**:
   - `postgresql+psycopg://` - Required for psycopg3
   - `postgresql://` - Does NOT work (defaults to psycopg2 in SQLAlchemy)

### Migration Path for Users

1. **URL format**: Must use `postgresql+psycopg://` (not `postgresql://`)
2. **Install**: Use `pip install 'psycopg[c,binary]'` or install the gateway with `[postgres]` extra
3. **Breaking change**: All PostgreSQL URLs must be updated to use `postgresql+psycopg://`

## Performance Optimizations

The migration to psycopg3 enabled several performance optimizations:

### 1. COPY Protocol Utility (for Large Bulk Imports)

A utility module provides psycopg3's COPY protocol for very large bulk inserts (1000+ rows).

**Location**: `mcpgateway/utils/psycopg3_optimizations.py`

**Important**: COPY is only faster for large batches. Testing showed:
- 1000+ rows: COPY is 5-10x faster than INSERT
- 10-100 rows: COPY is actually 2x **slower** due to protocol overhead
- For small batches, use SQLAlchemy's `bulk_insert_mappings()` instead

**Use cases**:
- Bulk data imports (tools, resources, prompts)
- Initial data seeding
- NOT recommended for metrics buffering (small frequent batches)

### 2. Automatic Prepared Statements

Psycopg3 automatically prepares frequently-executed queries server-side after a configurable threshold.

**Configuration**: `DB_PREPARE_THRESHOLD` (default: 5)

After N executions of the same query template, psycopg3 creates a server-side prepared statement, reducing:
- Query parsing overhead
- Network round-trips for query plans
- PostgreSQL CPU usage for repeated queries

Set to 0 to disable, 1 to prepare immediately, or higher values to reduce memory usage.

### 3. Optimized Utility Module

New utility module provides psycopg3-specific optimizations with automatic fallbacks:

**Location**: `mcpgateway/utils/psycopg3_optimizations.py`

Features:
- `bulk_insert_with_copy()` - COPY protocol for bulk inserts
- `bulk_insert_metrics()` - Optimized metrics insertion
- `execute_pipelined()` - Pipeline mode for batch queries
- `is_psycopg3_backend()` - Runtime backend detection

## Consequences

### Positive

- **Better security**: Server-side parameter binding prevents SQL injection at the protocol level
- **Improved performance**: Prepared statements and binary protocol reduce overhead
- **COPY protocol**: 5-10x faster bulk inserts for large import operations (1000+ rows)
- **Future-ready**: Native async support enables future async migration if needed
- **Active maintenance**: Psycopg3 receives regular updates and security fixes
- **Better connection pooling**: Option to use psycopg_pool for advanced scenarios
- **Simpler codebase**: Only one driver to support and test

### Negative

- **Breaking change**: Users with psycopg2 must migrate
- **Server-side binding limitations**: Some DDL statements don't support parameters (mitigated by using `psycopg.sql` module)

### Neutral

- **Keep-alive parameters**: Work the same way via libpq
- **SQLAlchemy abstraction**: Most application code unchanged

## Compatibility Notes

### SQL Patterns That Work Unchanged

- Standard SELECT/INSERT/UPDATE/DELETE with named parameters (`:name` style)
- Simple queries without parameters
- SQLAlchemy ORM operations
- Alembic migrations (all use compatible patterns)

### Patterns Requiring Attention

These patterns are not used in the MCP Gateway codebase but should be noted:

1. **Tuple IN clause**: `IN %s` with tuple doesn't work; use `= ANY(%s)` with list
2. **IS NULL with parameter**: `IS %s` doesn't work; use `IS NOT DISTINCT FROM %s`
3. **Multiple statements**: Can't execute multiple statements with parameters in one call

## Alternatives Considered

| Option | Why Not |
|--------|---------|
| **Keep psycopg2 support** | Maintenance burden, psycopg2 in maintenance mode |
| **asyncpg** | Not DBAPI-compatible, would require major rewrite of database layer |
| **pg8000** | Less mature, fewer features, smaller community |

## References

- [Psycopg3 Documentation](https://www.psycopg.org/psycopg3/docs/)
- [Differences from psycopg2](https://www.psycopg.org/psycopg3/docs/basic/from_pg2.html)
- [SQLAlchemy psycopg Dialect](https://docs.sqlalchemy.org/en/20/dialects/postgresql.html#module-sqlalchemy.dialects.postgresql.psycopg)
- [Server-side Binding](https://www.psycopg.org/psycopg3/docs/basic/params.html)

## Status

This decision is implemented. The MCP Gateway uses psycopg3 as the only supported PostgreSQL adapter.
