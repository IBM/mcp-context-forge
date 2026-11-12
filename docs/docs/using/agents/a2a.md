# A2A (Agent-to-Agent) Integration

ContextForge supports A2A (Agent-to-Agent) integration, allowing you to register external AI agents and expose them as MCP tools for seamless integration with other agents and MCP clients.

## Overview

A2A integration enables you to:

- **Register external AI agents** (OpenAI, Anthropic, custom agents)
- **Expose agents as MCP tools** for universal discovery and access
- **Support multiple protocols** (JSONRPC, custom formats)
- **Manage agent lifecycle** through admin UI and APIs
- **Monitor performance** with comprehensive metrics
- **Configure authentication** with various auth methods

## Quick Start

!!! tip "Base URL"
    - Direct installs (`uvx`, pip, or `docker run`): `http://localhost:4444`
    - Docker Compose (nginx proxy): `http://localhost:8080`

### 1. Enable A2A Features

```bash
# In your .env file or environment variables
MCPGATEWAY_A2A_ENABLED=true
MCPGATEWAY_A2A_METRICS_ENABLED=true
```

### When A2A Is Disabled

With `MCPGATEWAY_A2A_ENABLED=false`, every A2A route returns 404 with one typed body:

```json
{"detail": {"error": "a2a_disabled", "message": "A2A is disabled on this gateway"}}
```

Clients branch on `detail.error`. The check runs after authentication, so unauthenticated callers still receive 401. The OpenAPI schema omits the A2A operations.

Any authenticated user can discover the flag with `GET /auth/email/me`, which returns `features`:

```json
{"email": "user@example.com", "features": {"a2a": false}}
```

The admin state, edit, and delete form routes still redirect to the A2A tab, which is hidden when A2A is off.

Status changes from earlier releases:

| Route | Before | After |
|-------|--------|-------|
| `/a2a/*`, `/v1/a2a/*` | 404, generic body | 404, typed body |
| `GET /admin/a2a` | 200, empty page | 404, typed body |
| `GET /admin/a2a/{agent_id}`, `/admin/a2a/ids`, `/admin/a2a/search`, `/admin/a2a/partial` | 500 or 200 | 404, typed body |
| `POST /admin/a2a` | 403, `success: false` | 404, typed body |
| `POST /admin/a2a/{agent_id}/test` | 403, `success: false` | 404, typed body |
| `POST /metrics/reset`, entity `a2a` | 400, "A2A features are disabled" | 404, typed body |

### 2. Register an A2A Agent

**Via Admin UI:**

1. Go to `http://localhost:4444/admin`
2. Click the "A2A Agents" tab
3. Fill out the "Add New A2A Agent" form
4. Click "Add A2A Agent"

**Via REST API:**
```bash
curl -X POST "http://localhost:4444/a2a" \
  -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "hello_world_agent",
    "endpoint_url": "http://localhost:9999/",
    "agent_type": "jsonrpc",
    "description": "External AI agent for hello world functionality",
    "passthrough_headers": ["Authorization", "X-Tenant-Id"],
    "auth_type": "api_key",
    "auth_value": "your-api-key",
    "tags": ["ai", "hello-world"]
  }'
```

Optional request fields:

| Field | Description | Example |
| --- | --- | --- |
| `passthrough_headers` | Header names allowed to pass from the incoming request to this A2A agent. Unset (`null`) and empty (`[]`) both block request-header forwarding. `TOOL_PRE_INVOKE` plugin payloads receive only the non-sensitive subset. | `["Authorization", "X-Tenant-Id"]` |

### 3. Test the Agent

**Via Admin UI:**

- Click the blue "Test" button next to your agent
- See real-time test results

**Via API:**
```bash
curl -X POST "http://localhost:4444/a2a/hello_world_agent/invoke" \
  -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "parameters": {
      "message": {
        "messageId": "test-123",
        "role": "user",
        "parts": [{"type": "text", "text": "Hello!"}]
      }
    },
    "interaction_type": "test"
  }'
```

**Via the test endpoint:**

