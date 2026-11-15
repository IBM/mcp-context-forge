---
name: alembic-migrations
description: Create or review an Alembic migration in `mcpgateway/alembic`. Use when you add a column or table, change `mcpgateway/db.py` models, fix "Multiple heads", or write a `downgrade()` that reads `settings`.
---

# Alembic Database Migrations

Create an Alembic migration for every new database column or table.

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

```bash
# Verify single head after creating migration
cd mcpgateway && alembic heads
# Should show only ONE head

# Run tests to confirm migrations work
make test
```

Done when `alembic heads` prints one head and `make test` passes.

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
