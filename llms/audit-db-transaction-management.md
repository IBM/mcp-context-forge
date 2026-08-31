# Database Transaction Management Audit

## Overview

This prompt guides you through auditing ContextForge codebase for proper database transaction management. The goal is to identify endpoints missing explicit `db.commit(); db.close()` calls, which cause PostgreSQL connection leaks under load.

## Background: How Database Sessions Work

### The Problem

FastAPI uses dependency injection for database sessions via `Depends(get_db)`. The `get_db` generator yields a session and cleans up in a `finally` block:

```python
def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
```

**The issue**: Under high concurrency, the cleanup in `finally` may be delayed because:
1. The request completes its database query
2. The transaction stays open during response serialization (Pydantic model_dump, JSON encoding)
3. Response is sent to client
4. Only THEN does the `finally` block run

This causes connections to remain in PostgreSQL's `idle in transaction` state for 20-30+ seconds, exhausting the connection pool.

### The Solution

Explicitly commit and close the database session **immediately after database operations complete**, before any response processing:

```python
# CORRECT: Release transaction before response serialization
result = await service.do_operation(db, ...)
db.commit()
db.close()
return result

# INCORRECT: Transaction held during response serialization
return await service.do_operation(db, ...)
```

## Audit Instructions

### Step 1: Identify All Endpoints Using Database Sessions

Search for functions that have `db: Session = Depends(get_db)` in their signature:

```bash
grep -rn "db: Session = Depends(get_db)" mcpgateway/
```

### Step 2: Categorize Endpoints

For each endpoint, determine if it's:

1. **CUD (Create, Update, Delete)** - MUST have `db.commit(); db.close()`
2. **Read/List** - SHOULD have `db.commit(); db.close()` (commit ensures clean transaction state)
3. **Passthrough/Proxy** - May delegate to services that manage their own sessions

### Step 3: Verify Each Endpoint

For each endpoint, check:

1. **Does it have `db.commit()` before the return?**
2. **Does it have `db.close()` before the return?**
3. **Is the pattern applied BEFORE response serialization?**

### Correct Patterns

#### Pattern A: Simple Return
```python
async def get_item(item_id: str, db: Session = Depends(get_db)):
    service = ItemService(db)
    item = await service.get_item(item_id)
    if not item:
        raise HTTPException(status_code=404, detail="Not found")

    db.commit()
    db.close()
    return ItemResponse.from_orm(item)
```

#### Pattern B: Complex Response Building
```python
async def list_items(db: Session = Depends(get_db)):
    service = ItemService(db)
    items = await service.list_items()

    # Build response BEFORE commit/close if it needs db access
    result = [ItemResponse.from_orm(item) for item in items]

    db.commit()
    db.close()
    return result
```

#### Pattern C: Conditional Returns
```python
async def create_item(request: ItemCreate, db: Session = Depends(get_db)):
    try:
        service = ItemService(db)
        item = await service.create_item(request)

        result = ItemResponse.from_orm(item)
        db.commit()
        db.close()
        return result
    except ValidationError as e:
        # Don't commit/close here - let exception propagate
        raise HTTPException(status_code=400, detail=str(e))
```

#### Pattern D: Void Returns (DELETE endpoints)
```python
async def delete_item(item_id: str, db: Session = Depends(get_db)):
    service = ItemService(db)
    await service.delete_item(item_id)

    db.commit()
    db.close()
    return {"status": "success", "message": f"Item {item_id} deleted"}
```

### Incorrect Patterns to Fix

#### Anti-Pattern 1: Direct Return
```python
# WRONG: Transaction held during serialization
async def get_item(item_id: str, db: Session = Depends(get_db)):
    service = ItemService(db)
    return await service.get_item(item_id)  # No commit/close!
```

#### Anti-Pattern 2: Commit Without Close
```python
# WRONG: Connection not returned to pool
async def create_item(request: ItemCreate, db: Session = Depends(get_db)):
    service = ItemService(db)
    item = await service.create_item(request)
    db.commit()  # Missing db.close()!
    return item
```

#### Anti-Pattern 3: Close Without Commit
```python
# WRONG: Transaction implicitly rolled back
async def update_item(item_id: str, db: Session = Depends(get_db)):
    service = ItemService(db)
    item = await service.update_item(item_id)
    db.close()  # Missing db.commit()!
    return item
```

## Files to Audit

### Priority 1: Routers (High Traffic)
- `mcpgateway/routers/tokens.py`
- `mcpgateway/routers/teams.py`
- `mcpgateway/routers/rbac.py`
- `mcpgateway/routers/email_auth.py`
- `mcpgateway/routers/sso.py`
- `mcpgateway/routers/oauth_router.py`
- `mcpgateway/routers/llm_config_router.py`

### Priority 2: Main API (Core Operations)
- `mcpgateway/main.py` - REST endpoints and RPC handlers

### Priority 3: Admin API
- `mcpgateway/admin.py` - Admin UI and management endpoints

## Verification

After identifying and fixing issues, verify with:

### 1. Syntax Check
```bash
python3 -c "import ast; ast.parse(open('mcpgateway/routers/FILE.py').read())"
```

### 2. Unit Tests
```bash
pytest tests/unit/mcpgateway/routers/ -v
```

### 3. PostgreSQL Connection Monitoring (During Load Test)
```bash
# Check for idle-in-transaction connections
docker exec postgres psql -U postgres -d mcp -c "
SELECT state, COUNT(*)
FROM pg_stat_activity
WHERE datname = 'mcp'
GROUP BY state;"

# Target: 0 connections in 'idle in transaction' state
```

## Output Format

Report findings as:

```markdown
## Audit Results

### Missing db.commit(); db.close()

| File | Function | Line | Issue |
|------|----------|------|-------|
| routers/example.py | get_item | 123 | Missing both commit and close |
| routers/example.py | update_item | 456 | Missing close (has commit) |

### Already Correct
- routers/teams.py - All 18 endpoints verified ✓
- routers/rbac.py - All 12 endpoints verified ✓

### Exceptions (No Fix Needed)
- Functions that don't use db parameter (marked as `_db`)
- Functions that delegate to other services with own session management
```

## Notes

- The `get_db` dependency's `finally` block is a safety net, not a substitute for explicit cleanup
- Always commit even for read operations - it ensures clean transaction state
- The order must be: `db.commit()` THEN `db.close()`
- For endpoints with `_db: Session = Depends(get_db)` (underscore prefix), the parameter is unused - no action needed
