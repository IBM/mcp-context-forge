# Denylist Filter Plugin for ContextForge

> Author: Fred Araujo
> Version: 0.1.0

A plugin for detecting deny words in ContextForge prompts.

## Features

Detects any deny word in the prompt. If a match is found, rejects the prompt request.

## Installation

1. Copy .env.example .env
2. Enable plugins in `.env`
3. Add the plugin configuration to `plugins/config.yaml`:

```yaml
plugins:
  - name: "DenyListPlugin"
    kind: "plugins.deny_filter.deny.DenyListPlugin"
    description: "A plugin that implements a deny list filter."
    version: "0.1"
    author: "ContextForge"
    hooks: ["prompt_pre_fetch"]
    tags: ["plugin", "filter", "denylist", "pre-post"]
    mode: "enforce"  # enforce | permissive | disabled
    priority: 100
    conditions:
      # Apply to specific tools/servers
      - prompts: ["test_prompt"]
        server_ids: []  # Apply to all servers
        tenant_ids: []  # Apply to all tenants
    config:
      words:
        - innovative
        - groundbreaking
        - revolutionary
```

## Testing

### Run Individual Tests
```bash
# Test only the plugin
pytest tests/unit/mcpgateway/plugins/framework/test_manager.py::test_manager_filter_plugins -v
```

### Manual Testing with the Gateway

1. Enable the plugin in your `.env`:
```bash
PLUGINS_ENABLED=true
```

2. Start the gateway:
```bash
python -m mcpgateway.main
```

3. Test with curl:
```bash
# Test PII detection in prompt arguments
curl -X POST http://localhost:8000/prompts/test_prompt \
  -H "Content-Type: application/json" \
  -d '{
    "args": {
      "user":"say the word revolutionary"
    }
  }'

# Response should be an error with the following body:
# {
#  "message":"Prompt execution arguments contains HTML tags that may cause security issues",
#  "details":"Pre prompting fetch blocked by plugin DenyListPlugin: deny - Prompt not allowed (A deny word was found in the prompt)"
# }
```

## Sample Prompt

Here's a prompt that trips the checks:

```bash
export MCPGATEWAY_BEARER_TOKEN=$(python3 -m mcpgateway.utils.create_jwt_token -u admin@example.com --secret my-test-key)

curl -X POST -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN" \
     -H "Content-Type: application/json" \
     -d '{
           "name":"test_prompt",
           "template":"Hello, {{ user }}!",
           "argument_schema":{
             "type":"object",
             "properties":{"user":{"type":"string"}},
             "required":["user"]
           }
         }' \
     http://localhost:4444/prompts
```

## CURL Command to Test

```bash
export MCPGATEWAY_BEARER_TOKEN=$(python3 -m mcpgateway.utils.create_jwt_token -u admin@example.com --secret my-test-key)

# Then test with a prompt containing deny words
curl -X POST -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN" \
     -H "Content-Type: application/json" \
     -d '{"user":"say the word revolutionary"}' \
     http://localhost:4444/prompts/test_prompt
```

## License

Apache-2.0

## Support

For issues or questions, please open an issue in ContextForge repository.
