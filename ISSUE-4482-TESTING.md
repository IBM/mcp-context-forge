# Testing Plan for Issue #4482 Fix

## Pre-Commit Testing Checklist

### 1. Code Quality Checks

```bash
# Navigate to project root
cd /Users/rakhidutta/pr/mcp-context-forge

# Format code
make black
make isort

# Run linters
make ruff
make pylint

# Type checking
make mypy
```

### 2. Unit Tests

```bash
# Run full test suite
make test

# Run tests with coverage
make test-coverage

# Check for any broken tests
pytest -v tests/
```

### 3. Migration Testing - SQLite (Default)

```bash
# Check current head
.venv/bin/alembic -c mcpgateway/alembic.ini heads
# Should show: d21698ae4a19 (head)

# Test upgrade
.venv/bin/alembic -c mcpgateway/alembic.ini upgrade head

# Verify indexes were created
sqlite3 mcp.db "SELECT name FROM sqlite_master WHERE type='index' AND name LIKE 'uq_%';"
# Should show:
# uq_roles_name_scope_active
# uq_user_roles_email_role_scope_null_active
# uq_user_roles_email_role_scope_id_active

# Test downgrade
.venv/bin/alembic -c mcpgateway/alembic.ini downgrade -1

# Verify indexes were dropped
sqlite3 mcp.db "SELECT name FROM sqlite_master WHERE type='index' AND name LIKE 'uq_%';"
# Should show no results

# Test upgrade again (idempotency)
.venv/bin/alembic -c mcpgateway/alembic.ini upgrade head

# Run twice to verify idempotency
.venv/bin/alembic -c mcpgateway/alembic.ini downgrade -1
.venv/bin/alembic -c mcpgateway/alembic.ini upgrade head
```

### 4. Migration Testing - PostgreSQL (If Available)

```bash
# Set up test PostgreSQL database
createdb mcp_test_4482

# Update DATABASE_URL
export DATABASE_URL="postgresql://localhost/mcp_test_4482"

# Run migrations
.venv/bin/alembic -c mcpgateway/alembic.ini upgrade head

# Verify indexes
psql mcp_test_4482 -c "\d roles"
psql mcp_test_4482 -c "\d user_roles"
# Look for the three unique indexes

# Test downgrade
.venv/bin/alembic -c mcpgateway/alembic.ini downgrade -1

# Clean up
dropdb mcp_test_4482
unset DATABASE_URL
```

### 5. Race Condition Simulation (Manual)

This test simulates concurrent bootstrap to verify the fix works:

```python
# Save as test_race_condition.py
import asyncio
import sys
sys.path.insert(0, '/Users/rakhidutta/pr/mcp-context-forge')

from mcpgateway.db import SessionLocal, Role
from mcpgateway.services.role_service import RoleService
from sqlalchemy import select

async def create_role_worker(worker_id: int):
    """Simulate concurrent role creation"""
    db = SessionLocal()
    try:
        service = RoleService(db)
        role = await service.create_role(
            name="test_concurrent_role",
            description=f"Created by worker {worker_id}",
            scope="global",
            permissions=["test.permission"],
            created_by="test@example.com",
            is_system_role=False
        )
        print(f"Worker {worker_id}: Created/fetched role {role.id}")
        return role.id
    except Exception as e:
        print(f"Worker {worker_id}: Error: {e}")
        raise
    finally:
        db.close()

async def test_concurrent_creation():
    """Test that only one role is created despite concurrent attempts"""
    # Run 10 workers concurrently
    tasks = [create_role_worker(i) for i in range(10)]
    role_ids = await asyncio.gather(*tasks)
    
    # Verify all workers got the same role ID
    unique_ids = set(role_ids)
    print(f"\nTotal workers: {len(role_ids)}")
    print(f"Unique role IDs: {len(unique_ids)}")
    print(f"Role ID: {list(unique_ids)[0]}")
    
    # Verify only one active role in DB
    db = SessionLocal()
    result = db.execute(
        select(Role).where(
            Role.name == "test_concurrent_role",
            Role.scope == "global",
            Role.is_active == True
        )
    )
    roles = result.scalars().all()
    print(f"Active roles in DB: {len(roles)}")
    
    assert len(unique_ids) == 1, "All workers should get the same role"
    assert len(roles) == 1, "Only one active role should exist in DB"
    print("\n✅ Test passed: Race condition prevented!")

if __name__ == "__main__":
    asyncio.run(test_concurrent_creation())
```

