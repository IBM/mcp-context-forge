# Claude Desktop × ContextForge

[Claude Desktop](https://www.anthropic.com/index/claude-desktop) connects to remote MCP
servers through **Custom Connectors**.
By pointing one at your Gateway's `/mcp/` endpoint you give Claude access to every tool,
prompt and resource registered in your Gateway.

!!! tip "Gateway URL"
    - Direct installs (`uvx`, pip, or `docker run`): `http://localhost:4444`
    - Docker Compose (nginx proxy): `http://localhost:8080`

!!! warning "`claude_desktop_config.json` is stdio-only"
    The `claude_desktop_config.json` file launches **local subprocess** servers via
    `command` / `args`. It cannot connect to an HTTP endpoint. Use a Custom Connector
    for the Gateway, as described below.

---

## 🔌 Add the Gateway as a Custom Connector

1. Open **Settings** — `Ctrl+,` (or the top-left menu ▸ *File* ▸ *Settings*).
2. Click **Connectors** in the sidebar.
3. Click **Add** ▸ **Add custom connector**.
4. Paste your virtual server's MCP endpoint:

   ```text
   http://localhost:4444/servers/UUID_OF_SERVER_1/mcp/
   ```

5. Click **Add** and complete the authentication prompt.

> *Use the real server ID from the Admin UI instead of `UUID_OF_SERVER_1`.*

---

## 🔑 Authentication

Claude prompts for credentials when the connector is added — the Gateway's bearer token is
supplied through that flow rather than stored in a config file.

Generate a token with:

```bash
export MCPGATEWAY_BEARER_TOKEN=$(python3 -m mcpgateway.utils.create_jwt_token \
    --username admin@example.com --exp 10080 --secret my-test-key-but-now-longer-than-32-bytes)
```

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
