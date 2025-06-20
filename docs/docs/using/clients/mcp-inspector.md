# MCP Inspector

[MCP Inspector](https://www.npmjs.com/package/@modelcontextprotocol/inspector) is a visual
debugging GUI for the **Model Context Protocol**.
Point it at any MCP-compliant endpoint &mdash; a live Gateway **SSE** stream or a local
`mcpgateway.wrapper` stdio server &mdash; and you can:

* 🔍 Browse **tools**, **prompts** and **resources** in real time
* 🛠 Invoke tools with JSON params and inspect raw results
* 📜 Watch the full bidirectional JSON-RPC / MCP traffic live
* 🔄 Replay or edit previous requests
* 💬 Stream sampling messages (where supported)

---

## 🚀 Quick launch recipes

> All commands use **npx** (bundled with Node ≥ 14).
> Feel free to `npm install -g @modelcontextprotocol/inspector` for a global binary.

| Use-case | One-liner | What happens |
|----------|-----------|--------------|
| **1. Connect to Gateway (SSE)** |<br/>```bash<br/>npx @modelcontextprotocol/inspector \\<br/>  --url http://localhost:4444/servers/1/sse \\<br/>  --header "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN"<br/>``` | Inspector opens `http://localhost:5173` and attaches **directly** to the gateway stream. |
| **2. Connect to Gateway (Streamable HTTP)** |<br/>```bash<br/>npx @modelcontextprotocol/inspector \\<br/>  --url http://localhost:4444/servers/1/mcp/ \\<br/>  --header "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN"<br/>``` | Inspector opens `http://localhost:5173` and attaches **directly** to the gateway stream. |
| **3 · Spin up the stdio wrapper in-process** |<br/>```bash<br/>export MCP_AUTH_TOKEN=$MCPGATEWAY_BEARER_TOKEN<br/>export MCP_SERVER_CATALOG_URLS=http://localhost:4444/servers/1<br/><br/>npx @modelcontextprotocol/inspector \\<br/>  python -m mcpgateway.wrapper<br/>``` | Inspector forks `python -m mcpgateway.wrapper`, then connects to its stdio port automatically. |
| **4 · Same, but via uv / uvenv** |<br/>```bash<br/>npx @modelcontextprotocol/inspector \\<br/>  uvenv run python -m mcpgateway.wrapper<br/>``` | Uses the super-fast **uv** virtual-env if you prefer. |
| **5 · Wrapper already running** | Launch the wrapper in another shell, then:<br/>```bash<br/>npx @modelcontextprotocol/inspector --stdio<br/>``` | Inspector only opens the GUI and binds to the running stdio server on stdin/stdout. |

---

## 🔐 Environment variables

Most wrappers / servers will need at least:

```bash
export MCP_SERVER_CATALOG_URLS=http://localhost:4444/servers/1   # one or many
export MCP_AUTH_TOKEN=$(python -m mcpgateway.utils.create_jwt_token -u admin --secret my-test-key)
```

If you point Inspector **directly** at a Gateway SSE stream, pass the header:

```bash
--header "Authorization: Bearer $MCP_AUTH_TOKEN"
```

---

## 🔧 Inspector Highlights

* **Real-time catalogue** – tools/prompts/resources update as soon as the Gateway sends `*Changed` notifications.
* **Request builder** – JSON editor with schema hints (if the tool exposes an `inputSchema`).
* **Traffic console** – colour-coded view of every request & reply; copy as cURL.
* **Replay & edit** – click any previous call, tweak parameters, re-send.
* **Streaming** – see `sampling/createMessage` chunks scroll by live (MCP 2025-03-26 spec).

---

## 🛰 Connecting through SuperGateway (stdio → SSE bridge)

Want to test a **stdio-only** MCP server inside Inspector?

```bash
# Example: expose mcp-server-git over SSE on :8000
npx -y supergateway --stdio "uvx run mcp-server-git"
#   SSE stream:  http://localhost:8000/sse
#   POST back-channel: http://localhost:8000/message
```

Then simply start Inspector:

```bash
npx @modelcontextprotocol/inspector \
  --url http://localhost:8000/sse
```

SuperGateway handles the bridging; Inspector thinks it is speaking native SSE.