`POST /v1/a2a/{agent_id}/test` sends a test message and needs no payload. It requires `a2a.invoke`. The optional body field `query` sets the message.

```bash
curl -X POST "http://localhost:4444/v1/a2a/$AGENT_ID/test" \
  -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"query": "hello"}'
```

Success returns 200 with `success`, `result`, `agent_name`, and `test_timestamp`. Failure returns an error status with a `detail` object holding `success`, `error`, `error_type`, and `agent_id`. Request body validation failures (an extra field, a `query` over 4096 characters, a non-JSON body) return the default FastAPI 422, where `detail` is a list of validation errors.

| Status | `error_type` | `error` | Cause |
|--------|--------------|---------|-------|
| 404 | `not_found` | `A2A agent not found` | Agent missing or not visible to the caller |
| 502 | `agent_disabled` | `A2A agent is disabled` | Agent is disabled |
| 502 | `agent_error` | `A2A agent invocation failed` | Agent unreachable or returned an error |
| 422 | `validation_error` | Validation message | Invalid test parameters |
| 500 | `internal_error` | Sanitized message | Unexpected error |

The 404 response is identical for a missing agent and an agent the caller cannot see. The 502 response never carries upstream error text; the gateway logs it. The `result` field relays the agent response unchanged. The gateway forwards the same passthrough headers as a normal invocation, and a test call counts in the agent metrics.

### 4. Create Virtual Server with A2A Agent

```bash
curl -X POST "http://localhost:4444/servers" \
  -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "AI Assistant Server",
    "description": "Virtual server with AI agents",
    "associated_a2a_agents": ["agent-id-from-step-2"]
  }'
```

### 5. Use Agent via MCP Protocol

```bash
# A2A agents are now available as MCP tools
curl -X POST "http://localhost:4444/rpc" \
  -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc": "2.0",
    "method": "tools/call",
    "params": {
      "name": "a2a_hello_world_agent",
      "arguments": {
        "method": "message/send",
        "params": {"message": {"messageId": "test", "role": "user", "parts": [{"type": "text", "text": "Hi!"}]}}
      }
    },
    "id": 1
  }'
```

## A2A Invocation Methods

ContextForge provides multiple ways to invoke A2A agents depending on your use case:

### Method 1: Envelope Format (`/invoke`)

The standard invocation endpoint accepts ContextForge's envelope format. The gateway converts your parameters to JSON-RPC when forwarding to the agent:

```bash
curl -X POST "http://localhost:4444/a2a/{agent_name}/invoke" \
  -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "parameters": {
      "query": "Hello!"
    },
    "interaction_type": "query"
  }'
```

For A2A protocol agents expecting message format:

```bash
curl -X POST "http://localhost:4444/a2a/{agent_name}/invoke" \
  -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "parameters": {
      "message": {
        "messageId": "msg-123",
        "role": "ROLE_USER",
        "parts": [{"text": "Hello!"}]
      }
    },
    "interaction_type": "query"
  }'
```

**Use when:**
- You need to specify interaction type explicitly
- You're using ContextForge-specific features
- Your client is already integrated with ContextForge

**Note:** The `parameters` field contains agent-specific data, not JSON-RPC format. ContextForge handles the JSON-RPC conversion internally.

### Method 2: JSON-RPC Passthrough (`/jsonrpc`) ⭐ NEW

The passthrough endpoint accepts **raw A2A JSON-RPC** requests without envelope wrapping. This enables standard A2A SDKs (like Google ADK `RemoteA2aAgent`) to work without custom adapters:

```bash
curl -X POST "http://localhost:4444/a2a/{agent_name}/jsonrpc" \
  -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc": "2.0",
    "method": "SendMessage",
    "params": {
      "message": {
        "messageId": "msg-123",
        "role": "ROLE_USER",
        "parts": [{"text": "Hello!"}]
      }
    },
    "id": 1
  }'
```

**Success response:**
```json
{
  "jsonrpc": "2.0",
  "result": {
    "id": "task-456",
    "contextId": "ctx-789",
    "status": {
      "state": "TASK_STATE_WORKING",
      "message": "Processing..."
    }
  },
  "id": 1
}
```

