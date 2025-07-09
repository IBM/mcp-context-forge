# MCP Gateway - Basic

Test script for MCP Gateway development environments.
Verifies API readiness, JWT auth, Gateway/Tool/Server lifecycle, and RPC invocation.

---

## 🔧 Environment Setup

### 0. Bootstrap `.env`

```bash
cp .env.example .env
```

---

### 1. Start the Gateway

```bash
make podman podman-run-ssl
# or
make venv install serve-ssl
```

Gateway will listen on:

* Admin UI → [https://localhost:4444/admin](https://localhost:4444/admin)
* Swagger   → [https://localhost:4444/docs](https://localhost:4444/docs)
* ReDoc     → [https://localhost:4444/redoc](https://localhost:4444/redoc)

---

## 🔑 Authentication

### 2. Generate and export tokens

#### Gateway JWT (for local API access)

```bash
export MCPGATEWAY_BEARER_TOKEN=$(python3 -m mcpgateway.utils.create_jwt_token -u admin)
curl -s -k -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN" https://localhost:4444/health
```

Expected: `{"status":"ok"}`

#### Remote gateway token (peer)

```bash
export MY_MCP_TOKEN="sse-bearer-token-here..."
```

#### Optional: local test server token (GitHub MCP server)

```bash
export LOCAL_MCP_URL="http://localhost:8000/sse"
export LOCAL_MCP_TOOL_URL="http://localhost:9000/rpc"
```

---

### 3. Set convenience variables

```bash
export BASE_URL="https://localhost:4444"
export AUTH_HEADER="Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN"
export JSON="Content-Type: application/json"
```

---

## 🧪 Smoke Tests

### 4. Ping JSON-RPC system

```bash
curl -s -k -X POST $BASE_URL/protocol/ping \
  -H "$AUTH_HEADER" -H "$JSON" \
  -d '{"jsonrpc":"2.0","id":1,"method":"ping"}'
```

Expected:

```json
{"jsonrpc":"2.0","id":1,"result":{}}
```

---

### 5. Add a Peer Gateway

```bash
curl -s -k -X POST $BASE_URL/gateways \
  -H "$AUTH_HEADER" -H "$JSON" \
  -d '{
        "name": "my-mcp",
        "url": "https://link-to-remote-mcp-server/sse",
        "description": "My MCP Servers",
        "auth_type": "bearer",
        "auth_token": "'"$MY_MCP_TOKEN"'"
      }'
```

List gateways:

```bash
curl -s -k -H "$AUTH_HEADER" $BASE_URL/gateways
```

---

### 6. Add a Tool

```bash
curl -s -k -X POST $BASE_URL/tools \
  -H "$AUTH_HEADER" -H "$JSON" \
  -d '{
        "name": "clock_tool",
        "url": "'"$LOCAL_MCP_TOOL_URL"'",
        "description": "Returns current time",
        "request_type": "POST",
        "integration_type": "MCP",
        "input_schema": {
          "type": "object",
          "properties": {
            "timezone": { "type": "string" }
          }
        }
      }'
```

---

### 7. Create a Virtual Server

```bash
curl -s -k -X POST $BASE_URL/servers/ \
  -H "$AUTH_HEADER" -H "$JSON" -H 'accept: application/json' \
  -d '{
        "name": "demo-server",
        "description": "Smoke-test virtual server",
        "icon": "https://github.githubassets.com/assets/GitHub-Mark-ea2971cee799.png",
        "associatedTools": ["1"],
        "associatedResources": [],
        "associatedPrompts": []
      }'
```

Expected:

```json
{
  "id": 2,
  "name": "demo-server",
  "description": "Smoke-test virtual server",
  "icon": "https://github.githubassets.com/assets/GitHub-Mark-ea2971cee799.png",
  "createdAt": "2025-05-28T04:28:38.554558",
  "updatedAt": "2025-05-28T04:28:38.554564",
  "isActive": true,
  "associatedTools": [
    1
  ],
  "associatedResources": [],
  "associatedPrompts": [],
  "metrics": {
    "totalExecutions": 0,
    "successfulExecutions": 0,
    "failedExecutions": 0,
    "failureRate": 0,
    "minResponseTime": null,
    "maxResponseTime": null,
    "avgResponseTime": null,
    "lastExecutionTime": null
  }
}
```

Check:

```bash
curl -s -k -H "$AUTH_HEADER" $BASE_URL/servers | jq
```

---

### 8. Open an SSE stream

```bash
curl -s -k -N -H "$AUTH_HEADER" $BASE_URL/servers/UUID_OF_SERVER_1/sse
```

Leave running - real-time events appear here.

---

### 9. Invoke the Tool via RPC

```bash
curl -s -k -X POST $BASE_URL/rpc \
  -H "$AUTH_HEADER" -H "$JSON" \
  -d '{
        "jsonrpc": "2.0",
        "id": 99,
        "method": "get_system_time",
        "params": {
          "timezone": "Europe/Dublin"
        }
      }'
```

Expected:

```json
{
  "content": [
    {
      "type": "text",
      "text": "{\n  \"timezone\": \"Europe/Dublin\",\n  \"datetime\": \"2025-05-28T05:24:13+01:00\",\n  \"is_dst\": true\n}"
    }
  ],
  "is_error": false
}
```

---

### 10. Connect to GitHub MCP Tools via SuperGateway

You can test the Gateway against GitHub's official `mcp-server-git` tool using [`supergateway`](https://github.com/modelcontextprotocol/supergateway).

Start a temporary SSE wrapper around the GitHub MCP server:

```bash
npx -y supergateway --stdio "uvx mcp-server-git"
```

This starts:

* SSE endpoint: `http://localhost:8000/sse`
* Message POST: `http://localhost:8000/message`

To register it with the MCP Gateway:

```bash
export MY_MCP_TOKEN="optional-auth-header-if-needed"

curl -s -k -X POST $BASE_URL/gateways \
  -H "$AUTH_HEADER" -H "$JSON" \
  -d '{
        "name": "github-mcp",
        "url": "http://localhost:8000/sse",
        "description": "GitHub MCP Tools via SuperGateway",
        "auth_type": "none"
      }'
```

This gives you access to GitHub's MCP tools like `get_repo_issues`, `get_pull_requests`, etc.

---

### 11. Development Testing with MCP Inspector

Launch a visual inspector to interactively test your Gateway:

```bash
npx @modelcontextprotocol/inspector
```

Once launched at [http://localhost:5173](http://localhost:5173):

1. Click **"Add Server"**
2. Use the URL for your virtual server's SSE stream:

```
http://localhost:4444/servers/UUID_OF_SERVER_1/sse
```

3. Add this header:

```json
{
  "Authorization": "Bearer <your-jwt-token>"
}
```

4. Save and test tool invocations by selecting a tool and sending sample input:

```json
{ "timezone": "Europe/Dublin" }
```

---

## 🧹 Cleanup

```bash
curl -s -k -X DELETE -H "$AUTH_HEADER" $BASE_URL/servers/UUID_OF_SERVER_1
curl -s -k -X DELETE -H "$AUTH_HEADER" $BASE_URL/tools/1
curl -s -k -X DELETE -H "$AUTH_HEADER" $BASE_URL/gateways/1
```

---

## ✅ Summary

This smoke test validates:

* ✅ Gateway JWT auth
* ✅ Peer Gateway registration with remote bearer
* ✅ Tool registration and RPC wiring
* ✅ Virtual server creation
* ✅ SSE subscription and live messaging
* ✅ JSON-RPC invocation flow
* ✅ Connecting MCP Inspector to the MCP Gateway
* ✅ Connecting the official GitHub MCP server to the Gateway

---
