# Tool Plugin Bindings API

Per-tool, per-tenant plugin policy configuration for ContextForge.

## Overview

The Tool Plugin Bindings API lets you configure which plugins run on a specific tool for a specific team — and override the plugin's global `config.yaml` settings with team/tool-specific parameters.

A **binding** is a `(team_id, tool_name, plugin_id)` triple with an associated `mode`, `priority`, and plugin-specific `config`. Bindings are resolved at tool-invoke time and merged on top of the global plugin configuration.

### Supported plugins

| `plugin_id`          | Plugin class name          | Hook phase        | What it does                                       |
|----------------------|----------------------------|-------------------|----------------------------------------------------|
| `OUTPUT_LENGTH_GUARD`| `OutputLengthGuardPlugin`  | `tool_post_invoke`| Truncates or blocks responses that exceed a character limit |
| `RATE_LIMITER`       | `RateLimiterPlugin`        | `tool_pre_invoke` | Throttles calls per user, tenant, or tool          |
| `SECRETS_DETECTION`  | `SecretsDetection`         | `tool_post_invoke`| Detects and optionally redacts/blocks secrets in outputs |

---

## Authentication

All endpoints require a **Bearer JWT** token.

```
Authorization: Bearer <token>
```

Generate a token:

```bash
export TOKEN=$(python -m mcpgateway.utils.create_jwt_token \
  --username admin@example.com --exp 10080 --secret "$JWT_SECRET_KEY")
```

### Required permissions

| Operation         | Required permission       |
|-------------------|---------------------------|
| Create / update   | `tools.manage_plugins`    |
| Read (list)       | `tools.read`              |
| Delete            | `tools.manage_plugins`    |

Non-admin callers may only create bindings for teams they belong to. Attempting to configure bindings for another team returns **403**.

---

## Endpoints

### `POST /v1/tools/plugin_bindings`

**Upsert** one or more bindings. Each `(team_id, tool_name, plugin_id)` triple is:

- **Updated in place** if a row already exists (the `id`, `created_at`, and `created_by` are preserved).
- **Inserted** if no matching row exists.

**Stale tool pruning**: when a policy includes a `binding_reference_id`, any existing binding that shares the same `binding_reference_id` and `plugin_id` but whose `tool_name` is **not** in the incoming `tool_names` list is automatically deleted. This keeps the stored state in sync when an external system sends a full replacement tool list on an update event.

On success, returns **all created/updated** bindings and immediately invalidates the in-process plugin cache so the new config takes effect on the very next tool call.

#### Request body

```json
{
  "teams": {
    "<team_id>": {
      "policies": [
        {
          "tool_names": ["<tool_name_1>", "<tool_name_2>"],
          "plugin_id": "<PLUGIN_ID>",
          "mode": "enforce | permissive | disabled",
          "priority": 10,
          "binding_reference_id": "<EXTERNAL_BINDING_ID>",
          "config": { /* plugin-specific — see below */ }
        }
      ]
    }
  }
}
```

| Field                       | Type            | Required | Default    | Notes                                                              |
|-----------------------------|-----------------|----------|------------|--------------------------------------------------------------------|
| `teams`                     | object          | ✅        | —          | Keys are `team_id` strings                                         |
| `teams.<id>.policies`       | array           | ✅        | —          | At least one item required                                         |
| `policies[].tool_names`     | string[]        | ✅        | —          | Use `["*"]` to match all tools in the team                         |
| `policies[].plugin_id`      | enum string     | ✅        | —          | `OUTPUT_LENGTH_GUARD`, `RATE_LIMITER`, or `SECRETS_DETECTION`      |
| `policies[].mode`           | enum string     | ❌        | `enforce`  | `enforce` = fail on violation; `permissive` = log only; `disabled` = skip |
| `policies[].priority`       | int (1–1000)    | ❌        | `50`       | Lower runs first                                                    |
| `policies[].binding_reference_id` | string   | ❌        | `null`     | External reference ID for correlating this binding with an upstream system. Used for stale-tool pruning on update and bulk delete. |
| `policies[].config`         | object          | ✅        | —          | All config fields for the plugin must be present (full replace, no partial patch) |

#### `mode` semantics

| Value        | Behaviour                                                                 |
|--------------|---------------------------------------------------------------------------|
| `enforce`    | Plugin runs; violations raise an error / block the response               |
| `permissive` | Plugin runs; violations are logged but the response is still returned     |
| `disabled`   | Plugin is skipped entirely for this binding                               |

> **Note:** A binding with `mode: "enforce"` **overrides** a global `mode: "disabled"` in `config.yaml`. Use this to selectively enable a plugin for one team without enabling it globally.

