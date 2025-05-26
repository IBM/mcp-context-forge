# MCP Inspector

[MCP Inspector](https://www.npmjs.com/package/@modelcontextprotocol/inspector) is a visual debugging tool for the Model Context Protocol. It connects to MCP-compliant servers (like `mcpgateway-wrapper` or MCP Gateway directly) and allows you to:

- Inspect available tools
- Execute tool invocations
- View the full JSON-RPC/MCP traffic
- Simulate prompt rendering or resource access (future)

---

## 🚀 Launching MCP Inspector

If you have Node.js installed, you can launch it via `npx`:

```bash
npx @modelcontextprotocol/inspector \
  uv --directory path/to/mcpgateway-wrapper \
  run mcpgateway-wrapper
```

> This will:
>
> * Start the wrapper
> * Open a local Inspector session in your browser

---

## 🔧 Inspector Features

* 📜 View registered tools in real time
* 🧪 Send test completions or invocations
* 👀 Observe request/response JSON as it flows through the system
* 🔁 Replay or modify previous messages
* 🧵 View sampling messages (when streaming is supported)

---

## 🔐 Auth & Config

Ensure you provide the necessary `MCP_AUTH_USER` and `MCP_AUTH_PASS` as environment variables if your gateway requires authentication:

```bash
export MCP_GATEWAY_BASE_URL=http://localhost:4444
export MCP_SERVER_CATALOG_URLS=http://localhost:4444/servers/2
export MCP_AUTH_USER=admin
export MCP_AUTH_PASS=changeme
```

Then run the Inspector again.

---

## 🌐 Connect to Live Gateway

You can also connect directly to MCP Gateway without the wrapper:

```bash
npx @modelcontextprotocol/inspector --url http://localhost:4444
```

> This will query available tools, prompts, and metadata from the root.

---
