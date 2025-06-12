# Continue (VS Code Extension)

[Continue](https://www.continue.dev/) is an open-source AI code assistant for Visual Studio
Code.
Because it speaks the **Model Context Protocol (MCP)**, Continue can discover and call the
tools you publish through **MCP Gateway** – no plug-in code required.

---

## 🧰 Key Features

* ✨ **AI-powered completions, edits & chat**
* 🔌 **MCP integration** – dynamic tool list pulled from your gateway
* 🏗 **Bring-your-own model** – local Ollama, OpenAI, Anthropic, etc.
* 🧠 **Context-aware** – reads your workspace to craft better replies

---

## 🛠 Installation

1. **Install "Continue"**: `Ctrl ⇧ X` → search *Continue* → **Install**
2. **Open config**: `Ctrl ⇧ P` → *"Continue: Open Config"*
   → edits **`~/.continue/config.json`**

---

## 🔗 Connecting Continue to MCP Gateway

There are **two ways** to attach Continue to a gateway:

| Transport | When to use | Snippet |
|-----------|-------------|---------|
| **SSE (HTTP)** | Remote / SSL / no local process | `<-- see Option A>` |
| **Stdio wrapper** | Local dev, no SSE, or auth-header issues | `<-- see Option B>` |

> For both options you still need a **JWT** or Basic auth if the gateway is protected.

### Option A · Direct SSE

```jsonc
// ~/.continue/config.json
{
  "experimental": {
    "modelContextProtocolServer": {
      "transport": {
        "type": "sse",
        "url": "http://localhost:4444/servers/1/sse",
        "headers": {
          "Authorization": "Bearer ${env:MCP_AUTH_TOKEN}"
        }
      }
    }
  }
}
```

*Generate a token*:

```bash
export MCP_AUTH_TOKEN=$(python -m mcpgateway.utils.create_jwt_token -u admin --secret my-test-key)
```

### Option B · Local stdio bridge (`mcpgateway.wrapper`)

1. **Install the wrapper** (pipx keeps it isolated):

```bash
pipx install --include-deps mcp-contextforge-gateway
```

2. **Config in Continue**:

```jsonc
{
  "experimental": {
    "modelContextProtocolServer": {
      "transport": {
        "type": "stdio",
        "command": "python3",
        "args": ["-m", "mcpgateway.wrapper"],
        "env": {
          "MCP_SERVER_CATALOG_URLS": "http://localhost:4444/servers/1",
          "MCP_AUTH_TOKEN": "${env:MCP_AUTH_TOKEN}",
          "MCP_TOOL_CALL_TIMEOUT": "120"
        }
      }
    }
  }
}
```

> If you prefer Docker:<br/>
> replace `"command": "python3"` with `"command": "docker"` and use the same container
> arguments shown in the Copilot docs.

---

## 🧪 Using Gateway Tools

Once VS Code restarts:

1. Open **Continue Chat** (`⌥ C` on macOS / `Alt C` on Windows/Linux)
2. Click **Tools** – your gateway's tools should appear
3. Chat naturally:

   ```
   Run hello_world with name = "Alice"
   ```

   The wrapper/Gateway executes and streams the JSON result back to Continue.

---

## 📝 Tips

* **SSE vs stdio** – SSE is simpler in prod, stdio is great for offline or
  header-free environments.
* **Multiple servers** – add more blocks under `"servers"` if you run staging vs prod.
* **Custom instructions** – Continue's *Custom Instructions* pane lets you steer tool use.

---

## 📚 Resources

* 🌐 [Continue docs](https://docs.continue.dev/)
* 📖 [MCP Spec](https://modelcontextprotocol.io/)
* 🛠 [MCP Gateway GitHub](https://github.com/ibm/mcp-context-forge)
