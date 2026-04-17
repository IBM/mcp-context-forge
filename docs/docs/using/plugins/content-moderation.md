# Content Moderation Plugin

**Package:** [`cpex-content-moderation`](https://pypi.org/project/cpex-content-moderation/)
**Kind:** `cpex_content_moderation.ContentModerationPlugin`
**Version:** 0.1.0+

Advanced AI-powered content moderation plugin that supports IBM Watson Natural Language Understanding, IBM Granite Guardian, OpenAI, Azure Content Safety, and AWS Comprehend. Configurable per-category thresholds and actions allow fine-grained control over what is blocked, redacted, warned about, or transformed.

---

## Installation

```bash
pip install cpex-content-moderation
# or with the gateway extras
pip install "mcp-contextforge-gateway[plugins]"
```

---

## Hooks

| Hook | Direction | Description |
|------|-----------|-------------|
| `prompt_pre_fetch` | Inbound | Moderate prompt arguments before they reach the server |
| `tool_pre_invoke` | Inbound | Moderate tool arguments before tool execution |
| `tool_post_invoke` | Outbound | Moderate tool output before it is returned to the client |

---

## Supported Providers

| Provider | Key | Notes |
|----------|-----|-------|
| IBM Watson NLU | `ibm_watson` | Emotion and sentiment analysis; enterprise SLA |
| IBM Granite Guardian | `ibm_granite` | Local Ollama deployment; no external API calls |
| OpenAI Moderation | `openai` | High accuracy; requires OpenAI API key |
| Azure Content Safety | `azure` | Granular severity scoring |
| AWS Comprehend | `aws` | AWS ecosystem integration; multi-language |

---

## Moderation Actions

| Action | Behaviour |
|--------|-----------|
| `block` | Rejects the request with a `CONTENT_MODERATION` violation |
| `warn` | Logs the violation but allows the request to continue |
| `redact` | Replaces offending text with `[CONTENT REMOVED BY MODERATION]` |
| `transform` | Replaces specific words using configurable patterns |

---

## Configuration Reference

### Minimal example

```yaml
plugins:
  - name: "ContentModeration"
    kind: "cpex_content_moderation.ContentModerationPlugin"
    hooks: ["prompt_pre_fetch", "tool_pre_invoke", "tool_post_invoke"]
    mode: "enforce"
    priority: 30
    config:
      provider: "ibm_watson"
      ibm_watson:
        api_key: "${env.IBM_WATSON_API_KEY}"
        url: "${env.IBM_WATSON_URL}"
      categories:
        hate:
          threshold: 0.7
          action: "block"
```

### Full configuration options

```yaml
config:
  # Primary and fallback provider
  provider: "ibm_watson"              # Required. One of: ibm_watson, ibm_granite, openai, azure, aws
  fallback_provider: "ibm_granite"    # Optional. Used when primary provider fails.
  fallback_on_error: "warn"           # Optional. Action when ALL providers fail: allow, block, warn (default: warn)

  # IBM Watson NLU
  ibm_watson:
    api_key: "${env.IBM_WATSON_API_KEY}"
    url: "${env.IBM_WATSON_URL}"
    version: "2022-04-07"             # API version (default: 2022-04-07)
    language: "en"                    # Language hint (default: en)
    timeout: 30                       # HTTP timeout seconds (default: 30)

  # IBM Granite Guardian (local Ollama)
  ibm_granite:
    ollama_url: "http://localhost:11434"
    model: "granite3-guardian"        # default: granite3-guardian
    temperature: 0.1
    timeout: 30

  # OpenAI
  openai:
    api_key: "${env.OPENAI_API_KEY}"
    api_base: "https://api.openai.com/v1"
    model: "text-moderation-latest"
    timeout: 30

  # Azure Content Safety
  azure:
    api_key: "${env.AZURE_CONTENT_SAFETY_KEY}"
    endpoint: "${env.AZURE_CONTENT_SAFETY_ENDPOINT}"
    api_version: "2023-10-01"
    timeout: 30

  # AWS Comprehend
  aws:
    access_key_id: "${env.AWS_ACCESS_KEY_ID}"
    secret_access_key: "${env.AWS_SECRET_ACCESS_KEY}"
    region: "${env.AWS_DEFAULT_REGION}"
    timeout: 30

  # Per-category thresholds and actions
  categories:
    hate:
      threshold: 0.7           # Confidence threshold 0.0-1.0 (default: 0.7)
      action: "block"          # block | warn | redact | transform
      providers: []            # Optional list to restrict to specific providers
      custom_patterns: []      # Extra regex patterns that also trigger this category
    violence:
      threshold: 0.8
      action: "block"
    sexual:
      threshold: 0.8
      action: "block"
    self_harm:
      threshold: 0.7
      action: "block"
    harassment:
      threshold: 0.7
      action: "warn"
    spam:
      threshold: 0.6
      action: "warn"
    profanity:
      threshold: 0.6
      action: "redact"
    toxic:
      threshold: 0.7
      action: "warn"

  # Operational settings
  audit_decisions: true       # Log every moderation decision (default: true)
  enable_caching: true        # Cache results to avoid duplicate API calls (default: true)
  cache_ttl: 300              # Cache TTL in seconds (default: 300)
  max_text_length: 10000      # Truncate inputs longer than this before sending to provider
```

---

## Dynamic Configuration via API

Use the gateway Admin API to register the plugin at runtime without restarting the server.

### 1. Register via curl

```bash
export TOKEN=$(python -m mcpgateway.utils.create_jwt_token --username admin@example.com --exp 60 --secret "$JWT_SECRET_KEY")

curl -s -X POST http://localhost:4444/admin/plugins \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "ContentModeration",
    "kind": "cpex_content_moderation.ContentModerationPlugin",
    "hooks": ["prompt_pre_fetch", "tool_pre_invoke", "tool_post_invoke"],
    "mode": "enforce",
    "priority": 30,
    "config": {
      "provider": "ibm_watson",
      "ibm_watson": {
        "api_key": "'"$IBM_WATSON_API_KEY"'",
        "url": "'"$IBM_WATSON_URL"'"
      },
      "categories": {
        "hate": {"threshold": 0.7, "action": "block"},
        "violence": {"threshold": 0.8, "action": "block"},
        "profanity": {"threshold": 0.6, "action": "redact"}
      },
      "audit_decisions": true
    }
  }'
```

### 2. Update configuration dynamically

```bash
PLUGIN_ID="<id-from-registration-response>"

curl -s -X PATCH http://localhost:4444/admin/plugins/$PLUGIN_ID \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "config": {
      "provider": "ibm_granite",
      "ibm_granite": {
        "ollama_url": "http://localhost:11434",
        "model": "granite3-guardian"
      },
      "categories": {
        "hate": {"threshold": 0.6, "action": "block"}
      }
    }
  }'
```

### 3. Reload without restart

After updating, trigger a live reload:

```bash
curl -s -X POST http://localhost:4444/admin/plugins/reload \
  -H "Authorization: Bearer $TOKEN"
```

---

## Environment Variables

| Variable | Provider | Description |
|----------|----------|-------------|
| `IBM_WATSON_API_KEY` | ibm_watson | Watson NLU service credentials |
| `IBM_WATSON_URL` | ibm_watson | Watson NLU service URL |
| `OPENAI_API_KEY` | openai | OpenAI API key |
| `AZURE_CONTENT_SAFETY_KEY` | azure | Azure Content Safety key |
| `AZURE_CONTENT_SAFETY_ENDPOINT` | azure | Azure Content Safety endpoint |
| `AWS_ACCESS_KEY_ID` | aws | AWS access key |
| `AWS_SECRET_ACCESS_KEY` | aws | AWS secret key |
| `AWS_DEFAULT_REGION` | aws | AWS region (e.g. `us-east-1`) |

---

## Troubleshooting

**Plugin not found / ImportError**
Install the package: `pip install cpex-content-moderation`. Verify with `python -c "import cpex_content_moderation; print(cpex_content_moderation.ContentModerationPlugin)"`.

**All requests blocked in enforce mode**
Check that the provider credentials are correct and the service is reachable. Set `fallback_on_error: "warn"` to allow traffic while debugging.

**High latency**
Enable caching (`enable_caching: true`) and consider using IBM Granite locally to avoid network round-trips.

**Granite model not found**
Pull the model with Ollama: `ollama pull granite3-guardian`.
