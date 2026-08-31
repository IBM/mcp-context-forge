# Header Filter Plugin

A security plugin that filters sensitive HTTP headers before sending requests to MCP endpoints.

## Overview

The Header Filter Plugin prevents sensitive authentication and authorization headers from being leaked to MCP servers. It provides configurable header filtering with support for passthrough exceptions.

## Features

- **Configurable filtering**: Define which headers to filter via YAML configuration
- **Case-insensitive matching**: Headers are matched case-insensitively
- **Passthrough support**: Allow specific headers through even if they're in the filter list
- **Multi-hook support**: Works on tool_pre_invoke and agent_pre_invoke
- **Logging**: Optional logging of filtered headers for audit purposes

## Configuration

### Basic Configuration

```yaml
plugins:
  - name: "HeaderFilterPlugin"
    kind: "plugins.header_filter.header_filter_plugin.HeaderFilter"
    description: "Filters sensitive headers before sending to MCP endpoints"
    version: "1.0.0"
    hooks: ["tool_pre_invoke", "agent_pre_invoke"]
    mode: "permissive"  # or "enforce"
    priority: 20
    config:
      filter_headers:
        - "Cookie"
        - "Set-Cookie"
      log_filtered_headers: true
      allow_passthrough_headers: []
```

### Configuration Options

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `filter_headers` | List[str] | `["X-Vault-Tokens", "Cookie", "Set-Cookie"]` | Headers to filter (case-insensitive) |
| `log_filtered_headers` | bool | `true` | Whether to log filtered headers |
| `allow_passthrough_headers` | List[str] | `[]` | Headers to always allow through |

### Conservative Default Filtered Headers

By default (in config.yaml), the plugin filters only these headers:
- `X-Vault-Tokens` - Vault authentication tokens
- `Cookie` - Session cookies
- `Set-Cookie` - Cookie setting headers

**Note**: The plugin code has a more comprehensive default list if no config is provided, but the recommended deployment uses the conservative list above.

## Testing

Run the unit tests:

```bash
pytest tests/unit/mcpgateway/plugins/plugins/header_filter/test_header_filter_plugin.py -v
```

## License

Apache-2.0

## Author

Adrian Popa
