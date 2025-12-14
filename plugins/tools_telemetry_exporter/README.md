# Tools Telemetry Exporter Plugin

> Author: Bar Haim
> Version: 0.1.0

Export comprehensive tool invocation telemetry to OpenTelemetry for observability and monitoring.

## Hooks
- `tool_pre_invoke`
- `tool_post_invoke`

## Config
```yaml
config:
  export_full_payload: true
  max_payload_bytes_size: 10000  # 10 KB default
```

## Features

- **Pre-Invocation Telemetry**: Captures request context, tool metadata, target MCP server details, and tool arguments
- **Post-Invocation Telemetry**: Captures request context, tool results (optional), and error status
- **Automatic Payload Truncation**: Large results are truncated to respect size limits
- **Graceful Degradation**: Automatically disables if OpenTelemetry is not available

## Exported Attributes

### Pre-Invocation (`tool.pre_invoke`)
- Request metadata: `request_id`, `user`, `tenant_id`, `server_id`
- Target server: `target_mcp_server.id`, `target_mcp_server.name`, `target_mcp_server.url`
- Tool info: `tool.name`, `tool.target_tool_name`, `tool.description`
- Invocation data: `tool.invocation.args`, `headers`

### Post-Invocation (`tool.post_invoke`)
- Request metadata: `request_id`, `user`, `tenant_id`, `server_id`
- Results: `tool.invocation.result` (if `export_full_payload` is enabled and no error)
- Status: `tool.invocation.has_error`

## Configuration Options

| Option | Default | Description |
|--------|---------|-------------|
| `export_full_payload` | `true` | Export full tool results in post-invocation telemetry |
| `max_payload_bytes_size` | `10000` | Maximum payload size in bytes before truncation |

## Requirements

OpenTelemetry enabled on MCP context forge (see [Observability Setup](../../docs/docs/manage/observability.md#opentelemetry-external)).


## Usage

```yaml
plugins:
  - name: "ToolsTelemetryExporter"
    kind: "plugins.tools_telemetry_exporter.telemetry_exporter.ToolsTelemetryExporterPlugin"
    hooks: ["tool_pre_invoke", "tool_post_invoke"]
    mode: "permissive"
    priority: 200  # Run late to capture all context
    config:
        export_full_payload: true
        max_payload_bytes_size: 10000
```

## Limitations

- Requires active OpenTelemetry tracing to export telemetry
- No local buffering; telemetry exported in real-time only

## Security Notes

- Tool arguments are always exported in pre-invocation telemetry
- Consider running PII filter plugin before this plugin to sanitize data
- Disable `export_full_payload` in production for sensitive workloads
