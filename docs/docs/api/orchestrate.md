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
