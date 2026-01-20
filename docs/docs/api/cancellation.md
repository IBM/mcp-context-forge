# Cancellation API — Tool Cancellation

> **Configuration:** This feature is controlled by the `MCPGATEWAY_TOOL_CANCELLATION_ENABLED`
> environment variable (default: `true`). When disabled, these endpoints will return 404
> and tool executions will not be tracked for cancellation.

## Configuration

```bash
# Enable tool cancellation (default)
MCPGATEWAY_TOOL_CANCELLATION_ENABLED=true

# Disable tool cancellation
MCPGATEWAY_TOOL_CANCELLATION_ENABLED=false
```

When disabled:
- `POST /cancellation/cancel` returns 404
- `GET /cancellation/status/{id}` returns 404
- Tool executions are not registered for cancellation
- No overhead from cancellation tracking

## POST /cancellation/cancel
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

## GET /cancellation/status/{request_id}
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

## Implementation Details

### Tool Registration

Tool executions are automatically registered for cancellation tracking in the following scenarios:

1. **JSON-RPC `tools/call` requests**: All tool invocations via the JSON-RPC protocol are registered with their request ID for cancellation support
2. **LLMChat service**: Tool executions initiated through the `/llmchat/chat` endpoint with LangChain agents are also registered

### Multi-Worker Support (Redis Pubsub)

The cancellation service supports multi-worker deployments through Redis pubsub:

- Cancellation requests are published to the `cancellation:cancel` Redis channel
- All workers subscribe to this channel and process cancellation events
- This ensures cancellations propagate across the entire cluster, not just the local worker
- The service automatically initializes Redis pubsub on startup if Redis is configured

### Actual Task Interruption

The implementation provides **real task cancellation** beyond just marking runs as cancelled:

- Tool executions are wrapped in `asyncio.Task` objects
- The cancel callback invokes `task.cancel()` to immediately interrupt the running task
- Cancelled tasks raise `asyncio.CancelledError`, which is caught and converted to a JSON-RPC error response
- This provides immediate interruption of long-running tool executions

### Cancellation Semantics

Cancellation follows the MCP specification with enhanced implementation:

- The gateway marks the run as cancelled and invokes the registered callback
- The callback performs actual task cancellation via `asyncio.Task.cancel()`
- A `notifications/cancelled` broadcast is sent to all connected sessions
- For tools forwarded to external MCP servers, the broadcast allows those servers to handle cancellation
- Cancellation is **best-effort** but provides immediate interruption for local tool executions

### Error Handling

- Broadcast errors to individual sessions are logged but don't prevent cancellation
- Failed Redis pubsub operations are logged as warnings but don't block local cancellation
- Cancelled tasks return a JSON-RPC error with code `-32800` and details about the cancellation

### Limitations

- **Session broadcast scope**: The `notifications/cancelled` broadcast is sent to sessions connected to the local worker only. In multi-worker deployments, each worker broadcasts to its own sessions independently. Redis pubsub ensures cancellation callbacks are triggered on all workers, but session notifications are worker-local.
- **Pre-registration cancellations**: If a cancellation request arrives before the tool execution is registered (race condition), the cancellation will be queued but won't affect the subsequently registered run. The run will proceed normally unless cancelled again after registration.
- **Callback timing**: The cancel callback is invoked at registration time with a reference to the asyncio task. If cancellation occurs in the brief window between registration and task creation, the callback will safely no-op (task is None) and the run will be marked cancelled. A post-creation re-check ensures the task is cancelled if this race occurs.
