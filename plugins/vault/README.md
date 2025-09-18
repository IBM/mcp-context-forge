# Vault Plugin

The Vault Plugin provides secure storage and retrieval of secrets, ensuring that sensitive information is protected and managed effectively. It generates bearer tokens based on vault-saved tokens and integrates with gateway metadata and OAuth2 configurations.

## Quick Start

## Features

Replace the Bearer token in a tool invocation based on a header that is send to the agent. Header is matched based on the MCP server metadata
   - tag that start with system_tag_prefix
   - extract the host of the authentication server from



## Installation

1. Copy .env.example .env
2. Enable plugins in `.env`
3. Add the plugin configuration to `plugins/config.yaml`:

```yaml
  - name: "VaultPlugin"
    kind: "plugins.vault.vault_plugin.Vault"
    description: "Vault plugin that based  that will generate bearer token based on a vault saved token"
    version: "0.0.1"
    author: "Adrian Popa"
    hooks: ["tool_pre_invoke"]
    tags: ["security", "vault", "OAUTH2"]
    mode: "permissive"  # enforce | permissive | disabled
    priority: 10  # Lower number = higher priority (runs first)
    conditions:
      - prompts: []  # Empty list = apply to all prompts
        server_ids: []  # Apply to all servers
        tenant_ids: []  # Apply to all tenants
    config:
      system_tag_prefix: "system"
      vault_header_name: "X-Vault-Tokens"
      vault_handling: "raw"

```

## Configuration Examples

### Development Environment (Permissive)
```yaml
config:
  system_tag_prefix: "system" ### The prefix of the tag that contains the system name
  system_handling: "tag" # # Gets the OAUTH2 IDP host from tags. The tag must have the format "system:host" where host is the hostname of the IDP. Use oauth2_config to extract IDP hostname from the OAUTH_CONFIG metadata of the MCP Server template.
  vault_header_name: "X-Vault-Tokens"  # Name of the header that contains the tokens.
  vault_handling: "raw"  # Use the token that matches the system as bearer token


### Features
- Secure storage of secrets
- Retrieval of secrets with access control
- Integration with gateway metadata and OAuth2 configurations

## Available Hooks

The Vault Plugin implement hooks at these lifecycle points:

| Hook | Description | Payload Type | Use Cases |
|------|-------------|--------------|-----------|
| `tool_pre_invoke` | Before tool invocation | `ToolPreInvokePayload` | Access control for OAUTH2 server |



### Plugin Modes


- **`permissive`**: Change headers if possible but allows request to continue

### Plugin Priority

Lower priority numbers run first (higher priority). Recommended ranges:
- **1-50**: Critical security plugins (access control)
- **51-100**: Content filtering and validation
- **101-200**: Transformations and enhancements
- **201+**: Logging and monitoring


### Logging and Monitoring

```python
def __init__(self, config: PluginConfig):
    super().__init__(config)
    self.logger.info(f"Initialized {self.name} v{self.version}")

async def vault_pre_fetch(self, payload: VaultPreFetchPayload) -> VaultPreFetchPayload:
    self.logger.debug(f"Processing vault: {payload.secret_name}")
    # ... plugin logic
    self.metrics.increment("requests_processed")
```


## Testing
TBD
### Run Individual Tests
