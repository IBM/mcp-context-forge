# CONC-01 Gateways Manual Results (Working Notes)

Date: 2026-02-25
Scope:
- Endpoint: `POST /gateways`
- Goal: validate same-name parallel create behavior (`1 success`, `N-1 conflict`) and uniqueness
- Script: `tests/manual/concurrency/conc_01_gateways_parallel_create_pg_redis.py`

Environment notes:
- Local MCP translate endpoint running: `http://127.0.0.1:9000/sse`
- SSRF localhost/private overrides enabled for local testing
- Gateway app reachable at `http://127.0.0.1:8000`
- DB modes exercised:
  - SQLite (`mcp.db`) for early local runs
  - PostgreSQL + Redis (`postgresql+psycopg://.../concurrent_test`, `redis://127.0.0.1:6379`) for parent-scope validation

## Preflight checks

- `GET /health` -> `200`
- Token regenerated and validated against read endpoint (`GET /servers?limit=1` -> `200`)

## Manual gateway duplicate smoke (same payload twice)

Payload:
```json
{
  "name": "conc-gw-<ts>",
  "url": "http://127.0.0.1:9000/sse",
  "visibility": "public"
}
```

Observed:
- First create -> `200`
- Second create (same payload) -> `409` (`{"message":"Gateway name already exists"}`)

Verdict: baseline duplicate behavior works in sequential flow.

## Gateway script run 1 (initial matrix)

Command:
```bash
python tests/manual/concurrency/conc_01_gateways_parallel_create_pg_redis.py
```

Observed:
- `api_smoke_20`: all `409` (no success)
- `api_100`: all `409` (no success)
- `api_db_100`: timeouts (`ConnectTimeout`/`ReadTimeout`)

Interpretation:
- URL-level duplicate checks likely collided with prior runs (fixed later by appending run-unique query param).

## Gateway script run 2 (after run-unique URL fix)

Command:
```bash
python tests/manual/concurrency/conc_01_gateways_parallel_create_pg_redis.py
```

Observed:
- `api_smoke_20`: `API UNIQUENESS CHECK ERROR: ReadTimeout`
- `api_100`: `API UNIQUENESS CHECK ERROR: ReadTimeout`
- `api_db_100`: mostly `ConnectTimeout`/`ReadTimeout`

Interpretation:
- Under concurrency, gateway create path appears sensitive to upstream initialization latency/capacity.

## Controlled single-case run (higher timeout)

Command:
```bash
CONC_CASES=api_smoke_20 CONC_TIMEOUT_OVERRIDE=300 \
python tests/manual/concurrency/conc_01_gateways_parallel_create_pg_redis.py
```

Observed distribution:
- `200`: `1`
- `500`: `19`

Assertions:
- `success(200|201) == 1` -> pass
- `conflict(409) == 19` -> fail (got `0`)
- `api_unique_name_count(...) == 1` -> pass

Verdict:
- Concurrency acceptance (`1 success + N-1 conflict`) is **not met** for `/gateways` in current local setup.
- Current behavior shows `500` responses under contention instead of `409`.

## Current status

- Server-side CONC-01 script (`/servers`) is passing with API+DB checks.
- Gateway-side CONC-01 script reproduced contention failures on SQLite (timeouts/500).

## PostgreSQL + Redis validation run (parent-scope environment)

Command:
```bash
CONC_CASES=api_smoke_20 CONC_TIMEOUT_OVERRIDE=120 \
python tests/manual/concurrency/conc_01_gateways_parallel_create_pg_redis.py
```

Observed distribution:
- `200`: `20`
- `409`: `0`

Assertions:
- `success(200|201) == 1` -> fail (`20`)
- `conflict(409) == 19` -> fail (`0`)
- `api_unique_name_count(conc-gw-api_smoke_20-1772041688506) == 1` -> fail (`20`)

Interpretation:
- Under concurrent same-name gateway create, all requests succeeded and duplicate records were created.
- This does **not** satisfy CONC-01 acceptance criteria for `/gateways`.

## Conclusion

- CONC-01 appears **passing** for `/servers`.
- CONC-01 appears **failing** for `/gateways` in parent-scope environment (Postgres+Redis):
  - expected `1 success + N-1 conflict + no duplicates`
  - observed `N successes + duplicates`

## Possible technical reasoning

1. `NULL` behavior in Postgres unique constraints

