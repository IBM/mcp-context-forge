# Prompt: Investigate and Fix Locust Load Test Failures

Investigate and fix all Locust load test failures in `tests/loadtest/locustfile.py` against the platform running via `docker-compose.yml` on `localhost:8080` (nginx → gateway).

## Running Services

- Platform: `localhost:8080` (nginx → gateway:4444, via `docker-compose.yml`)
- Locust UI: `localhost:8089` (`make load-test-ui`)

## Key Files

- `tests/loadtest/locustfile.py` — ~3660 lines, 30+ User classes, all `@task` methods
- `mcpgateway/routers/*.py` — 19 router files defining all REST endpoints
- `infra/nginx/nginx.conf` — nginx reverse proxy config (timeouts: 60s default, 5s for health)
- `docker-compose.yml` — service topology, env vars, gunicorn timeouts (120s)
- OpenAPI spec: `GET /openapi.json` (or browse `http://localhost:8080/docs`)

## How to Check Current Failures

Locust stats JSON (extract errors):

```bash
curl -s http://localhost:8089/stats/requests | python3 -c "
import sys,json; data=json.load(sys.stdin)
[print(f'[{e[\"occurrences\"]}x] {e[\"method\"]} {e[\"name\"]}: {e[\"error\"][:120]}') for e in data.get('errors',[])]
"
```

Locust failures CSV (endpoints with failures > 0):

```bash
curl -s http://localhost:8089/stats/requests/csv | awk -F',' '$4 > 0 {printf "%-6s %-55s reqs=%-6s fails=%s\n", $1, $2, $3, $4}'
```

Reset stats between runs via the Locust UI "Reset Stats" button at `http://localhost:8089`.

## How to Manually Test Endpoints (curl against localhost:8080)

```bash
# Generate admin JWT (teams:null + is_admin:true for full access)
export JWT=$(python3 -c "
import jwt, datetime, uuid
payload = {'sub':'admin@example.com',
  'exp':datetime.datetime.now(datetime.timezone.utc)+datetime.timedelta(hours=1),
  'iat':datetime.datetime.now(datetime.timezone.utc),
  'aud':'mcpgateway-api','iss':'mcpgateway',
  'jti':str(uuid.uuid4()),'teams':None,'is_admin':True}
print(jwt.encode(payload, 'my-test-key', algorithm='HS256'))")
AUTH="Authorization: Bearer $JWT"

# Test any REST endpoint
curl -s -w "\nHTTP %{http_code} in %{time_total}s\n" \
  -H "$AUTH" -H "Accept: application/json" http://localhost:8080/tools

# Test a POST endpoint
curl -s -w "\nHTTP %{http_code} in %{time_total}s\n" \
  -X POST http://localhost:8080/teams/ \
  -H "$AUTH" -H "Content-Type: application/json" \
  -d '{"name":"test-team","description":"test","visibility":"private"}'

# Test a JSON-RPC call
curl -s -w "\nHTTP %{http_code} in %{time_total}s\n" \
  -X POST http://localhost:8080/rpc \
  -H "$AUTH" -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":"1","method":"tools/list","params":{}}'

# Check gateway logs for server-side errors
docker compose logs gateway --tail=100 | grep -i error
```

## Known Failure Patterns

### 1. 502 Bad Gateway (~80% of failures)

Affects most `/rpc` calls, toggles, creates. Intermittent — caused by upstream gateway overload under high concurrency (nginx → gunicorn). Confirm each manually with curl at low load. If the endpoint works at low load, these are infrastructure-level and the locustfile should tolerate 502 under stress (add to `allowed_codes` or mark as expected under load).

### 2. Timeouts / Connection Drops (`PUT /resources/[id] [update]` — ~5% fail rate)

`CatchResponseError got 0` means the connection was dropped. `EntityUpdateUser.update_resource()` does GET → sleep(50ms) → PUT. Under load, the resource version changes between GET and PUT (optimistic locking conflict). Confirm with curl: send a PUT with a stale `version` field and expect 409. Fix: handle 409 (conflict), consider retry logic, or add 500 to allowed codes.

### 3. Timeouts (`POST /teams/ [create]` — ~11% fail rate)

`RetriesExceeded: timed out`. The endpoint takes 58+ seconds and hits nginx's 60s `proxy_read_timeout`, returning 504. Fix options: increase `connection_timeout`/`network_timeout` for `TeamsCRUDUser`, add 504/502 to allowed codes, or investigate server-side slowness via `docker compose logs gateway`.

### 4. 500 Internal Server Error (sporadic)

Affects `PUT /resources/[id] [update]`, `GET /api/metrics/stats`. Server-side bugs. Reproduce with curl, check gateway logs: `docker compose logs gateway --tail=200 | grep -i "500\|traceback\|error"`.

## Steps

1. **Reproduce each failure** — For every error in the locust stats, reproduce with curl against `localhost:8080` to confirm root cause (bad payload, missing field, server bug, timeout, etc.)
2. **Check server logs** — `docker compose logs gateway --tail=200` to find tracebacks matching the failures
3. **Fix `locustfile.py`** — Add missing status codes to `allowed_codes`, adjust timeouts, fix payloads, add retry logic where appropriate
4. **Verify** — Restart locust (`make load-test-ui`), run a short test (10 users, 30s via `make load-test-light`), confirm 0 failures
5. **Iterate** — Increase load progressively and fix any new failures that appear only at scale

Do **not** add new endpoint coverage yet — focus entirely on making all existing tasks pass with 0 failures first.
