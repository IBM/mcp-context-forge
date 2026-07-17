# ICA Metering Exporter Plugin

Exports MCP tool invocation metrics to ICA core-services metering endpoint.

## Configuration

```yaml
plugins:
  - name: "IcaMeteringExporter"
    kind: "plugins.ica_metering_exporter.ica_metering_exporter.IcaMeteringExporterPlugin"
    version: "0.1.0"
    description: "Export MCP tool invocation metrics to ICA metering service"
    author: "ICA Team"
    hooks: ["tool_pre_invoke", "tool_post_invoke"]
    tags: ["metering", "ica", "observability"]
    mode: "disabled"
    priority: 200
    conditions: []
    config:
      metering_url: "http://service-launchpad:8080/internal/mcp-metering/event"
      metering_token: "${MCP_METERING_TOKEN}"
      enabled: true
```

## Required Settings

- `metering_url`: Internal ICA endpoint URL (required)
- `metering_token`: Shared secret for endpoint authentication (required)
- `enabled`: Set to `true` to activate (default: `false`)

## Security

The `metering_token` should be:
- At least 32 characters
- Generated with `openssl rand -base64 32`
- Stored in environment variables or secrets manager
- Never committed to git

## Data Sent

Sends structured JSON with:
- User/team identity
- Tool name, server ID, gateway metadata
- Execution latency, error status
- Optional: model name, trace ID, token counts

See `docs/MCP_TOOL_OBSERVABILITY_ARCHITECTURE.md` for full schema.