**Error response example:**

When an agent is not found or an error occurs, the response follows JSON-RPC error format:

```bash
# Request to nonexistent agent
curl -X POST "http://localhost:4444/a2a/nonexistent-agent/jsonrpc" \
  -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc": "2.0",
    "method": "SendMessage",
    "params": {"query": "Hello"},
    "id": 1
  }'
```

```json
{
  "jsonrpc": "2.0",
  "error": {
    "code": -32001,
    "message": "A2A Agent not found with name: nonexistent-agent"
  },
  "id": 1
}
```

Common error codes:
- `-32001`: Agent not found
- `-32603`: Agent execution error (internal error or forwarded from backend agent)
- `-32600`: Invalid JSON-RPC request format
- `-32700`: Parse error

**Use when:**
- Using standard A2A SDKs (Google ADK, etc.)
- Building agent-to-agent federation
- Need transparent proxy behavior
- Want SDK compatibility without custom code

**Supported A2A Methods:**
- `SendMessage` - Send a message to the agent
- `GetTask` - Retrieve task status
- `ListTasks` - List all tasks
- `CancelTask` - Cancel a running task
- `SubscribeToTask` - Subscribe to task updates
- `GetExtendedAgentCard` - Get agent capabilities

**Agent card shape:** Agents with a stored protocol version of 1.x return the A2A 1.0 card, with `supportedInterfaces`, `securitySchemes`, and `securityRequirements`. The 1.0 card omits `url`, `protocolVersion`, `supportsAuthenticatedExtendedCard`, and `stateTransitionHistory`. Agents with a 0.x version keep the legacy card. A caller that sends `A2A-Version: 0.3` also gets the legacy card. The card describes the upstream agent, so `supportedInterfaces` and OAuth flows carry the registered upstream URLs. The card never contains credential values. See [ADR-048](../../architecture/adr/048-a2a-v1-protocol-migration.md).

**Features:**
- ✅ Full RBAC and token scoping
- ✅ Cross-gateway authentication forwarding
- ✅ Observability (traces, metrics, logs)
- ✅ Rate limiting and governance
- ✅ UAID federation support
- ✅ Plugin hooks (pre/post invoke)

**Python SDK Example:**

```python
# Generic Python example - works with any A2A SDK or direct HTTP calls
import requests

# Send message to agent via JSON-RPC passthrough
response = requests.post(
    "http://localhost:4444/a2a/my-agent/jsonrpc",
    headers={
        "Authorization": "Bearer your-token",
        "Content-Type": "application/json"
    },
    json={
        "jsonrpc": "2.0",
        "method": "SendMessage",
        "params": {
            "message": {
                "messageId": "msg-001",
                "role": "ROLE_USER",
                "parts": [{"text": "What is the weather?"}]
            }
        },
        "id": 1
    }
)

result = response.json()
print(result["result"])
```

**Note:** Standard A2A SDKs can point to the `/jsonrpc` endpoint directly.

### Method 3: MCP Tool Bridge

A2A agents are automatically exposed as MCP tools, allowing MCP clients to discover and invoke them:

```bash
curl -X POST "http://localhost:4444/rpc" \
  -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc": "2.0",
    "method": "tools/call",
    "params": {
      "name": "a2a-working-a2a-agent1",
      "arguments": {
        "method": "SendMessage",
        "params": {
          "message": {
            "messageId": "msg-001",
            "role": "ROLE_USER",
            "parts": [{"text": "What is the weather?"}]
          }
        }
      }
    },
    "id": 1
  }'
```

**Use when:**
- Integrating with MCP clients (Claude Desktop, Cline, etc.)
- Need tool discovery via `tools/list`
- Want unified interface for both MCP and A2A tools

## Fetching an Agent Card

`GET /v1/a2a/{agent_id}/card` returns the A2A AgentCard for an agent. `agent_id` is the agent's ID, the same
identifier used by `GET /v1/a2a/{agent_id}`. If no standalone agent matches, the route falls back to a virtual
server with that ID that exposes an A2A interface. The caller needs the `a2a.read` permission.

