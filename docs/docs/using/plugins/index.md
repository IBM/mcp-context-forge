# Plugin Framework

!!! success "Production Ready"
    The plugin framework is **production ready** with comprehensive hook coverage, robust error handling, and battle-tested implementations. Supports both self-contained and external service plugins.

## Overview

The MCP Context Forge Plugin Framework provides a comprehensive, production-grade system for extending gateway functionality through pre/post processing hooks at various points in the MCP request lifecycle. The framework supports both high-performance self-contained plugins and sophisticated external AI service integrations.

### Key Capabilities

- **AI Safety Middleware** - Integration with LlamaGuard, OpenAI Moderation, custom ML models
- **Content Security** - PII detection and masking, input validation, output sanitization
- **Policy Enforcement** - Business rules, compliance checking, audit trails
- **Performance Protection** - Timeout handling, resource limits, graceful degradation
- **Operational Excellence** - Health‑oriented design, clear errors, sensible defaults
- **Enterprise Features** - Multi-tenant isolation, conditional execution, sophisticated context management

## Architecture

The plugin framework implements a **hybrid architecture** supporting both self-contained and external service integrations:

### Self-Contained Plugins
- **In-Process Execution:** Written in Python, run directly within the gateway process
- **High Performance:** Sub-millisecond latency, no network overhead
- **Direct Access:** Full access to gateway internals and context
- **Use Cases:** PII filtering, regex transformations, input validation, simple business rules
- **Examples:** `PIIFilterPlugin`, `SearchReplacePlugin`, `DenyListPlugin`

### External Service Plugins
- **MCP Integration:** External plugins communicate via MCP using STDIO or Streamable HTTP
- **Enterprise AI Support:** LlamaGuard, OpenAI Moderation, custom ML models
- **Independent Scaling:** Services run outside the gateway and can scale separately
- **Use Cases:** Advanced AI safety, complex ML inference, policy engines (e.g., OPA)
- **Examples:** OPA external plugin server, LlamaGuard integration, OpenAI Moderation

### Unified Plugin Interface

Both plugin types implement the same interface, enabling seamless switching between deployment models:

```python
class Plugin:
    async def prompt_pre_fetch(self, payload, context) -> PluginResult
    async def tool_pre_invoke(self, payload, context) -> PluginResult
    # ... unified interface for all hook points
```

## Enabling Plugins

### 1. Environment Configuration

Enable the plugin framework in your `.env` file:

```bash
# Enable plugin framework
PLUGINS_ENABLED=true

# Optional: Custom plugin config path
PLUGIN_CONFIG_FILE=plugins/config.yaml
```

## Build Your Own Plugin (Quickstart)

Decide between a native (in‑process) or external (MCP) plugin:

- Native: simplest path; write Python class extending `Plugin`, configure via `plugins/config.yaml` using fully‑qualified class path.
- External: runs as a separate MCP server (STDIO or Streamable HTTP); great for independent scaling and isolation.

Quick native skeleton:

```python
from mcpgateway.plugins.framework import Plugin, PluginConfig, PluginContext, PromptPrehookPayload, PromptPrehookResult

class MyPlugin(Plugin):
    def __init__(self, config: PluginConfig):
        super().__init__(config)

    async def prompt_pre_fetch(self, payload: PromptPrehookPayload, context: PluginContext) -> PromptPrehookResult:
        # modify or block
        return PromptPrehookResult(modified_payload=payload)
```

Register it in `plugins/config.yaml`:

```yaml
plugins:
  - name: "MyPlugin"
    kind: "plugins.my_plugin.plugin.MyPlugin"
    hooks: ["prompt_pre_fetch"]
    mode: "permissive"
    priority: 120
```

External plugin quickstart: see the Lifecycle guide for `mcpplugins bootstrap`, building, and serving. Then point the gateway at your server:

```yaml
plugins:
  - name: "MyExternal"
    kind: "external"
    priority: 10
    mcp:
      proto: STREAMABLEHTTP
      url: http://localhost:8000/mcp
```

