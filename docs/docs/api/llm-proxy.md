# LLM Proxy API

The LLM Proxy is an OpenAI-compatible gateway that routes model requests to one or more configured LLM providers.
It sits between your application and upstream LLM services, providing a unified API surface with encrypted credential
storage and multi-provider routing.

## Overview

The LLM Proxy exposes two primary endpoints under the `/v1` base path (configurable via `LLM_API_PREFIX`):

- **`POST /v1/chat/completions`** — Chat completions with optional streaming
- **`GET  /v1/models`** — Lists available models in OpenAI-compatible format

These endpoints use models configured in the Admin UI (**Settings → LLM Settings**). Clients never need to handle
provider-specific API keys or endpoint URLs; the gateway resolves the target provider from the database record.

> **Note:** There is also a model/provider configuration API at `/llm/*` (see [LLM Provider Settings](../manage/llm-settings.md)
> for details). The `/v1` path and `/llm` path serve different audiences.

## Activation

The proxy is **enabled when `LLMCHAT_ENABLED=true`** (the env var that maps to the `llmchat_enabled` config
flag). The chat router, config router, proxy router, and admin router are all loaded under the same condition
see [main.py]()).

| Setting | Default | Description |
|---|---|---|
| `LLMCHAT_ENABLED` | `true` | Master flag. When `false`, the proxy, config, and admin routers are all disabled. |

## Authentication & RBAC

| Feature | Detail |
|---|---|---|
| **Auth** | All LLM endpoints require authentication (JWT or session token). See [RBAC](../manage/rbac.md) for role information. |
| **Chat Completions RBAC** | Permission `llm.invoke`. Requires a **developer** or higher role that includes this permission. |
| **Models List RBAC** | Permission `llm.read`. Any authenticated role can use this endpoint. |
| **Config RBAC** | `admin.system_config` — platform admin only. |

## Endpoints

### 1. Chat Completions

```http
POST /v1/chat/completions
Content-Type: application/json
Authorization: Bearer <token>
```

- **RBAC**: `llm.invoke`
- **Streaming**: Enabled by default when `LLM_STREAMING_ENABLED=true`

Accepts the standard [OpenAI Chat Completions API](https://platform.openai.com/docs/api-reference/chat) request body.

#### Response

**Non-streaming** (JSON):

```json
{
  "id": "chatcmpl-...",
  "object": "chat.completion",
  "model": "gpt-4o",
  "choices": [
    {
      "index": 0,
      "message": {
        "role": "assistant",
        "content": "Hello!"
      },
      "finish_reason": "stop"
    }
  ],
  "usage": {
    "prompt_tokens": 15,
    "completion_tokens": 5,
    "total_tokens": 20
  }
}
```

**Streaming** (`stream=true`):

Returns SSE with `text/event-stream` media type.

```
data: {"id":"chatcmpl-...","object":"chat.completion.chunk","model":"gpt-4o","choices":[{"index":0,"delta":{"content":"Hello"},"finish_reason":null}]}

data: [DONE]
```

#### Error Responses

| Status | Cause |
|--------|-------|
| 400 | Invalid request body, or streaming requested but `LLM_STREAMING_ENABLED=false` |
| 401 | Missing or invalid auth token |
| 404 | Model or provider not found |
| 502 | Upstream provider error |
| 500 | Internal gateway error |

### 2. List Models

```http
GET /v1/models
Authorization: Bearer <token>
```

Returns an OpenAI-compatible model list from configured providers.

```json
{
  "object": "list",
  "data": [
    {
      "id": "gpt-4o",
      "object": "model",
      "created": 0,
      "owned_by": "OpenAI"
    },
    {
      "id": "claude-sonnet-4-20250514",
      "object": "model",
      "created": 0,
      "owned_by": "Anthropic"
    }
  ]
}
```

## Configuration Reference

| Environment Variable | Default | Description |
|---------------------|---------|-------------|
| `LLM_API_PREFIX` | `/v1` | The URL prefix for the LLM proxy endpoints. |
| `LLM_STREAMING_ENABLED` | `true` | Enables/disables streaming at the `/v1/chat/completions` endpoint. |
| `LLMCHAT_ENABLED` | `true` | Master flag that enables or disables the LLM Chat, proxy, config, and admin routes. |

## Using a Third-Party LLM Client

The proxy accepts requests from any OpenAI-compatible client:

```bash
# Example: use the OpenAI CLI through ContextForge
OPENAI_BASE_URL=https://your-gateway.example.com/v1 \
OPENAI_API_KEY="<token>"  # pragma: allowlist secret \
  openai chat completions create \
    --model "gpt-4o" \
    --message "Hello, world!"
```

## Config Router (Provider & Model Management)

Separate from the OpenAI-compatible proxy, the config router at `/llm/*` provides
CRUD endpoints for managing providers and models. See [LLM Provider Settings](../manage/llm-settings.md) for details.

| Route | Method | Description |
|---|---|---|
| `/llm/providers` | POST | Create provider |
| `/llm/providers` | GET | List providers |
| `/llm/providers/{id}` | GET, PATCH, DELETE | Provider details, update, delete |
| `/llm/providers/{id}/state` | POST | Toggle provider enabled state |
| `/llm/providers/{id}/health` | POST | Run provider health check |
| `/llm/models` | POST, GET | Create / list models |
| `/llm/models/{id}` | GET, PATCH, DELETE | Model details, update, delete |
| `/llm/models/{id}/state` | POST | Toggle model enabled state |
| `/llm/gateway/models` | GET | Chat dropdown model list |

## Admin Router (UI Backing)

The admin router at `/admin/llm/*` provides HTMX-backed admin UI endpoints for the **Settings → LLM Settings**
page and the live test panel.

| Route | Description |
|---|---|
| `/admin/llm/providers/html` | Providers table (HTMX partial) |
| `/admin/llm/models/html` | Models table (HTMX partial) |
| `/admin/llm/api-info/html` | API info & test panel |
| `/admin/llm/test` | Test a model chat (no API key needed for admin) |
| `/admin/llm/provider-defaults` | Default config per provider type |
| `/admin/llm/provider-configs` | Provider config field definitions |
