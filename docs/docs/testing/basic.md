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
export MCPGATEWAY_BEARER_TOKEN=$(python -m mcpgateway.utils.create_jwt_token -u admin)
curl -k -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN" https://localhost:4444/health
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
curl -k -X POST $BASE_URL/protocol/ping \
  -H "$AUTH_HEADER" -H "$JSON" \
  -d '{"jsonrpc":"2.0","id":1,"method":"ping"}'
```

---

### 5. Add a Peer Gateway

```bash
curl -k -X POST $BASE_URL/gateways \
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
curl -k -H "$AUTH_HEADER" $BASE_URL/gateways
```

---

### 6. Add a Tool

```bash
curl -k -X POST $BASE_URL/tools \
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
curl -k -X POST $BASE_URL/servers \
  -H "$AUTH_HEADER" -H "$JSON" \
  -d '{
        "name": "demo-server",
        "description": "Smoke-test virtual server",
        "icon": "mdi-server",
        "associatedTools": ["1"]
      }'
```

Check:

```bash
curl -k -H "$AUTH_HEADER" $BASE_URL/servers
```

---

### 8. Open an SSE stream

```bash
curl -k -N -H "$AUTH_HEADER" $BASE_URL/servers/1/sse
```

Leave running - real-time events appear here.

---

### 9. Invoke the Tool via RPC

```bash
curl -k -X POST $BASE_URL/rpc \
  -H "$AUTH_HEADER" -H "$JSON" \
  -d '{
        "jsonrpc": "2.0",
        "id": 99,
        "method": "clock_tool",
        "params": {
          "timezone": "Europe/Dublin"
        }
      }'
```

Expected:

```json
{
  "jsonrpc": "2.0",
  "id": 99,
  "result": {
    "time": "2025-05-27T14:23:01+01:00"
  }
}
```

---

## 🧹 Cleanup

```bash
curl -k -X DELETE -H "$AUTH_HEADER" $BASE_URL/servers/1
curl -k -X DELETE -H "$AUTH_HEADER" $BASE_URL/tools/1
curl -k -X DELETE -H "$AUTH_HEADER" $BASE_URL/gateways/1
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

---
