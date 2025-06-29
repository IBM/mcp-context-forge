# 🧠 GitHub Copilot + MCP Gateway

Super-charge Copilot (or any VS Code chat agent that speaks MCP) with tools, prompts and
resources from **your own MCP Gateway**.

With Copilot → MCP you can:

* 🔧 call custom / enterprise tools from chat
* 📂 pull live resources (configs, docs, snippets)
* 🧩 render prompts or templates directly inside the IDE

Copilot supports **SSE** streams out-of-the-box; for environments that forbid long-lived
HTTP or require local stdio, you can insert the bundled **`mcpgateway.wrapper`** bridge.

---

## 🛠 Prerequisites

* **VS Code ≥ 1.99**
* `"chat.mcp.enabled": true` in your *settings.json*
* An MCP Gateway running (`make serve`, Docker, or container image)
* A JWT or Basic credentials (`admin` / `changeme` in dev)

---

## 🔗 Option 1 · Direct SSE (best for prod / remote)

### 1 · Create `.vscode/mcp.json`

```json
{
  "servers": {
    "mcp-gateway": {
      "type": "sse",
      "url": "https://mcpgateway.example.com/servers/1/sse",
      "headers": {
        "Authorization": "Bearer <YOUR_JWT_TOKEN>"
      }
    }
  }
}
```

> **Tip – generate a token**

```bash
python -m mcpgateway.utils.create_jwt_token -u admin --exp 10080 --secret my-test-key
```

## 🔗 Option 2 · Streamable HTTP (best for prod / remote)

### 2 · Create `.vscode/mcp.json`

```json
{
  "servers": {
    "mcp-gateway": {
      "type": "http",
      "url": "https://mcpgateway.example.com/servers/1/mcp/",
      "headers": {
        "Authorization": "Bearer <YOUR_JWT_TOKEN>"
      }
    }
  }
}
```

---

## 🔗 Option 3 · Local stdio bridge (`mcpgateway.wrapper`)

Perfect when:

* the IDE cannot add HTTP headers, or
* you're offline / behind a corp proxy.

### 1 · Install the wrapper (one-liner)

```bash
pipx install --include-deps mcp-contextforge-gateway          # isolates in ~/.local/pipx/venvs
#   - or -
uv pip install mcp-contextforge-gateway                       # inside any uv/venv you like
```

### 2 · Create `.vscode/mcp.json`

```json
{
  "servers": {
    "mcp-wrapper": {
      "type": "stdio",
      "command": "python3",
      "args": ["-m", "mcpgateway.wrapper"],
      "env": {
        "MCP_SERVER_CATALOG_URLS": "http://localhost:4444/servers/1",
        "MCP_AUTH_TOKEN": "<YOUR_JWT_TOKEN>",
        "MCP_TOOL_CALL_TIMEOUT": "120"
      }
    }
  }
}
```

That's it – VS Code spawns the stdio process, pipes JSON-RPC, and you're ready to roll.

<details>
<summary><strong>🐳 Docker alternative</strong></summary>

```jsonc
{
  "command": "docker",
  "args": [
    "run", "--rm", "--network=host", "-i",
    "-e", "MCP_SERVER_CATALOG_URLS=http://localhost:4444/servers/1",
    "-e", "MCP_AUTH_TOKEN=<YOUR_JWT_TOKEN>",
    "ghcr.io/ibm/mcp-context-forge:latest",
    "python3", "-m", "mcpgateway.wrapper"
  ]
}
```

</details>

---

## 🧪 Verify inside Copilot

1. Open **Copilot Chat** → switch to *Agent* mode.
2. Click **Tools** – your Gateway tools should list.
3. Try:

```
#echo { "message": "Hello from VS Code" }
```

Copilot routes the call → Gateway → tool, and prints the reply.

---

## 📝 Good to know

* **Use SSE for production**, stdio for local/offline.
* You can manage servers, tools and prompts from the Gateway **Admin UI** (`/admin`).
* Need a bearer quickly?
  `export MCP_AUTH_TOKEN=$(python -m mcpgateway.utils.create_jwt_token -u admin --secret my-test-key)`

---

## 📚 Further Reading

* **Gateway GitHub** → [https://github.com/ibm/mcp-context-forge](https://github.com/ibm/mcp-context-forge)
* **MCP Spec** → [https://modelcontextprotocol.io/](https://modelcontextprotocol.io/)
* **Copilot docs** → [https://github.com/features/copilot](https://github.com/features/copilot)
