# Database Indexing Optimization

## Overview

This document describes the database indexing optimization initiative (Issue #1353) to improve query performance across the MCP Gateway database schema.

## Background

Foreign key columns without indexes can cause significant performance issues:

1. **JOIN Operations**: Queries joining tables need to scan entire tables without indexes
2. **Foreign Key Constraints**: INSERT/UPDATE/DELETE operations with foreign key checks are slower
3. **Cascading Operations**: CASCADE DELETE/UPDATE operations require full table scans
4. **Query Planning**: Database optimizer cannot efficiently plan queries without index statistics

## Implementation Phases

### Phase 0: Index Naming Standardization (Completed)

**Migration**: `n8h9i0j1k2l3_add_database_indexes.py` (Phase 0)

This phase standardizes index naming conventions by renaming all existing `ix_` prefixed indexes to `idx_` for consistency across the codebase.

**Actions:**
- Renames indexes from `ix_*` to `idx_*` format
- Handles database-specific rename operations (PostgreSQL, MySQL, SQLite)
- Skips renames where target name already exists

### Phase 0.5: Duplicate Index Cleanup (Completed)

**Migration**: `n8h9i0j1k2l3_add_database_indexes.py` (Phase 0.5)

This phase detects and removes duplicate indexes where the same columns have multiple indexes with different naming conventions.

**Detection Logic:**
1. Groups indexes by their column sets
2. Identifies cases where both `ix_*` and `idx_*` (or other) indexes exist on the same columns
3. Drops the `ix_*` prefixed duplicates, keeping the `idx_*` versions

**Example:**
```
Table: email_api_tokens
Columns: user_email
Before: idx_email_api_tokens_user_email, ix_email_api_tokens_user_email
After: idx_email_api_tokens_user_email (duplicate dropped)
```

**Benefits:**
- Reduces storage overhead from redundant indexes
- Improves write performance (fewer indexes to update)
- Maintains consistency with new naming standard


### Phase 1: Foreign Key Indexes (Completed)

**Migration**: `n8h9i0j1k2l3_add_database_indexes.py` (Phase 1)

This phase adds indexes on all foreign key columns that don't already have them. The migration creates 47 new indexes across the following categories:

#### Role and RBAC Indexes
- `idx_roles_inherits_from` - Role inheritance lookups
- `idx_roles_created_by` - Role creator tracking
- `idx_user_roles_user_email` - User role assignments
- `idx_user_roles_role_id` - Role membership queries
- `idx_user_roles_granted_by` - Role grant auditing

#### Team Management Indexes
- `idx_email_teams_created_by` - Team creator lookups
- `idx_email_team_members_team_id` - Team membership queries
- `idx_email_team_members_user_email` - User team memberships
- `idx_email_team_members_invited_by` - Invitation tracking
- `idx_email_team_member_history_*` - Team history queries (4 indexes)
- `idx_email_team_invitations_*` - Invitation management (2 indexes)
- `idx_email_team_join_requests_*` - Join request processing (3 indexes)

#### Metrics Indexes
- `idx_tool_metrics_tool_id` - Tool usage metrics
- `idx_resource_metrics_resource_id` - Resource access metrics
- `idx_server_metrics_server_id` - Server performance metrics
- `idx_prompt_metrics_prompt_id` - Prompt usage metrics
- `idx_a2a_agent_metrics_a2a_agent_id` - A2A agent metrics

#### Core Entity Indexes
- `idx_tools_gateway_id` - Tool federation lookups
- `idx_tools_team_id` - Team-scoped tool queries
- `idx_resources_gateway_id` - Resource federation lookups
- `idx_resources_team_id` - Team-scoped resource queries
- `idx_prompts_gateway_id` - Prompt federation lookups
- `idx_prompts_team_id` - Team-scoped prompt queries
- `idx_servers_team_id` - Team-scoped server queries
- `idx_gateways_team_id` - Team-scoped gateway queries
- `idx_a2a_agents_team_id` - Team-scoped A2A agent queries
- `idx_grpc_services_team_id` - Team-scoped gRPC service queries

#### OAuth and Authentication Indexes
- `idx_oauth_tokens_gateway_id` - OAuth token lookups by gateway
- `idx_oauth_tokens_app_user_email` - OAuth token lookups by user
- `idx_oauth_states_gateway_id` - OAuth state validation
- `idx_sso_auth_sessions_provider_id` - SSO session lookups
- `idx_sso_auth_sessions_user_email` - User SSO sessions

#### Other Indexes
- `idx_resource_subscriptions_resource_id` - Resource subscription queries
- `idx_session_message_records_session_id` - Session message history
- `idx_email_api_tokens_server_id` - Server-scoped API tokens
- `idx_token_revocations_revoked_by` - Token revocation auditing
- `idx_pending_user_approvals_approved_by` - User approval tracking
- `idx_llm_models_provider_id` - LLM model provider lookups

### Indexes Already Present

The following foreign keys already had indexes (marked with `index=True` in models):
- `observability_spans.trace_id`
- `observability_spans.parent_span_id`
- `observability_events.span_id`
- `observability_metrics.trace_id`
- `security_events.log_entry_id`
- `email_api_tokens.user_email`
- `email_api_tokens.team_id`
- `registered_oauth_clients.gateway_id`

### Phase 2: Composite Indexes (Completed)

**Migration**: `n8h9i0j1k2l3_add_database_indexes.py` (Phase 2)

This phase adds **37 composite indexes** for common query patterns identified in the service layer. Composite indexes significantly improve performance when queries filter on multiple columns or filter on one column and sort by another.

#### Team Management Composite Indexes (8 indexes)
- `idx_email_team_members_user_team_active` - User + team + active status lookups
- `idx_email_team_members_team_role_active` - Team role queries
- `idx_email_team_invitations_team_active_created` - Team invitation listing
- `idx_email_team_invitations_email_active_created` - User invitation queries
- `idx_email_team_join_requests_team_status_time` - Team join request management
- `idx_email_team_join_requests_user_status_time` - User join request tracking
- `idx_email_teams_visibility_active_created` - Public team discovery
- `idx_email_teams_creator_personal_active` - Personal team lookups

#### Core Entity Composite Indexes (12 indexes)
For each entity type (Tools, Resources, Prompts, Servers, Gateways, A2A Agents):
- `idx_{entity}_team_visibility_active_created` - Team-scoped entity listing
- `idx_{entity}_visibility_active_created` - Public entity discovery

These indexes optimize the most common query pattern: filtering by visibility and active status, then ordering by creation time.

#### Observability Composite Indexes (4 indexes)
- `idx_observability_traces_user_status_time` - User activity analysis
- `idx_observability_traces_status_method_time` - Error analysis by HTTP method
- `idx_observability_spans_trace_resource_time` - Trace span analysis
- `idx_observability_spans_resource_status_time` - Resource monitoring

#### Authentication & Token Composite Indexes (5 indexes)
- `idx_email_api_tokens_user_active_created` - User token listing
- `idx_email_api_tokens_team_active_created` - Team token management
- `idx_email_auth_events_user_type_time` - User activity audit
- `idx_sso_auth_sessions_provider_user_created` - SSO session lookup
- `idx_oauth_tokens_gateway_user_created` - OAuth token management

#### Metrics Composite Indexes (4 indexes)
- `idx_tool_metrics_tool_timestamp` - Tool usage time-series
- `idx_resource_metrics_resource_timestamp` - Resource access time-series
- `idx_server_metrics_server_timestamp` - Server performance time-series
- `idx_prompt_metrics_prompt_timestamp` - Prompt usage time-series

#### RBAC Composite Indexes (2 indexes)
- `idx_user_roles_user_scope_active` - User permission checks
- `idx_user_roles_role_scope_active` - Role membership queries

## Performance Impact

### Phase 1: Foreign Key Indexes

**Expected Improvements:**
1. **JOIN Performance**: 10-100x faster for queries joining on foreign keys
2. **Constraint Checks**: 5-50x faster for INSERT/UPDATE/DELETE operations
3. **Cascade Operations**: Significant improvement for bulk deletes with cascades
4. **Query Planning**: Better execution plans with index statistics

**Storage Impact:**
- Each index adds approximately 10-30% of the table size
- Phase 1 storage increase: ~10-15% of current database size

### Phase 2: Composite Indexes

**Expected Improvements:**
1. **Multi-Column Filtering**: 5-50x faster for queries with multiple WHERE conditions
2. **Filtered Sorting**: 10-100x faster for queries that filter and sort
3. **Team-Scoped Queries**: Dramatic improvement for multi-tenant queries
4. **Time-Series Queries**: Significant speedup for metrics and observability queries
5. **Index-Only Scans**: Some queries can be satisfied entirely from the index

**Storage Impact:**
- Composite indexes are larger than single-column indexes
- Phase 2 storage increase: ~15-20% of current database size
- **Total storage increase (both phases): 25-35% of original database size**

**Query Pattern Examples:**

```sql
-- Before: Full table scan + sort
-- After: Index scan on ix_tools_team_visibility_active_created
SELECT * FROM tools 
WHERE team_id = 'abc123' 
  AND visibility = 'team' 
  AND is_active = true 
ORDER BY created_at DESC;

-- Before: Multiple index scans + merge
-- After: Single index scan on ix_email_team_members_user_team_active
SELECT * FROM email_team_members 
WHERE user_email = 'user@example.com' 
  AND team_id = 'team123' 
  AND is_active = true;

-- Before: Full table scan on metrics
-- After: Index range scan on ix_tool_metrics_tool_timestamp
SELECT * FROM tool_metrics 
WHERE tool_id = 'tool123' 
  AND timestamp >= '2025-01-01' 
ORDER BY timestamp DESC;
```

## Migration Instructions

### Automatic Migration (Recommended)

Both migrations run automatically on gateway startup:

```bash
# Start the gateway (migrations run automatically)
mcpgateway

# Or explicitly run migrations
alembic upgrade head
```

### Manual Migration

For production environments with large databases, run migrations during maintenance window:

```bash
# 1. Backup database
cp mcp.db mcp.db.backup  # SQLite
# OR
pg_dump -h localhost -U user dbname > backup.sql  # PostgreSQL

# 2. Run Phase 1 (foreign key indexes)
alembic upgrade n8h9i0j1k2l3

# 3. Verify Phase 1
alembic current

# 4. Run Phase 2 (composite indexes)
alembic upgrade o9i0j1k2l3m4

# 5. Verify Phase 2
alembic current

# 6. Update statistics (important for query planner)
# PostgreSQL:
psql -d dbname -c "ANALYZE;"
# SQLite:
sqlite3 mcp.db "ANALYZE;"
```

### Rollback

If issues occur, rollback the migrations:

```bash
# Rollback Phase 2 only
alembic downgrade n8h9i0j1k2l3

# Rollback both phases
alembic downgrade m7g8h9i0j1k2

# Or rollback one step at a time
alembic downgrade -1
```

### Production Considerations

For large databases (>1GB), consider:

1. **Create indexes concurrently** (PostgreSQL only):
   ```sql
   -- Modify migration to use concurrent index creation
   CREATE INDEX CONCURRENTLY ix_name ON table (column);
   ```

2. **Monitor disk space**: Ensure 30-40% free space for index creation

3. **Schedule during low-traffic period**: Index creation can lock tables briefly

4. **Monitor progress**:
   ```sql
   -- PostgreSQL: Check index creation progress
   SELECT * FROM pg_stat_progress_create_index;
   ```

## Monitoring

### Index Usage Statistics

#### PostgreSQL

```sql
-- Check index usage
SELECT
    schemaname,
    relname as tablename,
    indexrelname as indexname,
    idx_scan as index_scans,
    idx_tup_read as tuples_read,
    idx_tup_fetch as tuples_fetched
FROM pg_stat_user_indexes
WHERE indexrelname LIKE 'idx_%'
ORDER BY idx_scan DESC;

-- Check index size
SELECT
    i.indexrelname as indexname,
    pg_size_pretty(pg_relation_size(i.indexrelid)) as index_size
FROM pg_stat_user_indexes i
WHERE i.indexrelname LIKE 'idx_%'
ORDER BY pg_relation_size(i.indexrelid) DESC;

-- Alternative: Check all indexes with their table sizes
SELECT
    t.tablename,
    i.indexrelname as indexname,
    pg_size_pretty(pg_total_relation_size(quote_ident(t.tablename)::regclass)) as table_size,
    pg_size_pretty(pg_relation_size(i.indexrelid)) as index_size,
    i.idx_scan as times_used
FROM pg_tables t
LEFT JOIN pg_indexes idx ON t.tablename = idx.tablename
LEFT JOIN pg_stat_user_indexes i ON i.indexrelname = idx.indexname
WHERE i.indexrelname LIKE 'idx_%'
ORDER BY pg_relation_size(i.indexrelid) DESC;
```

#### SQLite

```sql
-- Check if indexes exist
SELECT name, tbl_name, sql
FROM sqlite_master
WHERE type = 'index'
AND name LIKE 'idx_%';

-- Analyze query plans
EXPLAIN QUERY PLAN
SELECT * FROM tools t
JOIN email_teams et ON t.team_id = et.id
WHERE et.name = 'example';
```

### Performance Metrics

Monitor these metrics before and after migration:

1. **Query Response Time**: Average time for JOIN queries
2. **Database CPU Usage**: Should decrease for read-heavy workloads
3. **Lock Contention**: Should decrease for write operations
4. **Cache Hit Ratio**: May improve with better query plans
5. **Storage Usage**: Monitor index storage overhead (expected 25-35% increase)
6. **Write Performance**: Should improve after duplicate index cleanup

## Best Practices

### When to Add More Indexes

Consider adding indexes when:
- Query execution time > 100ms consistently
- EXPLAIN shows full table scans on large tables
- High CPU usage during specific query patterns
- Lock contention on frequently accessed tables

### When NOT to Add Indexes

Avoid excessive indexing when:
- Table has < 1000 rows (full scan is fast enough)
- Column has low cardinality (few distinct values)
- Table is write-heavy (indexes slow down writes)
- Storage constraints are critical

### Index Maintenance

#### PostgreSQL

```sql
-- Rebuild indexes (if fragmented)
REINDEX INDEX CONCURRENTLY ix_tools_team_id;

-- Update statistics
ANALYZE tools;

-- Vacuum to reclaim space
VACUUM ANALYZE;
```

#### SQLite

```sql
-- Rebuild indexes
REINDEX;

-- Update statistics
ANALYZE;

-- Optimize database
VACUUM;
```

## Troubleshooting

### Migration Fails

**Issue**: Migration fails with "index already exists"

**Solution**:
```bash
# Check existing indexes
alembic current

# If index exists, skip this migration
alembic stamp n8h9i0j1k2l3
```

### Duplicate Index Detection

**Issue**: Need to identify duplicate indexes before migration

**Solution**:
```bash
# Run the detection utility
python detect_duplicate_indexes.py

# Output shows duplicates that will be dropped:
# email_api_tokens|user_email|2|idx_email_api_tokens_user_email,ix_email_api_tokens_user_email
#   -> DROP: ix_email_api_tokens_user_email
```

### Performance Degradation

**Issue**: Queries slower after migration

**Possible causes**:
1. Statistics not updated - Run `ANALYZE` (PostgreSQL) or `ANALYZE` (SQLite)
2. Index not being used - Check query plan with `EXPLAIN`
3. Wrong index chosen - Consider adding composite indexes

### Storage Issues

**Issue**: Database size increased significantly

**Solution**:
```bash
# Check index sizes
# PostgreSQL: Use query above
# SQLite: Check file size

# If needed, drop unused indexes
DROP INDEX IF EXISTS ix_unused_index;
```

## Related Documentation

- [Database Configuration](../manage/supported-databases.md)
- [Performance Tuning](../manage/scale.md)
- [Observability](../manage/observability/internal-observability.md)
- [Migration Guide](../manage/upgrade.md)

## Summary

The database indexing optimization initiative (Issue #1353) has been completed in multiple phases:

- **Phase 0**: Index naming standardization (`ix_*` → `idx_*`)
- **Phase 0.5**: Duplicate index cleanup (removes redundant `ix_*` indexes)
- **Phase 1**: 47 foreign key indexes for improved JOIN and constraint performance
- **Phase 2**: 37 composite indexes for optimized multi-column queries

**Total**: 84 new indexes across the database schema

**Expected Performance Gains**:
- JOIN queries: 10-100x faster
- Multi-column filtering: 5-50x faster
- Team-scoped queries: Dramatic improvement
- Time-series queries: Significant speedup
- Write operations: Improved after duplicate cleanup

**Storage Impact**:
- Initial increase: 25-35% of database size
- Reduced by duplicate cleanup: Saves 5-10% where duplicates existed
- Net increase: ~20-30% of original database size

**Index Naming Convention**:
All indexes now use the `idx_` prefix for consistency:
- `idx_table_column` for single-column indexes
- `idx_table_col1_col2_col3` for composite indexes

## References

- Issue: [#1353 - Database Indexing Optimization](https://github.com/IBM/mcp-context-forge/issues/1353)
- Migration: `mcpgateway/alembic/versions/n8h9i0j1k2l3_add_database_indexes.py`
- Duplicate Detection: `detect_duplicate_indexes.py`
- Test Suite: `test_duplicate_index_detection.py`
- Detailed Documentation: `DUPLICATE_INDEX_CLEANUP.md`
- Related ADR: [002 - Use Async SQLAlchemy ORM](adr/002-use-async-sqlalchemy-orm.md)