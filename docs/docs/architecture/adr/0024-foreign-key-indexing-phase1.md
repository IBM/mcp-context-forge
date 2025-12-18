# ADR 0024: Foreign Key Indexing - Phase 1

## Status

Accepted

## Context

Issue [#1353](https://github.com/IBM/mcp-context-forge/issues/1353) identified the need for comprehensive database indexing optimization to improve query performance. Phase 1 focuses on creating indexes on all foreign key columns that don't already have them.

Foreign keys without indexes can cause performance issues in several ways:
1. **Slow JOIN operations**: Database engines need to scan entire tables when joining on unindexed foreign keys
2. **Foreign key constraint checks**: INSERT, UPDATE, and DELETE operations on parent tables require checking child tables
3. **Cascading operations**: CASCADE DELETE and CASCADE UPDATE operations are slower without indexes
4. **Query optimization**: The query planner has fewer options for efficient execution plans

## Decision

We will create indexes on all foreign key columns across the database schema that don't already have indexes. This is implemented in Alembic migration `n8h9i0j1k2l3_add_foreign_key_indexes_phase1.py`.

### Foreign Keys Indexed

The following foreign key columns now have indexes:

#### User and Role Management
- `user_roles.user_email` → `email_users.email`
- `user_roles.role_id` → `roles.id`
- `user_roles.granted_by` → `email_users.email`

#### Team Management
- `email_teams.created_by` → `email_users.email`
- `email_team_members.team_id` → `email_teams.id`
- `email_team_members.user_email` → `email_users.email`
- `email_team_members.invited_by` → `email_users.email`
- `email_team_member_history.team_member_id` → `email_team_members.id`
- `email_team_member_history.team_id` → `email_teams.id`
- `email_team_member_history.user_email` → `email_users.email`
- `email_team_member_history.action_by` → `email_users.email`
- `email_team_invitations.team_id` → `email_teams.id`
- `email_team_invitations.invited_by` → `email_users.email`
- `email_team_join_requests.team_id` → `email_teams.id`
- `email_team_join_requests.user_email` → `email_users.email`
- `email_team_join_requests.reviewed_by` → `email_users.email`
- `pending_user_approvals.approved_by` → `email_users.email`

#### Resource Management
- `resource_subscriptions.resource_id` → `resources.id`
- `servers.team_id` → `email_teams.id`
- `gateways.team_id` → `email_teams.id`
- `grpc_services.team_id` → `email_teams.id`

#### Session Management
- `mcp_messages.session_id` → `mcp_sessions.session_id`

#### OAuth and Authentication
- `oauth_tokens.gateway_id` → `gateways.id`
- `oauth_tokens.app_user_email` → `email_users.email`
- `oauth_states.gateway_id` → `gateways.id`
- `registered_oauth_clients.gateway_id` → `gateways.id`
- `email_api_tokens.server_id` → `servers.id`
- `token_revocations.revoked_by` → `email_users.email`
- `sso_auth_sessions.provider_id` → `sso_providers.id`
- `sso_auth_sessions.user_email` → `email_users.email`

### Foreign Keys Already Indexed (Skipped)

The following foreign keys already had indexes from previous migrations:
- `tools.gateway_id`, `tools.team_id` (migration 1bf06ef4b2d9)
- `resources.gateway_id`, `resources.team_id` (migration 1bf06ef4b2d9)
- `prompts.gateway_id`, `prompts.team_id` (migration 1bf06ef4b2d9)
- `a2a_agents.team_id` (migration 1bf06ef4b2d9)
- `tool_metrics.tool_id` (migration 1bf06ef4b2d9)
- `resource_metrics.resource_id` (migration 1bf06ef4b2d9)
- `prompt_metrics.prompt_id` (migration 1bf06ef4b2d9)
- `server_metrics.server_id` (migration 1bf06ef4b2d9)
- `a2a_agent_metrics.a2a_agent_id` (migration 1bf06ef4b2d9)
- `email_api_tokens.user_email`, `email_api_tokens.team_id` (defined in model)
- `email_auth_events.user_email` (defined in model)

## Consequences

### Positive

1. **Improved JOIN Performance**: Queries involving foreign key relationships will execute faster
2. **Faster Constraint Checks**: Foreign key constraint validation during INSERT/UPDATE/DELETE operations will be more efficient
3. **Better Query Plans**: The query optimizer will have more options for efficient execution plans
4. **Reduced Lock Contention**: Faster lookups mean shorter transaction times and less lock contention
5. **Scalability**: The database will handle larger datasets more efficiently

### Negative

1. **Increased Storage**: Each index requires additional disk space (typically 10-30% of table size)
2. **Slower Writes**: INSERT, UPDATE, and DELETE operations will be slightly slower due to index maintenance
3. **Migration Time**: Creating indexes on large tables may take time during deployment

### Neutral

1. **Index Maintenance**: Indexes need to be maintained, but this is automatic in modern databases
2. **Memory Usage**: Active indexes consume buffer pool memory, but this is generally beneficial

## Implementation Notes

### Migration Safety

The migration uses standard `CREATE INDEX` statements which are:
- **Non-blocking** in PostgreSQL (with `CONCURRENTLY` option if needed)
- **Safe to run** on production databases
- **Reversible** with the provided downgrade function

### Testing

To test the migration:

```bash
# Check migration status
alembic current

# Run the migration
alembic upgrade head

# Verify indexes were created
# PostgreSQL:
SELECT tablename, indexname FROM pg_indexes WHERE schemaname = 'public' AND indexname LIKE 'ix_%';

# SQLite:
SELECT name FROM sqlite_master WHERE type = 'index' AND name LIKE 'ix_%';

# Rollback if needed
alembic downgrade -1
```

### Performance Monitoring

After deployment, monitor:
1. Query execution times for JOIN operations
2. Foreign key constraint check times
3. Overall database response times
4. Index usage statistics

## Related Issues

- [#1353](https://github.com/IBM/mcp-context-forge/issues/1353) - Epic: Database Indexing Optimization
- [#1354](https://github.com/IBM/mcp-context-forge/issues/1354) - Epic: PostgreSQL Database Tuning & Optimization

## References

- [PostgreSQL Index Documentation](https://www.postgresql.org/docs/current/indexes.html)
- [SQLite Index Documentation](https://www.sqlite.org/lang_createindex.html)
- [Database Indexing Best Practices](https://use-the-index-luke.com/)
- Migration file: `mcpgateway/alembic/versions/n8h9i0j1k2l3_add_foreign_key_indexes_phase1.py`

## Date

2025-12-18

## Authors

- Bob (AI Assistant)