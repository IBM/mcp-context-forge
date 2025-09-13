API: Quick Usage & Testing Guide

- Purpose: Help LLMs and scripts call the MCP Gateway API reliably with correct auth, payloads, and common flows.
- Base URL: `http://localhost:4444` (production via `make serve`), or `http://127.0.0.1:8000` (dev via `make dev`).

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

**Tips**
- Prefer Authorization header (bearer token) over `jwt_token` cookie.
- For dev: `make dev` runs the app on `:8000` with hot reload; production `make serve` runs Gunicorn on `:4444`.
- If resources or prompts contain reserved characters, URL‑encode path params.