For detailed steps (bootstrap, build, serve, test), see the Lifecycle page.

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
    mode: "enforce"  # enforce | enforce_ignore_error | permissive | disabled
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

## Getting Started (Built‑in Plugins)

Use the built‑in plugins out of the box:

1) Copy and adapt the example config (enable any subset):

```yaml
# plugins/config.yaml
plugins:
  - name: "PIIFilterPlugin"
    kind: "plugins.pii_filter.pii_filter.PIIFilterPlugin"
    hooks: ["prompt_pre_fetch", "prompt_post_fetch", "tool_pre_invoke", "tool_post_invoke"]
    mode: "permissive"
    priority: 50
    config:
      detect_ssn: true
      detect_email: true
      detect_credit_card: true
      default_mask_strategy: "partial"

  - name: "ReplaceBadWordsPlugin"
    kind: "plugins.regex_filter.search_replace.SearchReplacePlugin"
    hooks: ["prompt_pre_fetch", "prompt_post_fetch", "tool_pre_invoke", "tool_post_invoke"]
    mode: "enforce"
    priority: 150
    config:
      words:
        - { search: "crap", replace: "crud" }
        - { search: "crud", replace: "yikes" }

  - name: "DenyListPlugin"
    kind: "plugins.deny_filter.deny.DenyListPlugin"
    hooks: ["prompt_pre_fetch"]
    mode: "enforce"
    priority: 100
    config:
      words: ["innovative", "groundbreaking", "revolutionary"]

  - name: "ResourceFilterExample"
    kind: "plugins.resource_filter.resource_filter.ResourceFilterPlugin"
    hooks: ["resource_pre_fetch", "resource_post_fetch"]
    mode: "enforce"
    priority: 75
    config:
      max_content_size: 1048576
      allowed_protocols: ["http", "https"]
      blocked_domains: ["malicious.example.com"]
      content_filters:
        - { pattern: "password\\s*[:=]\\s*\\S+", replacement: "password: [REDACTED]" }

plugin_settings:
  parallel_execution_within_band: false
  plugin_timeout: 30
  fail_on_plugin_error: false
  enable_plugin_api: true
  plugin_health_check_interval: 60
```

2) Ensure `.env` contains: `PLUGINS_ENABLED=true` and `PLUGIN_CONFIG_FILE=plugins/config.yaml`.

3) Start the gateway: `make dev` (or `make serve`).