---

### `GET /v1/tools/plugin_bindings`

List all bindings across all teams (admin use).

| Query param            | Type   | Required | Description                                          |
|------------------------|--------|----------|------------------------------------------------------|
| `binding_reference_id` | string | ❌        | Filter — return only bindings with this reference ID |

```bash
# All bindings
curl -s -H "Authorization: Bearer $TOKEN" \
  http://<GATEWAY_HOST>:<GATEWAY_PORT>/v1/tools/plugin_bindings | jq

# Filtered by external reference ID
curl -s -H "Authorization: Bearer $TOKEN" \
  "http://<GATEWAY_HOST>:<GATEWAY_PORT>/v1/tools/plugin_bindings?binding_reference_id=<EXTERNAL_REFERENCE_ID>" | jq
```

---

### `GET /v1/tools/plugin_bindings/{team_id}`

List all bindings for a specific team.

| Query param            | Type   | Required | Description                                                                                          |
|------------------------|--------|----------|------------------------------------------------------------------------------------------------------|
| `binding_reference_id` | string | ❌        | If provided, **takes precedence over `team_id`** — returns all bindings with this reference ID across all teams |

```bash
# All bindings for a team
curl -s -H "Authorization: Bearer $TOKEN" \
  http://<GATEWAY_HOST>:<GATEWAY_PORT>/v1/tools/plugin_bindings/<YOUR_TEAM_ID> | jq

# Filtered by external reference ID (team_id is ignored when binding_reference_id is present)
curl -s -H "Authorization: Bearer $TOKEN" \
  "http://<GATEWAY_HOST>:<GATEWAY_PORT>/v1/tools/plugin_bindings/<YOUR_TEAM_ID>?binding_reference_id=<EXTERNAL_REFERENCE_ID>" | jq
```

---

### `DELETE /v1/tools/plugin_bindings?binding_reference_id={ref}`

Delete **all** bindings tagged with the given external reference ID. Intended for external systems that need to remove all bindings associated with one of their own reference objects without knowing the internal ContextForge UUIDs.

Returns the deleted records. Returns an empty list (not an error) if no bindings matched.

```bash
curl -s -X DELETE \
  -H "Authorization: Bearer $TOKEN" \
  "http://<GATEWAY_HOST>:<GATEWAY_PORT>/v1/tools/plugin_bindings?binding_reference_id=<EXTERNAL_REFERENCE_ID>" | jq

Delete a single binding by its UUID. Returns the deleted record.

```bash
curl -s -X DELETE \
  -H "Authorization: Bearer $TOKEN" \
  http://<GATEWAY_HOST>:<GATEWAY_PORT>/v1/tools/plugin_bindings/3f2504e0-4f89-11d3-9a0c-0305e82c3301 | jq
```

---

## Response schema

All write operations (`POST`, `DELETE`) and read operations (`GET`) return the same shape.

### `ToolPluginBindingResponse`

```json
{
  "id": "3f2504e0-4f89-11d3-9a0c-0305e82c3301",
  "team_id": "<YOUR_TEAM_ID>",
  "tool_name": "echo_text",
  "plugin_id": "OUTPUT_LENGTH_GUARD",
  "mode": "enforce",
  "priority": 10,
  "config": {
    "min_chars": 0,
    "max_chars": 2000,
    "strategy": "truncate",
    "ellipsis": "..."
  },
  "binding_reference_id": "<EXTERNAL_REFERENCE_ID>",
  "created_at": "2026-04-07T17:00:00Z",
  "created_by": "admin@example.com",
  "updated_at": "2026-04-07T17:05:00Z",
  "updated_by": "admin@example.com"
}
```

### `ToolPluginBindingListResponse`

```json
{
  "bindings": [ /* array of ToolPluginBindingResponse */ ],
  "total": 3
}
```

---

## Plugin config payloads

The `config` object in a policy item **must include all fields** for the plugin. On upsert the config is fully replaced — fields you omit revert to the plugin's built-in defaults.

---

### `OUTPUT_LENGTH_GUARD`

Enforces a character-count budget on tool outputs. Responses that exceed `max_chars` are either truncated (with an optional `ellipsis` suffix) or blocked entirely.

**Hooks:** `tool_post_invoke`

```json
{
  "min_chars": 0,
  "max_chars": 2000,
  "strategy": "truncate",
  "ellipsis": "..."
}
```

| Field       | Type                     | Default    | Constraints       | Description                                      |
|-------------|--------------------------|------------|-------------------|--------------------------------------------------|
| `min_chars` | integer                  | `0`        | `>= 0`            | Minimum allowed character count (0 = no minimum) |
| `max_chars` | integer                  | `2000`     | `> 1`             | Maximum allowed character count                  |
| `strategy`  | `"truncate"` \| `"block"` | `"truncate"` | —               | `truncate` = cut output; `block` = return error  |
| `ellipsis`  | string                   | `"..."`    | max length 20     | Suffix appended to truncated output              |

**Validation:** `min_chars` must be strictly less than `max_chars`.

#### Example — truncate at 500 chars

```bash
curl -s -X POST \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "teams": {
      "<YOUR_TEAM_ID>": {
        "policies": [{
          "tool_names": ["echo_text"],
          "plugin_id": "OUTPUT_LENGTH_GUARD",
          "mode": "enforce",
          "priority": 10,
          "config": {
            "min_chars": 0,
            "max_chars": 500,
            "strategy": "truncate",
            "ellipsis": "…"
          }
        }]
      }
    }
  }' \
  http://<GATEWAY_HOST>:<GATEWAY_PORT>/v1/tools/plugin_bindings | jq
