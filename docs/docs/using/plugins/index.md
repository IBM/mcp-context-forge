# Plugin Framework

!!! warning "Experimental Feature"
    The plugin framework is currently in **MVP stage** and marked as experimental. Only prompt hooks (`prompt_pre_fetch` and `prompt_post_fetch`) are implemented. Additional hooks for tools, resources, authentication, and server registration are planned for future releases.

## Overview

The MCP Gateway Plugin Framework provides a standardized way to extend gateway functionality through pre/post processing hooks at various points in the request lifecycle. Plugins can inspect, modify, or block requests and responses, enabling use cases like:

- **Content Filtering** - PII detection and masking
- **AI Safety** - Integration with LLMGuard, OpenAI Moderation
- **Security** - Input validation and output sanitization
- **Policy Enforcement** - Business rules and compliance
- **Transformation** - Request/response modification
- **Auditing** - Logging and monitoring

## Architecture

The plugin framework supports two types of plugins:

### Native Plugins
- Written in Python and run in-process
- Zero additional deployment overhead
- Direct access to gateway internals
- Best for lightweight operations (regex, validation)

### External Service Plugins
- Integrate with external microservices
- Support for authentication (Bearer, API Key, etc.)
- Ideal for AI models and complex processing
- Examples: LLMGuard, OPA, custom ML services

## Enabling Plugins

### 1. Environment Configuration

Enable the plugin framework in your `.env` file:

```bash
# Enable plugin framework
PLUGINS_ENABLED=true

# Optional: Custom plugin config path
PLUGIN_CONFIG_FILE=plugins/config.yaml
```

### 2. Plugin Configuration

The plugin configuration file is used to configure a set of plugins to run a
set of hook points throughout the MCP Context Forge.  An example configuration
is below.  It contains two main sections: `plugins` and `plugin_settings`.

Create or modify `plugins/config.yaml`:

```yaml
# Main plugin configuration
plugins:
  - name: "ContentFilter"
    kind: "plugins.native.content_filter.ContentFilterPlugin"
    description: "Filters inappropriate content"
    version: "1.0"
    author: "Your Team"
    hooks: ["prompt_pre_fetch", "prompt_post_fetch"]
    tags: ["security", "filter"]
    mode: "enforce"  # enforce | permissive | disabled
    priority: 100    # Lower number = higher priority
    conditions:
      - prompts: ["customer_chat", "support_bot"]
        server_ids: []  # Apply to all servers
        tenant_ids: []  # Apply to all tenants
    config:
      # Plugin-specific configuration
      block_patterns: ["ssn", "credit_card"]
      mask_char: "*"

# Global plugin settings
plugin_settings:
  parallel_execution_within_band: false
  plugin_timeout: 30
  fail_on_plugin_error: false
  enable_plugin_api: true
  plugin_health_check_interval: 60
```

The `plugins` section lists the set of configured plugins that will be loaded
by the Context Forge at startup.  Each plugin contains a set of standard configurations,
and then a `config` section designed for plugin specific configurations. The attributes
are defined as follows:

