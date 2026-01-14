# plugins/AGENTS.md

Plugin development guidance for AI coding assistants.

## Directory Structure

```
plugins/
├── config.yaml              # Central plugin configuration (Jinja-enabled)
├── README.md                # Plugin documentation
├── install.yaml             # Installation manifest
├── pii_filter/              # Built-in: PII detection and masking
├── deny_filter/             # Built-in: Denylist blocking
├── regex_filter/            # Built-in: Search/replace
├── resource_filter/         # Built-in: Resource validation
├── argument_normalizer/     # Built-in: Input normalization
└── [many more plugins...]   # 47+ plugin directories
```

## Plugin Framework

Location: `mcpgateway/plugins/framework/`

### Core Interfaces

```python
from mcpgateway.plugins.framework import Plugin, PluginConfig, PluginContext
from mcpgateway.plugins.framework import (
    PromptPrehookPayload, PromptPrehookResult,
    ToolPreInvokePayload, ToolPreInvokeResult,
    ResourcePreFetchPayload, ResourcePreFetchResult,
    PluginViolation,
)
```

### Hook Lifecycle

Six production hooks:
- `prompt_pre_fetch` / `prompt_post_fetch` - Before/after prompt rendering
- `tool_pre_invoke` / `tool_post_invoke` - Before/after tool execution
- `resource_pre_fetch` / `resource_post_fetch` - Before/after resource fetch

Plugins execute in priority order (ascending). Lower priority runs first.

### Plugin Modes

- `enforce` - Block on violation
- `enforce_ignore_error` - Block violations, but errors don't block
- `permissive` - Log violations, continue processing
- `disabled` - Loaded but not executed

## Creating a Plugin

### 1. Bootstrap from Template

```bash
mcpplugins bootstrap --destination plugins/my_plugin --type native
```

### 2. Implement the Plugin Class

```python
# plugins/my_plugin/my_plugin.py
from mcpgateway.plugins.framework import Plugin, PluginConfig, PluginContext
from mcpgateway.plugins.framework import PromptPrehookPayload, PromptPrehookResult, PluginViolation

class MyPlugin(Plugin):
    async def prompt_pre_fetch(self, payload: PromptPrehookPayload, context: PluginContext) -> PromptPrehookResult:
        # Check for forbidden content
        if payload.args and any("forbidden" in str(v) for v in payload.args.values()):
            return PromptPrehookResult(
                continue_processing=False,
                violation=PluginViolation(
                    reason="Forbidden content",
                    description="Blocked by MyPlugin",
                    code="FORBIDDEN",
                    details={"matched": True},
                ),
            )
        # Allow with optional modification
        return PromptPrehookResult(modified_payload=payload)
```

### 3. Register in config.yaml

```yaml
plugins:
  - name: "MyPlugin"
    kind: "plugins.my_plugin.my_plugin.MyPlugin"
    hooks: ["prompt_pre_fetch"]
    mode: "enforce"
    priority: 100
    config:
      # Plugin-specific configuration
      custom_setting: "value"
```

### 4. Enable in .env

```bash
PLUGINS_ENABLED=true
PLUGIN_CONFIG_FILE=plugins/config.yaml
```

## Configuration Schema

`plugins/config.yaml` structure:

```yaml
plugins: []           # List of plugin configurations
plugin_dirs: []       # Additional plugin directories
plugin_settings:
  plugin_timeout: 30            # Per-call timeout (seconds)
  fail_on_plugin_error: false   # Strict error handling
  enable_plugin_api: true       # Enable plugin management API
```

Plugin entry fields:
- `name` - Unique identifier
- `kind` - Fully-qualified class path (native) or `external` (MCP)
- `hooks` - List of hooks to implement
- `mode` - Execution mode
- `priority` - Execution order (lower = earlier)
- `conditions` - Selective execution filters
- `config` - Plugin-specific settings

## External Plugins (MCP)

External plugins run as separate MCP servers.

```yaml
plugins:
  - name: "ExternalFilter"
    kind: "external"
    priority: 10
    mcp:
      proto: STREAMABLEHTTP    # or STDIO
      url: http://localhost:8000/mcp
      # tls:
      #   ca_bundle: /path/to/ca.crt
```

Required tools on external server:
- `get_plugin_config`
- `prompt_pre_fetch`, `prompt_post_fetch`
- `tool_pre_invoke`, `tool_post_invoke`
- `resource_pre_fetch`, `resource_post_fetch`

## Testing Plugins

### Unit Test

```python
import pytest
from mcpgateway.plugins.framework import (
    HookType, PluginConfig, PluginContext, GlobalContext,
    PromptPrehookPayload,
)
from plugins.my_plugin.my_plugin import MyPlugin

@pytest.mark.asyncio
async def test_my_plugin_blocks_forbidden():
    cfg = PluginConfig(
        name="test",
        kind="plugins.my_plugin.my_plugin.MyPlugin",
        hooks=[HookType.PROMPT_PRE_FETCH],
        priority=100,
    )
    plugin = MyPlugin(cfg)
    payload = PromptPrehookPayload(name="test", args={"text": "forbidden content"})
    ctx = PluginContext(global_context=GlobalContext(request_id="t-1"))

    result = await plugin.prompt_pre_fetch(payload, ctx)
    assert result.continue_processing is False
    assert result.violation is not None
```

### Run Tests

```bash
pytest tests/unit/mcpgateway/plugins/
make doctest test
```

## Built-in Plugin Examples

| Plugin | Hooks | Purpose |
|--------|-------|---------|
| `PIIFilterPlugin` | prompt/tool pre/post | Detect and mask PII |
| `DenyListPlugin` | prompt pre | Block denylisted words |
| `SearchReplacePlugin` | prompt/tool pre/post | Regex search/replace |
| `ResourceFilterPlugin` | resource pre/post | Validate URIs, size limits |
| `ArgumentNormalizer` | prompt/tool pre | Normalize inputs |

## Key Files

- `mcpgateway/plugins/framework/base.py` - Plugin base class
- `mcpgateway/plugins/framework/models.py` - Pydantic models for payloads/results
- `mcpgateway/plugins/framework/manager.py` - Plugin execution manager
- `mcpgateway/plugins/framework/registry.py` - Plugin instance registry
- `plugins/config.yaml` - Plugin configuration
- `plugin_templates/` - Bootstrap templates
