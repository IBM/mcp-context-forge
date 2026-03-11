# Manual Migration Testing

This guide describes how to manually test Alembic database migrations against PostgreSQL using Docker containers.

---

## 📖 What Are Database Migrations?

Database migrations are versioned, incremental changes to a database schema — adding columns, creating tables, renaming fields, or adjusting constraints. ContextForge uses [Alembic](https://alembic.sqlalchemy.org/) to manage migrations, which tracks every schema change as a numbered revision file under `mcpgateway/alembic/versions/`.

When the gateway starts, Alembic compares the current database state against the revision history and automatically applies any pending migrations in order.

### Why Do Migrations Need to Be Tested Manually?

Automated unit tests run against SQLite, which is permissive and forgiving about types, constraints, and syntax. Production deployments, however, commonly use **PostgreSQL** — which has stricter type enforcement, different default behaviours, and subtle SQL dialect differences.

A migration that works perfectly on SQLite can fail silently or raise errors on PostgreSQL. Manual testing catches:

- **Type incompatibilities** — e.g. `BOOLEAN` vs `TINYINT(1)`, `TEXT` length limits
- **Constraint differences** — nullable defaults, foreign key enforcement
- **SQL dialect issues** — syntax accepted by one engine but rejected by another
- **Migration ordering bugs** — a revision that assumes a column exists before it is created
- **Idempotency failures** — a migration that errors when run twice on an existing schema

Testing migrations manually before merging ensures that upgrades work reliably across all supported databases.

---

## 🧩 Prerequisites

- Docker
- [DBeaver](https://dbeaver.io/) (or any SQL client)
- A working `.env` file

---

## 🐳 Start Database Containers

Start the PostgreSQL container:

### PostgreSQL

```bash
docker run -d \
  --name mcp-postgres \
  -e POSTGRES_USER=postgres  \
  -e POSTGRES_PASSWORD=mysecretpassword \
  -p 5432:5432 \
  postgres:17
```

---

## 🗄️ Inspect the Database in DBeaver

1. Open **DBeaver** and create a new connection to the running container using the credentials above.
2. Verify the `mcp` database exists. If for any reason it was not created automatically, create it manually:

```sql
CREATE DATABASE mcp;
```

---

## ⚙️ Configure the Gateway

Update `DATABASE_URL` in your `.env` to point to the PostgreSQL database:

```bash
DATABASE_URL=postgresql+psycopg://postgres:mysecretpassword@localhost:5432/mcp
```

---

## 🚀 Start the Gateway

Start the gateway. On first run it will apply all Alembic migrations and populate the tables:

```bash
make dev
```

---

## ✅ Verify Migration Status

Check that all migrations were applied successfully:

```bash
make db-status
```

You should see all revisions listed as applied with no pending migrations.

You can also inspect the tables directly in DBeaver to confirm the schema matches the expected structure.

---

## 🌱 Populate the Database (Optional)

Once the gateway is running you can seed it with test data using the populate scripts.

`make populate-small` defaults to port **8080**. When running `make dev` (port **8000**), override the target URL with `--base-url` or the `MCPGATEWAY_BASE_URL` environment variable:

```bash
# Pass the URL directly
source .venv/bin/activate
export MCPGATEWAY_BEARER_TOKEN="your_token"
python -m tests.populate --profile small --base-url http://localhost:8000
```

Check if the values your migration affects are populated in the DB.

---

## 🧹 Cleanup

Stop and remove the container when done:

```bash
docker rm -f mcp-postgres
```

---

## 🔀 Testing Migrations Against Existing Data (Upgrade Simulation)

The most realistic migration test is to verify that a new migration applies cleanly to a database that already contains data — exactly as it would in a production upgrade.

### Step-by-step

**1. Start with a clean database on `main`**

Ensure the Docker container is running and the database is empty (or drop and recreate it):

```bash
# Drop and recreate the mcp database to start fresh
docker exec -it mcp-postgres psql -U postgres -c "DROP DATABASE IF EXISTS mcp; CREATE DATABASE mcp;"
```

**2. Checkout `main` and start the gateway**

```bash
git checkout main
make dev
```

The gateway will apply all current migrations and create the schema.

**3. Populate the database with test data**

```bash
MCPGATEWAY_BASE_URL=http://localhost:8000 make populate-small
```

This seeds the database with realistic data that the migration must handle without data loss or errors.

**4. Stop the gateway**

```bash
# Ctrl+C to stop make dev
```

**5. Checkout the branch containing the new migration**

```bash
git checkout your-migration-branch
```

**6. Apply the pending migration**

```bash
make db-upgrade
```

This runs `alembic upgrade head`, applying only the new revision(s) on top of the existing populated schema.

**7. Verify the migration succeeded**

```bash
make db-status
```

All revisions should show as applied. Inspect the affected tables in DBeaver to confirm the schema change is correct and existing data is intact.