| Attribute | Description | Example Value |
|-----------|-------------|---------------|
| **name**  | A unique name for the plugin. | MyFirstPlugin |
| **kind**  | A fully qualified string representing the plugin python object. | plugins.native.content_filter.ContentFilterPlugin |
| **description** | The description of the plugin configuration. | A plugin for replacing bad words. |
| **version** | The version of the plugin configuration. | 0.1 |
| **author** | The team that wrote the plugin. | MCP Context Forge |
| **hooks** | A list of hooks for which the plugin will be executed. Supported hooks: "prompt_pre_fetch", "prompt_post_fetch", "tool_pre_invoke", "tool_post_invoke"  | ["prompt_pre_fetch", "prompt_post_fetch", "tool_pre_invoke", "tool_post_invoke"] |
| **tags** | Descriptive keywords that make the configuration searchable. | ["security", "filter"] |
| **mode** | Mode of operation of the plugin. - enforce (stops during a violation), permissive (audits a violation but doesn't stop), disabled (disabled) | permissive |
| **priority** | The priority in which the plugin will run - 0 is higher priority | 100 |
| **conditions** | A list of conditions under which a plugin is run. See section on conditions.|  |
| **config** | Plugin specific configuration.  This is a dictionary and is passed to the plugin on initialization. |   |

The `plugin_settings` are as follows:

| Attribute | Description | Example Value |
|-----------|-------------|---------------|
| **parallel_execution_within_band** | Plugins in the same band are run in parallel (currently not implemented). | true or false |
| **plugin_timeout** | The time in seconds before stopping plugin execution (not implemented). | 30 |
| **fail_on_plugin_error** | Cause the execution of the task to fail if the plugin errors. | true or false |
| **plugin_health_check_interval** | Health check interval in seconds (not implemented). | 60 |


### 3. Execution Modes

Each plugin can operate in one of three modes:

| Mode | Description | Use Case |
|------|-------------|----------|
| **enforce** | Blocks requests on policy violations | Production guardrails |
| **permissive** | Logs violations but allows requests | Testing and monitoring |
| **disabled** | Plugin loaded but not executed | Temporary deactivation |

### 4. Priority and Execution Order

Plugins execute in priority order (ascending):

```yaml
# Execution order example
plugins:
  - name: "Authentication"
    priority: 10      # Runs first

  - name: "RateLimiter"
    priority: 50      # Runs second

  - name: "ContentFilter"
    priority: 100     # Runs third

  - name: "Logger"
    priority: 200     # Runs last
```

Plugins with the same priority may execute in parallel if `parallel_execution_within_band` is enabled.

### 5. Conditions of Execution

Users may only want plugins to be invoked on specific servers, tools, and prompts. To address this, a set of conditionals can be applied to a plugin. The attributes in a conditional combine together in as a set of `and` operations, while each attribute list item is `ored` with other items in the list.  The attributes are defined as follows:

| Attribute | Description
|-----------|------------|
| **server_ids** | The list of MCP servers on which the plugin will trigger |
| **tools** | The list of tools on which the plugin will be applied. |
| **prompts** | The list of prompts on which the plugin will be applied. |
| **user_patterns** | The list of users on which the plugin will be applied. |
| **content_types** | The list of content types on which the plugin will trigger. |

## Available Hooks

Currently implemented hooks:

| Hook | Description | Use Cases |
|------|-------------|-----------|
| `prompt_pre_fetch` | Before prompt retrieval | Validate/modify prompt arguments |
| `prompt_post_fetch` | After prompt rendering | Filter/transform rendered prompts |
| `tool_pre_invoke` | Before tool invocation | Validate/modify tool arguments, block dangerous operations |
| `tool_post_invoke` | After tool execution | Filter/transform tool results, audit tool usage |

### Tool Hooks Details

The tool hooks enable plugins to intercept and modify tool invocations:

- **`tool_pre_invoke`**: Receives the tool name and arguments before execution. Can modify arguments or block the invocation entirely.
- **`tool_post_invoke`**: Receives the tool result after execution. Can modify the result or block it from being returned.

Example use cases:
- PII detection and masking in tool inputs/outputs
- Rate limiting specific tools
- Audit logging of tool usage
- Input validation and sanitization
- Output filtering and transformation

Planned hooks (not yet implemented):

- `resource_pre_fetch` / `resource_post_fetch` - Resource content filtering
- `server_pre_register` / `server_post_register` - Server validation
- `auth_pre_check` / `auth_post_check` - Custom authentication
- `federation_pre_sync` / `federation_post_sync` - Gateway federation

## Writing Plugins

### Plugin Structure

```python
from mcpgateway.plugins.framework.base import Plugin
from mcpgateway.plugins.framework.models import PluginConfig
from mcpgateway.plugins.framework.plugin_types import (
    PluginContext,
    PromptPrehookPayload,
    PromptPrehookResult,
    PromptPosthookPayload,
    PromptPosthookResult,
    ToolPreInvokePayload,
    ToolPreInvokeResult,
    ToolPostInvokePayload,
    ToolPostInvokeResult
)

class MyPlugin(Plugin):
    """Example plugin implementation."""

    def __init__(self, config: PluginConfig):
        super().__init__(config)
        # Initialize plugin-specific configuration
        self.my_setting = config.config.get("my_setting", "default")

    async def prompt_pre_fetch(
        self,
        payload: PromptPrehookPayload,
        context: PluginContext
    ) -> PromptPrehookResult:
        """Process prompt before retrieval."""

        # Access prompt name and arguments
        prompt_name = payload.name
        args = payload.args

        # Example: Block requests with forbidden words
        if "forbidden" in str(args.values()).lower():
            return PromptPrehookResult(
                continue_processing=False,
                violation=PluginViolation(
                    plugin_name=self.name,
                    description="Forbidden content detected",
                    violation_code="FORBIDDEN_CONTENT",
                    details={"found_in": "arguments"}
                )
            )

        # Example: Modify arguments
        if "transform_me" in args:
            args["transform_me"] = args["transform_me"].upper()
            return PromptPrehookResult(
                modified_payload=PromptPrehookPayload(prompt_name, args)
            )

        # Allow request to continue unmodified
        return PromptPrehookResult()

    async def prompt_post_fetch(
        self,
        payload: PromptPosthookPayload,
        context: PluginContext
    ) -> PromptPosthookResult:
        """Process prompt after rendering."""

        # Access rendered prompt
        prompt_result = payload.result

        # Example: Add metadata to context
        context.metadata["processed_by"] = self.name

        # Example: Modify response
        for message in prompt_result.messages:
            message.content.text = message.content.text.replace(
                "old_text", "new_text"
            )

        return PromptPosthookResult(
            modified_payload=payload
        )

    async def tool_pre_invoke(
        self,
        payload: ToolPreInvokePayload,
        context: PluginContext
    ) -> ToolPreInvokeResult:
        """Process tool before invocation."""

        # Access tool name and arguments
        tool_name = payload.name
        args = payload.args

        # Example: Block dangerous operations
        if tool_name == "file_delete" and "system" in str(args):
            return ToolPreInvokeResult(
                continue_processing=False,
                violation=PluginViolation(
                    plugin_name=self.name,
                    description="Dangerous operation blocked",
                    violation_code="DANGEROUS_OP",
                    details={"tool": tool_name}
                )
            )

        # Example: Modify arguments
        if "sanitize_me" in args:
            args["sanitize_me"] = self.sanitize_input(args["sanitize_me"])
            return ToolPreInvokeResult(
                modified_payload=ToolPreInvokePayload(tool_name, args)
            )

        return ToolPreInvokeResult()

    async def tool_post_invoke(
        self,
        payload: ToolPostInvokePayload,
        context: PluginContext
    ) -> ToolPostInvokeResult:
        """Process tool after invocation."""

        # Access tool result
        tool_name = payload.name
        result = payload.result

        # Example: Filter sensitive data from results
        if isinstance(result, dict) and "sensitive_data" in result:
            result["sensitive_data"] = "[REDACTED]"
            return ToolPostInvokeResult(
                modified_payload=ToolPostInvokePayload(tool_name, result)
            )

        # Example: Add audit metadata
        context.metadata["tool_executed"] = tool_name
        context.metadata["execution_time"] = time.time()

        return ToolPostInvokeResult()

    async def shutdown(self):
        """Cleanup when plugin shuts down."""
        # Close connections, save state, etc.
        pass
```

### Plugin Context and State

Plugins can maintain state between pre/post hooks:

```python
async def prompt_pre_fetch(self, payload, context):
    # Store state for later use
    context.set_state("request_time", time.time())
    context.set_state("original_args", payload.args.copy())

    return PromptPrehookResult()

async def prompt_post_fetch(self, payload, context):
    # Retrieve state from pre-hook
    elapsed = time.time() - context.get_state("request_time", 0)
    original = context.get_state("original_args", {})

    # Add timing metadata
    context.metadata["processing_time_ms"] = elapsed * 1000

    return PromptPosthookResult()
```

### External Service Plugin Example

```python
class LLMGuardPlugin(Plugin):
    """Example external service integration."""

    def __init__(self, config: PluginConfig):
        super().__init__(config)
        self.service_url = config.config.get("service_url")
        self.api_key = config.config.get("api_key")
        self.timeout = config.config.get("timeout", 30)

    async def prompt_pre_fetch(self, payload, context):
        # Call external service
        async with httpx.AsyncClient() as client:
            try:
                response = await client.post(
                    f"{self.service_url}/analyze",
                    json={
                        "text": str(payload.args),
                        "policy": "strict"
                    },
                    headers={
                        "Authorization": f"Bearer {self.api_key}"
                    },
                    timeout=self.timeout
                )

                result = response.json()

                if result.get("blocked", False):
                    return PromptPrehookResult(
                        continue_processing=False,
                        violation=PluginViolation(
                            plugin_name=self.name,
                            description=result.get("reason", "Content blocked"),
                            violation_code="LLMGUARD_BLOCKED",
                            details=result
                        )
                    )

            except Exception as e:
                # Handle errors based on plugin settings
                if self.config.mode == PluginMode.ENFORCE:
                    return PromptPrehookResult(
                        continue_processing=False,
                        violation=PluginViolation(
                            plugin_name=self.name,
                            description=f"Service error: {str(e)}",
                            violation_code="SERVICE_ERROR",
                            details={"error": str(e)}
                        )
                    )

        return PromptPrehookResult()
```

## Plugin Development Guide

### 1. Create Plugin Directory

```bash
mkdir -p plugins/my_plugin
touch plugins/my_plugin/__init__.py
touch plugins/my_plugin/plugin.py
touch plugins/my_plugin/plugin-manifest.yaml
```

### 2. Write Plugin Manifest

```yaml
# plugins/my_plugin/plugin-manifest.yaml
description: "My custom plugin for X"
author: "Your Name"
version: "1.0.0"
tags: ["custom", "filter"]
available_hooks:
  - "prompt_pre_fetch"
  - "prompt_post_fetch"
default_config:
  setting_one: "default_value"
  setting_two: 123
```

### 3. Implement Plugin Class

```python
# plugins/my_plugin/plugin.py
from mcpgateway.plugins.framework.base import Plugin

class MyPlugin(Plugin):
    # Implementation here
    pass
```

### 4. Register in Configuration

```yaml
# plugins/config.yaml
plugins:
  - name: "MyCustomPlugin"
    kind: "plugins.my_plugin.plugin.MyPlugin"
    hooks: ["prompt_pre_fetch"]
    # ... other configuration
```

### 5. Test Your Plugin

```python
# tests/test_my_plugin.py
import pytest
from plugins.my_plugin.plugin import MyPlugin
from mcpgateway.plugins.framework.models import PluginConfig

@pytest.mark.asyncio
async def test_my_plugin():
    config = PluginConfig(
        name="test",
        kind="plugins.my_plugin.plugin.MyPlugin",
        hooks=["prompt_pre_fetch"],
        config={"setting_one": "test_value"}
    )

    plugin = MyPlugin(config)

    # Test your plugin logic
    result = await plugin.prompt_pre_fetch(payload, context)
    assert result.continue_processing
```

## Best Practices

### 1. Error Handling

Always handle errors gracefully:

```python
async def prompt_pre_fetch(self, payload, context):
    try:
        # Plugin logic
        pass
    except Exception as e:
        logger.error(f"Plugin {self.name} error: {e}")

        # In permissive mode, log and continue
        if self.mode == PluginMode.PERMISSIVE:
            return PromptPrehookResult()

        # In enforce mode, block the request
        return PromptPrehookResult(
            continue_processing=False,
            violation=PluginViolation(
                plugin_name=self.name,
                description="Plugin error occurred",
                violation_code="PLUGIN_ERROR",
                details={"error": str(e)}
            )
        )
```

### 2. Performance Considerations

- Keep plugin operations lightweight
- Use caching for expensive operations
- Respect the configured timeout
- Consider async operations for I/O

```python
class CachedPlugin(Plugin):
    def __init__(self, config):
        super().__init__(config)
        self._cache = {}
        self._cache_ttl = config.config.get("cache_ttl", 300)

    async def expensive_operation(self, key):
        # Check cache first
        if key in self._cache:
            cached_value, timestamp = self._cache[key]
            if time.time() - timestamp < self._cache_ttl:
                return cached_value

        # Perform expensive operation
        result = await self._do_expensive_work(key)

        # Cache result
        self._cache[key] = (result, time.time())
        return result
```

### 3. Conditional Execution

Use conditions to limit plugin scope:

```yaml
conditions:
  - prompts: ["sensitive_prompt"]
    server_ids: ["prod-server-1", "prod-server-2"]
    tenant_ids: ["enterprise-tenant"]
    user_patterns: ["admin-*", "support-*"]
```

### 4. Logging and Monitoring

Use appropriate log levels:

```python
logger.debug(f"Plugin {self.name} processing prompt: {payload.name}")
logger.info(f"Plugin {self.name} blocked request: {violation_code}")
logger.warning(f"Plugin {self.name} timeout approaching")
logger.error(f"Plugin {self.name} failed: {error}")
```

## API Reference

### Plugin Management Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/plugins` | GET | List all loaded plugins |
| `/plugins/stats` | GET | Get plugin execution statistics |
| `/plugins/reload/{name}` | POST | Reload a specific plugin |
| `/plugins/stats/reset` | POST | Reset plugin statistics |

### Example API Usage

```bash
# List plugins
curl http://localhost:8000/plugins

# Response
[
  {
    "name": "ContentFilter",
    "priority": 100,
    "mode": "enforce",
    "hooks": ["prompt_pre_fetch", "prompt_post_fetch"],
    "tags": ["security", "filter"],
    "conditions": {
      "prompts": ["customer_chat"]
    }
  }
]
```

## Troubleshooting

### Plugin Not Loading

1. Check server logs for initialization errors
2. Verify plugin class path in configuration
3. Ensure all dependencies are installed
4. Check Python import path includes plugin directory

### Plugin Not Executing

1. Verify plugin is enabled (`mode` != "disabled")
2. Check conditions match your request
3. Review priority ordering
4. Enable debug logging to see execution flow

### Performance Issues

1. Monitor plugin execution time in logs
2. Check for blocking I/O operations
3. Review timeout settings
4. Consider caching expensive operations

## Future Roadmap

The plugin framework is under active development. Planned features include:

- **Additional Hooks** - Tool, resource, auth, and server hooks
- **Admin UI** - Visual plugin management interface
- **Hot Reload** - Configuration changes without restart
- **Plugin Marketplace** - Share and discover plugins
- **Advanced Features** - Rate limiting, caching, metrics

## Contributing

To contribute a plugin:

1. Follow the plugin structure guidelines
2. Include comprehensive tests
3. Document configuration options
4. Submit a pull request with examples

For framework improvements, please open an issue to discuss proposed changes.
