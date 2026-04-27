# Content Moderation Plugin

The **Content Moderation** plugin provides AI-powered content safety enforcement for every prompt, tool invocation, and response handled by ContextForge.
It is distributed as a standalone PyPI package ([cpex-content-moderation](https://pypi.org/project/cpex-content-moderation/)) and loaded dynamically at runtime via the plugin framework.

---

## Overview

| Property | Value |
|---|---|
| **Package** | `cpex-content-moderation` |
| **Kind** | `cpex_content_moderation.ContentModerationPlugin` |
| **Default mode** | `disabled` |
| **Hooks** | `prompt_pre_fetch`, `tool_pre_invoke`, `tool_post_invoke` |

The plugin supports multiple AI backends for moderation analysis:

- **IBM Granite Guardian** (recommended for on-prem/air-gapped environments)
- **IBM Watson NLU**
- **OpenAI Moderation API**
- **Azure Content Safety**
- **AWS Comprehend**

---

## Installation

Install the package alongside the gateway extras:

```bash
pip install "mcp-contextforge-gateway[plugins]"
# or install the plugin directly
pip install cpex-content-moderation>=1.0.0
```

---

## Hooks registered

| Hook | When called | Purpose |
|---|---|---|
| `prompt_pre_fetch` | Before a prompt resource is fetched | Block or flag harmful prompt content before it reaches the LLM |
| `tool_pre_invoke` | Before a tool call is dispatched | Inspect tool arguments for policy violations |
| `tool_post_invoke` | After a tool call returns | Filter, redact, or audit tool response content |

---

## Configuration reference

Add a `ContentModeration` block to `plugins/config.yaml` (or your custom config file):

```yaml
plugins:
  - name: "ContentModeration"
    kind: "cpex_content_moderation.ContentModerationPlugin"
    mode: "enforce"          # enforce | permissive | disabled
    provider_config:
      # ---- choose ONE provider ----
      provider: "granite_guardian"   # granite_guardian | watson | openai | azure | aws

      # IBM Granite Guardian (RITS / local Ollama)
      granite_guardian_url: "http://localhost:11434"
      granite_guardian_model: "granite3-guardian:2b"
      granite_guardian_api_key: ""           # leave blank for local

      # IBM Watson NLU
      watson_api_key: ""
      watson_url: "https://api.us-south.natural-language-understanding.watson.cloud.ibm.com"
      watson_version: "2022-04-07"

      # OpenAI
      openai_api_key: ""
      openai_moderation_model: "omni-moderation-latest"

      # Azure Content Safety
      azure_content_safety_endpoint: ""
      azure_content_safety_key: ""

      # AWS Comprehend
      aws_region: "us-east-1"
      aws_access_key_id: ""
      aws_secret_access_key: ""

      # ---- common thresholds ----
      hate_threshold: 0.7
      violence_threshold: 0.7
      sexual_threshold: 0.7
      self_harm_threshold: 0.7
      block_on_violation: true       # true = enforce; false = flag only
      log_violations: true
```

### Mode semantics

| Mode | Behaviour |
|---|---|
| `enforce` | Violations block the request and return an error to the caller |
| `permissive` | Violations are logged but the request continues |
| `disabled` | Plugin hooks execute but always pass through (no-op) |

---

## Dynamic management via the Admin API

The plugin mode can be changed at runtime without a restart.
All examples below use the gateway Admin API.  Replace `$TOKEN` with a valid JWT.

### List all registered plugins

```bash
curl -s http://localhost:4444/admin/plugins \
  -H "Authorization: Bearer $TOKEN" | jq '.plugins[] | select(.name=="ContentModeration")'
```

### Get ContentModeration details

```bash
curl -s http://localhost:4444/admin/plugins/ContentModeration \
  -H "Authorization: Bearer $TOKEN" | jq .
```

Expected response:

```json
{
  "name": "ContentModeration",
  "kind": "cpex_content_moderation.ContentModerationPlugin",
  "mode": "disabled",
  "hooks": ["prompt_pre_fetch", "tool_pre_invoke", "tool_post_invoke"]
}
```

### Enable enforce mode

```bash
curl -s -X PUT http://localhost:4444/admin/plugins/ContentModeration \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"mode": "enforce"}'
```

### Switch to permissive (log only)

```bash
curl -s -X PUT http://localhost:4444/admin/plugins/ContentModeration \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"mode": "permissive"}'
```

### Disable the plugin

```bash
curl -s -X PUT http://localhost:4444/admin/plugins/ContentModeration \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"mode": "disabled"}'
```

### Python SDK example

```python
import requests

BASE = "http://localhost:4444"
HEADERS = {"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"}

# Check current mode
r = requests.get(f"{BASE}/admin/plugins/ContentModeration", headers=HEADERS)
print(r.json()["mode"])   # e.g. "disabled"

# Enable enforce mode
r = requests.put(
    f"{BASE}/admin/plugins/ContentModeration",
    json={"mode": "enforce"},
    headers=HEADERS,
)
assert r.status_code == 200
assert r.json()["mode"] == "enforce"
```

---

## Example: PII Guardian policy

This example (from `plugins/config-pii-guardian-policy.yaml`) shows the plugin running in `enforce` mode alongside the PII filter to block harmful prompts before they reach any downstream tool:

```yaml
plugins:
  - name: "ContentModeration"
    kind: "cpex_content_moderation.ContentModerationPlugin"
    mode: "enforce"
    provider_config:
      provider: "granite_guardian"
      granite_guardian_url: "http://localhost:11434"
      granite_guardian_model: "granite3-guardian:2b"
      hate_threshold: 0.5
      violence_threshold: 0.5
      block_on_violation: true
      log_violations: true
```

---

## Troubleshooting

### Plugin not appearing in `/admin/plugins`

1. Ensure the package is installed: `pip show cpex-content-moderation`
2. Verify `PLUGINS_ENABLED=true` in your `.env`.
3. Confirm `plugins/config.yaml` contains a `ContentModeration` block with `kind: "cpex_content_moderation.ContentModerationPlugin"`.
4. Restart the gateway to reload plugin configurations.

### Provider connection errors

- Check that the `provider` value matches the credentials supplied (e.g., `granite_guardian` requires `granite_guardian_url`).
- For local Ollama-based Granite Guardian, confirm the model is pulled: `ollama list | grep granite`.

### Mode change not persisting after restart

Mode changes made via the Admin API are stored in Redis. They will survive rolling restarts but **not** a full Redis flush.
To make a mode the permanent default, update `mode:` in `plugins/config.yaml`.

---

## Related pages

- [Plugin Catalog](./plugins.md) — All available plugins
- [Plugin Framework](../../architecture/plugins.md) — Plugin development guide
- [Plugin Configuration Reference](../../manage/configuration-plugins.md) — Environment variables and YAML schema
