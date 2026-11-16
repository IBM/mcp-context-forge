---
name: alembic-migrations
description: Create or review an Alembic migration in `mcpgateway/alembic`. Use when you add a column or table, change `mcpgateway/db.py` models, fix "Multiple heads", or write a `downgrade()` that reads `settings`.
---

# Alembic Database Migrations

Every change to a model in `mcpgateway/db.py` needs a matching Alembic migration. This includes every new column and table.

## Migration Chain Rules

- Work on one migration at a time. Merge or finish one migration before you start the next.
- The `revision` -> `down_revision` links form one linked list. The chain never branches.
- Each migration has exactly one parent. `alembic heads` shows exactly one head.
- A new migration sets `down_revision` to the current head.

## Create a Migration

```bash
# CRITICAL: Always check the current head FIRST
cd mcpgateway && alembic heads

# Generate a new migration (auto-generates from model changes)
alembic revision --autogenerate -m "add_column_to_table"

# Or create an empty migration for manual edits
alembic revision -m "add_column_to_table"
```

## Migration File Requirements

The `down_revision` MUST point to the current head. Read the head from `alembic heads`. Never copy the value from an older migration.

```python
# CORRECT: points to the actual current head (verified with `alembic heads`)
revision: str = "<new_revision_id>"
down_revision: Union[str, Sequence[str], None] = "<current_head_id>"

# WRONG: creates multiple heads (breaks all tests)
down_revision: Union[str, Sequence[str], None] = "<some_older_revision_id>"
```

## Idempotent Migrations Pattern

Write idempotent migrations. Check state before you change it:

```python
def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())

    # Skip if table doesn't exist (fresh DB uses db.py models directly)
    if "my_table" not in inspector.get_table_names():
        return

    # Skip if column already exists
    columns = [col["name"] for col in inspector.get_columns("my_table")]
    if "new_column" in columns:
        return

    op.add_column("my_table", sa.Column("new_column", sa.String(), nullable=True))
```

## Verification

Run these commands from `mcpgateway/`.

### Inspect the chain

```bash
alembic heads              # must show exactly ONE head
alembic current            # revision the DB is at
alembic history --verbose  # full chain
alembic branches           # find branch points
```

### Upgrade

```bash
alembic upgrade head              # apply all
alembic upgrade +1                # apply the next one
alembic upgrade <revision_id>     # apply up to a specific revision
alembic upgrade <rev>:head --sql  # print the SQL only (offline mode, no DB change)
```

### Downgrade

```bash
alembic downgrade -1              # revert the latest migration
alembic downgrade <revision_id>   # revert to a specific revision
alembic downgrade base            # revert everything
alembic downgrade head:-1 --sql   # print the SQL only (offline mode, no DB change)
```

### Round-trip test of a new migration

```bash
alembic upgrade head && alembic downgrade -1 && alembic upgrade head
```

Run the test suite to confirm the migrations work:

```bash
make test
```

Done when `alembic heads` prints one head, the round-trip test passes, and `make test` passes.

## Common Errors

- **"Multiple heads are present"**: `down_revision` points to the wrong parent. Set it to the actual current head.
- **"Target database is not up to date"**: Run `alembic upgrade head` first.

## Hermetic Downgrade: Config Snapshot Pattern

A `downgrade()` that reads runtime configuration (`mcpgateway.config.settings`) **must** snapshot those values into `migration_metadata` during `upgrade()`. `downgrade()` reads the snapshot back. The migration is then hermetic: database state determines its behavior, not the current environment.

```python
from mcpgateway.config import settings
from sqlalchemy import inspect, text

REVISION = "<your_revision_id>"

def upgrade() -> None:
    bind = op.get_bind()
    # ... schema changes ...

    # Snapshot any settings values used in downgrade
    if "migration_metadata" in inspect(bind).get_table_names():
        bind.execute(
            text(
                "INSERT INTO migration_metadata (revision, key, value, created_at) "
                "VALUES (:rev, :key, :val, CURRENT_TIMESTAMP) "
                "ON CONFLICT (revision, key) DO UPDATE SET value = excluded.value"
            ),
            {"rev": REVISION, "key": "some_setting", "val": settings.some_setting},
        )

def downgrade() -> None:
    bind = op.get_bind()

    # Read from snapshot; fall back to live settings only if table is absent
    # (pre-existing DB that was upgraded before this pattern was introduced)
    cfg = {}
    if "migration_metadata" in inspect(bind).get_table_names():
        rows = bind.execute(
            text("SELECT key, value FROM migration_metadata WHERE revision = :rev"),
            {"rev": REVISION},
        ).all()
        cfg = {r[0]: r[1] for r in rows}

    some_setting = cfg.get("some_setting") or settings.some_setting

    # ... use some_setting for downgrade logic ...

    # Clean up snapshot rows
    if "migration_metadata" in inspect(bind).get_table_names():
        bind.execute(
            text("DELETE FROM migration_metadata WHERE revision = :rev"),
            {"rev": REVISION},
        )
```

**Rule:** If a migration imports `settings` and uses it in `downgrade()`, follow this pattern. A migration that uses `settings` only in `upgrade()` (for example, to seed initial data) is exempt.
