# Claude Desktop × ContextForge

[Claude Desktop](https://www.anthropic.com/index/claude-desktop) launches local **stdio**
processes for MCP servers. FastMCP's `fastmcp-remote` bridges one of those processes to your
Gateway's Streamable HTTP endpoint, giving Claude every tool, prompt and resource registered
in the Gateway.

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

```json
{
  "mcpServers": {
    "contextforge": {
      "command": "uvx",
      "args": [
        "fastmcp-remote",
        "http://localhost:4444/servers/UUID_OF_SERVER_1/mcp/",
        "--header",
        "Authorization: Bearer <YOUR_JWT_TOKEN>"
      ]
    }
  }
}
```

> *Use the real server ID from the Admin UI instead of `UUID_OF_SERVER_1`, and paste your
> bearer token.*

`claude_desktop_config.json` launches subprocess servers via `command` / `args` and cannot
dial an HTTP endpoint itself — `fastmcp-remote` speaks stdio to Claude and Streamable HTTP
to the Gateway. Passing `--header "Authorization: ..."` selects bearer mode; use
`--auth none` instead when the Gateway requires no authentication.

Restart Claude Desktop after editing the file.

---

## 🔑 Generate a token

```bash
python3 -m mcpgateway.utils.create_jwt_token \
    --username admin@example.com --exp 10080 --secret my-test-key-but-now-longer-than-32-bytes
```

The `--secret` value must match the Gateway's `JWT_SECRET_KEY`, otherwise the Gateway
rejects the token. Paste the result into the `Authorization: Bearer ...` argument above.

---

## 🧪 Smoke-test inside Claude

1. Click the **"Add files, connectors, and more /"** indicator at the bottom-left of the
   message box.
2. Hover **Connectors** — your Gateway server should be listed.
3. Type:

   ```
   #get_system_time { "timezone": "Europe/Dublin" }
   ```
4. Claude calls the Gateway → tool → chat reply.

If tools don't appear, re-open **Settings ▸ Connectors**, select the server, and check
which tools are enabled under its permissions.

---
