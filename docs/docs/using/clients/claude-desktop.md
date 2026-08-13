# Claude Desktop × ContextForge

[Claude Desktop](https://www.anthropic.com/index/claude-desktop) connects to MCP servers over
**Streamable HTTP**.
By pointing it at your Gateway's `/mcp/` endpoint you give Claude instant access to every tool,
prompt and resource registered in your Gateway.

!!! tip "Gateway URL"
    - Direct installs (`uvx`, pip, or `docker run`): `http://localhost:4444`
    - Docker Compose (nginx proxy): `http://localhost:8080`

---

## 📂 Where to edit the config

| OS | Path |
|----|------|
| **macOS** | `~/Library/Application Support/Claude/claude_desktop_config.json` |
| **Windows** | `%APPDATA%\Claude\claude_desktop_config.json` |
| **Linux (Flatpak / AppImage)** | `$HOME/.config/Claude/claude_desktop_config.json` |

---

## ⚙️ Minimal JSON block

```jsonc
{
  "servers": {
    "contextforge": {
      "type": "http",
      "url": "http://localhost:4444/servers/UUID_OF_SERVER_1/mcp/",
      "headers": {
        "Authorization": "Bearer <YOUR_JWT_TOKEN>"
      }
    }
  }
}
```

> *Use the real server ID instead of `UUID_OF_SERVER_1` and paste your bearer token.*

---

## 🧪 Smoke-test inside Claude

1. **Restart** Claude Desktop (quit from system-tray).
2. Select **"contextforge"** in the chat dropdown.
3. Type:

   ```
   #get_system_time { "timezone": "Europe/Dublin" }
   ```
4. Claude calls the Gateway → tool → chat reply.

If tools don't appear, open *File ▸ Settings ▸ Developer ▸ View Logs*.

---
