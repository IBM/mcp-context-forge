# Prompt: Achieve 100% Locust Coverage of All REST API Endpoints

Systematically extend `tests/loadtest/locustfile.py` to cover every REST API endpoint exposed by the platform. The goal is 100% endpoint coverage — every method+path in the OpenAPI spec has a corresponding `@task` in at least one Locust User class.

**Prerequisite:** All existing tests must pass with 0 failures first. See `llms/prompts/locust-fix-failures.md`.

## Running Services

- Platform: `localhost:8080` (nginx → gateway:4444, via `docker-compose.yml`)
- Locust UI: `localhost:8089` (`make load-test-ui`)

## Key Files

- `tests/loadtest/locustfile.py` — Main locust test file (~3660 lines, 30+ User classes)
- `mcpgateway/routers/*.py` — 19 router files defining all REST endpoints
- `infra/nginx/nginx.conf` — nginx reverse proxy (timeouts, routing)
- `docker-compose.yml` — service topology, env vars
- OpenAPI spec: `GET http://localhost:8080/openapi.json`

## Step 1: Generate the Coverage Map

Extract every endpoint from the OpenAPI spec and cross-reference with existing locust tasks:

```bash
# Get all API endpoints (method + path)
curl -s http://localhost:8080/openapi.json | python3 -c "
import sys, json
spec = json.load(sys.stdin)
for path in sorted(spec.get('paths', {}).keys()):
    methods = [m.upper() for m in spec['paths'][path].keys() if m in ('get','post','put','delete','patch')]
    for m in methods:
        print(f'{m:7s} {path}')
"

# Get all endpoints currently tested in locustfile (grep for URL patterns)
grep -oP '(?:self\.client\.(get|post|put|delete|patch))\(\s*[f"]([^"]+)"' \
  tests/loadtest/locustfile.py | sort -u
```

Compare the two lists. Any endpoint in the OpenAPI spec but not in the locustfile is a coverage gap.

## Step 2: Categorize Endpoints by Router Group

The API has 399 endpoints across these groups (by count):

| Group | Endpoints | Router File |
|---|---|---|
| `/admin/*` | ~200 | Various (HTMX admin UI) |
| `/teams/*` | 18 | `routers/teams.py` |
| `/servers/*` | 15 | `main.py` (core) |
| `/llm/*` | 14 | `routers/llm_admin_router.py`, `llm_proxy_router.py` |
| `/rbac/*` | 13 | `routers/rbac.py` |
| `/auth/*` | 12 | `routers/auth.py`, `routers/email_auth.py` |
| `/resources/*` | 12 | `main.py` (core) |
| `/a2a/*` | 10 | `main.py` (core) |
| `/gateways/*` | 10 | `main.py` (core) |
| `/prompts/*` | 10 | `main.py` (core) |
| `/tokens/*` | 10 | `routers/tokens.py` |
| `/api/logs/*` | 5 | `routers/log_search.py` |
| `/api/metrics/*` | 4 | `routers/metrics_maintenance.py` |
| `/tools/*` | 9 | `main.py` (core) |
| `/oauth/*` | 7 | `routers/oauth_router.py` |
| `/llmchat/*` | 6 | `routers/llmchat_router.py` |
| `/roots/*` | 6 | `main.py` (core) |
| `/protocol/*` | 5 | `main.py` (core) |
| `/import/*` | 4 | `main.py` (core) |
| `/reverse-proxy/*` | 4 | `routers/reverse_proxy.py` |
| `/metrics/*` | 3 | `main.py` (core) |
| `/tags/*` | 3 | `main.py` (core) |
| `/cancellation/*` | 2 | `routers/cancellation_router.py` |
| `/export/*` | 2 | `main.py` (core) |
| `/v1/*` | 2 | `routers/llm_proxy_router.py` |
| Other singletons | ~10 | `/health`, `/ready`, `/version`, `/sse`, etc. |

## Step 3: Manually Test New Endpoints Before Writing Locust Tasks

For every uncovered endpoint, manually test with curl first to understand the expected request/response:

```bash
# Generate admin JWT
export JWT=$(python3 -c "
import jwt, datetime, uuid
payload = {'sub':'admin@example.com',
  'exp':datetime.datetime.now(datetime.timezone.utc)+datetime.timedelta(hours=1),
  'iat':datetime.datetime.now(datetime.timezone.utc),
  'aud':'mcpgateway-api','iss':'mcpgateway',
  'jti':str(uuid.uuid4()),'teams':None,'is_admin':True}
print(jwt.encode(payload, 'my-test-key', algorithm='HS256'))")
AUTH="Authorization: Bearer $JWT"

# Example: test an uncovered endpoint
curl -s -w "\nHTTP %{http_code}\n" -H "$AUTH" http://localhost:8080/version
curl -s -w "\nHTTP %{http_code}\n" -H "$AUTH" http://localhost:8080/tags
curl -s -w "\nHTTP %{http_code}\n" -H "$AUTH" -X POST http://localhost:8080/logging/setLevel \
  -H "Content-Type: application/json" -d '{"level":"INFO"}'

# For admin HTMX endpoints, use Accept: text/html
curl -s -w "\nHTTP %{http_code}\n" -H "$AUTH" -H "Accept: text/html" http://localhost:8080/admin/plugins
```

Document the required headers, payload shape, and expected status codes for each endpoint before adding it to the locustfile.

## Step 4: Add Missing Coverage Systematically

Follow the existing patterns in `locustfile.py`:

- **One User class per logical group** (e.g., `LLMProviderUser`, `ServerWellKnownUser`)
- **Use `@tag` decorators** for filtering (e.g., `@tag("llm", "read")`)
- **Use `catch_response=True`** with `_validate_json_response()` or `_validate_html_response()`
- **Include realistic `allowed_codes`** — don't just allow 200; include 401, 403, 404, 409, 422 where appropriate
- **CRUD operations** should create → read → update → delete in a single task method to avoid orphaned test data
- **Weight classes appropriately** — read-heavy users get higher weight, write/admin users get weight=1
- **Clean up test data** in `on_stop()` method

### Endpoint categories to handle differently:

| Type | Pattern | Approach |
|---|---|---|
| **Read-only GET** | `/version`, `/tags`, `/health/security` | Simple GET, validate JSON/status |
| **Admin HTMX pages** | `/admin/*` | GET with `Accept: text/html`, use `_validate_html_response()` |
| **CRUD lifecycle** | POST→GET→PUT→DELETE | Single task does full lifecycle, cleans up |
| **JSON-RPC** | `POST /rpc` | Use `_json_rpc_request()` helper, validate with `_validate_jsonrpc_response()` |
| **SSE/streaming** | `/sse`, `/servers/{id}/sse` | Skip or test connection-only (no streaming load test) |
| **OAuth flows** | `/oauth/authorize/*`, `/oauth/callback` | May require browser redirects — test what's possible via API |
| **File operations** | `/admin/logs/export`, `/admin/support-bundle/*` | GET with appropriate timeout |

## Step 5: Verify Coverage

After adding tasks, re-run the coverage map from Step 1 and confirm every endpoint has a corresponding task. Then:

```bash
# Light test to verify no failures
make load-test-light   # 10 users, 30s

# Check failures
curl -s http://localhost:8089/stats/requests/csv | awk -F',' '$4 > 0'

# Full test
make load-test-ui      # Start UI, configure desired load, run
```

## Step 6: Create Coverage Tracking Document

Create `todo/locust-coverage.md` with:

1. Full endpoint list grouped by router
2. Coverage status for each (covered / not covered / skipped with reason)
3. Which User class covers each endpoint
4. Any endpoints intentionally skipped (SSE streaming, OAuth browser flows, etc.) with justification

## Priority Order for Adding Coverage

1. **Core REST API** — `/tools`, `/servers`, `/gateways`, `/resources`, `/prompts`, `/roots` (CRUD + state + toggle)
2. **Auth & RBAC** — `/auth/*`, `/rbac/*`, `/tokens/*`, `/teams/*`
3. **Observability** — `/api/logs/*`, `/api/metrics/*`, `/metrics/*`
4. **LLM & Chat** — `/llm/*`, `/llmchat/*`, `/v1/*`
5. **Admin UI pages** — `/admin/*` (HTMX, lower priority but high endpoint count)
6. **Specialized** — `/oauth/*`, `/reverse-proxy/*`, `/cancellation/*`, `/protocol/*`
7. **Singletons** — `/version`, `/tags`, `/export`, `/import`, `/sse`, `/.well-known/*`
