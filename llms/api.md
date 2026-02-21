API: Quick Usage & Testing Guide

- Purpose: Help LLMs and scripts call ContextForge API reliably with correct auth, payloads, and common flows.
- Base URL: `http://localhost:4444` (production via `make serve`), or `http://127.0.0.1:8000` (dev via `make dev`).
- OpenAPI spec: Available at `/openapi.json` when server is running
- Swagger UI: Available at `/docs` when server is running (requires auth)

**Authentication**
- Scheme: HTTP Bearer (JWT). Prefer the `Authorization` header over cookies.
- Generate a short‑lived token and export it:
  ```bash
  export MCPGATEWAY_BEARER_TOKEN=$(python -m mcpgateway.utils.create_jwt_token \
    --username admin@example.com --exp 60 --secret KEY | tr -d '\n')
  ```
- Use in requests:
  - Header: `Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN`
  - Many endpoints also accept an optional `jwt_token` cookie parameter, but the header is preferred.

**Token Scoping (affects what resources you can see)**

- The `teams` claim in your JWT determines resource visibility:
  - No `teams` key → PUBLIC-ONLY (secure default, can only see `visibility=public` resources)
  - `teams: null` + `is_admin: true` → ADMIN BYPASS (see all resources)
  - `teams: []` → PUBLIC-ONLY (even for admins)
  - `teams: ["team-uuid"]` → Team + Public resources
- Generate team-scoped token:
  ```bash
  export MCPGATEWAY_BEARER_TOKEN=$(python -m mcpgateway.utils.create_jwt_token \
    --username user@example.com --exp 60 --secret KEY --teams '["team-uuid"]' | tr -d '\n')
  ```
- Generate public-only token (for automation):
  ```bash
  export MCPGATEWAY_BEARER_TOKEN=$(python -m mcpgateway.utils.create_jwt_token \
    --username ci@example.com --exp 60 --secret KEY --teams '[]' | tr -d '\n')
  ```
- Full documentation: `docs/docs/manage/rbac.md`

**Health & Metadata**
- Health: `GET /health` (no auth) — returns basic health status.
  ```bash
  curl -s http://localhost:4444/health | jq
  ```
- Readiness: `GET /ready` (no auth)
  ```bash
  curl -s http://localhost:4444/ready | jq
  ```
- Version/diagnostics (auth): `GET /version`
  ```bash
  curl -s -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN" \
       http://localhost:4444/version | jq
  ```

**Servers**
- List servers:
  ```bash
  curl -s -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN" \
       "http://localhost:4444/servers?include_inactive=false" | jq
  ```
- Create server:
  ```bash
  curl -s -X POST -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN" \
       -H "Content-Type: application/json" \
       -d '{
             "server": {
               "name": "fast-time",
               "description": "Demo server",
               "tags": ["demo"]
             },
             "visibility": "private"
           }' \
       http://localhost:4444/servers | jq
  ```
- Get server details:
  ```bash
  curl -s -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN" \
       http://localhost:4444/servers/<server_id> | jq
  ```
- Server tools list:
  ```bash
  curl -s -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN" \
       http://localhost:4444/servers/<server_id>/tools | jq
  ```

**JSON‑RPC Tool Calls**
- Endpoint: `POST /rpc` (auth). Body is JSON‑RPC 2.0.
- Example calling a tool named `fast-time-git-status`:
  ```bash
  curl -s -X POST -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN" \
       -H "Content-Type: application/json" \
       -d '{
             "jsonrpc": "2.0",
             "id": 1,
             "method": "fast-time-git-status",
             "params": {"repo_path": "/path/to/repo"}
           }' \
       http://localhost:4444/rpc | jq
  ```

**Prompts**
- List prompts:
  ```bash
  curl -s -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN" \
       "http://localhost:4444/prompts?include_inactive=false" | jq
  ```
- Get a prompt by name (no args):
  ```bash
  curl -s -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN" \
       http://localhost:4444/prompts/<prompt_name> | jq
  ```
- Render a prompt with args (POST body is a dict of key→string):
  ```bash
  curl -s -X POST -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN" \
       -H "Content-Type: application/json" \
       -d '{"user_input": "hello"}' \
       http://localhost:4444/prompts/<prompt_name> | jq
  ```

**Resources**
- List resources:
  ```bash
  curl -s -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN" \
       "http://localhost:4444/resources?include_inactive=false" | jq
  ```
