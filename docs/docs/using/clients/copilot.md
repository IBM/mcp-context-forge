# 🧠 GitHub Copilot + ContextForge

Super-charge Copilot (or any VS Code chat agent that speaks MCP) with tools, prompts and
resources from **your own ContextForge**.

With Copilot → MCP you can:

* 🔧 call custom / enterprise tools from chat
* 📂 pull live resources (configs, docs, snippets)
* 🧩 render prompts or templates directly inside the IDE

Copilot supports for MCP integration via Streamable HTTP.

!!! tip "Gateway URL"
    - Direct installs (`uvx`, pip, or `docker run`): `http://localhost:4444`
    - Docker Compose (nginx proxy): `http://localhost:8080`

---

## 🛠 Prerequisites

* **VS Code ≥ 1.99**
* `"chat.mcp.enabled": true` in your *settings.json*
* ContextForge running (`make serve`, Docker, or container image)
* A JWT or Basic credentials (`admin` / `changeme` in dev)

---

## 🔗 Streamable HTTP (recommended)

### 1 - Create `.vscode/mcp.json`

```json
{
  "servers": {
    "mcp-gateway": {
      "type": "http",
      "url": "https://mcpgateway.example.com/servers/UUID_OF_SERVER_1/mcp/",
      "headers": {
        "Authorization": "Bearer <YOUR_JWT_TOKEN>"
      }
    }
  }
}
```

> **Tip - generate a token**

```bash
python3 -m mcpgateway.utils.create_jwt_token -u admin@example.com --exp 10080 --secret my-test-key-but-now-longer-than-32-bytes
```

### 2 - Create `.vscode/mcp.json`

```json
{
  "servers": {
    "mcp-gateway": {
      "type": "http",
      "url": "https://mcpgateway.example.com/servers/UUID_OF_SERVER_1/mcp/",
      "headers": {
        "Authorization": "Bearer <YOUR_JWT_TOKEN>"
      }
    }
  }
}
```

---

## 🧪 Verify inside Copilot

1. Open **Copilot Chat** → switch to *Agent* mode.
2. Click **Tools** - your Gateway tools should list.
3. Try:

```
#echo { "message": "Hello from VS Code" }
```

Copilot routes the call → Gateway → tool, and prints the reply.

---

## 📝 Good to know

    * **Streamable HTTP** - preferred for all production connections.
* You can manage servers, tools and prompts from the Gateway **Admin UI** (`/admin`).
* Need a bearer quickly?
  `export MCP_AUTH=$(python3 -m mcpgateway.utils.create_jwt_token -u admin@example.com --secret my-test-key-but-now-longer-than-32-bytes)`

---

## 📚 Further Reading

* **Gateway GitHub** → [https://github.com/ibm/mcp-context-forge](https://github.com/ibm/mcp-context-forge)
* **MCP Spec** → [https://modelcontextprotocol.io/](https://modelcontextprotocol.io/)
* **Copilot docs** → [https://github.com/features/copilot](https://github.com/features/copilot)