```bash
curl -s -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN" \
  http://localhost:4444/v1/a2a/$AGENT_ID/card
```

```json
{
  "name": "demo-agent",
  "description": "Demo agent",
  "url": "http://localhost:9999/",
  "version": "1",
  "protocolVersion": "1.0",
  "defaultInputModes": ["text"],
  "defaultOutputModes": ["text"],
  "capabilities": {"streaming": false, "pushNotifications": false, "stateTransitionHistory": false},
  "skills": [],
  "supportsAuthenticatedExtendedCard": true
}
```

- A missing ID, a disabled agent, and an agent the caller cannot see all return the same `404`. The response never confirms that a private agent exists.
- A virtual server card lists only the skills of attached agents that the caller can see.
- The response carries `Cache-Control: private, no-store` because its content depends on the caller.
- `supportsAuthenticatedExtendedCard` is `true`, but the gateway does not serve an extended card yet.

## Agent Skills

Set the skills an agent advertises with the top-level `skills` field on `POST /a2a` and `PUT /a2a/{agent_id}`. An update that sends only `skills` leaves `capabilities` unchanged.

```json
{
  "skills": [
    {"id": "summarize", "name": "Summarize", "description": "Summarize text", "tags": ["text"]}
  ]
}
```

- Each skill needs `id`, `name`, `description`, and `tags`. Extra keys such as `examples` pass through to the card.
- `name`, `description`, and `tags` reject HTML and script patterns.
- An agent holds at most 100 skills, each skill holds at most 50 tags, and every `id` must be unique in the list.
- `id`, `name`, and each tag are limited to the name length limit. `description` is limited to the description length limit.
- Cards read the `skills` field first. An agent without the field publishes `capabilities["skills"]`.
- An explicit `"skills": []` is authoritative. The agent publishes no skills and the `capabilities["skills"]` fallback does not apply.

## Reading an Agent Card Before Registration

`POST /v1/a2a/fetch-card` (also `/a2a/fetch-card`) reads the Agent Card of an agent that is not registered yet. The response
carries the card in the A2A 1.0 shape and a suggested set of `A2AAgentCreate` fields, so a client can pre-fill a registration form.
The route stores nothing. It needs `a2a.create`, the permission that registering the agent needs, because it makes the gateway
send an outbound request to a caller-chosen host.

```bash
curl -s -X POST -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN" -H "Content-Type: application/json" \
  -d '{"baseUrl": "https://agent.example.com"}' \
  http://localhost:4444/v1/a2a/fetch-card
```

| Request field | Meaning |
|---------------|---------|
| `baseUrl` | Agent endpoint, or a direct URL ending in `.json`. Userinfo, a query and a fragment are rejected with 422. |
| `path` | Optional card path appended to `baseUrl`. Traversal, percent-encoding, a query and a fragment are rejected with 422. |
| `headers` | Optional headers, for example `Authorization` for a protected card. Framing headers (`Content-Length`, `Transfer-Encoding`, `Connection`, `Upgrade`, `Proxy-*`), `Host` and `Accept-Encoding` are rejected. Send credentials over HTTPS only. |

Without `path`, the gateway tries `/.well-known/agent-card.json` and then `/.well-known/agent.json`.

| `outcome` | `found` | Meaning |
|-----------|---------|---------|
| `found` | `true` | A valid card. `card` is normalized to 1.0, `rawCard` is the document as fetched (omitted when identical), `suggestedAgent` maps the card, `warnings` lists what could not be mapped. |
| `no_card` | `false` | The host answered, but no valid card exists at the tried locations. A card with wrongly typed fields also reports `no_card`, for example a `streaming` that is not a boolean, or required scopes that are not a list of strings. |
| `auth_required` | `false` | The card endpoint answered 401 or 403. `authScheme` holds the `WWW-Authenticate` scheme name. Retry with `headers`. |
| `unreachable` | `false` | The outbound URL policy refused the address, the connection failed, or the search took longer than `FEDERATION_TIMEOUT`. All causes return the same response. |

