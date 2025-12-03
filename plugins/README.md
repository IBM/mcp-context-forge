# ContextForge Plugin Framework

The ContextForge Plugin Framework provides a powerful, production-ready system for AI safety middleware, content security, policy enforcement, and operational excellence. Plugins run as middleware components that can intercept and transform requests and responses at various points in the gateway lifecycle.

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

### HTTP Authentication & Middleware Hooks

| Hook | Description | Payload Type | Use Cases |
|------|-------------|--------------|-----------|
| `http_pre_request` | Before any authentication (middleware) | `HttpPreRequestPayload` | Header transformation (X-API-Key → Bearer), correlation IDs |
| `http_auth_resolve_user` | Custom user authentication (auth layer) | `HttpAuthResolveUserPayload` | LDAP, mTLS, token auth, external auth services |
| `http_auth_check_permission` | Custom permission checking (RBAC layer) | `HttpAuthCheckPermissionPayload` | Bypass RBAC, time-based access, IP restrictions |
| `http_post_request` | After request completion (middleware) | `HttpPostRequestPayload` | Audit logging, metrics, response headers |

**See**: [HTTP Authentication Hooks Guide](../docs/docs/using/plugins/http-auth-hooks.md) for detailed examples and flow diagrams.

### MCP Protocol Hooks

| Hook | Description | Payload Type | Use Cases |
|------|-------------|--------------|-----------|
| `prompt_pre_fetch` | Before prompt template retrieval | `PromptPrehookPayload` | Input validation, access control |
| `prompt_post_fetch` | After prompt template retrieval | `PromptPosthookPayload` | Content filtering, transformation |
| `tool_pre_invoke` | Before tool execution | `ToolPreInvokePayload` | Parameter validation, safety checks |
| `tool_post_invoke` | After tool execution | `ToolPostInvokePayload` | Result filtering, audit logging |
| `resource_pre_fetch` | Before resource retrieval | `ResourcePreFetchPayload` | Protocol/domain validation |
| `resource_post_fetch` | After resource retrieval | `ResourcePostFetchPayload` | Content scanning, size limits |
| `agent_pre_invoke` | Before agent invocation | `AgentPreInvokePayload` | Message filtering, access control |
| `agent_post_invoke` | After agent response | `AgentPostInvokePayload` | Response filtering, audit logging |

### Future Hooks (Planned)

- `server_pre_register` / `server_post_register` - Virtual server verification
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

### Understanding the Plugin Base Class

The `Plugin` class is an abstract base class (ABC) that provides the foundation for all plugins. You **must** subclass it and implement at least one hook method to create a functional plugin.

```python
from abc import ABC
from mcpgateway.plugins.framework import Plugin

class MyPlugin(Plugin):
    """Your plugin must inherit from Plugin."""
    # Implement hook methods (see patterns below)
```

### Three Hook Registration Patterns

The plugin framework supports three flexible patterns for registering hook methods:

#### Pattern 1: Convention-Based (Recommended for Standard Hooks)

The simplest approach - just name your method to match the hook type:

```python
from mcpgateway.plugins.framework import (
    Plugin,
    PluginContext,
    ToolPreInvokePayload,
    ToolPreInvokeResult,
)

class MyPlugin(Plugin):
    """Convention-based hook - method name matches hook type."""

    async def tool_pre_invoke(
        self,
        payload: ToolPreInvokePayload,
        context: PluginContext
    ) -> ToolPreInvokeResult:
        """This hook is automatically discovered by its name."""

        # Your logic here
        modified_args = {**payload.args, "processed": True}

        modified_payload = ToolPreInvokePayload(
            name=payload.name,
            args=modified_args,
            headers=payload.headers
        )

        return ToolPreInvokeResult(
            modified_payload=modified_payload,
            metadata={"processed_by": self.name}
        )
```

**When to use:** Default choice for implementing standard framework hooks.

#### Pattern 2: Decorator-Based (Custom Method Names)