- In SQL, `NULL` means "no value"/"unknown value" (not `''` and not `0`).
- In `Gateway`, `team_id` is nullable (`nullable=True`) and uniqueness is defined as:
  - `UniqueConstraint("team_id", "owner_email", "slug", name="uq_team_owner_slug_gateway")`
- Postgres treats `NULL` values as distinct in unique checks.
- Practical effect: rows with the same `owner_email + slug` can still coexist when `team_id` is `NULL` (global/public scope).
- This matches our observed duplicate rows for `team_id` shown as blank (`NULL`) in `psql`.

2. Concurrent gateway registration path adds instability under load

- For higher-concurrency cases (`api_100`, `api_db_100`), responses included a mix of `200`, `502`, and `ReadError`.
- This indicates create requests are not all resolving to conflict handling under contention and some requests fail along network/upstream initialization paths.
- Even with those failures, duplicates are still persisted (API and DB uniqueness counts > 1).

Verification query used:
```sql
SELECT team_id, owner_email, slug, COUNT(*) AS cnt
FROM gateways
WHERE name LIKE 'conc-gw-api_smoke_20-%'
GROUP BY team_id, owner_email, slug
ORDER BY cnt DESC;
```

## Code references supporting this hypothesis

Gateway schema and constraints:
- `mcpgateway/db.py:4355` → `Gateway` maps to `gateways`.
- `mcpgateway/db.py:4357` → primary key on `id`.
- `mcpgateway/db.py:4426` → `team_id` is nullable (`nullable=True`).
- `mcpgateway/db.py:4427` → `owner_email` field used in tenant/user scoping.
- `mcpgateway/db.py:4359` → `slug` field.
- `mcpgateway/db.py:4466` → unique key is `("team_id", "owner_email", "slug")`.

Slug identity path:
- `mcpgateway/db.py:6179` / `mcpgateway/db.py:6189` → `before_insert` listener sets `slug = slugify(name)`.
- `mcpgateway/services/gateway_service.py:728` → service computes `slug_name = slugify(gateway.name)` before create checks.

Create path + conflict handling:
- `mcpgateway/services/gateway_service.py:731`-`mcpgateway/services/gateway_service.py:735` → pre-check for existing public gateway by slug.
- `mcpgateway/services/gateway_service.py:740`-`mcpgateway/services/gateway_service.py:744` → team-scoped pre-check by slug/team.
- `mcpgateway/services/gateway_service.py:1065`-`mcpgateway/services/gateway_service.py:1091` → gateway insert model includes `team_id`, `owner_email`, `visibility`.
- `mcpgateway/services/gateway_service.py:1100`-`mcpgateway/services/gateway_service.py:1102` → `db.add` + `db.flush`.
- `mcpgateway/main.py:5469`-`mcpgateway/main.py:5472` → conflict exceptions map to `409`.
- `mcpgateway/main.py:5477`-`mcpgateway/main.py:5478` → `IntegrityError` maps to `409`.

Locking helper used by pre-check:
- `mcpgateway/db.py:5473` (`get_for_update`) and `mcpgateway/db.py:5543` (`FOR UPDATE` on PostgreSQL).

Migration intent (constraint shape):
- `mcpgateway/alembic/versions/e182847d89e6_unique_constraints_changes_for_gateways_.py:41` and `mcpgateway/alembic/versions/e182847d89e6_unique_constraints_changes_for_gateways_.py:87`-`mcpgateway/alembic/versions/e182847d89e6_unique_constraints_changes_for_gateways_.py:88` show the gateway unique constraint composed from `team_id`, `owner_email`, and `slug`.

SSRF validation context (why localhost overrides were needed in local runs):
- `mcpgateway/schemas.py:2607` calls URL validator for gateway create.
- `mcpgateway/common/validators.py:1246`-`mcpgateway/common/validators.py:1248` localhost blocking logic.
- `mcpgateway/common/validators.py:1251`-`mcpgateway/common/validators.py:1266` private-network blocking logic.
- `mcpgateway/config.py:416` and `mcpgateway/config.py:422` configure `SSRF_ALLOW_LOCALHOST` and `SSRF_ALLOW_PRIVATE_NETWORKS`.

## Repeatability proof (Postgres)

DB query:
```bash
psql "postgresql://postgres:postgres@127.0.0.1:5432/concurrent_test" -c \
"SELECT name, COUNT(*) AS cnt FROM gateways WHERE name LIKE 'conc-gw-api_smoke_20-%' GROUP BY name ORDER BY name DESC LIMIT 2;"
```

