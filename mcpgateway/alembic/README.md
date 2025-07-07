# Alembic Migration Guide for `mcpgateway`

> Creating, applying, and managing schema migrations with Alembic.

---

## Table of Contents

1. [Why Alembic?](#why-alembic)
2. [Prerequisites](#prerequisites)
3. [Directory Layout](#directory-layout)
4. [Everyday Workflow](#everyday-workflow)
5. [Helpful Make Targets](#helpful-make-targets)
6. [Troubleshooting](#troubleshooting)
7. [Further Reading](#further-reading)

---

## Why Alembic?

- **Versioned DDL** - Revisions are timestamped, diff-able, and reversible.
- **Autogeneration** - Detects model vs. DB drift and writes `op.create_table`, `op.add_column`, etc.
- **Multi-DB Support** - Works with SQLite, PostgreSQL, MySQL-anything SQLAlchemy supports.
- **Zero Runtime Cost** - Only runs when you call it (dev, CI, deploy).

---

## Prerequisites

```bash
# Activate your virtual environment first
pip install --upgrade alembic
```

You do not need to set up `alembic.ini`, `env.py`, or metadata wiring - they're already configured.

---

## Directory Layout

```
alembic.ini
alembic/
├── env.py
├── script.py.mako
└── versions/
    ├── 20250626235501_initial_schema.py
    └── ...
```

* `alembic.ini`: Configuration file
* `env.py`: Connects Alembic to your models and DB settings
* `script.py.mako`: Template for new revisions (keep this!)
* `versions/`: Contains all migration scripts

---

## Everyday Workflow

> **1 Edit → 2 Revision → 3 Upgrade**

| Step                     | What you do                                                                   |
| ------------------------ | ----------------------------------------------------------------------------- |
| **1. Change models**     | Modify SQLAlchemy models in `mcpgateway.db` or its submodules.                |
| **2. Generate revision** | Run: `MSG="add users table"` then `alembic revision --autogenerate -m "$MSG"` |
| **3. Review**            | Open the new file in `alembic/versions/`. Verify the operations are correct.  |
| **4. Upgrade DB**        | Run: `alembic upgrade head`                                                   |
| **5. Commit**            | Run: `git add alembic/versions/*.py`                                          |

### Other Common Commands

```bash
alembic -c mcpgateway/alembic.ini current             # Show current DB revision
alembic history --verbose   # Show all migrations and their order
alembic downgrade -1        # Roll back one revision
alembic downgrade <rev>     # Roll back to a specific revision hash
```

---

## ✅ Make Targets: Alembic Migration Commands

These targets help you manage database schema migrations using Alembic.

> You must have a valid `alembic/` setup and a working SQLAlchemy model base (`Base.metadata`).

---

### 💡 List all available targets (with help)

```bash
make help
```

This will include the Alembic section:

```
# 🛢️ Alembic tasks
db-new        Autogenerate revision (MSG="title")
db-up         Upgrade DB to head
db-down       Downgrade one step (REV=-1 or hash)
db-current    Show current DB revision
db-history    List the migration graph
```

---

### 🔨 Commands

| Command                    | Description                                            |
| -------------------------- | ------------------------------------------------------ |
| `make db-new MSG="..."`    | Generate a new migration based on model changes.       |
| `make db-up`               | Apply all unapplied migrations.                        |
| `make db-down`             | Roll back the latest migration (`REV=-1` by default).  |
| `make db-down REV=abc1234` | Roll back to a specific revision by hash.              |
| `make db-current`          | Print the current revision ID applied to the database. |
| `make db-history`          | Show the full migration history and graph.             |

---

### 📌 Examples

```bash
# Create a new migration with a custom message
make db-new MSG="add users table"

# Apply it to the database
make db-up

# Downgrade the last migration
make db-down

# Downgrade to a specific revision
make db-down REV=cf1283d7fa92

# Show the current applied revision
make db-current

# Show all migration history
make db-history
```

---

### 🛑 Notes

* You must **edit models first** before `make db-new` generates anything useful.
* Always **review generated migration files** before committing.
* Don't forget to run `make db-up` on CI or deploy if using migrations to manage schema.

---

## Troubleshooting

| Symptom                            | Cause / Fix                                                                                                                                           |
| ---------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Empty migration (`pass`)**       | Alembic couldn't detect models. Make sure all model classes are imported before `Base.metadata` is used (already handled in your `env.py`).           |
| **`Can't locate revision ...`**    | You deleted or renamed a revision file that the DB is pointing to. Either restore it or run `alembic stamp base` and recreate the revision.           |
| **`script.py.mako` missing**       | This file is required. Run `alembic init alembic` in a temp folder and copy the missing template into your project.                                   |
| **SQLite foreign key limitations** | SQLite doesn't allow dropping constraints. Use `create table → copy → drop` flow manually, or plan around it.                                         |
| **DB not updating**                | Did you forget to run `alembic upgrade head`? Check with `alembic -c mcpgateway/alembic.ini current`.                                                                           |
| **Wrong DB URL or config errors**  | Confirm `settings.database_url` is valid. Check `env.py` and your `.env`/config settings. Alembic ignores `alembic.ini` for URLs in your setup.       |
| **Model changes not detected**     | Alembic only picks up declarative models in `Base.metadata`. Ensure all models are imported and not behind `if TYPE_CHECKING:` or other lazy imports. |

---

## Further Reading

* Official docs: [https://alembic.sqlalchemy.org](https://alembic.sqlalchemy.org)
* Autogenerate docs: [https://alembic.sqlalchemy.org/en/latest/autogenerate.html](https://alembic.sqlalchemy.org/en/latest/autogenerate.html)

---