That's it — the gateway now runs the enabled plugins at the selected hook points.

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
| **hooks** | Hook points where the plugin runs. Supported hooks: "prompt_pre_fetch", "prompt_post_fetch", "tool_pre_invoke", "tool_post_invoke", "resource_pre_fetch", "resource_post_fetch" | ["prompt_pre_fetch", "prompt_post_fetch", "tool_pre_invoke", "tool_post_invoke", "resource_pre_fetch", "resource_post_fetch"] |
| **tags** | Descriptive keywords that make the configuration searchable. | ["security", "filter"] |
| **mode** | Mode of operation of the plugin. - enforce (stops during a violation), permissive (audits a violation but doesn't stop), disabled (disabled) | permissive |
| **priority** | The priority in which the plugin will run - 0 is higher priority | 100 |
| **conditions** | A list of conditions under which a plugin is run. See section on conditions.|  |
| **config** | Plugin specific configuration.  This is a dictionary and is passed to the plugin on initialization. |   |

The `plugin_settings` are as follows:

| Attribute | Description | Example Value |
|-----------|-------------|---------------|
| **parallel_execution_within_band** | Reserved for future: execute same‑priority plugins in parallel (not implemented). | true or false |
| **plugin_timeout** | Per‑plugin call timeout in seconds. | 30 |
| **fail_on_plugin_error** | Cause the execution of the task to fail if the plugin errors. | true or false |
| **plugin_health_check_interval** | Reserved for future health checks (not implemented). | 60 |


### 3. Execution Modes

Each plugin can operate in one of four modes:

| Mode | Description | Use Case |
|------|-------------|----------|
| **enforce** | Blocks requests on policy violations and plugin errors | Production guardrails |
| **enforce_ignore_errors** | Blocks requests on policy violations but only logs errors | Production guardrails |
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
| **resources** | The list of resource URIs on which the plugin will be applied. |
| **user_patterns** | The list of users on which the plugin will be applied. |
| **content_types** | The list of content types on which the plugin will trigger. |

## Available Hooks

The plugin framework provides comprehensive hook coverage across the entire MCP request lifecycle:

### Production Hooks (Implemented)

| Hook | Execution Point | Use Cases | Payload Type |
|------|----------------|-----------|--------------|
| `prompt_pre_fetch` | Before prompt template retrieval | Argument validation, PII scanning, input sanitization | `PromptPrehookPayload` |
| `prompt_post_fetch` | After prompt template rendering | Content filtering, output transformation, safety checks | `PromptPosthookPayload` |
| `tool_pre_invoke` | Before tool execution | Authorization, argument validation, dangerous operation blocking | `ToolPreInvokePayload` |
| `tool_post_invoke` | After tool execution | Result filtering, PII masking, audit logging, response transformation | `ToolPostInvokePayload` |
| `resource_pre_fetch` | Before resource fetching | URI validation, protocol checking, metadata injection | `ResourcePreFetchPayload` |
| `resource_post_fetch` | After resource content retrieval | Content filtering, size validation, sensitive data redaction | `ResourcePostFetchPayload` |

### Planned Hooks (Roadmap)

| Hook | Purpose | Expected Release |
|------|---------|-----------------|
| `server_pre_register` | Server attestation and validation before admission | v0.7.0 |
| `server_post_register` | Post-registration processing and setup | v0.7.0 |
| `auth_pre_check` | Custom authentication logic integration | v0.7.0 |
| `auth_post_check` | Post-authentication processing and enrichment | v0.7.0 |
| `federation_pre_sync` | Gateway federation validation and filtering | v0.8.0 |
| `federation_post_sync` | Post-federation data processing and reconciliation | v0.8.0 |

### Prompt Hooks Details

The prompt hooks allow plugins to intercept and modify prompt retrieval and rendering:

- **`prompt_pre_fetch`**: Receives the prompt name and arguments before prompt template retrieval.  Can modify the arguments.
- **`prompt_post_fetch`**: Receives the completed prompt after rendering.  Can modify the prompt text or block it from being returned.

Example Use Cases:
- Detect prompt injection attacks
- Sanitize or anonymize prompts
- Search and replace

#### Prompt Hook Payloads

**PromptPrehookPayload**: Payload for prompt pre-fetch hooks.

```python
class PromptPrehookPayload(BaseModel):
    name: str                                    # Prompt template name
    args: Optional[dict[str, str]] = Field(default_factory=dict)  # Template arguments
```

**Example**:
```python
payload = PromptPrehookPayload(
    name="user_greeting",
    args={"user_name": "Alice", "time_of_day": "morning"}
)
```

**PromptPosthookPayload**: Payload for prompt post-fetch hooks.

```python
class PromptPosthookPayload(BaseModel):
    name: str                                    # Prompt name
    result: PromptResult                         # Rendered prompt result
```

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

#### Tool Hook Payloads

**ToolPreInvokePayload**: Payload for tool pre-invoke hooks.

```python
class ToolPreInvokePayload(BaseModel):
    name: str                                    # Tool name
    args: Optional[dict[str, Any]] = Field(default_factory=dict)  # Tool arguments
    headers: Optional[HttpHeaderPayload] = None  # HTTP pass-through headers
```

**ToolPostInvokePayload**: Payload for tool post-invoke hooks.

```python
class ToolPostInvokePayload(BaseModel):
    name: str                                    # Tool name
    result: Any                                  # Tool execution result
```

The associated `HttpHeaderPayload` object for the `ToolPreInvokePayload` is as follows:

Special payload for HTTP header manipulation.

```python
class HttpHeaderPayload(RootModel[dict[str, str]]):
    # Provides dictionary-like access to HTTP headers
    # Supports: __iter__, __getitem__, __setitem__, __len__
```

**Usage**:
```python
headers = HttpHeaderPayload({"Authorization": "Bearer token", "Content-Type": "application/json"})
headers["X-Custom-Header"] = "custom_value"
auth_header = headers["Authorization"]
```

### Resource Hooks Details

The resource hooks enable plugins to intercept and modify resource fetching:

- **`resource_pre_fetch`**: Receives the resource URI and metadata before fetching. Can modify the URI, add metadata, or block the fetch entirely.
- **`resource_post_fetch`**: Receives the resource content after fetching. Can modify the content, redact sensitive information, or block it from being returned.

Example use cases:
- Protocol validation (block non-HTTPS resources)
- Domain blocklisting/allowlisting
- Content size limiting
- Sensitive data redaction
- Content transformation and filtering
- Resource caching metadata

#### Resource Hook Payloads

**ResourcePreFetchPayload**: Payload for resource pre-fetch hooks.

```python
class ResourcePreFetchPayload(BaseModel):
    uri: str                                     # Resource URI
    metadata: Optional[dict[str, Any]] = Field(default_factory=dict)  # Request metadata
```

**ResourcePostFetchPayload**: Payload for resource post-fetch hooks.

```python
class ResourcePostFetchPayload(BaseModel):
    uri: str                                     # Resource URI
    content: Any                                 # Fetched resource content
```

Planned hooks (not yet implemented):

- `server_pre_register` / `server_post_register` - Server validation
- `auth_pre_check` / `auth_post_check` - Custom authentication
- `federation_pre_sync` / `federation_post_sync` - Gateway federation

## Writing Plugins

### Plugin Structure

```python
from mcpgateway.plugins.framework import (
    Plugin,
    PluginConfig,
    PluginContext,
    PromptPrehookPayload,
    PromptPrehookResult,
    PromptPosthookPayload,
    PromptPosthookResult,
    ToolPreInvokePayload,
    ToolPreInvokeResult,
    ToolPostInvokePayload,
    ToolPostInvokeResult,
    ResourcePreFetchPayload,
    ResourcePreFetchResult,
    ResourcePostFetchPayload,
    ResourcePostFetchResult
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
                    reason="Forbidden content",
                    description="Forbidden content detected",
                    code="FORBIDDEN_CONTENT",
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
                    reason="Dangerous operation blocked",
                    description="Dangerous operation blocked",
                    code="DANGEROUS_OP",
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

    async def resource_pre_fetch(
        self,
        payload: ResourcePreFetchPayload,
        context: PluginContext
    ) -> ResourcePreFetchResult:
        """Process resource before fetching."""

        # Access resource URI and metadata
        uri = payload.uri
        metadata = payload.metadata

        # Example: Block certain protocols
        from urllib.parse import urlparse
        parsed = urlparse(uri)
        if parsed.scheme not in ["http", "https", "file"]:
        return ResourcePreFetchResult(
            continue_processing=False,
            violation=PluginViolation(
                reason="Protocol not allowed",
                description=f"Protocol {parsed.scheme} not allowed",
                code="PROTOCOL_BLOCKED",
                details={"uri": uri, "protocol": parsed.scheme}
            )
        )

        # Example: Add metadata
        metadata["validated_by"] = self.name
        return ResourcePreFetchResult(
            modified_payload=ResourcePreFetchPayload(uri, metadata)
        )

    async def resource_post_fetch(
        self,
        payload: ResourcePostFetchPayload,
        context: PluginContext
    ) -> ResourcePostFetchResult:
        """Process resource after fetching."""

        # Access resource content
        uri = payload.uri
        content = payload.content

        # Example: Redact sensitive patterns from text content
        if hasattr(content, 'text') and content.text:
            # Redact email addresses
            import re
            content.text = re.sub(
                r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b',
                '[EMAIL_REDACTED]',
                content.text
            )

        return ResourcePostFetchResult(
            modified_payload=ResourcePostFetchPayload(uri, content)
        )

    async def shutdown(self):
        """Cleanup when plugin shuts down."""
        # Close connections, save state, etc.
        pass
```

### Plugin Context and State

Each hook function has a `context` object of type `PluginContext` which is designed to allow plugins to pass state between one another (across pre/post hook pairs) or for a plugin to pass state information to itself across pre/post hook pairs.  The plugin context looks as follows:

```python
class GlobalContext(BaseModel):
    """The global context, which shared across all plugins.

    Attributes:
            request_id (str): ID of the HTTP request.
            user (str): user ID associated with the request.
            tenant_id (str): tenant ID.
            server_id (str): server ID.
            metadata (Optional[dict[str,Any]]): a global shared metadata across plugins (Read-only from plugin's perspective.).
            state (Optional[dict[str,Any]]): a global shared state across plugins.
    """

    request_id: str
    user: Optional[str] = None
    tenant_id: Optional[str] = None
    server_id: Optional[str] = None
    state: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)


class PluginContext(BaseModel):
    """The plugin's context, which lasts a request lifecycle.

    Attributes:
       state:  the inmemory state of the request.
       global_context: the context that is shared across plugins.
       metadata: plugin meta data.
    """

    state: dict[str, Any] = Field(default_factory=dict)
    global_context: GlobalContext
    metadata: dict[str, Any] = Field(default_factory=dict)
```

As can be seen, the `PluginContext` has both a `state` dictionary and a `global_context` object that also has a `state` dictionary. A single plugin can share state between pre/post hook pairs by using the
the `PluginContext` state dictionary. It can share state with other plugins using the `context.global_context.state` dictionary.  Metadata for the specific hook site is passed in through the `metadata` dictionaries in the `context.global_context.metadata`. It is meant to be read-only. The `context.metadata` is plugin specific metadata and can be used to store metadata information such as timing information.

The following shows how plugins can maintain state between pre/post hooks:

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

#### Tool and Gateway Metadata

Currently, the tool pre/post hooks have access to tool and gateway metadata through the global context metadata dictionary.  They are accessible as follows:

It can be accessed inside of the tool hooks through:

```python
from mcpgateway.plugins.framework.constants import GATEWAY_METADATA, TOOL_METADATA

tool_meta = context.global_context.metadata[TOOL_METADATA]
assert tool_meta.original_name == "test_tool"
assert tool_meta.url.host == "example.com"
assert tool_meta.integration_type == "REST" or tool_meta.integration_type == "MCP"
```

Note, if the integration type is `MCP` the gateway information may also be available as follows.

```python
gateway_meta = context.global_context.metadata[GATEWAY_METADATA]
assert gateway_meta.name == "test_gateway"
assert gateway_meta.transport == "sse"
assert gateway_meta.url.host == "example.com"
```

Metadata for other entities such as prompts and resources will be added in future versions of the gateway.

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
                            reason="External service blocked",
                            description=result.get("reason", "Content blocked"),
                            code="LLMGUARD_BLOCKED",
                            details=result
                        )
                    )

            except Exception as e:
                # Handle errors based on plugin settings
                if self.config.mode == PluginMode.ENFORCE:
                    return PromptPrehookResult(
                        continue_processing=False,
                        violation=PluginViolation(
                            reason="Service error",
                            description=f"Service error: {str(e)}",
                            code="SERVICE_ERROR",
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
from mcpgateway.plugins.framework import Plugin

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
from mcpgateway.plugins.framework import PluginConfig

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

Errors inside a plugin should be raised as exceptions.  The plugin manager will catch the error, and its behavior depends on both the gateway's and plugin's configuration as follows:

1. if `plugin_settings.fail_on_plugin_error` in the plugin `config.yaml` is set to `true` the exception is bubbled up as a PluginError and the error is passed to the client of the MCP Context Forge regardless of the plugin mode.
2. if `plugin_settings.fail_on_plugin_error` is set to false the error is handled based off of the plugin mode in the plugin's config as follows:
  * if `mode` is `enforce`, both violations and errors are bubbled up as exceptions and the execution is blocked.
  * if `mode` is `enforce_ignore_error`, violations are bubbled up as exceptions and execution is blocked, but errors are logged and execution continues.
  * if `mode` is `permissive`, execution is allowed to proceed whether there are errors or violations. Both are logged.


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
logger.info(f"Plugin {self.name} blocked request: {violation.code}")
logger.warning(f"Plugin {self.name} timeout approaching")
logger.error(f"Plugin {self.name} failed: {error}")
```

## API Reference

Plugin management endpoints are not exposed in the gateway at this time.

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

## Production Deployment Examples

### Enterprise AI Safety Pipeline

```yaml
# Production-grade AI safety configuration
plugins:
  # Step 1: PII Detection and Masking (Highest Priority)
  - name: "PIIFilter"
    kind: "plugins.pii_filter.pii_filter.PIIFilterPlugin"
    hooks: ["prompt_pre_fetch", "prompt_post_fetch", "tool_pre_invoke", "tool_post_invoke"]
    mode: "enforce"
    priority: 10
    config:
      detect_ssn: true
      detect_credit_card: true
      detect_email: true
      mask_strategy: "partial"
      block_on_detection: false

  # Step 2: External AI Safety Service (LlamaGuard)
  - name: "LlamaGuardSafety"
    kind: "external"
    hooks: ["prompt_pre_fetch", "tool_pre_invoke"]
    mode: "enforce"
    priority: 20
    mcp:
      proto: STREAMABLEHTTP
      url: "https://ai-safety.internal.corp/llamaguard/v1"
    conditions:
      - server_ids: ["production-chat", "customer-support"]

  # Step 3: OpenAI Moderation for Final Check
  - name: "OpenAIMod"
    kind: "external"
    hooks: ["prompt_post_fetch", "tool_post_invoke"]
    mode: "permissive"  # Log violations but don't block
    priority: 30
    mcp:
      proto: STREAMABLEHTTP
      url: "https://api.openai.com/v1/moderations"

  # Step 4: Audit Logging (Lowest Priority)
  - name: "AuditLogger"
    kind: "plugins.audit.audit_logger.AuditLoggerPlugin"
    hooks: ["prompt_pre_fetch", "tool_pre_invoke", "tool_post_invoke"]
    mode: "permissive"
    priority: 100
    config:
      log_level: "INFO"
      include_payloads: false  # For privacy
      audit_endpoints: ["https://audit.internal.corp/api/v1/logs"]
```

### Multi-Tenant Security Configuration

```yaml
plugins:
  # Enterprise tenant gets strict filtering
  - name: "EnterpriseSecurityFilter"
    kind: "plugins.security.enterprise_filter.EnterpriseFilterPlugin"
    hooks: ["prompt_pre_fetch", "tool_pre_invoke"]
    mode: "enforce"
    priority: 50
    conditions:
      - tenant_ids: ["enterprise-corp", "banking-client"]
        tools: ["database-query", "file-access", "system-command"]
    config:
      sql_injection_protection: true
      command_injection_protection: true
      file_system_restrictions: true

  # Free tier gets basic content filtering
  - name: "BasicContentFilter"
    kind: "plugins.content.basic_filter.BasicFilterPlugin"
    hooks: ["prompt_pre_fetch", "prompt_post_fetch"]
    mode: "permissive"
    priority: 75
    conditions:
      - tenant_ids: ["free-tier"]
    config:
      profanity_filter: true
      spam_detection: true
      rate_limit_warnings: true
```

### Development vs Production Configurations

```yaml
# Development Environment
plugins:
  - name: "DevPIIFilter"
    kind: "plugins.pii_filter.pii_filter.PIIFilterPlugin"
    hooks: ["prompt_pre_fetch", "tool_pre_invoke"]
    mode: "permissive"  # Don't block in dev
    priority: 50
    config:
      detect_ssn: true
      log_detections: true
      mask_strategy: "partial"
      whitelist_patterns:
        - "test@example.com"
        - "555-555-5555"
        - "123-45-6789"  # Test SSN

# Production Environment
plugins:
  - name: "ProdPIIFilter"
    kind: "plugins.pii_filter.pii_filter.PIIFilterPlugin"
    hooks: ["prompt_pre_fetch", "prompt_post_fetch", "tool_pre_invoke", "tool_post_invoke"]
    mode: "enforce"  # Block in production
    priority: 10
    config:
      detect_ssn: true
      detect_credit_card: true
      detect_phone: true
      detect_email: true
      detect_api_keys: true
      block_on_detection: true
      audit_detections: true
      compliance_mode: "strict"
```

## Performance and Scalability

### Benchmark Results

- **Self-Contained Plugins:** <1ms latency overhead per hook
- **External Service Plugins:** 10-100ms depending on service (cached responses: <5ms)
- **Memory Usage:** ~5MB base overhead + ~1MB per active plugin
- **Throughput:** Tested to 1,000+ req/s with 5 active plugins

### Performance Optimization Tips

```yaml
# Optimize plugin configuration for high-throughput environments
plugin_settings:
  plugin_timeout: 5000  # 5 second timeout for external services
  parallel_execution_within_band: true  # Enable when available
  fail_on_plugin_error: false  # Continue processing on plugin failures

plugins:
  - name: "CachedAIService"
    kind: "external"
    priority: 50
    config:
      cache_ttl_seconds: 300  # Cache responses for 5 minutes
      cache_max_entries: 10000  # LRU cache with 10K entries
      timeout_ms: 2000  # Fast timeout for high-throughput
      retry_attempts: 1  # Single retry only
```

## Monitoring and Observability

General observability guidance:
- Emit structured logs at appropriate levels (debug/info/warn/error)
- Track plugin execution time in logs where useful
- Use external APM/logging stacks for end‑to‑end tracing if needed

## Security Considerations

### Plugin Isolation and Security

- **Input Validation:** Plugin configurations validated with Pydantic models
- **Timeout Protection:** Configurable timeouts prevent plugin hangs
- **Payload Limits:** Payload size guards (~1MB) prevent resource exhaustion
- **Error Isolation:** Plugin failures don't affect gateway stability
- **Audit Logging:** Log plugin executions and violations

### External Plugin Security

Secure external plugin servers as you would any service (authentication, TLS). The gateway's external plugin client communicates over MCP (STDIO or Streamable HTTP).

## Future Roadmap

### Near‑term Enhancements

- **Server Attestation Hooks:** `server_pre_register` (TPM/TEE)
- **Authentication Hooks:** `auth_pre_check`/`auth_post_check`
- **Admin UI:** Visual plugin management and monitoring dashboard
- **Hot Configuration Reload:** Update plugin configs without restart
- **Advanced Caching:** Redis-backed caching for external service calls

### Long-term Vision (v0.8.0+)

- **Plugin Marketplace:** Community plugin sharing and discovery
- **Advanced Analytics:** Plugin performance analytics and optimization recommendations
- **A/B Testing Framework:** Split traffic between plugin configurations
- **Policy as Code:** Integration with Open Policy Agent (OPA) for complex rule evaluation
- **Machine Learning Pipeline:** Built-in support for custom ML model deployment

## Contributing

To contribute a plugin:

1. Follow the plugin structure guidelines
2. Include comprehensive tests
3. Document configuration options
4. Submit a pull request with examples

For framework improvements, please open an issue to discuss proposed changes.
