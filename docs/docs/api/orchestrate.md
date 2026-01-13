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
