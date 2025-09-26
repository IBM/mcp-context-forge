
[Back to Plugin Specification Main Page](../plugin-framework-specification.md)

[Next: Hook Function Architecture](./hooks-overview.md)

## 4. Plugin Types and Models

### 4.1 Overview

The plugin configuration system is the cornerstone of the MCP Context Forge plugin framework, providing a declarative, YAML-based approach to plugin management, deployment, and orchestration. This system enables administrators and developers to:

**🎯 Plugin Lifecycle Management**

- **Discovery & Loading**: Automatically discover and load plugins from configuration
- **Dependency Resolution**: Handle plugin dependencies and load order
- **Runtime Control**: Enable, disable, or modify plugin behavior without code changes
- **Version Management**: Track plugin versions and manage updates

**🔧 Operational Control**

- **Environment-Specific Deployment**: Different configurations for dev/staging/production
- **Conditional Execution**: Run plugins only under specific conditions (tenant, server, user)
- **Priority-Based Orchestration**: Control execution order through priority settings
- **Mode-Based Behavior**: Switch between enforce/enforce_ignore_error/permissive/disabled modes

**🔐 Security & Compliance**

- **Access Control**: Restrict plugin execution to specific users, tenants, or servers
- **Audit Trail**: Track plugin configuration changes and deployment history
- **Policy Enforcement**: Implement organizational security policies through configuration
- **External Service Integration**: Securely configure connections to external AI safety services

**⚡ Performance Optimization**

- **Resource Limits**: Configure timeouts, memory limits, and execution constraints
- **Selective Loading**: Load only necessary plugins to optimize performance
- **Monitoring Integration**: Configure metrics collection and health monitoring
- **Caching Strategies**: Control plugin result caching and optimization

The configuration system supports both **native plugins** (running in-process) and **external plugins** (remote MCP servers), providing a unified interface for managing diverse plugin architectures while maintaining type safety, validation, and operational excellence.

### 4.2 Plugin Configuration Schema

Below is an example of a plugin configuration file.  A plugin configuration file can configure one or more plugins in a prioritized list as below.  Each individual plugin is an instance of the of a plugin class that subclasses the base `Plugin` object and implements a set of hooks as listed in the configuration.   

```yaml
# plugins/config.yaml
plugins:
  - name: "PIIFilterPlugin"                    # Unique plugin identifier
    kind: "plugins.pii_filter.pii_filter.PIIFilterPlugin"  # Plugin class path
    description: "Detects and masks PII"       # Human-readable description
    version: "1.0.0"                          # Plugin version
    author: "Security Team"                   # Plugin author
    hooks:                                    # Hook registration
      - "prompt_pre_fetch"
      - "tool_pre_invoke"
      - "tool_post_invoke"
    tags:                                     # Searchable tags
      - "security"
      - "pii"
      - "compliance"
    mode: "enforce"                           # enforce|enforce_ignore_error|permissive|disabled
    priority: 50                              # Execution priority (lower = higher)
    conditions:                               # Conditional execution
      - server_ids: ["prod-server"]
        tenant_ids: ["enterprise"]
        tools: ["sensitive-tool"]
    config:                                   # Plugin-specific configuration
      detect_ssn: true
      detect_credit_card: true
      mask_strategy: "partial"
      redaction_text: "[REDACTED]"

# Global plugin settings
plugin_settings:
  parallel_execution_within_band: false      # Execute same-priority plugins in parallel
  plugin_timeout: 30                         # Per-plugin timeout (seconds)
  fail_on_plugin_error: false                # Continue on plugin failures
  plugin_health_check_interval: 60           # Health check interval (seconds)
```

Details of each field are below:

| Field | Type | Required | Default | Description | Example Values |
|-------|------|----------|---------|-------------|----------------|
| `name` | `string` | ✅ | - | Unique plugin identifier within the configuration | `"PIIFilterPlugin"`, `"OpenAIModeration"` |
| `kind` | `string` | ✅ | - | Plugin class path for self-contained plugins or `"external"` for MCP servers | `"plugins.pii_filter.pii_filter.PIIFilterPlugin"`, `"external"` |
| `description` | `string` | ❌ | `null` | Human-readable description of plugin functionality | `"Detects and masks PII in requests"` |
| `author` | `string` | ❌ | `null` | Plugin author or team responsible for maintenance | `"Security Team"`, `"AI Safety Group"` |
| `version` | `string` | ❌ | `null` | Plugin version for tracking and compatibility | `"1.0.0"`, `"2.3.1-beta"` |
| `hooks` | `string[]` | ❌ | `[]` | List of hook points where plugin executes | `["prompt_pre_fetch", "tool_pre_invoke"]` |
| `tags` | `string[]` | ❌ | `[]` | Searchable tags for plugin categorization | `["security", "pii", "compliance"]` |
| `mode` | `string` | ❌ | `"enforce"` | Plugin execution mode controlling behavior on violations | `"enforce"`, `"enforce_ignore_error"`, `"permissive"`, `"disabled"` |
| `priority` | `integer` | ❌ | `null` | Execution priority (lower number = higher priority) | `10`, `50`, `100` |
| `conditions` | `object[]` | ❌ | `[]` | Conditional execution rules for targeting specific contexts | See [Condition Fields](#condition-fields) below |
| `config` | `object` | ❌ | `{}` | Plugin-specific configuration parameters | `{"detect_ssn": true, "mask_strategy": "partial"}` |
| `mcp` | `object` | ❌ | `null` | External MCP server configuration (required for external plugins) | See [MCP Configuration](#mcp-configuration-fields) below |

#### Hook Types
Available hook values for the `hooks` field:

| Hook Value | Description | Timing |
|------------|-------------|--------|
| `"prompt_pre_fetch"` | Process prompt requests before template processing | Before prompt template retrieval |
| `"prompt_post_fetch"` | Process prompt responses after template rendering | After prompt template processing |
| `"tool_pre_invoke"` | Process tool calls before execution | Before tool invocation |
| `"tool_post_invoke"` | Process tool results after execution | After tool completion |
| `"resource_pre_fetch"` | Process resource requests before fetching | Before resource retrieval |
| `"resource_post_fetch"` | Process resource content after loading | After resource content loading |

#### Plugin Modes
Available values for the `mode` field:

| Mode | Behavior | Use Case |
|------|----------|----------|
| `"enforce"` | Block requests when plugin detects violations or errors | Production security plugins, critical compliance checks |
| `"enforce_ignore_error"` | Block on violations but continue on plugin errors | Security plugins that should block violations but not break on technical errors |
| `"permissive"` | Log violations and errors but allow requests to continue | Development environments, monitoring-only plugins |
| `"disabled"` | Plugin is loaded but never executed | Temporary plugin deactivation, maintenance mode |

#### Condition Fields
The `conditions` array contains objects that specify when plugins should execute:

| Field | Type | Description | Example |
|-------|------|-------------|---------|
| `server_ids` | `string[]` | Execute only for specific virtual server IDs | `["prod-server", "api-gateway"]` |
| `tenant_ids` | `string[]` | Execute only for specific tenant/organization IDs | `["enterprise", "premium-tier"]` |
| `tools` | `string[]` | Execute only for specific tool names | `["file_reader", "web_scraper"]` |
| `prompts` | `string[]` | Execute only for specific prompt names | `["user_prompt", "system_message"]` |
| `resources` | `string[]` | Execute only for specific resource URI patterns | `["https://api.example.com/*"]` |
| `user_patterns` | `string[]` | Execute for users matching regex patterns | `["admin_.*", ".*@company.com"]` |
| `content_types` | `string[]` | Execute for specific content types | `["application/json", "text/plain"]` |

#### MCP Configuration Fields
For external plugins (`kind: "external"`), the `mcp` object configures the MCP server connection:

| Field | Type | Required | Description | Example |
|-------|------|----------|-------------|---------|
| `proto` | `string` | ✅ | MCP transport protocol | `"stdio"`, `"sse"`, `"streamablehttp"`, `"websocket"` |
| `url` | `string` | ❌ | Service URL for HTTP-based transports | `"http://openai-plugin:3000/mcp"` |
| `script` | `string` | ❌ | Script path for STDIO transport | `"/opt/plugins/custom-filter.py"` |

#### Global Plugin Settings
The `plugin_settings` object controls framework-wide behavior:

| Setting | Type | Default | Description |
|---------|------|---------|-------------|
| `parallel_execution_within_band` | `boolean` | `false` | Execute plugins with same priority in parallel |
| `plugin_timeout` | `integer` | `30` | Per-plugin timeout in seconds |
| `fail_on_plugin_error` | `boolean` | `false` | Stop processing on plugin errors |
| `plugin_health_check_interval` | `integer` | `60` | Health check interval in seconds |

### 4.3 Plugin Configuration Model

```python
class PluginConfig(BaseModel):
    """Plugin configuration schema"""
    name: str                                    # Required: Unique plugin name
    kind: str                                    # Required: Plugin class path or "external"
    description: Optional[str] = None            # Plugin description
    author: Optional[str] = None                 # Plugin author
    version: Optional[str] = None                # Plugin version
    hooks: Optional[list[HookType]] = None       # Hook points to register
    tags: Optional[list[str]] = None             # Searchable tags
    mode: PluginMode = PluginMode.ENFORCE        # Execution mode
    priority: Optional[int] = None               # Execution priority
    conditions: Optional[list[PluginCondition]] = None # Execution conditions
    config: Optional[dict[str, Any]] = None      # Plugin-specific settings
    mcp: Optional[MCPConfig] = None              # External MCP server configuration
```


### 4.4 External Plugin Configuration

```python
class MCPConfig(BaseModel):
    """MCP configuration for external plugins"""
    proto: TransportType                     # STDIO, SSE, or STREAMABLEHTTP
    url: Optional[str] = None                # Service URL (for HTTP transports)
    script: Optional[str] = None             # Script path (for STDIO transport)
```

### 4.5 Configuration Loading

```python
class ConfigLoader:
    """Configuration loading and validation"""

    @staticmethod
    def load_config(config_path: str) -> Config:
        """Load plugin configuration from YAML file"""

    @staticmethod
    def validate_config(config: Config) -> None:
        """Validate plugin configuration"""

    @staticmethod
    def merge_configs(base: Config, override: Config) -> Config:
        """Merge configuration files"""
```

### 4.6 Plugin Modes

```python
class PluginMode(str, Enum):
    """Plugin execution modes"""
    ENFORCE = "enforce"              # Block requests that violate plugin rules
    ENFORCE_IGNORE_ERROR = "enforce_ignore_error"  # Enforce rules, ignore errors
    PERMISSIVE = "permissive"        # Log violations but allow continuation
    DISABLED = "disabled"            # Plugin loaded but not executed
```

### 4.7 Hook Types

```python
class HookType(str, Enum):
    """Available hook points in MCP request lifecycle"""
    HTTP_PRE_FORWARDING_CALL = "http_pre_forwarding_call"   # Before HTTP forwarding
    HTTP_POST_FORWARDING_CALL = "http_post_forwarding_call" # After HTTP forwarding
    PROMPT_PRE_FETCH = "prompt_pre_fetch"     # Before prompt retrieval
    PROMPT_POST_FETCH = "prompt_post_fetch"   # After prompt rendering
    TOOL_PRE_INVOKE = "tool_pre_invoke"       # Before tool execution
    TOOL_POST_INVOKE = "tool_post_invoke"     # After tool execution
    RESOURCE_PRE_FETCH = "resource_pre_fetch" # Before resource fetching
    RESOURCE_POST_FETCH = "resource_post_fetch" # After resource retrieval
```

### 4.8 Plugin Manifest

The plugin manifest is a metadata file that provides structured information about a plugin's capabilities, dependencies, and characteristics. This manifest serves multiple purposes in the plugin ecosystem: development guidance, runtime validation, discoverability, and documentation.

#### 4.8.1 Manifest Purpose and Usage

The plugin manifest (`plugin-manifest.yaml`) is primarily used by:

- **Plugin Templates**: Bootstrap process uses manifest to generate plugin scaffolding
- **Development Tools**: IDEs and editors can provide enhanced support based on manifest information
- **Plugin Discovery**: Registry systems can index plugins based on manifest metadata
- **Documentation Generation**: Automated documentation can be generated from manifest content
- **Dependency Management**: Future versions may use manifest for dependency resolution

#### 4.8.2 Manifest Structure

The plugin manifest follows a structured YAML format that captures comprehensive plugin metadata:

```yaml
# plugin-manifest.yaml
name: "Advanced PII Filter"
description: "Comprehensive PII detection and masking with configurable sensitivity levels"
author: "Security Engineering Team"
version: "2.1.0"
license: "MIT"
homepage: "https://github.com/company/advanced-pii-filter"
repository: "https://github.com/company/advanced-pii-filter.git"

# Plugin capabilities and hook registration
available_hooks:
  - "prompt_pre_fetch"
  - "prompt_post_fetch"
  - "tool_pre_invoke"
  - "tool_post_invoke"
  - "resource_post_fetch"

# Categorization and discovery
tags:
  - "security"
  - "pii"
  - "compliance"
  - "data-protection"
  - "gdpr"

# Plugin characteristics
plugin_type: "native"                    # native | external
language: "python"                       # python | typescript | go | rust | java
performance_tier: "high"                 # high | medium | low (expected latency)

# Default configuration template
default_config:
  detection_sensitivity: 0.8
  masking_strategy: "partial"             # partial | full | token
  pii_types:
    - "ssn"
    - "credit_card"
    - "email"
    - "phone"
  compliance_mode: "gdpr"                 # gdpr | hipaa | pci | custom
  log_violations: true
  max_content_length: 1048576

# Runtime requirements
requirements:
  python_version: ">=3.11"
  memory_mb: 64
  cpu_cores: 0.5
  timeout_seconds: 5

# Dependencies (for external plugins)
dependencies:
  - "spacy>=3.4.0"
  - "presidio-analyzer>=2.2.0"
  - "pydantic>=2.0.0"

# Plugin metadata for advanced features
features:
  configurable: true                      # Plugin accepts runtime configuration
  stateful: false                         # Plugin maintains state between requests
  async_capable: true                     # Plugin supports async execution
  external_dependencies: true             # Plugin requires external services
  multi_tenant: true                      # Plugin supports tenant isolation

# Documentation and examples
documentation:
  readme: "README.md"
  examples: "examples/"
  api_docs: "docs/api.md"

# Testing and quality assurance
testing:
  unit_tests: "tests/unit/"
  integration_tests: "tests/integration/"
  coverage_threshold: 90

# Compatibility and versioning
compatibility:
  min_framework_version: "1.0.0"
  max_framework_version: "2.x.x"
  python_versions: ["3.11", "3.12"]

# Optional deployment metadata
deployment:
  container_image: "company/pii-filter:2.1.0"
  k8s_manifest: "k8s/deployment.yaml"
  health_check_endpoint: "/health"
```

#### 4.8.3 Manifest Fields Reference

| Field | Type | Required | Description | Example |
|-------|------|----------|-------------|---------|
| `name` | `string` | ✅ | Human-readable plugin name | `"Advanced PII Filter"` |
| `description` | `string` | ✅ | Detailed plugin description | `"Comprehensive PII detection with GDPR compliance"` |
| `author` | `string` | ✅ | Plugin author or team | `"Security Engineering Team"` |
| `version` | `string` | ✅ | Semantic version | `"2.1.0"` |
| `license` | `string` | ❌ | License identifier | `"MIT"`, `"Apache-2.0"` |
| `homepage` | `string` | ❌ | Plugin homepage URL | `"https://github.com/company/plugin"` |
| `repository` | `string` | ❌ | Source code repository | `"https://github.com/company/plugin.git"` |

#### 4.8.4 Plugin Capability Fields

| Field | Type | Description | Values |
|-------|------|-------------|--------|
| `available_hooks` | `string[]` | Hook points the plugin can implement | `["prompt_pre_fetch", "tool_pre_invoke"]` |
| `plugin_type` | `string` | Plugin architecture type | `"native"`, `"external"` |
| `language` | `string` | Implementation language | `"python"`, `"typescript"`, `"go"`, `"rust"` |
| `performance_tier` | `string` | Expected latency characteristics | `"high"` (<1ms), `"medium"` (<10ms), `"low"` (<100ms) |

#### 4.8.5 Configuration and Dependencies

| Field | Type | Description |
|-------|------|-------------|
| `default_config` | `object` | Default plugin configuration template |
| `requirements` | `object` | Runtime resource requirements |
| `dependencies` | `string[]` | External package dependencies |
| `features` | `object` | Plugin capability flags |

#### 4.8.6 Manifest Usage in Development

**Plugin Template Generation**:
```bash
# Bootstrap uses manifest to generate plugin structure
mcpplugins bootstrap --destination ./my-plugin --template advanced-filter

# Generated files include manifest-based configuration
├── plugin-manifest.yaml        # Copied from template
├── my_plugin.py               # Generated with hooks from manifest
├── config.yaml               # Default config from manifest
└── README.md                 # Generated with manifest metadata
```

**IDE Integration**:

The manifest enables development tools to provide:

- **Hook Autocomplete**: Available hooks based on `available_hooks`
- **Configuration Validation**: Schema validation using `default_config`
- **Dependency Management**: Package requirements from `dependencies`
- **Documentation Links**: Direct access to `documentation` resources

#### 4.8.7 Best Practices for Plugin Manifests

**Versioning**:

- Use semantic versioning (MAJOR.MINOR.PATCH)
- Update version for any changes that affect plugin behavior
- Include pre-release identifiers for development versions (e.g., `2.1.0-beta.1`)

**Documentation**:

- Provide clear, comprehensive descriptions
- Include usage examples in the repository
- Document all configuration options in `default_config`
- Maintain up-to-date README files

**Dependencies**:

- Pin dependency versions for reproducible builds
- Use minimum version constraints where appropriate
- Document external service dependencies in description

**Tags and Categories**:

- Use consistent, descriptive tags for discoverability
- Include functional tags (`security`, `validation`) and domain tags (`gdpr`, `healthcare`)
- Follow established tag conventions within your organization

The plugin manifest system provides a foundation for plugin ecosystem management, enabling better development workflows, automated tooling, and enhanced discoverability while maintaining consistency across plugin implementations.


[Back to Plugin Specification Main Page](../plugin-framework-specification.md)

[Next: Hook Function Architecture](./hooks-overview.md)