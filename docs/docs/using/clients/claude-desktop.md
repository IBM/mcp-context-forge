# Claude Desktop × ContextForge

[Claude Desktop](https://www.anthropic.com/index/claude-desktop) can launch MCP servers
configured via `claude_desktop_config.json`. ContextForge exposes a **Streamable HTTP**
endpoint that Claude can connect to directly.

!!! tip "Gateway URL"
    - Direct installs (`uvx`, pip, or `docker run`): `http://localhost:4444`
    - Docker Compose (nginx proxy): `http://localhost:8080`

---

## 🔗 Streamable HTTP (recommended)

### Minimal JSON block

```jsonc
{
  "mcpServers": {
    "mcp-gateway": {
      "type": "http",
      "url": "http://localhost:4444/servers/UUID_OF_SERVER_1/mcp/",
      "headers": {
        "Authorization": "Bearer <YOUR_JWT_TOKEN>"
      }
    }
  }
}
```

> *Use the real server ID instead of `1` and paste your bearer token.*

---

## 🧪 Smoke-test inside Claude

1. **Restart** Claude Desktop (quit from system-tray).
2. Select your gateway server in the chat dropdown.
3. Type:

    ```
    #get_system_time { "timezone": "Europe/Dublin" }
    ```

If tools don't appear, open *File ▸ Settings ▸ Developer ▸ View Logs* to see output.

---
