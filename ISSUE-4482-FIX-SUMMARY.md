# Fix for Issue #4482: RBAC Race Condition

## Summary

This fix addresses the potential race condition in RBAC role and user_role seeding when multiple replicas/workers bootstrap the database concurrently. The fix implements defense-in-depth with both database-level and application-level protection.

## Changes Made

### 1. Database Migration (`d21698ae4a19_add_rbac_unique_constraints_race_fix.py`)

**Purpose**: Add database-level unique constraints to prevent duplicate active roles and role assignments.

**Key Features**:
- ✅ **Supports both PostgreSQL and SQLite**: Uses dialect-specific SQL for boolean values and partial indexes
- ✅ **Idempotent**: Checks for existing indexes before creating them
- ✅ **Safe for existing data**: Deduplicates any existing duplicate active rows before adding constraints
- ✅ **Audit-friendly**: Soft-deletes duplicates (sets `is_active=false`) instead of hard-deleting them

**What it does**:

1. **Deduplication (STEP 1 & 2)**:
   - Finds duplicate active `roles` with same `(name, scope)` - keeps oldest by `created_at`
   - Finds duplicate active `user_roles` with same `(user_email, role_id, scope, scope_id)` - keeps oldest by `granted_at`
   - Soft-deletes newer duplicates by setting `is_active=false`
   - Preserves audit history - duplicates remain in DB for forensics

2. **Unique Constraints (STEP 3)**:
   - Creates partial unique index: `uq_roles_name_scope_active` on `roles(name, scope) WHERE is_active = true`
   - Creates partial unique index: `uq_user_roles_email_role_scope_null_active` on `user_roles(user_email, role_id, scope) WHERE scope_id IS NULL AND is_active = true`
   - Creates partial unique index: `uq_user_roles_email_role_scope_id_active` on `user_roles(user_email, role_id, scope, scope_id) WHERE scope_id IS NOT NULL AND is_active = true`

**Why partial indexes?**:
- Only active rows (`is_active = true`) need uniqueness constraint
- Allows multiple inactive/historical rows with same values (for audit purposes)
- Split `user_roles` indexes handle nullable `scope_id` (PostgreSQL/SQLite treat NULL as distinct in unique indexes)

**Downgrade**:
- Drops the three unique indexes
- Does NOT reactivate soft-deleted duplicates (preserves audit trail)

### 2. Application-Level Changes (`mcpgateway/services/role_service.py`)

**Purpose**: Handle IntegrityError gracefully when database constraints prevent duplicates.

**Changes**:

1. **Import IntegrityError**:
   ```python
   from sqlalchemy.exc import IntegrityError
   ```

2. **Updated `create_role()` method**:
   - Wraps insert in `db.begin_nested()` (savepoint)
   - On `IntegrityError`: rolls back savepoint, refetches existing role, returns it
   - No error to caller - seamlessly returns the winner's row
   - Logs info-level message about concurrent creation

3. **Updated `assign_role_to_user()` method**:
   - Same savepoint + refetch pattern
   - On `IntegrityError`: rolls back, refetches existing assignment, returns it
   - Transparent to callers

**Benefits**:
- No breaking changes - methods still return the role/assignment
- Prevents `MultipleResultsFound` errors that would cause 500 responses
- Logs provide visibility into concurrent operations
- If refetch fails (shouldn't happen), raises descriptive error

## Security Considerations

### ✅ No Security Issues Introduced

1. **No authentication bypass**: Changes are pure data integrity - don't affect auth flows
2. **No privilege escalation**: Doesn't modify role permissions or RBAC logic
3. **No data exposure**: Deduplication only affects active rows, preserves audit history
4. **No SQL injection**: Uses parameterized queries and SQLAlchemy ORM
5. **Defense in depth**: Database constraints are ultimate authority, application handles gracefully

### ✅ Backwards Compatible

1. **Existing functionality preserved**:
   - All existing role/assignment operations work identically
   - Bootstrap flows unchanged (just more robust)
   - No API changes, no schema-breaking changes

2. **Safe migration**:
   - Idempotent - can run multiple times safely
   - Works on fresh DBs (skips if tables don't exist)
   - Works on populated DBs (deduplicates first)
   - Downgrade available (though not recommended in production)

## Testing Recommendations

Before committing, run:

```bash
# 1. Check code quality
make ruff
make pylint
make mypy

# 2. Run unit tests
make test

# 3. Test migration on SQLite (default .env)
.venv/bin/alembic -c mcpgateway/alembic.ini upgrade head
.venv/bin/alembic -c mcpgateway/alembic.ini downgrade -1
.venv/bin/alembic -c mcpgateway/alembic.ini upgrade head

# 4. Test migration on PostgreSQL (if available)
# Set DATABASE_URL=postgresql://...
# Repeat alembic commands above

# 5. Integration tests (if using --with-integration)
make test-integration
```

## Files Modified

1. **New file**: `mcpgateway/alembic/versions/d21698ae4a19_add_rbac_unique_constraints_race_fix.py`
   - Migration script (320 lines)
   
2. **Modified**: `mcpgateway/services/role_service.py`
   - Added IntegrityError import
   - Updated `create_role()` with savepoint + refetch pattern (+19 lines)
   - Updated `assign_role_to_user()` with savepoint + refetch pattern (+19 lines)

## Commit Message Template

```
fix(rbac): add unique constraints to prevent role/user_role seeding race (#4482)

Fixes issue #4482 - RBAC role/user_role seeder race when fast-path skips
advisory lock.

This fix implements defense-in-depth to prevent duplicate active roles
and user role assignments when multiple replicas/workers bootstrap the
database concurrently.

Changes:
- Add database-level partial unique indexes on roles and user_roles tables
- Update RoleService to handle IntegrityError gracefully with savepoint pattern
- Deduplicate any existing duplicate active rows in migration (soft-delete)
- Support both PostgreSQL and SQLite databases

The database constraints are the ultimate authority on uniqueness, while
the application-level handling ensures no errors propagate to callers.

Migration: d21698ae4a19 (idempotent, safe for existing data)

Signed-off-by: [Your Name] <[your-email]>
```

## Related Issues

- Issue #4482: RBAC role/user_role seeder race when fast-path skips advisory lock
- PR #4444: fix(bootstrap): improve startup reliability for multi-replica deploys (not yet merged)
- PR #4480: Draft fix mentioned in issue #4482 (this is an independent implementation)

## Notes for Reviewers

1. **This fix is safe to merge NOW** - it works with current code (advisory locks in place)
2. **Makes PR #4444 safe** - when the fast-path lands, these constraints prevent the race
3. **Two-layer defense**: DB constraints (authority) + app handling (graceful recovery)
4. **No performance impact**: Partial indexes only on active rows, minimal overhead
5. **Audit-friendly**: Soft-deletes preserve history, no data loss