Use the `@hook` decorator to register a hook with a custom method name:

```python
from mcpgateway.plugins.framework import Plugin, PluginContext
from mcpgateway.plugins.framework.decorator import hook
from mcpgateway.plugins.framework import (
    ToolHookType,
    ToolPostInvokePayload,
    ToolPostInvokeResult,
)

class MyPlugin(Plugin):
    """Decorator-based hook with custom method name."""

    @hook(ToolHookType.TOOL_POST_INVOKE)
    async def my_custom_handler_name(
        self,
        payload: ToolPostInvokePayload,
        context: PluginContext
    ) -> ToolPostInvokeResult:
        """Method name doesn't match hook type, but @hook decorator registers it."""

        # Your logic here
        return ToolPostInvokeResult(continue_processing=True)
```

**When to use:** When you want descriptive method names that better match your plugin's purpose.

#### Pattern 3: Custom Hooks (Advanced)

Register completely new hook types with custom payload and result types:

```python
from mcpgateway.plugins.framework import Plugin, PluginContext, PluginPayload, PluginResult
from mcpgateway.plugins.framework.decorator import hook

# Define custom payload type
class EmailPayload(PluginPayload):
    recipient: str
    subject: str
    body: str

# Define custom result type
class EmailResult(PluginResult[EmailPayload]):
    pass

class MyPlugin(Plugin):
    """Custom hook with new hook type."""

    @hook("email_pre_send", EmailPayload, EmailResult)
    async def validate_email(
        self,
        payload: EmailPayload,
        context: PluginContext
    ) -> EmailResult:
        """Completely new hook type: 'email_pre_send'"""

        # Validate email address
        if "@" not in payload.recipient:
            # Fix invalid email
            modified_payload = EmailPayload(
                recipient=f"{payload.recipient}@example.com",
                subject=payload.subject,
                body=payload.body
            )
            return EmailResult(
                modified_payload=modified_payload,
                metadata={"fixed_email": True}
            )

        return EmailResult(continue_processing=True)
```

**When to use:** When extending the framework with domain-specific hook points not covered by standard hooks.

### Hook Method Signature Requirements

All hook methods must follow these rules:

1. **Must be async**: All hooks are asynchronous
2. **Three parameters**: `self`, `payload`, `context`
3. **Type hints required** (for validation): Payload and result types must be properly typed
4. **Return appropriate result type**: Each hook returns a `PluginResult` typed with the hook's payload type

```python
async def hook_name(
    self,
    payload: PayloadType,           # Specific to the hook (e.g., ToolPreInvokePayload)
    context: PluginContext          # Always PluginContext
) -> PluginResult[PayloadType]:     # PluginResult generic, parameterized by the payload type
    """Hook implementation."""
    pass
```

**Understanding Result Types:**

Each hook has a corresponding result type that is actually a type alias for `PluginResult[PayloadType]`:

```python
# These are type aliases defined in the framework
ToolPreInvokeResult = PluginResult[ToolPreInvokePayload]
ToolPostInvokeResult = PluginResult[ToolPostInvokePayload]
PromptPrehookResult = PluginResult[PromptPrehookPayload]
# ... and so on for each hook type
```

This means when you return a result, you're returning a `PluginResult` instance that knows about the specific payload type:

```python
# All of these are valid ways to construct results:
return ToolPreInvokeResult(continue_processing=True)
return ToolPreInvokeResult(modified_payload=new_payload)
return ToolPreInvokeResult(
    modified_payload=new_payload,
    metadata={"processed": True}
)
```

### Complete Plugin Example

Here's a complete plugin showing all patterns:

```python
# plugins/my_plugin/my_plugin.py
from mcpgateway.plugins.framework import (
    Plugin,
    PluginContext,
    PluginPayload,
    PluginResult,
    ToolPreInvokePayload,
    ToolPreInvokeResult,
    ToolPostInvokePayload,
    ToolPostInvokeResult,
    ToolHookType,
)
from mcpgateway.plugins.framework.decorator import hook

class MyPlugin(Plugin):
    """Example plugin demonstrating all three patterns."""

    # Pattern 1: Convention-based
    async def tool_pre_invoke(
        self,
        payload: ToolPreInvokePayload,
        context: PluginContext
    ) -> ToolPreInvokeResult:
        """Pre-process tool invocation - found by naming convention."""

        # Access plugin configuration
        threshold = self.config.config.get("threshold", 0.5)

        # Modify payload
        modified_args = {**payload.args, "plugin_processed": True}
        modified_payload = ToolPreInvokePayload(
            name=payload.name,
            args=modified_args,
            headers=payload.headers
        )

        return ToolPreInvokeResult(
            modified_payload=modified_payload,
            metadata={"threshold": threshold}
        )

    # Pattern 2: Decorator with custom name
    @hook(ToolHookType.TOOL_POST_INVOKE)
    async def process_tool_result(
        self,
        payload: ToolPostInvokePayload,
        context: PluginContext
    ) -> ToolPostInvokeResult:
        """Post-process tool result - found via decorator."""

        # Transform result
        if isinstance(payload.result, dict):
            modified_result = {
                **payload.result,
                "processed_by": self.name
            }
            modified_payload = ToolPostInvokePayload(
                name=payload.name,
                result=modified_result
            )
            return ToolPostInvokeResult(modified_payload=modified_payload)

        return ToolPostInvokeResult(continue_processing=True)
```

### Plugin Structure

Create a new directory under `plugins/`:

```
plugins/my_plugin/
├── __init__.py
├── plugin-manifest.yaml
├── my_plugin.py
└── README.md
```

### Plugin Manifest (`plugin-manifest.yaml`)

```yaml
description: "My custom plugin"
author: "Your Name"
version: "1.0.0"
available_hooks:
  - "tool_pre_invoke"
  - "tool_post_invoke"
default_configs:
  threshold: 0.8
  enable_logging: true
```

### Register Your Plugin

Add to `plugins/config.yaml`:

```yaml
plugins:
  - name: "MyCustomPlugin"
    kind: "plugins.my_plugin.my_plugin.MyPlugin"
    description: "My custom plugin description"
    version: "1.0.0"
    author: "Your Name"
    hooks: ["tool_pre_invoke", "tool_post_invoke"]
    mode: "enforce"
    priority: 100
    config:
      threshold: 0.8
      enable_logging: true
```

## Plugin Development Best Practices

### Hook Results and Control Flow

Each hook returns a result object that controls execution flow:

```python
# Allow processing to continue
return ToolPreInvokeResult(continue_processing=True)

# Modify the payload
return ToolPreInvokeResult(
    modified_payload=modified_payload,
    metadata={"processed": True}
)

# Block execution with a violation
from mcpgateway.plugins.framework import PluginViolation

return ToolPreInvokeResult(
    continue_processing=False,
    violation=PluginViolation(
        code="POLICY_VIOLATION",
        reason="Request blocked by security policy",
        description="Detected prohibited content"
    )
)
```

### Error Handling

Errors inside a plugin should be raised as exceptions. The plugin manager will catch the error, and its behavior depends on both the gateway's and plugin's configuration as follows:

1. If `plugin_settings.fail_on_plugin_error` in the plugin `config.yaml` is set to `true`, the exception is bubbled up as a PluginError and the error is passed to the client of ContextForge regardless of the plugin mode.
2. If `plugin_settings.fail_on_plugin_error` is set to false, the error is handled based off of the plugin mode in the plugin's config as follows:
   * If `mode` is `enforce`, both violations and errors are bubbled up as exceptions and the execution is blocked.
   * If `mode` is `enforce_ignore_error`, violations are bubbled up as exceptions and execution is blocked, but errors are logged and execution continues.
   * If `mode` is `permissive`, execution is allowed to proceed whether there are errors or violations. Both are logged.

### Accessing Plugin Context

