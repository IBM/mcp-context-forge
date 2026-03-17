# Error Model

Modules in different languages must still present a coherent failure model to
the core and to clients.

## Canonical Error Categories

| Category | Meaning |
|----------|---------|
| `INVALID_ARGUMENT` | Client supplied malformed or semantically invalid input |
| `UNAUTHENTICATED` | Caller identity could not be established |
| `PERMISSION_DENIED` | Caller is authenticated but not allowed |
| `NOT_FOUND` | Resource intentionally absent or hidden |
| `CONFLICT` | Request conflicts with current state |
| `FAILED_PRECONDITION` | State is valid but not ready for this operation |
| `RATE_LIMITED` | Policy denied due to rate or quota |
| `UNSUPPORTED` | Optional feature or method is not supported |
| `UNAVAILABLE` | Core, module, or upstream dependency is temporarily unavailable |
| `UPSTREAM_ERROR` | Upstream protocol peer failed |
| `INTERNAL` | Unexpected internal failure |

## Required Error Envelope

Every structured module error should include:

- canonical category
- stable machine-readable code
- human-readable message safe for clients
- origin
  - `module`
  - `core`
  - `plugin`
  - `upstream`
- retryability hint
- trace or correlation id when available

Example:

```json
{
  "error": {
    "category": "PERMISSION_DENIED",
    "code": "a2a.invoke.denied",
    "message": "Access denied",
    "origin": "core",
    "retryable": false,
    "traceId": "trace-123"
  }
}
```

## Safety Rules

- Do not expose stack traces to clients.
- Do not expose raw `err.to_string()` data from internal libraries on public
  paths.
- Hide existence where the current product intentionally uses not-found
  semantics for protected records.
- Preserve protocol-correct error mapping where the protocol defines it.

## Mapping Guidance

| Canonical category | HTTP | gRPC |
|-------------------|------|------|
| `INVALID_ARGUMENT` | `400` | `INVALID_ARGUMENT` |
| `UNAUTHENTICATED` | `401` | `UNAUTHENTICATED` |
| `PERMISSION_DENIED` | `403` | `PERMISSION_DENIED` |
| `NOT_FOUND` | `404` | `NOT_FOUND` |
| `CONFLICT` | `409` | `ALREADY_EXISTS` or `ABORTED` |
| `FAILED_PRECONDITION` | `412` or `400` | `FAILED_PRECONDITION` |
| `RATE_LIMITED` | `429` | `RESOURCE_EXHAUSTED` |
| `UNSUPPORTED` | `400`, `404`, or protocol-specific unsupported response | `UNIMPLEMENTED` |
| `UNAVAILABLE` | `503` | `UNAVAILABLE` |
| `UPSTREAM_ERROR` | `502` | `UNKNOWN` or mapped upstream status |
| `INTERNAL` | `500` | `INTERNAL` |

Protocol-specific documents may add more precise mappings, but they must not
break these semantics.