- Read a resource (URI path parameter must be URL‑encoded):
  ```bash
  URI=$(python3 - <<'PY'
import urllib.parse
print(urllib.parse.quote('http://example.com/file.txt', safe=''))
PY
  )
  curl -s -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN" \
       "http://localhost:4444/resources/${URI}" | jq
  ```
- Subscribe to a resource (server‑sent updates):
  ```bash
  curl -s -X POST -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN" \
       http://localhost:4444/resources/subscribe/${URI}
  ```

**SSE Streams**
- Global SSE endpoint (auth):
  ```bash
  curl -N -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN" \
       http://localhost:4444/sse
  ```
- Per‑server SSE endpoint:
  ```bash
  curl -N -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN" \
       http://localhost:4444/servers/<server_id>/sse
  ```

**Common Query Parameters**
- `include_inactive` (bool): include disabled entities.
- `tags` (comma‑separated or repeated): filter by tag.
- `team_id` (str): team scoping.
- `visibility` (str): `private|team|public`.

**Auth & Errors**
- 401 Unauthorized when the bearer token is missing/invalid.
- 422 Validation Error for malformed payloads or params.
- Plugins may block requests in `enforce` mode; look for a structured violation in the response.

**Gateways (MCP Server Registry)**
- List gateways:
  ```bash
  curl -s -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN" \
       "http://localhost:4444/gateways?include_inactive=false" | jq
  ```
- Create gateway (register an external MCP server):
  ```bash
  curl -s -X POST -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN" \
       -H "Content-Type: application/json" \
       -d '{
             "url": "http://localhost:9000",
             "name": "my-mcp-server",
             "description": "Example MCP server"
           }' \
       http://localhost:4444/gateways | jq
  ```
- Refresh gateway (re-discover tools/resources):
  ```bash
  curl -s -X POST -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN" \
       http://localhost:4444/gateways/<gateway_id>/refresh | jq
  ```

**Tools**
- List tools:
  ```bash
  curl -s -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN" \
       "http://localhost:4444/tools?include_inactive=false" | jq
  ```
- Get tool details:
  ```bash
  curl -s -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN" \
       http://localhost:4444/tools/<tool_name> | jq
  ```

**A2A Agents (Agent-to-Agent)**
- List A2A agents:
  ```bash
  curl -s -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN" \
       "http://localhost:4444/a2a?include_inactive=false" | jq
  ```
- Create A2A agent:
  ```bash
  curl -s -X POST -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN" \
       -H "Content-Type: application/json" \
       -d '{
             "name": "my-agent",
             "description": "Agent description",
             "url": "http://localhost:9001"
           }' \
       http://localhost:4444/a2a | jq
  ```

**WebSocket Transport**
- Connect to WebSocket for bidirectional MCP communication:
  ```bash
  websocat "ws://localhost:4444/ws" -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN"
  ```
- Per-server WebSocket:
  ```bash
  websocat "ws://localhost:4444/servers/<server_id>/ws" -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN"
  ```

**Admin API**
- Get system stats (requires admin API enabled):
  ```bash
  curl -s -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN" \
       http://localhost:4444/admin/api/stats | jq
  ```
- Export configuration:
  ```bash
  curl -s -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN" \
       http://localhost:4444/admin/export | jq
  ```

**Import/Export**
- Export all configuration:
  ```bash
  curl -s -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN" \
       http://localhost:4444/export > backup.json
  ```
- Import configuration:
  ```bash
  curl -s -X POST -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN" \
       -H "Content-Type: application/json" \
       -d @backup.json \
       "http://localhost:4444/import?conflict_strategy=skip" | jq
  ```

**Well-Known Endpoints**
- MCP discovery (/.well-known/mcp.json):
  ```bash
  curl -s http://localhost:4444/.well-known/mcp.json | jq
  ```

**Tips**
- Prefer Authorization header (bearer token) over `jwt_token` cookie.
- For dev: `make dev` runs the app on `:8000` with hot reload; production `make serve` runs Gunicorn on `:4444`.
- If resources or prompts contain reserved characters, URL‑encode path params.
- Pagination: Most list endpoints support `cursor` and `limit` params for cursor-based pagination.
- Tags filtering: Use `tags=tag1,tag2` query parameter to filter by tags.
- Team scoping: Use `team_id` query parameter to filter by team.