```

#### Example — block responses over 1000 chars

```json
{
  "min_chars": 0,
  "max_chars": 1000,
  "strategy": "block",
  "ellipsis": "..."
}
```

---

### `RATE_LIMITER`

Throttles tool invocations before they are dispatched. Limits can be set independently for the calling user, the tenant (team), and the tool itself. At least one limit field must be non-null.

**Hooks:** `tool_pre_invoke`

Rate strings use the format `<count>/<period>` where period is `s` (second) or `m` (minute).

```json
{
  "by_user":   "60/m",
  "by_tenant": "600/m",
  "by_tool":   "10/s"
}
```

| Field       | Type            | Default | Format            | Description                              |
|-------------|-----------------|---------|-------------------|------------------------------------------|
| `by_user`   | string \| null  | `null`  | `<int>/s` or `<int>/m` | Per-user rate limit                |
| `by_tenant` | string \| null  | `null`  | `<int>/s` or `<int>/m` | Per-tenant (team) rate limit       |
| `by_tool`   | string \| null  | `null`  | `<int>/s` or `<int>/m` | Per-tool rate limit                |

**Validation:** Each non-null value must match `^\d+/[sm]$`.

#### Example — 30 calls/min per user, 300/min per tenant

```bash
curl -s -X POST \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "teams": {
      "<YOUR_TEAM_ID>": {
        "policies": [{
          "tool_names": ["*"],
          "plugin_id": "RATE_LIMITER",
          "mode": "enforce",
          "priority": 5,
          "config": {
            "by_user":   "30/m",
            "by_tenant": "300/m",
            "by_tool":   null
          }
        }]
      }
    }
  }' \
  http://<GATEWAY_HOST>:<GATEWAY_PORT>/v1/tools/plugin_bindings | jq
```

> Using `["*"]` as `tool_names` applies the rate limit to every tool in the team.

---

### `SECRETS_DETECTION`

Scans tool outputs for common secret patterns (AWS keys, GCP API keys, Slack tokens, private keys, JWTs, hex secrets, etc.). Can redact findings or block the response.

**Hooks:** `tool_post_invoke`

```json
{
  "enabled": {
    "aws_access_key_id":     true,
    "aws_secret_access_key": true,
    "google_api_key":        true,
    "slack_token":           true,
    "private_key_block":     true,
    "jwt_like":              true,
    "hex_secret_32":         true,
    "base64_24":             false
  },
  "redact":              true,
  "redaction_text":      "[REDACTED]",
  "block_on_detection":  false,
  "min_findings_to_block": 1
}
```

| Field                   | Type              | Default           | Constraints         | Description                                                              |
|-------------------------|-------------------|-------------------|---------------------|--------------------------------------------------------------------------|
| `enabled`               | object            | see below         | —                   | Map of pattern name → boolean; controls which detectors are active       |
| `redact`                | boolean           | `true`            | —                   | Replace detected secrets with `redaction_text`                           |
| `redaction_text`        | string            | `"[REDACTED]"`    | max length 50       | Replacement text for redacted secrets                                    |
| `block_on_detection`    | boolean           | `false`           | —                   | Return an error response instead of (possibly redacted) output           |
| `min_findings_to_block` | integer           | `1`               | `>= 1`              | Number of findings required before blocking triggers                     |

**Pattern names for `enabled` map:**

| Pattern key               | What it matches                                |
|---------------------------|------------------------------------------------|
| `aws_access_key_id`       | AWS access keys (`AKIA…`)                      |
| `aws_secret_access_key`   | AWS secret keys (40-char alphanumeric)         |
| `google_api_key`          | GCP API keys (`AIza…`)                         |
| `slack_token`             | Slack bot / user tokens (`xox[bprs]-…`)        |
| `private_key_block`       | PEM private key blocks                         |
| `jwt_like`                | JWT-shaped tokens (three base64url segments)   |
| `hex_secret_32`           | 32-character hexadecimal strings               |
| `base64_24`               | 24+ char base64 strings (high false-positive rate — keep `false` unless needed) |

#### Example — redact AWS keys and JWTs, block on any finding

```bash
curl -s -X POST \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "teams": {
      "<YOUR_TEAM_ID>": {
        "policies": [{
          "tool_names": ["fetch_data", "query_db"],
          "plugin_id": "SECRETS_DETECTION",
          "mode": "enforce",
          "priority": 20,
          "config": {
            "enabled": {
              "aws_access_key_id":     true,
              "aws_secret_access_key": true,
              "google_api_key":        false,
              "slack_token":           false,
              "private_key_block":     true,
              "jwt_like":              true,
              "hex_secret_32":         false,
              "base64_24":             false
            },
            "redact":              true,
            "redaction_text":      "[REDACTED]",
            "block_on_detection":  true,
            "min_findings_to_block": 1
          }
        }]
      }
    }
  }' \
  http://<GATEWAY_HOST>:<GATEWAY_PORT>/v1/tools/plugin_bindings | jq