Observed:
- `conc-gw-api_smoke_20-1772042731271` -> `cnt=20`
- `conc-gw-api_smoke_20-1772042640357` -> `cnt=20`

Interpretation:
- Duplicate creation under concurrent same-name gateway create is reproducible across runs.

## Postgres + Redis execution steps (what we ran)

1. Started local container runtime (`colima`) and verified Docker was healthy.
2. Started Postgres and Redis containers:
   - `conc-postgres` on `:5432`
   - `conc-redis` on `:6379`
3. Switched gateway app runtime to Postgres + Redis:
   - `DATABASE_URL=postgresql+psycopg://postgres:postgres@127.0.0.1:5432/concurrent_test`
   - `REDIS_URL=redis://127.0.0.1:6379`
4. Enabled local gateway URL testing for SSRF-protected validation:
   - `SSRF_ALLOW_LOCALHOST=true`
   - `SSRF_ALLOW_PRIVATE_NETWORKS=true`
5. Installed Postgres driver in venv:
   - `uv pip install "psycopg[binary]"`
6. Restarted gateway with `make dev` and confirmed readiness via `GET /health -> 200`.
7. Regenerated bearer token for the test shell.
8. Ran controlled gateway concurrency case:
   - `CONC_CASES=api_smoke_20 CONC_TIMEOUT_OVERRIDE=120 python tests/manual/concurrency/conc_01_gateways_parallel_create_pg_redis.py`
9. Observed API result:
   - `200: 20`, `409: 0`, `api_unique_name_count(...)=20`
10. Verified duplicates directly in Postgres via `psql`:
   - `COUNT(*) = 20` for the same gateway name.
11. Rechecked latest runs and again saw `cnt=20`, confirming repeatability.

## Rerun steps (setup already running)

Assumes:
- Gateway app is already running via `make dev` with Postgres + Redis env.
- MCP translate endpoint is already reachable at `http://127.0.0.1:9000/sse`.
- Postgres/Redis containers are already up.

Preferred one-command rerun:
```bash
make conc-01-gateways
```

Optional overrides for one-command rerun:
```bash
CONC_CASES=api_smoke_20 CONC_TIMEOUT_OVERRIDE=120 make conc-01-gateways
CONC_CASES=api_100 CONC_TIMEOUT_OVERRIDE=180 make conc-01-gateways
CONC_REFRESH_TOKEN=1 make conc-01-gateways
```

What `make conc-01-gateways` automates:
- sets default `DATABASE_URL`/`REDIS_URL` (if not already set)
- generates `CONC_TOKEN` using `JWT_SECRET_KEY` (unless already set)
- runs preflight checks (`/health`, auth check, translator TCP check)
- runs `tests/manual/concurrency/conc_01_gateways_parallel_create_pg_redis.py`

Manual equivalent:

1. Open a fresh terminal, activate venv, and export test env:
```bash
cd /Users/pratik/Desktop/work/mcf/mcp-context-forge
. /Users/pratik/.venv/mcpgateway/bin/activate
export DATABASE_URL="postgresql+psycopg://postgres:postgres@127.0.0.1:5432/concurrent_test"
export REDIS_URL="redis://127.0.0.1:6379"
export CONC_TOKEN="$(
  python -m mcpgateway.utils.create_jwt_token \
    --username admin@example.com \
    --exp 120 \
    --secret "$JWT_SECRET_KEY"
)"
```

2. Quick sanity checks:
```bash
curl -sS -i http://127.0.0.1:8000/health
curl -sS -i "http://127.0.0.1:8000/servers?limit=1" -H "Authorization: Bearer $CONC_TOKEN"
```

3. Run controlled gateway concurrency case (smoke):
```bash
CONC_CASES=api_smoke_20 CONC_TIMEOUT_OVERRIDE=120 \
python tests/manual/concurrency/conc_01_gateways_parallel_create_pg_redis.py
```

4. Verify duplicate counts in Postgres:
```bash
psql "postgresql://postgres:postgres@127.0.0.1:5432/concurrent_test" -c \
"SELECT name, COUNT(*) AS cnt FROM gateways WHERE name LIKE 'conc-gw-api_smoke_20-%' GROUP BY name ORDER BY name DESC LIMIT 3;"
```

5. Optional scale-up run:
```bash
CONC_CASES=api_100 CONC_TIMEOUT_OVERRIDE=180 \
python tests/manual/concurrency/conc_01_gateways_parallel_create_pg_redis.py
```
