# Orchestrate API — Cancellation

## POST /orchestrate/cancel
Request cancellation for a long-running tool execution (gateway-authoritative).

Request body (application/json):

{
  "requestId": "<string>",
  "reason": "<string|null>"
}

Response 200 (application/json):

{
  "status": "cancelled" | "queued",
  "requestId": "<string>",
  "reason": "<string|null>"
}

Notes:
- The gateway will attempt to cancel a local run if registered and will broadcast a JSON-RPC notification to connected sessions:
```
{"jsonrpc":"2.0","method":"notifications/cancelled","params":{"requestId":"<id>","reason":"<reason>"}}
```
- `status == "cancelled"` indicates the gateway found the run locally and attempted cancellation.
- `status == "queued"` indicates the gateway did not find the run locally but broadcasted the notification for remote peers to handle.

Permissions: `admin.system_config` by default (RBAC). Adjust as appropriate for your deployment.

## GET /orchestrate/status/{request_id}
Query the status of a registered tool execution run.

Path parameters:
- `request_id` (string, required): The unique identifier of the run to query

Response 200 (application/json):

{
  "name": "<string|null>",
  "registered_at": <float>,
  "cancelled": <boolean>,
  "cancelled_at": <float|null>,
  "cancel_reason": "<string|null>"
}

Response 404 (application/json):

{
  "detail": "Run not found"
}

Notes:
- Returns the current status of a registered run including cancellation state
- `registered_at` is a Unix timestamp (seconds since epoch)
- `cancelled_at` is present only if the run has been cancelled
- `cancel_reason` contains the reason provided during cancellation (if any)

Permissions: `admin.system_config` by default (RBAC). Adjust as appropriate for your deployment.

## Current Limitations

### Tool Registration Scope

Currently, only tool executions initiated through the LLMChat service (`/llmchat/chat` endpoint with LangChain agents) are automatically registered for cancellation tracking. Direct JSON-RPC `tools/call` requests are not registered.

### Broadcast Scope (Single-Process)

The `notifications/cancelled` broadcast currently enumerates sessions from the local in-memory session registry. In multi-worker deployments with Redis or database session backends, this broadcast will not reach sessions on other workers. For true gateway-authoritative cancellation across a cluster, additional coordination via Redis pubsub is recommended.

### Cancellation Semantics

Cancellation is **best-effort** per the MCP specification:

- The gateway marks the run as cancelled and invokes any registered callback
- The registered callback is currently a no-op placeholder; actual interruption of in-progress tool execution is not yet implemented
- For tools forwarded to external MCP servers, the `notifications/cancelled` broadcast allows those servers to handle cancellation