```

---

## Multi-plugin, multi-team example

A single `POST` can configure multiple plugins across multiple teams:

```bash
curl -s -X POST \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "teams": {
      "team_id": {
        "policies": [
          {
            "tool_names": ["*"],
            "plugin_id": "RATE_LIMITER",
            "mode": "enforce",
            "priority": 5,
            "config": {
              "by_user": "60/m",
              "by_tenant": "600/m",
              "by_tool": null
            }
          },
          {
            "tool_names": ["summarize_doc", "extract_invoice"],
            "plugin_id": "OUTPUT_LENGTH_GUARD",
            "mode": "enforce",
            "priority": 10,
            "config": {
              "min_chars": 0,
              "max_chars": 4000,
              "strategy": "truncate",
              "ellipsis": "…"
            }
          }
        ]
      },
      "team_beta": {
        "policies": [
          {
            "tool_names": ["*"],
            "plugin_id": "SECRETS_DETECTION",
            "mode": "enforce",
            "priority": 20,
            "config": {
              "enabled": {
                "aws_access_key_id":     true,
                "aws_secret_access_key": true,
                "google_api_key":        true,
                "slack_token":           true,
                "private_key_block":     true,
                "jwt_like":              true,
                "hex_secret_32":         true,
                "base64_24":             false
              },
              "redact":              true,
              "redaction_text":      "[REDACTED]",
              "block_on_detection":  false,
              "min_findings_to_block": 1
            }
          }
        ]
      }
    }
  }' \
  http://<GATEWAY_HOST>:<GATEWAY_PORT>/v1/tools/plugin_bindings | jq
```

---

## Error responses

| HTTP status | When                                                                     |
|-------------|--------------------------------------------------------------------------|
| `400`       | Invalid request payload (missing fields, bad config values)              |
| `401`       | Missing or invalid Bearer token                                          |
| `403`       | Caller lacks `tools.manage_plugins` or configuring bindings for a team they don't belong to |
| `404`       | Binding ID not found (DELETE `/{binding_id}` only)                       |

### Example 400 — bad `OUTPUT_LENGTH_GUARD` config

```json
{
  "detail": "Invalid OUTPUT_LENGTH_GUARD config: [min_chars must be less than max_chars]"
}
```

### Example 400 — invalid rate string

```json
{
  "detail": "Invalid RATE_LIMITER config: [by_user: Rate string '5/h' is invalid. Use format '<count>/s' or '<count>/m']"
}
```

---

## How bindings are resolved at runtime

1. When a tool is invoked, `tool_service.py` computes a **context ID**: `"{team_id}::{tool_name}"`.
2. `GatewayTenantPluginManagerFactory.get_config_from_db()` fetches all DB bindings for the `(team_id, tool_name)` pair, including any wildcard `*` bindings.
3. For each binding, the DB `mode` and `config` are merged over the global `config.yaml` values (`_merge_tenant_config`). DB values always win.
4. A **`TenantPluginManager`** is instantiated with the merged config and cached in memory, keyed by context ID.
5. On upsert or delete, the cache entry is invalidated immediately so the next call picks up the new config.

### Priority execution order

Plugins with lower `priority` values run first. The default is `50`. Example ordering:

```
priority 5  → RATE_LIMITER   (gate-keep before any work is done)
priority 10 → OUTPUT_LENGTH_GUARD
priority 20 → SECRETS_DETECTION
```
