# REST Tool Gateway Delegation

## Overview

A REST tool can delegate two things to the gateway it belongs to:

- **Endpoint delegation.** The tool stores a path, not a full URL. ContextForge joins the path to the gateway URL on each call.
- **Credential inheritance.** The tool stores no credential. ContextForge sends the credential of the gateway on each call.

Both features are explicit per tool. A tool that sets neither keeps its own `url` and its own authentication.

Credential inheritance follows the same model as [SigV4 inheritance](sigv4-gateway-auth.md#sign-rest-tool-calls). The tool must name a gateway. The caller must own that gateway. A public gateway does not grant its credential.

!!! tip "Gateway URL"
    - Direct installs (`uvx`, pip, or `docker run`): `http://localhost:4444`
    - Docker Compose (nginx proxy): `http://localhost:8080`
    - Dev server (`make dev`): `http://localhost:8000`

## Prerequisites

- A gateway with a `url`. For credential inheritance, the gateway also needs a supported `auth_type`.
- A ContextForge API token with permission to create tools.
- A migration: `c4e8a1d7b392` adds the `tools.endpoint` column. Restart the gateway or run `alembic upgrade head`.

## Delegate the endpoint

Set `endpoint` and `gateway_id`. Omit `url`.

```bash
curl -sS -X POST "$GW/tools" \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{
    "tool": {
      "name": "orders-api",
      "endpoint": "/api/orders/{id}",
      "integration_type": "REST",
      "request_type": "GET",
      "gateway_id": "<gateway-id>"
    }
  }'
```

Rules:

- A tool with `endpoint` must be a REST tool with a `gateway_id`. A tool with `endpoint` rejects `url`.
- `endpoint` is a path. It starts with a single `/`. It holds no host, no `.` or `..` segment, no encoded `/`, `\` or `.`, no `@`, no `#`, and no control character. The limit is 767 characters.
- `endpoint` can carry a query, for example `/api/orders?expand=true`. URL template values such as `{id}` work as in `url`.
- The caller must see the gateway under the usual visibility rules, including the team scope of the token. Ownership is not required, because the tool sends no gateway credential.
- A request without a caller identity fails. An unknown gateway ID and a hidden gateway return the same error.

### How the URL resolves

ContextForge keeps the path of the gateway URL as a prefix and appends the endpoint.

| Gateway URL | `endpoint` | Request URL |
|-------------|------------|-------------|
| `https://api.example.com` | `/v1/items/{id}` | `https://api.example.com/v1/items/{id}` |
| `https://api.example.com/base/` | `/v1/items?expand=true` | `https://api.example.com/base/v1/items?expand=true` |
| `http://host/mcp` | `/api/orders` | `http://host/mcp/api/orders` |

The call fails and sends no request when the gateway URL has a query or a fragment. Change the gateway URL to a plain URL, or use `url` on the tool.

A change to the gateway URL moves every delegating tool of that gateway. No tool update is needed.

## Inherit the gateway credential

Set `auth_type` to `inherit` and `gateway_id`. Omit `auth_value`, `auth`, and `sigv4_config`.

```bash
curl -sS -X POST "$GW/tools" \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{
    "tool": {
      "name": "secure-orders-api",
      "endpoint": "/api/secure/orders",
      "integration_type": "REST",
      "request_type": "GET",
      "auth_type": "inherit",
      "gateway_id": "<gateway-id>"
    }
  }'
```

`inherit` works with `endpoint` or with a full `url`. Use both for a tool that stores neither a host nor a credential.

### Supported gateway authentication

| Gateway `auth_type` | Header the tool sends |
|---------------------|-----------------------|
| `basic` | The `Authorization` header of the gateway. |
| `bearer` | The `Authorization` header of the gateway. |
| `authheaders` | Each stored header of the gateway. |
| `oauth` with `client_credentials` or `password` | `Authorization: Bearer <token>`. ContextForge fetches the token for the gateway. |

These gateways are not inheritable: `query_param`, `sigv4`, `token-exchange`, `oauth` with `authorization_code`, and a gateway with no authentication. A `sigv4` gateway keeps its own inheritance with `auth_type: "sigv4"`.

### Who can inherit

- The caller must see the gateway under the usual visibility rules, including the team scope of the token.
- The caller must also own the gateway, hold the team owner role for it, or be a platform admin. A public gateway does not grant the credential to other callers. Otherwise the request fails with HTTP 403.
- ContextForge repeats the check when an update changes a tool to `inherit`, or changes the `url` or `endpoint` of an inheriting tool.
- Bulk registration applies the check to each inheriting tool. The tool is rejected and counted as failed, and the rest of the batch continues.
- A tool never stores the credential. A read of the tool returns `auth_type: "inherit"` and no secret.
- A client `Authorization` header never replaces the inherited credential.

## Update and remove

- Set `auth_type` to another value on `PUT /tools/{id}` to drop inheritance. Send the new credential with it.
- Send a `url` on `PUT /tools/{id}` to return to a standalone tool. The update clears `endpoint`. Send an `endpoint` to switch back, which clears `url`.
- A change to the gateway credential reaches every inheriting tool on the next call. Rotate it on the gateway.

## Export and import

Export skips tools that use `endpoint` or `auth_type: "inherit"`, so a gateway credential or a gateway-relative path never reaches an export file. Register those tools through the API after an import. Import does not create them.

## Limits

- Only REST tools accept `endpoint` and `inherit`. MCP tools from a gateway use the gateway transport and credential already.
- Inheritance sends the gateway credential to the resolved tool URL. When a tool uses its own `url`, the owner of the gateway decides where the credential goes. Use `endpoint` to keep the request on the gateway host.
- The Admin UI tool forms have no `endpoint` or `inherit` option. Use the API.
- The downgrade of migration `c4e8a1d7b392` drops `tools.endpoint`. It first disables each tool that has an `endpoint` or `auth_type = 'inherit'`, and clears its `auth_type`. Set a `url` and an auth type, then re-enable the tool.

## Troubleshooting

| Symptom | Likely cause |
|---------|--------------|
| `422` on `POST /tools` with `endpoint` | The path is not valid, the tool has a `url`, the tool is not REST, or `gateway_id` is missing. |
| `403` with "Only the owner of the gateway can use its credential" | The caller does not own the gateway. Ask the owner to register the tool. |
| `403` with "No access to the gateway" | The gateway is hidden from the caller, or the ID is wrong. |
| `400` with "The gateway does not use an authentication type that tools can inherit" | The gateway has no authentication, or uses an unsupported type. |
| Call fails with "The gateway URL must not hold a query or fragment" | Remove the query or fragment from the gateway URL. |
| `no such column: endpoint` | The database lacks migration `c4e8a1d7b392`. Restart the gateway or run `alembic upgrade head`. |
