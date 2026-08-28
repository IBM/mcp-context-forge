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

---

## 🔗 Connecting Continue to ContextForge

Attach Continue to a gateway over **Streamable HTTP**:

> You still need a **JWT** or Basic auth if the gateway is protected.

### Direct Streamable HTTP

Add the gateway as an MCP server in your workspace, in
`.continue/mcpServers/contextforge.json`:

```json
{
  "mcpServers": {
    "contextforge": {
      "type": "streamable-http",
      "url": "http://localhost:4444/servers/UUID_OF_SERVER_1/mcp/",
      "requestOptions": {
        "headers": {
          "Authorization": "Bearer <YOUR_AUTH_TOKEN_HERE>"
        }
      }
    }
  }
}
```

Auth headers belong under `requestOptions.headers` — Continue does not read a top-level
`headers` key for MCP servers.

*Generate a token to paste above*:

```bash
python3 -m mcpgateway.utils.create_jwt_token -u admin@example.com --secret my-test-key-but-now-longer-than-32-bytes
```


## 🧪 Using Gateway Tools

Once VS Code restarts:

1. Open **Continue Chat** (`⌥ C` on macOS / `Alt C` on Windows/Linux)
2. Click **Tools** - your gateway's tools should appear
3. Chat naturally:

   ```
   Run hello_world with name = "Alice"
   ```

   The Gateway executes and streams the JSON result back to Continue.

---

## 📝 Tips

* **Multiple servers** - add more blocks under `"servers"` if you run staging vs prod.
* **Custom instructions** - Continue's *Custom Instructions* pane lets you steer tool use.

---

## 📚 Resources

* 🌐 [Continue docs](https://docs.continue.dev/)
* 📖 [MCP Spec](https://modelcontextprotocol.io/)
* 🛠 [ContextForge GitHub](https://github.com/ibm/mcp-context-forge)
