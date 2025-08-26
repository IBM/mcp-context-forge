# MCP Context Forge Plugin Framework

The MCP Context Forge Plugin Framework provides a powerful, production-ready system for AI safety middleware, content security, policy enforcement, and operational excellence. Plugins run as middleware components that can intercept and transform requests and responses at various points in the gateway lifecycle.

## Quick Start

### Enable Plugins

1. Set environment variables in `.env`:
```bash
PLUGINS_ENABLED=true
PLUGIN_CONFIG_FILE=plugins/config.yaml
PLUGINS_CLI_COMPLETION=false
PLUGINS_CLI_MARKUP_MODE=rich
```

2. Configure plugins in `plugins/config.yaml` (see [Configuration](#configuration) section)

3. Restart the gateway: `make dev`

## Plugin Architecture

The framework supports two types of plugins:

### 1. Self-Contained Plugins
- Written in Python and run directly in the gateway process
- Sub-millisecond latency (<1ms)
- Perfect for high-frequency operations like PII filtering and regex transformations
- Examples: `pii_filter`, `regex_filter`, `deny_filter`, `resource_filter`

### 2. External Service Plugins
- Call external AI safety services via HTTP/MCP
- Support microservice integrations with authentication
- 10-100ms latency depending on service
- Examples: LlamaGuard, OpenAI Moderation, custom safety services

## Available Hooks

Plugins can implement hooks at these lifecycle points:

| Hook | Description | Payload Type | Use Cases |
|------|-------------|--------------|-----------|
| `prompt_pre_fetch` | Before prompt template retrieval | `PromptPrehookPayload` | Input validation, access control |
| `prompt_post_fetch` | After prompt template retrieval | `PromptPosthookPayload` | Content filtering, transformation |
| `tool_pre_invoke` | Before tool execution | `ToolPreInvokePayload` | Parameter validation, safety checks |
| `tool_post_invoke` | After tool execution | `ToolPostInvokeResult` | Result filtering, audit logging |
| `resource_pre_fetch` | Before resource retrieval | `ResourcePreFetchPayload` | Protocol/domain validation |
| `resource_post_fetch` | After resource retrieval | `ResourcePostFetchResult` | Content scanning, size limits |

Future hooks (in development):
- `server_pre_register` / `server_post_register` - Virtual server verification
- `auth_pre_check` / `auth_post_check` - Custom authentication logic
- `federation_pre_sync` / `federation_post_sync` - Gateway federation

## Configuration

### Main Configuration File (`plugins/config.yaml`)

```yaml
plugins:
  - name: "PIIFilterPlugin"
    kind: "plugins.pii_filter.pii_filter.PIIFilterPlugin"
    description: "Detects and masks Personally Identifiable Information"
    version: "0.1.0"
    author: "Your Name"
    hooks: ["prompt_pre_fetch", "tool_pre_invoke"]
    tags: ["security", "pii", "compliance"]
    mode: "enforce"  # enforce | permissive | disabled
    priority: 50     # Lower number = higher priority (runs first)
    conditions:
      - prompts: []     # Empty = apply to all prompts
        server_ids: []  # Apply to specific servers
        tenant_ids: []  # Apply to specific tenants
    config:
      detect_ssn: true
      detect_email: true
      default_mask_strategy: "partial"

# Global settings
plugin_settings:
  parallel_execution_within_band: true
  plugin_timeout: 30
  fail_on_plugin_error: false
  plugin_health_check_interval: 60
```

### Plugin Modes

- **`enforce`**: Blocks violations and prevents request processing
- **`permissive`**: Logs violations but allows request to continue
- **`disabled`**: Plugin is not executed (useful for temporary disabling)

### Plugin Priority

Lower priority numbers run first (higher priority). Recommended ranges:
- **1-50**: Critical security plugins (PII, access control)
- **51-100**: Content filtering and validation
- **101-200**: Transformations and enhancements
- **201+**: Logging and monitoring

## Built-in Plugins

### PII Filter Plugin
Detects and masks Personally Identifiable Information (PII):

```yaml
- name: "PIIFilterPlugin"
  kind: "plugins.pii_filter.pii_filter.PIIFilterPlugin"
  config:
    detect_ssn: true
    detect_credit_card: true
    detect_email: true
    detect_phone: true
    detect_aws_keys: true
    default_mask_strategy: "partial"  # redact | partial | hash | tokenize
    block_on_detection: false
    whitelist_patterns:
      - "test@example.com"
```

### Regex Filter Plugin
Find and replace text patterns:

```yaml
- name: "ReplaceBadWordsPlugin"
  kind: "plugins.regex_filter.search_replace.SearchReplacePlugin"
  config:
    words:
      - search: "inappropriate_word"
        replace: "[FILTERED]"
```

### Deny List Plugin
Block requests containing specific terms:

```yaml
- name: "DenyListPlugin"
  kind: "plugins.deny_filter.deny.DenyListPlugin"
  config:
    words:
      - "blocked_term"
      - "another_blocked_term"
```

### Resource Filter Plugin
Validate and filter resource requests:

```yaml
- name: "ResourceFilterExample"
  kind: "plugins.resource_filter.resource_filter.ResourceFilterPlugin"
  config:
    max_content_size: 1048576  # 1MB
    allowed_protocols: ["http", "https"]
    blocked_domains: ["malicious.example.com"]
    content_filters:
      - pattern: "password\\s*[:=]\\s*\\S+"
        replacement: "password: [REDACTED]"
```

## Writing Custom Plugins

### 1. Plugin Structure

Create a new directory under `plugins/`:

```
plugins/my_plugin/
├── __init__.py
├── plugin-manifest.yaml
├── my_plugin.py
└── README.md
```

### 2. Plugin Manifest (`plugin-manifest.yaml`)

```yaml
description: "My custom plugin"
author: "Your Name"
version: "1.0.0"
available_hooks:
  - "tool_pre_invoke"
  - "tool_post_invoke"
default_configs:
  my_setting: true
  threshold: 0.8
```

### 3. Plugin Implementation

```python
# my_plugin.py
from mcpgateway.plugins.framework.base import Plugin
from mcpgateway.plugins.framework.models import (
    ToolPreInvokePayload,
    ToolPreInvokeResult,
    PluginResult
)

class MyPlugin(Plugin):
    """Custom plugin implementation."""

    async def tool_pre_invoke(self, payload: ToolPreInvokePayload) -> ToolPreInvokeResult:
        """Process tool invocation before execution."""

        # Get plugin configuration
        my_setting = self.config.get("my_setting", False)
        threshold = self.config.get("threshold", 0.5)

        # Implement your logic
        if my_setting and self._should_block(payload):
            return ToolPreInvokeResult(
                result=PluginResult.BLOCK,
                message="Request blocked by custom logic",
                modified_payload=payload
            )

        # Modify payload if needed
        modified_payload = self._transform_payload(payload)

        return ToolPreInvokeResult(
            result=PluginResult.CONTINUE,
            modified_payload=modified_payload
        )

    def _should_block(self, payload: ToolPreInvokePayload) -> bool:
        """Custom blocking logic."""
        # Implement your validation logic here
        return False

    def _transform_payload(self, payload: ToolPreInvokePayload) -> ToolPreInvokePayload:
        """Transform payload if needed."""
        return payload
```

### 4. Register Your Plugin

Add to `plugins/config.yaml`:

```yaml
plugins:
  - name: "MyCustomPlugin"
    kind: "plugins.my_plugin.my_plugin.MyPlugin"
    description: "My custom plugin description"
    version: "1.0.0"
    author: "Your Name"
    hooks: ["tool_pre_invoke"]
    mode: "enforce"
    priority: 100
    config:
      my_setting: true
      threshold: 0.8
```

## Plugin Development Best Practices

### Error Handling
```python
async def tool_pre_invoke(self, payload: ToolPreInvokePayload) -> ToolPreInvokeResult:
    try:
        # Your plugin logic
        result = await self._process_payload(payload)
        return ToolPreInvokeResult(result=PluginResult.CONTINUE)
    except Exception as e:
        self.logger.error(f"Plugin error: {e}")
        if self.mode == PluginMode.ENFORCE:
            return ToolPreInvokeResult(
                result=PluginResult.BLOCK,
                message=f"Plugin failed: {e}"
            )
        return ToolPreInvokeResult(result=PluginResult.CONTINUE)
```

### Logging and Monitoring
```python
def __init__(self, config: PluginConfig):
    super().__init__(config)
    self.logger.info(f"Initialized {self.name} v{self.version}")

async def tool_pre_invoke(self, payload: ToolPreInvokePayload) -> ToolPreInvokeResult:
    self.logger.debug(f"Processing tool: {payload.tool_name}")
    # ... plugin logic
    self.metrics.increment("requests_processed")
```

### Configuration Validation
```python
def validate_config(self) -> None:
    """Validate plugin configuration."""
    required_keys = ["threshold", "api_key"]
    for key in required_keys:
        if key not in self.config:
            raise ValueError(f"Missing required config key: {key}")

    if not 0 <= self.config["threshold"] <= 1:
        raise ValueError("threshold must be between 0 and 1")
```

## Performance Considerations

### Latency Guidelines
- **Self-contained plugins**: <1ms target
- **External service plugins**: <100ms target
- Use async/await for I/O operations
- Implement timeouts for external calls

### Resource Management
```python
class MyPlugin(Plugin):
    def __init__(self, config: PluginConfig):
        super().__init__(config)
        self._session = None

    async def __aenter__(self):
        self._session = aiohttp.ClientSession()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self._session:
            await self._session.close()
```

## Testing Plugins

### Unit Testing
```python
import pytest
from mcpgateway.plugins.framework.models import ToolPreInvokePayload, PluginConfig
from plugins.my_plugin.my_plugin import MyPlugin

@pytest.fixture
def plugin():
    config = PluginConfig(
        name="test_plugin",
        config={"my_setting": True}
    )
    return MyPlugin(config)

async def test_tool_pre_invoke(plugin):
    payload = ToolPreInvokePayload(
        tool_name="test_tool",
        arguments={"arg1": "value1"}
    )

    result = await plugin.tool_pre_invoke(payload)
    assert result.result == PluginResult.CONTINUE
```

### Integration Testing
```bash
# Test with live gateway
make dev
curl -X POST http://localhost:4444/tools/invoke \
  -H "Content-Type: application/json" \
  -d '{"name": "test_tool", "arguments": {}}'
```

## Troubleshooting

### Common Issues

1. **Plugin not loading**: Check `plugin_dirs` in config and Python import paths
2. **Configuration errors**: Validate YAML syntax and required fields
3. **Performance issues**: Profile plugin execution time and optimize bottlenecks
4. **Hook not triggering**: Verify hook name matches available hooks in manifest

### Debug Mode
```bash
LOG_LEVEL=DEBUG make serve # port 4444
# Or with reloading dev server:
LOG_LEVEL=DEBUG make dev # port 8000
```

## Documentation Links

- **Plugin Usage Guide**: https://ibm.github.io/mcp-context-forge/using/plugins/
- **Plugin Lifecycle**: https://ibm.github.io/mcp-context-forge/using/plugins/lifecycle/
- **API Reference**: Generated from code docstrings
- **Examples**: See `plugins/` directory for complete implementations

## Performance Metrics

The framework supports high-performance operations:
- **1,000+ requests/second** with 5 active plugins
- **Sub-millisecond latency** for self-contained plugins
- **Parallel execution** within priority bands
- **Resource isolation** and timeout protection

## Security Features

- Input validation and sanitization
- Timeout protection for external calls
- Resource limits and quota enforcement
- Error isolation between plugins
- Comprehensive audit logging
- Plugin configuration validation
