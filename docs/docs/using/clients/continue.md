# Continue (VS Code Extension)

[Continue](https://www.continue.dev/) is an open-source AI code assistant for Visual Studio
Code.
Because it speaks the **Model Context Protocol (MCP)**, Continue can discover and call the
tools you publish through **ContextForge** - no plug-in code required.

!!! tip "Gateway URL"
    - Direct installs (`uvx`, pip, or `docker run`): `http://localhost:4444`
    - Docker Compose (nginx proxy): `http://localhost:8080`

---

## 🧰 Key Features

* ✨ **AI-powered completions, edits & chat**
* 🔌 **MCP integration** - dynamic tool list pulled from your gateway
* 🏗 **Bring-your-own model** - local Ollama, OpenAI, Anthropic, etc.
* 🧠 **Context-aware** - reads your workspace to craft better replies

---

## 🛠 Installation

1. **Install "Continue"**: `Ctrl ⇧ X` → search *Continue* → **Install**
2. **Open config**: `Ctrl ⇧ P` → *"Continue: Open Config"*
   → edits **`~/.continue/config.json`**

---

## 🔗 Connecting Continue to ContextForge

Attach Continue using **Streamable HTTP** transport (recommended):

```jsonc
// ~/.continue/config.json
{
  "experimental": {
    "modelContextProtocolServer": {
      "transport": {
        "type": "http",
        "url": "http://localhost:4444/servers/UUID_OF_SERVER_1/mcp/",
        "headers": {
          "Authorization": "Bearer ${env:MCP_AUTH}"
        }
      }
    }
  }
}
```

*Generate a token*:

```bash
export MCP_AUTH=$(python3 -m mcpgateway.utils.create_jwt_token -u admin@example.com --secret my-test-key-but-now-longer-than-32-bytes)
```

---

## 🧪 Using Gateway Tools

Once VS Code restarts:

1. Open **Continue Chat** (`⌥ C` on macOS / `Alt C` on Windows/Linux)
2. Click **Tools** - your gateway's tools should appear
3. Chat naturally:

   ```
   Run hello_world with name = "Alice"
   ```

   The wrapper/Gateway executes and streams the JSON result back to Continue.

---

## 📝 Tips

* **Streamable HTTP** - preferred for all client connections.

* **Multiple servers** - add more blocks under `"servers"` if you run staging vs prod.
* **Custom instructions** - Continue's *Custom Instructions* pane lets you steer tool use.

---

## 📚 Resources

* 🌐 [Continue docs](https://docs.continue.dev/)
* 📖 [MCP Spec](https://modelcontextprotocol.io/)
* 🛠 [ContextForge GitHub](https://github.com/ibm/mcp-context-forge)
