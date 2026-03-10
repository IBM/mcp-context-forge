# CONC-02 Gateway Read-During-Write: Runbook + Results

Date: 2026-03-02  
Ticket scope: CONC-02 for gateway endpoint (`GET/PUT /gateways/{id}`)  
Out of scope: CONC-01 create race, cache/session/leader-election scenarios

## Objective

Validate CONC-02 acceptance for gateway read consistency during concurrent writes:

- Create one baseline gateway
- Run concurrent writer(s) updating the same gateway
- Run concurrent reader(s) fetching the same gateway
- Ensure no malformed/partial reads and no 5xx responses

## Environment used

- Gateway app: `http://127.0.0.1:8000`
- Translate endpoint: `http://127.0.0.1:9000/sse`
- DB/Cache: PostgreSQL + Redis
- Runner command: `make conc-02-gateways`
- Test script: `tests/manual/concurrency/conc_02_gateways_read_during_write.py`
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

### 2) Terminal A: start gateway

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

### 4) Terminal C: generate token and run CONC-02

```bash
cd <repo-root>
export CONC_TOKEN="$(python3 -m mcpgateway.utils.create_jwt_token --username admin@example.com --exp 120 --secret my-test-key)"
make conc-02-gateways
```

### 5) Optional sanity checks

```bash
curl -sS --max-time 5 -o /dev/null -w "health=%{http_code}\n" http://127.0.0.1:8000/health
curl -sS --max-time 5 -o /dev/null -w "servers=%{http_code}\n" -H "Authorization: Bearer $CONC_TOKEN" "http://127.0.0.1:8000/servers?limit=1"
```

Expected: both return `200`.

### 6) Optional custom run controls

```bash
CONC_RW_DURATION_SEC=30 CONC_RW_READERS=10 CONC_RW_WRITERS=2 make conc-02-gateways
```

## Expected vs observed

| Check | Expected | Observed (latest stable run) |
|------|----------|-------------------------------|
| Write path status | no 5xx | `200: 169`, `write_5xx=0` |
| Read path status | no 5xx | `200: 339`, `read_5xx=0` |
| Payload quality | malformed payloads = 0 | `malformed_read_payloads=0` |
| Final read status | `200` | `200` |
| Final payload validity | `True` | `True (ok)` |

## Latest run evidence (PASS)

Command:

```bash
CONC_RW_TIMEOUT_SEC=90 CONC_RW_DURATION_SEC=10 CONC_RW_READERS=1 CONC_RW_WRITERS=1 make conc-02-gateways
```

```text
Status/Error distribution:
Write path (PUT /gateways/{id}):
  200: 169
Read path (GET /gateways/{id}):
  200: 339

Assertions:
  write_5xx == 0 -> 0
  read_5xx == 0 -> 0
  malformed_read_payloads == 0 -> 0
  final_read_status == 200 -> 200
  final_payload_valid == True -> True (ok)

PASS: CONC-02 read-during-write consistency checks passed.
```

## Final statement

- PASS/FAIL: PASS (for `CONC_RW_TIMEOUT_SEC=90`, `CONC_RW_DURATION_SEC=10`, `CONC_RW_READERS=1`, `CONC_RW_WRITERS=1`)
- Notes:
  - This is intentionally a manual test flow for now, to keep reproduction straightforward and explicit.
  - If we need to run this more frequently, we can later extend `tests/manual/concurrency/run_conc_02_gateways.sh` to automate more setup steps.
