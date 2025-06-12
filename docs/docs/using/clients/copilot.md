# 🧠 Microsoft GitHub Copilot + MCP Gateway

Extend GitHub Copilot's functionality in VS Code by connecting it to your **MCP Gateway**, enabling powerful tool invocation, resource access, and dynamic integration—all via the [Model Context Protocol (MCP)](https://modelcontextprotocol.io/).

GitHub Copilot can also be configured to use local models via [Ollama](https://ollama.com/).

---

## 🛠 Prerequisites

* **VS Code ≥ 1.99**
* `"chat.mcp.enabled": true` in your VS Code settings
* MCP Gateway running (via `make serve` or Docker)
* Admin JWT or basic credentials to authenticate

---

## 🔗 Option 1: SSE (Direct HTTP Integration)

For remote or authenticated servers, use the **SSE transport** in `.vscode/mcp.json`:

### 1. Create the Config File

Create `.vscode/mcp.json` in your project root:

```json
{
  "servers": {
    "mcp": {
      "type": "sse",
      "url": "https://mcpgateway.domain/servers/1/sse",
      "headers": {
        "Authorization": "Bearer <YOUR_JWT_TOKEN>"
      }
    }
  }
}
```

> 💡 You can generate a JWT with:

```bash
python3 -m mcpgateway.utils.create_jwt_token -u admin -e 10080 > token.txt
```

---

## 🔗 Option 2: `mcpgateway-wrapper` (STDIO Integration)

If your client (e.g., Copilot) supports **stdio-based MCP servers**, use `mcpgateway-wrapper` to expose the Gateway as a local process:

### 1. Install the Wrapper

Clone or download the [`mcpgateway-wrapper`](https://github.com/IBM/mcp-context-forge) repository and navigate to it:

```bash
# Clone the repo
git clone git@github.com:IBM/mcp-context-forge.git
cd mcp-context-forge

# Install dependencies and activate the venv
make venv install activate
. ~/.venv/mcpgateway/bin/activate

# Install uvx
pip install uvx

cd mcpgateway-wrapper
```

### 2. Run the Wrapper Locally

```bash
uv run mcpgateway-wrapper
```

Or using Inspector for debug:

```bash
npx @modelcontextprotocol/inspector uv --directory . run mcpgateway-wrapper
```

### 3. Create `.vscode/mcp.json`

Point Copilot to the local wrapper process:

```json
{
  "servers": {
    "mcp-wrapper": {
      "type": "stdio",
      "command": "uv",
      "args": [
        "--directory",
        "path/to/mcpgateway-wrapper",
        "run",
        "mcpgateway-wrapper"
      ],
      "env": {
        "MCP_GATEWAY_BASE_URL": "http://localhost:4444",
        "MCP_SERVER_CATALOG_URLS": "http://localhost:4444/servers/1",
        "MCP_AUTH_TOKEN": "your_bearer_token"
      }
    }
  }
}
```

> ✅ This setup allows Copilot to invoke Gateway-managed tools without HTTP auth headers, ideal for local dev or restrictive environments.

---

## 🧪 Verifying Tool Access

After setup:

1. Open the **Copilot chat** pane (`Ctrl + Shift + i`)
2. Switch to **Agent Mode**
3. Click **Tools** - tools from your MCP server should appear

Try prompting:

```
#echo { "message": "Hello" }
```

Expected: Copilot invokes the Gateway's `echo` tool and displays the response.

---

## 📝 Tips for Success

* Use **SSE** for production, **stdio** for local/CLI workflows
* Register servers via Admin UI or `/admin#catalog`
* Use JWTs for secure, headless integration

---

## 📚 Resources

* [MCP Gateway GitHub](https://github.com/hexmos/mcpgateway)
* [mcpgateway-wrapper](https://github.com/hexmos/mcpgateway-wrapper)
* [MCP Spec](https://modelcontext.org)
* [Copilot Docs](https://github.com/features/copilot)

---