Notes on the suggested mapping:

- ContextForge stores one `auth_type`. Alternative security requirements are reported in `warnings`. Schemes that one requirement lists together cannot be represented and are skipped with a warning.
- OAuth `scopes` hold only the scopes the requirement names. A requirement with no scopes requests none.
- The suggestion never contains credential values, team, visibility or tags.
- `tokenUrl` and `authorizationUrl` come from the remote card. A warning appears when either points to a host other than the agent host, or does not use `https`. Verify the URL before entering a client secret.
- A requirement that only a skill declares cannot be mapped, because ContextForge stores one authentication configuration per agent. A warning names up to three such skills. Configure their authentication manually.

The fetch applies the SSRF settings (`SSRF_ALLOW_LOCALHOST`, `SSRF_ALLOW_PRIVATE_NETWORKS`, `SSRF_BLOCKED_NETWORKS`, `SSRF_ALLOWED_NETWORKS`), does not follow redirects,
pins DNS, rejects content-encoded responses, caps the body at 1 MiB, and ends after `FEDERATION_TIMEOUT` seconds in total, including DNS resolution and every candidate URL.

## Agent Types

### Generic/JSONRPC Agents
For agents that expect standard JSONRPC format:
```json
{
  "agent_type": "jsonrpc",
  "endpoint_url": "http://your-agent/",
  "protocol_version": "1.0"
}
```

### OpenAI-compatible Agents
```json
{
  "agent_type": "openai",
  "endpoint_url": "https://api.openai.com/v1/chat/completions",
  "auth_type": "api_key",
  "auth_value": "your-openai-api-key"
}
```

### Anthropic-compatible Agents
```json
{
  "agent_type": "anthropic",
  "endpoint_url": "https://api.anthropic.com/v1/messages",
  "auth_type": "api_key",
  "auth_value": "your-anthropic-api-key"
}
```

### Custom Agents
```json
{
  "agent_type": "custom",
  "endpoint_url": "https://your-custom-agent.com/api",
  "auth_type": "bearer",
  "auth_value": "your-token",
  "capabilities": {"streaming": true, "functions": false},
  "config": {"max_tokens": 1000, "temperature": 0.7}
}
```

## Authentication Methods

| Auth Type | Description | Example |
|-----------|-------------|---------|
| `api_key` | API key in Authorization header | `Authorization: Bearer your-key` |
| `bearer` | Bearer token authentication | `Authorization: Bearer your-token` |
| `oauth` | OAuth 2.0 client credentials | The gateway gets a token from `oauth_config.token_url` and sends it as `Authorization: Bearer`. It caches the token until 30 seconds before it expires. A token with no `expires_in`, or with `expires_in` of 30 seconds or less, is not cached. The authorization-code grant is not supported. A missing `oauth_config`, an unsupported grant, or a token failure fails the invocation with an error that names the agent. |
| `none` | No authentication required | - |

When `auth_type` is `api_key`, the configured API key is sent as the outbound `Authorization` header. If a base or passthrough request header also contains `Authorization`, the configured A2A agent API key takes precedence for the outbound agent call.

## Protocol Detection

The gateway automatically detects agent protocols:

- **JSONRPC Format**: For `agent_type: "jsonrpc"` or URLs ending with `/`
- **Custom A2A Format**: For other agent types

## Monitoring and Metrics

A2A agents provide comprehensive metrics:

- **Execution Count**: Total number of invocations
- **Success Rate**: Percentage of successful calls
- **Response Times**: Min/max/average response times
- **Last Interaction**: Timestamp of most recent call
- **Error Tracking**: Failed call details and error messages

### Aggregate Metrics Endpoint

`GET /v1/a2a/metrics` returns aggregate metrics for the agents the caller can see. The route requires `a2a.read`, not `admin.metrics`.

| Caller | Agents counted |
|--------|----------------|
| Token with `teams: []` | Public |
| Token with `teams: ["t1"]` | Public, team `t1`, own private |
| Admin token with `teams: null` | Public, all team, own private |

