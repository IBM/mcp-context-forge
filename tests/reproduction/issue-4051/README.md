# Reproduction — Issue #4051

Alembic migration advisory lock hangs when multiple gateway replicas start
concurrently through PgBouncer in transaction-pooling mode.

Issue: https://github.com/IBM/mcp-context-forge/issues/4051

## What's here

Three ways to observe / prove the bug, in increasing order of abstraction:

| Artifact | Scope | When to use |
|---|---|---|
| `demonstrate_orphan.sh` | Mechanism proof | Fastest, deterministic. Proves the PgBouncer session-advisory-lock orphan exists. Runs in ~10s against just postgres + pgbouncer. |
| `reproduce.sh` | End-to-end symptom | Scales gateway to N replicas through PgBouncer and watches for the hang. Matches the issue reporter's OCP symptoms. |
| `tests/integration/test_migrations_under_transaction_pool.py` | Pinned regression | The mechanism as three pytest assertions. Keeps the invariants enforceable as the stack evolves. |

All three drive the same `tests/integration/fixtures/transaction_pool/docker-compose.yml` stack:

- `postgres:17`
- `edoburu/pgbouncer:latest` with `POOL_MODE=transaction` and a deliberately small `DEFAULT_POOL_SIZE=2` to force backend multiplexing
- N gateway replicas (default 3) pointed at `pgbouncer:6432` (only used by `reproduce.sh`)

## Prerequisites

- Docker and Docker Compose v2.
- For `reproduce.sh` only: a local gateway image tagged `mcpgateway/mcpgateway:latest`. Build from the repo root with `make docker` (or `make docker-prod`); override the tag via `IMAGE_LOCAL` if needed.
- For the pytest regression test: the `postgres` optional extra — `uv sync --extra postgres`.

## 1. Mechanism proof — `demonstrate_orphan.sh`

Start here. Fastest, always deterministic, doesn't need the gateway image.

```bash
cd tests/reproduction/issue-4051
./demonstrate_orphan.sh
```

Three steps:

1. Through PgBouncer, take advisory lock `42424242424242`, close the connection.
2. Query `pg_locks` directly on Postgres → lock is still held by the orphaned backend.
3. From a fresh direct-to-Postgres session, `pg_try_advisory_lock(...)` returns `f`.

Step 3 returning `f` is the exact condition that makes `bootstrap_db.main()` hang: a new gateway pod spinning on a lock no-one owns anymore.

## 2. Symptom reproduction — `reproduce.sh`

Scales gateway replicas through PgBouncer and reports whether all replicas reached `"Database ready"`.

```bash
cd tests/reproduction/issue-4051
./reproduce.sh
```

Environment knobs:

| Variable           | Default | Purpose |
|--------------------|---------|---------|
| `REPLICAS`         | `3`     | Number of concurrent gateway replicas. |
| `TIMEOUT_SECONDS`  | `600`   | How long to wait before declaring a hang. |
| `POLL_INTERVAL`    | `10`    | Log-sampling interval during the wait loop. |
| `IMAGE_LOCAL`      | `mcpgateway/mcpgateway:latest` | Gateway image under test. |

### What you'll see

- **Full hang** (matches reporter's OCP symptom): `reproduce.sh` exits `1`, one container shows `"Database ready"` in its log, the others end at `INFO  [alembic.runtime.migration] Will assume transactional DDL.`, and `pg_locks` has one granted advisory row plus many backends `idle in transaction` on `SELECT pg_try_advisory_lock(...)`.
- **Partial hang**: multiple workers inside each replica race; "lucky" workers finish and the pod reports healthy, but `pg_stat_activity` reveals several backends still wedged on the lock. This is the residue that poisons the next pod that starts.

Either observation confirms the mechanism. `demonstrate_orphan.sh` gives you the deterministic-every-time version of the same signal.

### Expected behavior after the fix lands

All N replicas log `Database ready` within the timeout, `pg_stat_activity` shows no backends stuck on `pg_try_advisory_lock`, and the script exits `0`.

## 3. Pinned regression test

```bash
# stack must be up first (postgres + pgbouncer are enough)
docker compose -f tests/integration/fixtures/transaction_pool/docker-compose.yml up -d postgres pgbouncer

# from repo root
uv run pytest tests/integration/test_migrations_under_transaction_pool.py -v --with-integration
```

Three assertions, each under one second:

- A disconnected PgBouncer client's advisory lock remains held on Postgres.
- A fresh Postgres session is blocked from acquiring the orphaned lock.
- A same-backend PgBouncer reuse *can* reacquire the lock (documents the reentrant-session gotcha so future readers aren't confused).

The test is marked `@pytest.mark.integration`; it's skipped by default unless `--with-integration` is passed. It keeps passing after the fix lands — it documents the PgBouncer behavior, not the bug itself.

## Tear down

```bash
docker compose -f tests/integration/fixtures/transaction_pool/docker-compose.yml down -v
```

## Host-exposed ports

So you can attach `psql` / `pgbouncer admin` from the host while the stack runs:

| Service   | Host port | In-network port |
|-----------|-----------|-----------------|
| postgres  | `54320`   | `5432`          |
| pgbouncer | `64320`   | `6432`          |

```bash
PGPASSWORD=reprosecret psql -h localhost -p 54320 -U postgres -d mcp   # direct to postgres
PGPASSWORD=reprosecret psql -h localhost -p 64320 -U postgres -d mcp   # through pgbouncer
PGPASSWORD=reprosecret psql -h localhost -p 64320 -U postgres -d pgbouncer -c 'SHOW pools;'   # pgbouncer admin
```

## Notes

- The stack deliberately omits Redis, the admin UI, plugins, federation, and A2A — they're not required to trigger the bug and would only add noise to the logs.
- `PgBouncer`'s `DEFAULT_POOL_SIZE` is set low (`2`) so total client connections comfortably exceed it; without multiplexing pressure the bug is hard to trigger locally because bootstrap can finish before any backend handoff happens.
- Production OCP/Helm deployments hit this reliably because real migrations take seconds to tens of seconds (plenty of handoff opportunities) and pool sizes are often sized for steady-state, not for migration bursts.
