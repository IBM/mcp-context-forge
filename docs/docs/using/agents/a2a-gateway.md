# Native A2A Protocol Gateway

ContextForge provides a **native A2A protocol gateway** that exposes registered A2A agents via the standard [A2A v1.0 JSON-RPC 2.0](https://google.github.io/A2A/) protocol. This allows any A2A-compatible client to discover and communicate with agents through the gateway — with full governance (auth, RBAC, token scoping, plugins, metrics, and logging) applied automatically.

## Overview

The A2A gateway acts as a **transparent proxy**: it receives A2A JSON-RPC requests from clients, applies the full gateway pipeline, and forwards them to downstream agents. The gateway does not store task state — that remains with the downstream agent.

```
A2A Client ──► ContextForge Gateway ──► Downstream A2A Agent
                │ Auth (JWT/API Key)
                │ RBAC (permissions)
                │ Token Scoping (team/public)
                │ Plugin Hooks (pre/post)
                │ Prometheus Metrics
                │ Structured Logging
                │ Correlation IDs
```

### Supported Methods

| JSON-RPC Method                       | Type            | Description                                   |
| ------------------------------------- | --------------- | --------------------------------------------- |
| `message/send`                        | Non-streaming   | Send a message, get a complete response       |
| `message/stream`                      | Streaming (SSE) | Send a message, receive events as they arrive |
| `tasks/get`                           | Non-streaming   | Get current task status by ID                 |
| `tasks/list`                          | Non-streaming   | List tasks with filtering and pagination      |
| `tasks/cancel`                        | Non-streaming   | Cancel a running task                         |
| `tasks/resubscribe`                   | Streaming (SSE) | Re-subscribe to task events                   |
| `tasks/pushNotificationConfig/set`    | Non-streaming   | Configure push notifications                  |
| `tasks/pushNotificationConfig/get`    | Non-streaming   | Get push notification config                  |
| `tasks/pushNotificationConfig/list`   | Non-streaming   | List push notification configs                |
| `tasks/pushNotificationConfig/delete` | Non-streaming   | Delete push notification config               |
| `agent/getAuthenticatedExtendedCard`  | Local           | Get agent card (handled by gateway)           |

### Endpoints

| Endpoint                                           | Method | Description                                                        |
| -------------------------------------------------- | ------ | ------------------------------------------------------------------ |
| `/{prefix}/{agent_id}`                             | POST   | JSON-RPC 2.0 dispatcher — all methods routed from the request body |
| `/{prefix}/{agent_id}/.well-known/agent-card.json` | GET    | Agent Card discovery (A2A-spec compliant)                          |

!!! note "Route Prefix"
The `{prefix}` defaults to `a2a/agent` and is configurable via the `A2A_GATEWAY_ROUTE_PREFIX` environment variable. The `{agent_id}` is the agent's database UUID (returned when registering the agent via the admin API).

## Quick Start

!!! tip "Base URL" - Direct installs (`uvx`, pip, or `docker run`): `http://localhost:4444` - Docker Compose (nginx proxy): `http://localhost:8080`

### 1. Enable the Gateway

The A2A gateway is enabled by default when A2A is enabled. Verify these settings:

```bash
# In your .env file
MCPGATEWAY_A2A_ENABLED=true
MCPGATEWAY_A2A_GATEWAY_ENABLED=true  # default: true

# Optional: customize the route prefix (default: a2a/agent)
# A2A_GATEWAY_ROUTE_PREFIX=a2a/agent
```

### 2. Register an A2A Agent

Register a downstream A2A agent via the admin API. The response includes the agent's `id` — use this in all gateway URLs.

```bash
export TOKEN=$(python3 -m mcpgateway.utils.create_jwt_token \
  --username admin@example.com --exp 60 --secret $JWT_SECRET_KEY)

curl -X POST "http://localhost:4444/a2a" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Echo Agent",
    "endpoint_url": "http://localhost:9999/",
    "agent_type": "jsonrpc",
    "description": "Echoes back messages for testing",
    "capabilities": {"streaming": true, "pushNotifications": false},
    "tags": ["echo", "test"]
  }'
# Note the "id" field in the response (e.g., "abc123def456...")
export AGENT_ID=<agent-id-from-response>
```

### 3. Discover the Agent Card

```bash
curl "http://localhost:4444/a2a/agent/$AGENT_ID/.well-known/agent-card.json" \
  -H "Authorization: Bearer $TOKEN"
```

Response:

```json
{
    "name": "Echo Agent",
    "description": "Echoes back messages for testing",
    "url": "http://localhost:4444/a2a/agent/abc123def456",
    "version": "1.0",
    "protocolVersion": "1.0",
    "capabilities": {
        "streaming": true,
        "pushNotifications": false,
        "stateTransitionHistory": false
    },
    "defaultInputModes": ["text"],
    "defaultOutputModes": ["text"],
    "skills": [
        { "id": "echo", "name": "echo", "description": "Skill: echo" },
        { "id": "test", "name": "test", "description": "Skill: test" }
    ]
}
```

### 4. Send a Message

```bash
curl -X POST "http://localhost:4444/a2a/agent/$AGENT_ID" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc": "2.0",
    "method": "message/send",
    "params": {
      "message": {
        "messageId": "msg-001",
        "role": "user",
        "parts": [{"kind": "text", "text": "Hello, Echo Agent!"}]
      }
    },
    "id": 1
  }'
```

Response:

```json
{
    "jsonrpc": "2.0",
    "result": {
        "id": "task-abc123",
        "status": { "state": "completed" },
        "artifacts": [
            {
                "parts": [{ "kind": "text", "text": "Hello, Echo Agent!" }]
            }
        ]
    },
    "id": 1
}
```

## Real-World Usage Examples

### Example 1: Multi-Turn Conversation with a Coding Assistant

Register a coding assistant agent:

```bash
curl -X POST "http://localhost:4444/a2a" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Code Review Agent",
    "endpoint_url": "https://my-code-reviewer.internal/a2a",
    "agent_type": "jsonrpc",
    "description": "Reviews code and suggests improvements",
    "auth_type": "bearer",
    "auth_value": "internal-service-token",
    "capabilities": {"streaming": true},
    "tags": ["code-review", "python", "security"]
  }'
# Export the agent ID from the response
export CODE_REVIEW_ID=<agent-id-from-response>
```

Send code for review:

```bash
curl -X POST "http://localhost:4444/a2a/agent/$CODE_REVIEW_ID" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc": "2.0",
    "method": "message/send",
    "params": {
      "message": {
        "messageId": "review-001",
        "role": "user",
        "parts": [
          {
            "kind": "text",
            "text": "Review this Python function for security issues:\n\ndef get_user(db, user_id):\n    query = f\"SELECT * FROM users WHERE id = {user_id}\"\n    return db.execute(query)"
          }
        ]
      }
    },
    "id": 1
  }'
```

Follow up on the same task using the returned task ID:

```bash
curl -X POST "http://localhost:4444/a2a/agent/$CODE_REVIEW_ID" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc": "2.0",
    "method": "tasks/get",
    "params": {"id": "task-abc123"},
    "id": 2
  }'
```

### Example 2: Streaming Response from a Research Agent

Use `message/stream` for long-running tasks where you want incremental updates:

```bash
curl -N -X POST "http://localhost:4444/a2a/agent/$RESEARCH_AGENT_ID" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc": "2.0",
    "method": "message/stream",
    "params": {
      "message": {
        "messageId": "research-001",
        "role": "user",
        "parts": [{"kind": "text", "text": "Research the latest advances in quantum computing"}]
      }
    },
    "id": 1
  }'
```

The response is an SSE (Server-Sent Events) stream:

```
data: {"jsonrpc":"2.0","result":{"id":"task-xyz","status":{"state":"working"}},"id":1}

data: {"jsonrpc":"2.0","result":{"id":"task-xyz","status":{"state":"working"},"artifacts":[{"parts":[{"kind":"text","text":"Searching for recent papers..."}]}]},"id":1}

data: {"jsonrpc":"2.0","result":{"id":"task-xyz","status":{"state":"completed"},"artifacts":[{"parts":[{"kind":"text","text":"Here are the latest advances..."}]}]},"id":1}
```

### Example 3: Python Client

```python
import httpx

GATEWAY_URL = "http://localhost:4444"
TOKEN = "your-jwt-token"
AGENT_ID = "abc123def456"  # Agent ID from registration response

headers = {
    "Authorization": f"Bearer {TOKEN}",
    "Content-Type": "application/json",
}

# 1. Discover the agent
card = httpx.get(
    f"{GATEWAY_URL}/a2a/agent/{AGENT_ID}/.well-known/agent-card.json",
    headers=headers,
).json()
print(f"Agent: {card['name']} at {card['url']}")

# 2. Send a message
response = httpx.post(
    f"{GATEWAY_URL}/a2a/agent/{AGENT_ID}",
    headers=headers,
    json={
        "jsonrpc": "2.0",
        "method": "message/send",
        "params": {
            "message": {
                "messageId": "py-001",
                "role": "user",
                "parts": [{"kind": "text", "text": "Summarize this document..."}],
            }
        },
        "id": 1,
    },
)
result = response.json()
task_id = result["result"]["id"]
print(f"Task {task_id}: {result['result']['status']['state']}")

# 3. Check task status (if still working)
if result["result"]["status"]["state"] != "completed":
    status = httpx.post(
        f"{GATEWAY_URL}/a2a/agent/{AGENT_ID}",
        headers=headers,
        json={
            "jsonrpc": "2.0",
            "method": "tasks/get",
            "params": {"id": task_id},
            "id": 2,
        },
    ).json()
    print(f"Status: {status['result']['status']['state']}")

# 4. Cancel a task
cancel = httpx.post(
    f"{GATEWAY_URL}/a2a/agent/{AGENT_ID}",
    headers=headers,
    json={
        "jsonrpc": "2.0",
        "method": "tasks/cancel",
        "params": {"id": task_id},
        "id": 3,
    },
).json()
print(f"Cancel result: {cancel}")
```

### Example 4: Python Streaming Client

```python
import httpx
import httpx_sse

GATEWAY_URL = "http://localhost:4444"
TOKEN = "your-jwt-token"

headers = {
    "Authorization": f"Bearer {TOKEN}",
    "Content-Type": "application/json",
}

body = {
    "jsonrpc": "2.0",
    "method": "message/stream",
    "params": {
        "message": {
            "messageId": "stream-001",
            "role": "user",
            "parts": [{"kind": "text", "text": "Generate a report on Q3 sales"}],
        }
    },
    "id": 1,
}

with httpx.Client(timeout=300) as client:
    with httpx_sse.connect_sse(
        client, "POST",
        f"{GATEWAY_URL}/a2a/agent/{AGENT_ID}",
        json=body, headers=headers,
    ) as event_source:
        for event in event_source.iter_sse():
            import json
            data = json.loads(event.data)
            state = data.get("result", {}).get("status", {}).get("state")
            print(f"State: {state}")
            if state == "completed":
                artifacts = data["result"].get("artifacts", [])
                for artifact in artifacts:
                    for part in artifact.get("parts", []):
                        if part["kind"] == "text":
                            print(part["text"])
```

## Configuration

| Variable                             | Description                                                           | Default     |
| ------------------------------------ | --------------------------------------------------------------------- | ----------- |
| `MCPGATEWAY_A2A_GATEWAY_ENABLED`     | Enable/disable the native A2A gateway                                 | `true`      |
| `A2A_GATEWAY_ROUTE_PREFIX`           | Route prefix for gateway endpoints (without leading/trailing slashes) | `a2a/agent` |
| `A2A_GATEWAY_CLIENT_TIMEOUT`         | HTTP timeout for downstream agent calls (seconds)                     | `30`        |
| `A2A_GATEWAY_STREAM_TIMEOUT`         | SSE stream timeout (seconds)                                          | `300`       |
| `A2A_GATEWAY_MAX_CONCURRENT_STREAMS` | Max concurrent SSE streams                                            | `100`       |
| `A2A_GATEWAY_RATE_LIMIT`             | Max requests per minute per agent per user                            | `100`       |

## Authentication & RBAC

The A2A gateway uses the same authentication and RBAC model as the rest of ContextForge.

### Required Permissions

| Permission            | Required For                                              |
| --------------------- | --------------------------------------------------------- |
| `a2a_gateway.read`    | Agent card discovery (`GET /.well-known/agent-card.json`) |
| `a2a_gateway.execute` | JSON-RPC requests (`POST /{agent_id}`)                    |
| `a2a_gateway.manage`  | Administrative operations                                 |

### Role Permissions

| Role             | Read | Execute | Manage |
| ---------------- | ---- | ------- | ------ |
| `platform_admin` | Yes  | Yes     | Yes    |
| `team_admin`     | Yes  | Yes     | Yes    |
| `developer`      | Yes  | Yes     | No     |
| `viewer`         | Yes  | No      | No     |

### Token Scoping

Agent visibility follows the standard ContextForge token scoping rules:

- **Public agents**: Visible to all authenticated users
- **Team agents**: Visible only to users whose JWT `teams` claim includes the agent's `team_id`
- **Private agents**: Visible only to the agent owner

Access denied returns **404** (not 403) to avoid leaking the existence of private agents.

## Metrics

The gateway exposes Prometheus metrics for monitoring:

| Metric                       | Type    | Labels                         | Description                  |
| ---------------------------- | ------- | ------------------------------ | ---------------------------- |
| `a2a_gateway_requests_total` | Counter | `agent_id`, `method`, `status` | Total JSON-RPC requests      |
| `a2a_gateway_errors_total`   | Counter | `agent_id`, `error_type`       | Total gateway errors         |
| `a2a_gateway_streams_active` | Gauge   | `agent_id`                     | Currently active SSE streams |

## Plugin Hooks

The gateway supports pre-invoke and post-invoke plugin hooks:

- **`a2a_gateway_pre_invoke`**: Fires before forwarding a request to the downstream agent. Can inspect/modify request params.
- **`a2a_gateway_post_invoke`**: Fires after receiving a response. Can inspect the result and metrics.

## Error Handling

All errors are returned as proper JSON-RPC 2.0 error responses with HTTP 200:

| Code     | Name             | When                                                 |
| -------- | ---------------- | ---------------------------------------------------- |
| `-32700` | Parse Error      | Request body is not valid JSON                       |
| `-32600` | Invalid Request  | Missing `jsonrpc`, `method`, or wrong version        |
| `-32601` | Method Not Found | Unknown JSON-RPC method                              |
| `-32603` | Internal Error   | Agent not found, disabled, downstream error, timeout |

Example error response:

```json
{
    "jsonrpc": "2.0",
    "error": {
        "code": -32603,
        "message": "Agent not found: nonexistent-agent"
    },
    "id": 1
}
```

## How It Differs from MCP Tool Wrapping

ContextForge offers two ways to interact with A2A agents:

| Feature              | A2A Gateway (`/a2a/agent/`) | MCP Tool Wrapping (`/rpc`) |
| -------------------- | --------------------------- | -------------------------- |
| Protocol             | Native A2A JSON-RPC 2.0     | MCP `tools/call`           |
| Streaming            | SSE (`message/stream`)      | Not supported              |
| Task Management      | `tasks/get`, `tasks/cancel` | Not supported              |
| Push Notifications   | `pushNotificationConfig/*`  | Not supported              |
| Client Compatibility | Any A2A client              | Any MCP client             |
| Use Case             | Full A2A protocol features  | Simple tool invocation     |

Use the **A2A gateway** when you need streaming, task management, or A2A protocol compliance. Use **MCP tool wrapping** when integrating with MCP-only clients.

## Troubleshooting

### Gateway Returns 404 for Agent Card

1. Verify the agent is registered: `GET /a2a` (admin API)
2. Check the agent ID in the URL matches the `id` field from the registration response
3. Ensure the agent is enabled
4. Verify your JWT token has the correct team scope

### Downstream Agent Timeout

1. Increase `A2A_GATEWAY_CLIENT_TIMEOUT` (default: 30s)
2. For streaming, increase `A2A_GATEWAY_STREAM_TIMEOUT` (default: 300s)
3. Check that the downstream agent is reachable from the gateway
4. Verify the downstream agent's endpoint URL is correct

### Permission Denied

1. Verify your JWT token includes the required permissions
2. Check your role has `a2a_gateway.execute` permission
3. For team-scoped agents, ensure your token's `teams` claim includes the agent's team
4. For private agents, verify you are the agent owner

### Streaming Not Working

1. Ensure the agent's `capabilities.streaming` is set to `true`
2. Use `message/stream` method (not `message/send`)
3. Check that no reverse proxy is buffering the SSE response
4. Add `X-Accel-Buffering: no` header if behind nginx