The count includes disabled agents. `activeAgents` counts the enabled ones. An admin never counts the private agents of other users, so the result can be lower than `a2aAgents` on `GET /v1/metrics`, which aggregates every agent.

| Status | Cause |
|--------|-------|
| 200 | `A2AAgentAggregateMetrics` body |
| 401/403 | Missing authentication or missing `a2a.read` |
| 404 | `MCPGATEWAY_A2A_METRICS_ENABLED` is `false` |
| 503 | A2A service unavailable |

## Task and Push Notification Routes

ContextForge stores A2A task state and serves it under `/v1/a2a/{agent_id}/tasks`.

| Method | Path | Permission |
|--------|------|------------|
| GET | `/v1/a2a/{agent_id}/tasks` | `a2a.read` |
| GET | `/v1/a2a/{agent_id}/tasks/{task_id}` | `a2a.read` |
| POST | `/v1/a2a/{agent_id}/tasks/{task_id}/cancel` | `a2a.invoke` |
| POST | `/v1/a2a/{agent_id}/tasks/{task_id}/messages` | `a2a.invoke` |
| POST, GET | `/v1/a2a/{agent_id}/tasks/{task_id}/pushNotificationConfigs` | `a2a.update`, `a2a.read` |
| GET, DELETE | `/v1/a2a/{agent_id}/tasks/{task_id}/pushNotificationConfigs/{config_id}` | `a2a.read`, `a2a.update` |

- Tasks have no owner of their own. Access follows the agent: the agent owner, a team owner for team agents, or a platform admin. Other callers receive `404`.
- The list route returns task summaries without `history` and `artifacts`. Use the single-task route for those fields.
- The list route accepts `pageSize` (1-100) and `pageToken`. Pass `nextPageToken` from one response as `pageToken` in the next request. An empty `nextPageToken` marks the last page. A malformed `pageToken` returns `400`.
- The `state` filter accepts the A2A task states: `submitted`, `working`, `input-required`, `auth-required`, `completed`, `canceled`, `failed`, `rejected`.
- The cancel route changes the task state in the gateway only. It does not signal the remote agent. A task in a terminal state is returned unchanged.
- Creating a push notification config returns `201`. Posting the same `webhook_url` again updates the config and returns `200`. Responses never include `auth_token`.
- Cancel, follow-up message, and push config writes create audit trail entries. The follow-up entry holds IDs only.

### Follow-up Messages

`POST /v1/a2a/{agent_id}/tasks/{task_id}/messages` sends a follow-up message to an existing task, for example the answer to an `input-required` or `auth-required` task. The caller must own the agent, as on the cancel route.

```json
{"text": "Yes, proceed."}
```

Send either `text` (one text part) or `message` (an A2A message object in the 0.3 or 1.0 shape). Send exactly one of them.

- The gateway sets `taskId` and `contextId` from the stored task, sets `role` to the user role, and generates `messageId`. It converts the message for 0.3 and 1.0 agents.
- `message` accepts only `parts`, `metadata`, `extensions`, `referenceTaskIds`, and the identity fields `messageId`, `role`, `taskId`, `contextId` and `kind`. A message holds at most 50 parts. A text part and `text` hold at most 65536 characters.
- The `task_continued` event stores the message ID and the kind and length of each part. It never stores the content.
- Two follow-ups sent at the same moment can both pass the state check.

| Status | Cause |
|--------|-------|
| 200 | The agent response, unchanged. The stored task takes the state from the response. |
| 400 | `taskId` or `contextId` differs from the stored task, `role` is not the user role, or the agent call fails |
| 404 | The agent or task does not exist, or the caller does not own the agent |
| 409 | The task is in a terminal state |
| 422 | The body is invalid, has unsupported `message` fields, or exceeds the size limits |

## Lifecycle Management

### Agent-Tool State Cascade

When an A2A agent is registered, a corresponding MCP tool is automatically created (with `integration_type: "A2A"`). The agent and its tool share a linked lifecycle:

