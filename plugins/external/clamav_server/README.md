# ClamAV Remote Plugin (External MCP)

> Author: Mihai Criveti
> Version: 0.1.0

External MCP server plugin that scans files and text content using ClamAV.

## Modes
- `eicar_only` (default): No clamd dependency; flags EICAR strings (for tests/dev).
- `clamd_tcp`: Connect to clamd via TCP host/port; use INSTREAM.
- `clamd_unix`: Connect to clamd via UNIX socket path; use INSTREAM.

## Hooks
- `resource_pre_fetch`: Scans local `file://` URIs.
- `resource_post_fetch`: Scans text content of fetched resources.
- `prompt_post_fetch`: Scans rendered prompt messages for EICAR/malware.
- `tool_post_invoke`: Recursively scans string fields in tool outputs.

## Server Launch
- Use the gateway runtime: `mcpgateway.plugins.framework.external.mcp.server.runtime`.
- Provide `PLUGINS_CONFIG_PATH` pointing to this project's `resources/plugins/config.yaml`.

Example run script is created at `plugins/external/clamav_server/run.sh`.

## Health Check (MCP Tool)
The external server exposes an MCP tool `plugin_health` that returns plugin-specific health and stats when available:

```json
{
  "method": "plugin_health",
  "params": { "plugin_name": "ClamAVRemote" }
}
```

Response includes mode, block_on_positive, cumulative stats, and clamd reachability (when configured):

```json
{
  "result": {
    "mode": "clamd_tcp",
    "block_on_positive": true,
    "stats": { "attempted": 42, "infected": 2, "blocked": 2, "errors": 0 },
    "clamd_reachable": true
  }
}
```

## Plugin Config (server-side)
```yaml
plugins:
  - name: "ClamAVRemote"
    kind: "plugins.external.clamav_server.clamav_plugin.ClamAVRemotePlugin"
    hooks: ["resource_pre_fetch", "resource_post_fetch", "prompt_post_fetch", "tool_post_invoke"]
    mode: "enforce"
    priority: 50
    config:
      mode: "eicar_only"         # eicar_only | clamd_tcp | clamd_unix
      clamd_host: "127.0.0.1"
      clamd_port: 3310
      clamd_socket: null          # e.g., /var/run/clamav/clamd.ctl
      timeout_seconds: 5.0
      block_on_positive: true
      max_scan_bytes: 10485760
```

## Gateway Config (client-side)
Add external plugin entry:
```yaml
  - name: "ClamAVRemote"
    kind: "external"
    hooks: ["resource_pre_fetch", "resource_post_fetch"]
    mode: "enforce"
    priority: 62
    mcp:
      proto: STDIO
      script: plugins/external/clamav_server/run.sh
```

## Design
- External MCP process runs the plugin and exposes standard hooks via the generic MCP runtime.
- Scanning:
  - `resource_pre_fetch`: reads local file bytes (file://) up to `max_scan_bytes` and scans via EICAR mode or clamd INSTREAM.
  - `resource_post_fetch`: scans resource text bytes.
  - `prompt_post_fetch`: scans rendered messages' text.
  - `tool_post_invoke`: recursively scans string fields in tool outputs.
- Policy: `block_on_positive` controls whether detections block or just annotate metadata.
- Size guard: `max_scan_bytes` limits read/scan to avoid excessive payload sizes.

## Limitations
- `eicar_only` is intended for dev/test; real scanning requires clamd configured and reachable.
- Current implementation scans plain text content and local files; it does not extract archives or scan binary blobs in resource_post_fetch.
- Scanning is synchronous within the hook (can add async offloading if needed).
- No automatic signature updates or clamd health checks in this module (operate operationally).

## TODOs
- Add archive extraction (zip/tar) with recursion limits and size thresholds.
- Add binary blob scanning for resource_post_fetch when `ResourceContent.blob` is present.
- Add asynchronous/background scanning option with follow-up violation (webhook/event) capabilities.
- Support clamd health check and more robust error reporting/metrics (success/scan time/status).
- Add signature freshness checks and optional freshclam integration hooks.
- Provide per-tenant or per-route overrides and dynamic config reload.
- Add allow/deny filename patterns and MIME-type based skip rules.
- Rate-limit scanning and add concurrency controls to avoid overloading clamd.
