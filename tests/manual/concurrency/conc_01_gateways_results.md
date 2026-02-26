# CONC-01 Gateway Parallel Create Results

Date: 2026-02-26
Ticket scope: CONC-01 for gateway endpoint (`POST /gateways`)
Out of scope: server endpoint results

## Objective
Validate CONC-01 acceptance for gateway create under concurrency:
- 100 parallel creates with same name
- Expected: exactly 1 success, 99 conflicts (`409`), no duplicates persisted

## Test setup used
- Gateway app: `http://127.0.0.1:8000`
- Translate endpoint: `http://127.0.0.1:9000/sse`
- DB/Cache: PostgreSQL + Redis
- Runner: `make conc-01-gateways`
- Script: `tests/manual/concurrency/conc_01_gateways_parallel_create_pg_redis.py`

## Repro commands
One-command matrix:
```bash
make conc-01-gateways
```

Focused smoke rerun:
```bash
CONC_CASES=api_smoke_20 CONC_TIMEOUT_OVERRIDE=120 make conc-01-gateways
```

## Expected vs observed

| Case | Expected | Observed |
|------|----------|----------|
| `api_smoke_20` | `1x 200/201`, `19x 409`, uniqueness=1 | `20x 200`, `0x 409`, uniqueness=20 |
| `api_100` | `1x 200/201`, `99x 409`, uniqueness=1 | mixed (`200`, `500/502`, `ReadError`), `0x 409`, uniqueness > 1 |
| `api_db_100` | same as above + DB uniqueness=1 | mixed (`200`, `500/502`, `ReadError`), `0x 409`, API/DB uniqueness > 1 |

Latest full-matrix evidence snapshot:
- `api_smoke_20`: `200=20`, `409=0`, API uniqueness `20`
- `api_100`: `200=56`, `502=32`, `ReadError=12`, API uniqueness `50`
- `api_db_100`: `200=46`, `502=46`, `ReadError=8`, API uniqueness `46`, DB uniqueness `46`

## Database proof (duplicates)
Grouped duplicate count by run name:
```bash
psql "postgresql://postgres:postgres@127.0.0.1:5432/concurrent_test" -c \
"SELECT name, COUNT(*) AS cnt FROM gateways WHERE name LIKE 'conc-gw-api_smoke_20-%' GROUP BY name ORDER BY name DESC;"
```

Sample observed output:
- `conc-gw-api_smoke_20-1772112068765 | 20`
- `conc-gw-api_smoke_20-1772107637078 | 20`
- `conc-gw-api_smoke_20-1772107480373 | 20`

Constraint-focused check:
```bash
psql "postgresql://postgres:postgres@127.0.0.1:5432/concurrent_test" -c \
"SELECT team_id, owner_email, slug, COUNT(*) AS cnt FROM gateways WHERE name LIKE 'conc-gw-api_smoke_20-%' GROUP BY team_id, owner_email, slug ORDER BY cnt DESC;"
```

Observed pattern:
- `team_id` is `NULL` (blank in `psql` output)
- same `owner_email` + same `slug` groups appear with `cnt=20`

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
This test artifact captures reproducible evidence that current `/gateways` behavior does not meet CONC-01 acceptance in this setup:
- Expected conflict pattern (`1 success + N-1 conflicts`) is not observed.
- Duplicate rows are persisted for same-name concurrent creates.

This PR does not change gateway behavior; it adds reproducible CONC-01 gateway test coverage and evidence.
