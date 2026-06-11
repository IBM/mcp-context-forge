# LLM Provider Settings

The **LLM Provider Settings** page in the Admin UI is the central place to configure LLM providers (OpenAI,
Anthropic, Ollama, etc.), register models, and enable/disable providers and models for use with the
gateway's OpenAI-compatible proxy and the internal LLM Chat interface.

## Navigation

**Admin UI → Settings → LLM Settings**

## What You Can Do

### Configure a Provider

1. Click **"Add Provider"** in the LLM Settings page.
2. Select a **Provider Type** from the list of supported types.
3. Enter the provider-specific configuration fields (API key, base URL, optional settings).
4. Click **Save**.

The system stores API keys encrypted at rest.

### Create and Manage Models

After adding or editing a provider, models become manageable for it. You can either:

- **Create models manually** — enter a model ID (e.g. `gpt-4o`, `claude-sonnet-4-20250514`).
- **Sync models from the provider API** — click the **Sync Models** button on the provider row to
  fetch the full model list from the provider's `/models` endpoint and create records for any
  that don't already exist in the database.

For providers that support the OpenAI `/models` API (OpenAI, Ollama, Cohere, etc.), the system automatically
fetches available models when you configure or edit a provider.

### Enable and Disable Providers and Models

Each provider and each model has an **enabled** toggle:

- A disabled provider is hidden from the model list and cannot be used for chat completions.
- A disabled model within an enabled provider is also hidden from the model list.
- Toggling state is atomic (one click) and immediately visible in the UI and via API.

### Health Checks

Run a health check on any provider to verify connectivity and credentials. The result shows:

- **Status** — `healthy`, `unhealthy`, or `unknown`
- **Response latency** in milliseconds
- **Error details** if the check failed

### Delete Providers and Models

- Deleting a provider cascades to all its models.
- Models can also be deleted individually.

## Supported Provider Types

| Provider | Description | Base URL | API Key? |
|----------|-------------|----------|----------|
| `openai` | OpenAI GPT models (GPT-4, GPT-4o, etc.) | `https://api.openai.com/v1` | Required |
| `azure_openai` | Azure OpenAI Service | `https://{resource}.openai.azure.com/openai/deployments/{deployment}` | Required |
| `anthropic` | Anthropic Claude models | `https://api.anthropic.com` | Required |
| `bedrock` | AWS Bedrock (uses IAM credentials) | *(IAM auth, no base URL)* | IAM credentials |
| `google_vertex` | Google Vertex AI (uses service account) | *(uses default Vertex endpoint)* | Service account |
| `watsonx` | IBM watsonx.ai | *(IBM endpoint)* | Required |
| `ollama` | Local Ollama server | `http://localhost:11434` | Not required |
| `openai_compatible` | Any OpenAI-compatible API server (vLLM, LocalAI, etc.) | User-provided | Optional |
| `cohere` | Cohere Command models | `https://api.cohere.ai/v1` | Required |
| `mistral` | Mistral AI models | `https://api.mistral.ai/v1` | Required |
| `groq` | Groq high-speed inference | `https://api.groq.com/openai/v1` | Required |
| `together` | Together AI inference | `https://api.together.xyz/v1` | Required |

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `LLMCHAT_ENABLED` | `true` | **Master flag.** When set to `false`, disables the entire LLM Chat, proxy, config, and admin router groups (`/llmchat/*`, `/llm/*`, `/v1/*`, `/admin/llm/*`). |
| `LLM_API_PREFIX` | `/v1` | The API prefix for the OpenAI-compatible proxy (`/v1/chat/completions`). |
| `LLM_STREAMING_ENABLED` | `true` | Enables or disables SSE streaming at the `/v1/chat/completions` endpoint. |
| `LLMCHAT_SESSION_TTL` | `300` | Active chat session TTL in seconds (Redis key expiry). |
| `LLMCHAT_CHAT_HISTORY_TTL` | `3600` | Chat message history TTL in seconds. |
| `LLMCHAT_CHAT_HISTORY_MAX_MESSAGES` | `50` | Maximum messages kept per user. |
| `LLM_HEALTH_CHECK_INTERVAL` | `300` | Provider health check interval in seconds. |

> **Note on `LLM_API_PREFIX`**: The config router (provider/model management) always uses `/llm` as its base.
> The proxy router (OpenAI-compatible endpoints) uses the value of `LLM_API_PREFIX` which defaults to `/v1`.

## Error Responses

| Status | Meaning |
|---|---|
| 404 | Provider or model not found |
| 409 | Conflict (e.g. Provider/model name already exists) |
| 422 | Invalid input (Pydantic validation error) |

## Next Steps

- [LLM Proxy API](../api/llm-proxy.md) — Programmatic interface for chat completions and model listing
- [LLM Chat](../using/clients/llm-chat.md) — Interactive chat agent with MCP tool integration