- **Deactivating an agent** automatically deactivates its associated tool, removing it from virtual server tool listings. (Invocation of disabled A2A tools was already rejected; this fix ensures the tool's own `enabled` flag stays in sync so it no longer *appears* as available.)
- **Reactivating an agent** automatically reactivates its associated tool, restoring it to virtual server tool listings.

This mirrors how MCP server (gateway) deactivation cascades to all child tools, prompts, and resources. Since each A2A agent creates a single tool, the cascade updates exactly one tool record.

!!! note
    If the tool is already in the desired state (e.g., already disabled when the agent is deactivated), no redundant database update occurs.

## Virtual Server Integration

Associate A2A agents with virtual servers to:

- **Organize agents** by purpose or team
- **Control access** via server-specific endpoints
- **Group capabilities** for specific use cases
- **Enable MCP discovery** for client tools

## Configuration

| Variable | Description | Default |
|----------|-------------|---------|
| `MCPGATEWAY_A2A_ENABLED` | Master toggle for A2A features | `true` |
| `MCPGATEWAY_A2A_MAX_AGENTS` | Maximum agents allowed | `100` |
| `MCPGATEWAY_A2A_DEFAULT_TIMEOUT` | HTTP timeout (seconds) | `30` |
| `MCPGATEWAY_A2A_MAX_RETRIES` | Retry attempts | `3` |
| `MCPGATEWAY_A2A_METRICS_ENABLED` | Enable metrics collection | `true` |

## Required Permissions

Every A2A endpoint is guarded by both layers of the security model: a token scope check
(Layer 1) followed by an RBAC check (Layer 2). A caller needs the permission below granted
by *both* — an API token scoped to `tools.read` cannot reach `/a2a` even if its user holds
the `a2a.read` role.

| Endpoint | Method | Permission |
|----------|--------|------------|
| `/a2a` | GET | `a2a.read` |
| `/a2a/{agent_id}` | GET | `a2a.read` |
| `/a2a/{agent_id}/card` | GET | `a2a.read` |
| `/a2a` | POST | `a2a.create` |
| `/a2a/fetch-card` | POST | `a2a.create` |
| `/a2a/{agent_id}` | PUT | `a2a.update` |
| `/a2a/{agent_id}/state` | POST | `a2a.update` |
| `/a2a/{agent_id}/toggle` | POST | `a2a.update` (deprecated, use `/state`) |
| `/a2a/{agent_id}` | DELETE | `a2a.delete` |
| `/a2a/invoke` | POST | `a2a.invoke` |
| `/a2a/{agent_name}/invoke` | POST | `a2a.invoke` |
| `/a2a/{agent_name}/jsonrpc` | POST | `a2a.invoke` |

A token whose scopes are empty inherits its permissions from RBAC at runtime rather than
being denied — see [Token Scope Semantics](../../manage/rbac.md#token-scope-semantics).

## Security Considerations

- **Encrypted Storage**: Agent credentials are encrypted in the database
- **Rate Limiting**: Configurable limits on agent invocations
- **Access Control**: Full authentication and authorization
- **Audit Logging**: All agent interactions are logged
- **Network Security**: HTTPS support and SSL verification

## Local Testing

### Demo A2A Agent

The repository includes a demo A2A agent with calculator and weather tools for local testing.

#### Prerequisites

Before running the demo agent, ensure the following configuration:

1. **Allow localhost in .env** (required for local agent registration)

  ```bash
  SSRF_ALLOW_LOCALHOST=true
  ```

  Restart ContextForge after adding this. The default blocks loopback addresses as an SSRF safeguard. This is intentional for production, but must be opted into locally.

2. **Pass an admin identity at runtime**

  The script creates a JWT signed with your instance's secret. The token identity must resolve to a user in the
  database. The helper commands below pass your `PLATFORM_ADMIN_EMAIL` as a legacy email subject; service-issued tokens
  now use opaque UUID subjects for token-catalog API tokens platform-wide and carry the human email in signed metadata
  such as `user.email`. See the "Running the Demo" section below for the actual commands.

#### Running the Demo

```bash
# Terminal 1: Start ContextForge
make dev

# Terminal 2: Start the demo agent (auto-registers with ContextForge)
# Override the admin email if it differs from the default:
#   export PLATFORM_ADMIN_EMAIL=you@example.com
uv run python scripts/demo_a2a_agent.py

# Optional: Generate a token for the curl test commands below
export TOKEN=$(python -m mcpgateway.utils.create_jwt_token \
  --username "admin@example.com" --exp 60)
```

Note: The script reads `JWT_SECRET_KEY` and `PLATFORM_ADMIN_EMAIL` from environment variables (defaults: `my-test-key…` and `admin@example.com`).

The demo agent supports these query formats:

| Query | Example | Response |
|-------|---------|----------|
| Calculator | `calc: 7*8+2` | `58` |
| Weather | `weather: Dallas` | `The weather in Dallas is sunny, 25C` |

**Test via Admin UI:**

1. Go to `http://localhost:8000/admin`
2. Click the "A2A Agents" tab
3. Add a new agent "demo-calculator-agent" with Endpoint URL of http://localhost:9100/run
4. In "demo-calculator-agent" click on **Test**
5. Enter a query like `calc: 100/4+25` in the modal
6. Click **Run Test** to see the result

**Test via API:**

```bash
# Get a token
export TOKEN=$(python3 -m mcpgateway.utils.create_jwt_token \
  --username admin@example.com --exp 60)

curl -X POST "http://localhost:8000/a2a/demo-calculator-agent/invoke" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"parameters": {"query": "calc: 15*4+10"}}'
```

### A2A SDK HelloWorld Sample

Test with the official A2A Python SDK sample:

```bash
# Clone and run the HelloWorld agent
git clone https://github.com/google/a2a-samples.git
cd a2a-samples/samples/python/agents/helloworld
uv run python __main__.py  # Starts on port 9999

# Register with ContextForge (in another terminal)
export TOKEN=$(python3 -m mcpgateway.utils.create_jwt_token \
  --username admin@example.com --exp 60 --secret my-test-key-but-now-longer-than-32-bytes)

curl -X POST "http://localhost:8000/a2a" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "agent": {
      "name": "Hello World Agent",
      "endpoint_url": "http://localhost:9999/",
      "agent_type": "jsonrpc",
      "description": "Official A2A SDK HelloWorld sample"
    },
    "visibility": "public"
  }'
```

### Admin UI Query Input

The Admin UI test button opens a modal where you can enter custom queries:

1. **Open Modal**: Click the blue **Test** button next to any A2A agent
2. **Enter Query**: Type your query in the textarea (e.g., `calc: 5*10+2`)
3. **Run Test**: Click **Run Test** to send the query to the agent
4. **View Response**: The agent's response appears in the modal

This allows testing A2A agents with real user queries instead of hardcoded test messages.

### Testing via MCP Tools

A2A agents are automatically exposed as MCP tools. After registration, invoke them via the MCP protocol:

```bash
curl -X POST "http://localhost:8000/rpc" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc": "2.0",
    "method": "tools/call",
    "params": {
      "name": "a2a_demo-calculator-agent",
      "arguments": {"query": "calc: 99+1"}
    },
    "id": 1
  }'
```

## Troubleshooting

### Agent Not Responding
1. Check agent status in Admin UI (should be "Active" and "Reachable")
2. Verify endpoint URL is correct and accessible
3. Test authentication credentials
4. Check agent logs for protocol format issues

### Protocol Format Issues
1. Verify agent expects JSONRPC format vs custom format
2. Check required fields in agent's API documentation
3. Use Admin UI test button to validate communication
4. Review gateway logs for request/response details

### Authentication Problems
1. Verify auth_type matches agent's expected authentication
2. Check auth_value is correct and not expired
3. Test direct agent communication outside gateway
4. Review agent's authentication documentation

---

For more information on ContextForge features and configuration, see the [main documentation](../../overview/index.md).
