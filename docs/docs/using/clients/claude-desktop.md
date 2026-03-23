# Claude Desktop × ContextForge

[Claude Desktop](https://www.anthropic.com/index/claude-desktop) can launch a local **stdio**
process for every chat "backend".
By pointing it at **`mcpgateway.wrapper`** you give Claude instant access to every tool,
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
  "mcpServers": {
    "mcpgateway-wrapper": {
      "command": "python3",
      "args": ["-m", "mcpgateway.wrapper"],
      "env": {
        "MCP_SERVER_URL": "http://localhost:4444/servers/UUID_OF_SERVER_1",
        "MCP_AUTH": "Bearer <YOUR_JWT_TOKEN>",
        "MCP_TOOL_CALL_TIMEOUT": "120"
      }
    }
  }
}
```

> *Use the real server ID instead of `1` and paste your bearer token.*

---

### 🐳 Docker alternative

```jsonc
{
  "command": "docker",
  "args": [
    "run", "--rm", "--network=host", "-i",
    "-e", "MCP_SERVER_URL=http://localhost:4444/servers/UUID_OF_SERVER_1",
    "-e", "MCP_AUTH=<Bearer YOUR_JWT_TOKEN>",
    "ghcr.io/ibm/mcp-context-forge:1.0.0-RC-2",
    "python3", "-m", "mcpgateway.wrapper"
  ]
}
```

*(Mac / Windows users should replace `localhost` with `host.docker.internal`.)*

---

### ⚡ pipx / uvx one-liner (wrapper already installed)

If you installed the package globally:

```jsonc
{
  "command": "pipx",
  "args": ["run", "python3", "-m", "mcpgateway.wrapper"],
  "env": {
    "MCP_SERVER_URL": "http://localhost:4444/servers/UUID_OF_SERVER_1",
    "MCP_AUTH": "Bearer <YOUR_JWT_TOKEN>"
  }
}
```

---

## 🧪 Smoke-test inside Claude

1. **Restart** Claude Desktop (quit from system-tray).
2. Select **"mcpgateway-wrapper"** in the chat dropdown.
3. Type:

   ```
   #get_system_time { "timezone": "Europe/Dublin" }
   ```
4. The wrapper should proxy the call → Gateway → tool → chat reply.

If tools don't appear, open *File ▸ Settings ▸ Developer ▸ View Logs* to see wrapper output.

---

## 🔑 Environment variables recap

| Var                       | Purpose                                           |
| ------------------------- | ------------------------------------------------- |
| `MCP_SERVER_URL` | One or more `/servers/{id}` endpoints (comma-sep) |
| `MCP_AUTH`          | JWT bearer for Gateway auth                       |
| `MCP_TOOL_CALL_TIMEOUT`   | Per-tool timeout (seconds, optional)              |
| `MCP_WRAPPER_LOG_LEVEL`   | `DEBUG`, `INFO`, `OFF` (optional)                 |

You can place them:

* under `"env"` in the **mcpServers** block (preferred)
* in your user/environment shell before launching Claude.

---
