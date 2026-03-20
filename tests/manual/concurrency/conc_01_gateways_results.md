# CONC-01 Gateway Parallel Create: Runbook + Results

Date: 2026-03-02
Ticket scope: CONC-01 for gateway endpoint (`POST /gateways`)
Out of scope: server endpoint results

## Objective

Validate CONC-01 acceptance for gateway create under concurrency:

- 100 parallel creates with same name
- Expected: exactly 1 success, 99 conflicts (`409`)
- No duplicates persisted (API and DB uniqueness count must be `1`)

## Environment used

- Gateway app: `http://127.0.0.1:8000`
- Translate endpoint: `http://127.0.0.1:9000/sse`
- DB/Cache: PostgreSQL + Redis
- Runner command: `make conc-01-gateways`
- Test script: `tests/manual/concurrency/conc_01_gateways_parallel_create_pg_redis.py`
- Local SSRF test overrides required when using localhost translator:
  - `SSRF_ALLOW_LOCALHOST=true`
  - `SSRF_ALLOW_PRIVATE_NETWORKS=true`

## Steps to run (copy/paste)

Note for reviewers:
- The commands below were executed on macOS with Colima.
- On Linux, run equivalent Docker runtime/container startup commands for Postgres and Redis.

### 1) Start Postgres + Redis in Docker

```bash
colima start
docker context use colima

docker rm -f conc-postgres conc-redis 2>/dev/null || true

docker run -d --name conc-postgres -p 5432:5432 \
  -e POSTGRES_USER=postgres \
  -e POSTGRES_PASSWORD=postgres \
  -e POSTGRES_DB=concurrent_test \
  postgres:16

docker run -d --name conc-redis -p 6379:6379 redis:7

docker ps --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}' | rg 'conc-postgres|conc-redis'
```

### 2) Terminal A: start gateway (Postgres + Redis + local SSRF overrides)

```bash
cd <repo-root>
pkill -f "mcpgateway.main|uvicorn" || true

DATABASE_URL='postgresql+psycopg://postgres:postgres@127.0.0.1:5432/concurrent_test' \
REDIS_URL='redis://127.0.0.1:6379/0' \
CACHE_TYPE='redis' \
JWT_SECRET_KEY='my-test-key' \
SSRF_ALLOW_LOCALHOST=true \
SSRF_ALLOW_PRIVATE_NETWORKS=true \
make dev
```

### 3) Terminal B: start translator

```bash
cd <repo-root>
python -m mcpgateway.translate --stdio "uvx mcp-server-git" --port 9000
```

### 4) Terminal C: generate token and run matrix

```bash
cd <repo-root>
export CONC_TOKEN="$(python3 -m mcpgateway.utils.create_jwt_token --username admin@example.com --exp 120 --secret my-test-key)"
make conc-01-gateways
```

### 5) Optional sanity checks

```bash
curl -sS --max-time 5 -o /dev/null -w "servers=%{http_code}\n" -H "Authorization: Bearer $CONC_TOKEN" "http://127.0.0.1:8000/servers?limit=1"
curl -sS --max-time 5 -o /dev/null -w "health=%{http_code}\n" "http://127.0.0.1:8000/health"
```

Expected: both return `200`.

## Expected vs observed

| Case | Expected | Observed (latest run) |
|------|----------|-----------------------|
| `api_smoke_20` | `1x 200/201`, `19x 409`, uniqueness=1 | `200=20`, `409=0`, API uniqueness=`20` |
| `api_100` | `1x 200/201`, `99x 409`, uniqueness=1 | `200=49`, `500=3`, `502=32`, `ReadError=16`, `409=0`, API uniqueness=`49` |
| `api_db_100` | same as above + DB uniqueness=1 | `200=42`, `502=37`, `ReadError=21`, `409=0`, API uniqueness=`42`, DB uniqueness=`42` |

## Latest matrix output snapshot (2026-03-02)

- `api_smoke_20`:
  - `success(200|201) == 1 -> 20`
  - `conflict(409) == 19 -> 0`
  - `api_unique_name_count(...) == 1 -> 20`
- `api_100`:
  - `success(200|201) == 1 -> 49`
  - `conflict(409) == 99 -> 0`
  - `api_unique_name_count(...) == 1 -> 49`
- `api_db_100`:
  - `success(200|201) == 1 -> 42`
  - `conflict(409) == 99 -> 0`
  - `api_unique_name_count(...) == 1 -> 42`
  - `db_unique_name_count(...) == 1 -> 42`

Result: all 3 cases fail CONC-01 acceptance criteria for `/gateways`.

## Database proof (duplicates)

```bash
psql "postgresql://postgres:postgres@127.0.0.1:5432/concurrent_test" -c \
"SELECT name, COUNT(*) AS cnt FROM gateways WHERE name LIKE 'conc-gw-api_smoke_20-%' GROUP BY name ORDER BY name DESC LIMIT 5;"
```

Constraint-focused grouping:

```bash
psql "postgresql://postgres:postgres@127.0.0.1:5432/concurrent_test" -c \
"SELECT team_id, owner_email, slug, COUNT(*) AS cnt FROM gateways WHERE name LIKE 'conc-gw-api_smoke_20-%' GROUP BY team_id, owner_email, slug ORDER BY cnt DESC LIMIT 20;"
```

Observed pattern:

- `team_id` appears `NULL` (blank in `psql` output)
- Same `owner_email + slug` groups can appear with high counts (for example `cnt=20`)

## Code references

- Gateway schema/constraint:
  - `mcpgateway/db.py:4426` (`team_id` nullable)
  - `mcpgateway/db.py:4466` (`UniqueConstraint(team_id, owner_email, slug)`)
- Slug derivation:
  - `mcpgateway/db.py:6179`
  - `mcpgateway/db.py:6189`
- Gateway create path:
  - `mcpgateway/services/gateway_service.py:728`
  - `mcpgateway/services/gateway_service.py:731`
  - `mcpgateway/services/gateway_service.py:1065`
  - `mcpgateway/services/gateway_service.py:1100`
- HTTP conflict mapping:
  - `mcpgateway/main.py:5469`
  - `mcpgateway/main.py:5477`

## Interpretation (non-fix)

This artifact captures reproducible evidence that current `/gateways` behavior does not meet CONC-01 acceptance in this setup:

- Expected conflict pattern (`1 success + N-1 conflicts`) is not observed.
- Duplicate rows are persisted for same-name concurrent creates.

This PR does not change gateway behavior; it adds reproducible CONC-01 gateway test coverage and evidence.