Run the test:
```bash
.venv/bin/python test_race_condition.py
```

Expected output:
```
Worker 0: Created/fetched role <uuid>
Worker 1: Created/fetched role <uuid>
...
Worker 9: Created/fetched role <uuid>

Total workers: 10
Unique role IDs: 1
Role ID: <uuid>
Active roles in DB: 1

✅ Test passed: Race condition prevented!
```

### 6. Deduplication Testing (Manual)

Test that the migration properly handles existing duplicates:

```sql
-- Create test duplicates BEFORE running migration
-- (only run this if testing on a fresh DB)

-- Downgrade to before the fix
.venv/bin/alembic -c mcpgateway/alembic.ini downgrade -1

-- Manually insert duplicate roles (simulate race that happened pre-fix)
sqlite3 mcp.db <<EOF
INSERT INTO roles (id, name, description, scope, permissions, created_by, is_system_role, is_active, created_at, updated_at)
VALUES 
  ('dup-role-1', 'duplicate_test', 'First duplicate', 'global', '["test.read"]', 'admin@example.com', 0, 1, datetime('now', '-2 days'), datetime('now')),
  ('dup-role-2', 'duplicate_test', 'Second duplicate', 'global', '["test.read"]', 'admin@example.com', 0, 1, datetime('now', '-1 days'), datetime('now')),
  ('dup-role-3', 'duplicate_test', 'Third duplicate', 'global', '["test.read"]', 'admin@example.com', 0, 1, datetime('now'), datetime('now'));

SELECT id, name, is_active, created_at FROM roles WHERE name = 'duplicate_test';
EOF

-- Now upgrade to apply the fix
.venv/bin/alembic -c mcpgateway/alembic.ini upgrade head

-- Verify: only oldest duplicate should remain active
sqlite3 mcp.db <<EOF
SELECT id, name, is_active, created_at, 
       CASE WHEN is_active = 1 THEN 'ACTIVE' ELSE 'DEDUPED' END as status
FROM roles 
WHERE name = 'duplicate_test' 
ORDER BY created_at;
EOF

-- Expected:
-- dup-role-1 | duplicate_test | 1 | <oldest-date> | ACTIVE
-- dup-role-2 | duplicate_test | 0 | <middle-date> | DEDUPED
-- dup-role-3 | duplicate_test | 0 | <newest-date> | DEDUPED
```

### 7. Integration Testing (Optional)

If using `--with-integration` flag:

```bash
# Run integration tests
pytest tests/integration/ --with-integration -v

# Run specific RBAC tests
pytest tests/integration/test_rbac*.py -v --with-integration
```

## Expected Results

### ✅ All tests should pass
- Code quality checks: no errors
- Unit tests: all passing
- Migration: upgrades and downgrades cleanly
- Race condition: only one role created despite concurrent attempts
- Deduplication: correctly identifies and soft-deletes newer duplicates

### ✅ No Breaking Changes
- Existing tests continue to pass
- No changes to API behavior
- Bootstrap flows work identically

### ❌ If Tests Fail

1. **Migration fails to create indexes**:
   - Check database dialect support for partial indexes
   - Verify table exists before index creation
   - Check logs for constraint violations

2. **Race condition test creates multiple roles**:
   - Verify migration ran successfully
   - Check that indexes were created
   - Ensure database supports UNIQUE constraints

3. **Deduplication doesn't work**:
   - Check SQL query syntax for your database dialect
   - Verify `is_active` column exists and has correct type
   - Check migration logs for row counts

## Post-Merge Validation

After merging to main:

```bash
# On a staging environment with multiple replicas
# 1. Deploy the new code
# 2. Watch logs for concurrent bootstrap
# 3. Verify no "MultipleResultsFound" errors
# 4. Check that role creation logs show "refetching existing role" for replicas 2-N

# Query metrics
# - Number of duplicate roles deduped during migration
# - Number of concurrent role creation conflicts handled gracefully
```

## Rollback Plan

If issues arise in production:

```bash
# Downgrade the migration
.venv/bin/alembic -c mcpgateway/alembic.ini downgrade -1

# This removes the unique indexes but keeps the deduped state
# (soft-deleted duplicates remain inactive for audit)

# Revert code changes
git revert <commit-hash>
```

Note: Rolling back removes the protection against future duplicates but doesn't break existing functionality.