The `context` parameter provides access to request-scoped and global state:

```python
async def tool_pre_invoke(
    self,
    payload: ToolPreInvokePayload,
    context: PluginContext
) -> ToolPreInvokeResult:
    # Access request ID
    request_id = context.global_context.request_id

    # Access user information
    user = context.global_context.user
    tenant_id = context.global_context.tenant_id

    # Store plugin-specific state (persists across all hooks in the request)
    context.state["invocation_count"] = context.state.get("invocation_count", 0) + 1

    # Add metadata
    context.metadata["processing_time"] = 0.123

    return ToolPreInvokeResult(continue_processing=True)
```

### Logging and Monitoring

```python
def __init__(self, config: PluginConfig):
    super().__init__(config)
    self.logger.info(f"Initialized {self.name} v{self.version}")

async def tool_pre_invoke(self, payload: ToolPreInvokePayload, context: PluginContext) -> ToolPreInvokeResult:
    self.logger.debug(f"Processing tool: {payload.name}")
    # ... plugin logic
    self.metrics.increment("requests_processed")
```

### Configuration Validation

```python
def __init__(self, config: PluginConfig):
    super().__init__(config)
    self._validate_config()

def _validate_config(self) -> None:
    """Validate plugin configuration."""
    required_keys = ["threshold", "api_key"]
    for key in required_keys:
        if key not in self.config.config:
            raise ValueError(f"Missing required config key: {key}")

    threshold = self.config.config.get("threshold")
    if not 0 <= threshold <= 1:
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

    async def initialize(self):
        """Called when plugin is loaded."""
        self._session = aiohttp.ClientSession()

    async def shutdown(self):
        """Called when plugin manager shuts down."""
        if self._session:
            await self._session.close()
```

## Testing Plugins

### Unit Testing

```python
import pytest
from mcpgateway.plugins.framework import (
    PluginConfig,
    PluginContext,
    GlobalContext,
    ToolPreInvokePayload,
)
from plugins.my_plugin.my_plugin import MyPlugin

@pytest.fixture
def plugin():
    config = PluginConfig(
        name="test_plugin",
        description="Test",
        version="1.0",
        author="Test",
        kind="plugins.my_plugin.my_plugin.MyPlugin",
        hooks=["tool_pre_invoke"],
        config={"threshold": 0.8}
    )
    return MyPlugin(config)

@pytest.mark.asyncio
async def test_tool_pre_invoke(plugin):
    payload = ToolPreInvokePayload(
        name="test_tool",
        args={"arg1": "value1"}
    )
    context = PluginContext(
        global_context=GlobalContext(request_id="test-123")
    )

    result = await plugin.tool_pre_invoke(payload, context)

    assert result.continue_processing is True
    assert result.modified_payload.args["plugin_processed"] is True
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
5. **Method signature errors**: Ensure hooks have correct parameters (self, payload, context) and are async

### Debug Mode

```bash
LOG_LEVEL=DEBUG make serve # port 4444
# Or with reloading dev server:
LOG_LEVEL=DEBUG make dev # port 8000
```

### Testing Hook Discovery

To verify your hooks are properly registered:

```python
from mcpgateway.plugins.framework import PluginManager

manager = PluginManager("path/to/config.yaml")
await manager.initialize()

# Check loaded plugins
for plugin_config in manager.config.plugins:
    print(f"Plugin: {plugin_config.name}")
    print(f"  Hooks: {plugin_config.hooks}")
```

## Documentation Links

- **Plugin Usage Guide**: https://ibm.github.io/mcp-context-forge/using/plugins/
- **Plugin Lifecycle**: https://ibm.github.io/mcp-context-forge/using/plugins/lifecycle/
- **API Reference**: Generated from code docstrings
- **Examples**: See `plugins/` directory for complete implementations
- **Hook Patterns Test**: `tests/unit/mcpgateway/plugins/framework/hooks/test_hook_patterns.py`

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
- Hook signature validation at plugin load time
