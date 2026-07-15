# MCP Inspector

[MCP Inspector](https://www.npmjs.com/package/@modelcontextprotocol/inspector) is a visual
debugging GUI for the **Model Context Protocol**.
Point it at any MCP-compliant endpoint &mdash; a Gateway **Streamable HTTP** endpoint &mdash; and you can:

* 🔍 Browse **tools**, **prompts** and **resources** in real time
* 🛠 Invoke tools with JSON params and inspect raw results
* 📜 Watch the full bidirectional JSON-RPC / MCP traffic live
* 🔄 Replay or edit previous requests
* 💬 Stream sampling messages (where supported)

---

## 🚀 Quick launch recipes

> All commands use **npx** (bundled with Node ≥ 14).
> Feel free to `npm install -g @modelcontextprotocol/inspector` for a global binary.

!!! tip "Base URL"
    - Direct installs (`uvx`, pip, or `docker run`): `http://localhost:4444`
    - Docker Compose (nginx proxy): `http://localhost:8080`

| Use-case | One-liner | What happens |
|----------|-----------|--------------|
| **1. Connect to Gateway (Streamable HTTP)** |<br/>```bash<br/>npx @modelcontextprotocol/inspector \\<br/>  --url http://localhost:4444/servers/UUID_OF_SERVER_1/mcp/ \\<br/>  --header "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN"<br/>``` | Inspector opens `http://localhost:5173` and attaches **directly** to the gateway endpoint. |
| **2. Connect via Gateway Root** |<br/>```bash<br/>npx @modelcontextprotocol/inspector \\<br/>  --url http://localhost:4444/mcp/ \\<br/>  --header "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN"<br/>``` | Inspector opens `http://localhost:5173` and attaches to the gateway root endpoint. |
| **3 - Inspector only (UI)** |<br/>```bash<br/>npx @modelcontextprotocol/inspector --stdio<br/>``` | Inspector opens the GUI for manual configuration. |

---

## 🔐 Environment variables

Most wrappers / servers will need at least:

```bash
export MCP_SERVER_URL=http://localhost:4444/servers/UUID_OF_SERVER_1   # one or many
export MCP_AUTH=$(python3 -m mcpgateway.utils.create_jwt_token -u admin@example.com --secret my-test-key-but-now-longer-than-32-bytes)
```

If you point Inspector **directly** at a Gateway Streamable HTTP endpoint, pass the header:

```bash
--header "Authorization: Bearer $MCP_AUTH"
```

---

## 🔧 Inspector Highlights

* **Real-time catalogue** - tools/prompts/resources update as soon as the Gateway sends `*Changed` notifications.
* **Request builder** - JSON editor with schema hints (if the tool exposes an `inputSchema`).
* **Traffic console** - colour-coded view of every request & reply; copy as cURL.
* **Replay & edit** - click any previous call, tweak parameters, re-send.
* **Streaming** - see `sampling/createMessage` chunks scroll by live (MCP 2025-03-26 spec).

---

## 🛰 Connecting through Translate Bridge (stdio → SSE bridge)

Want to test a **stdio-only** MCP server inside Inspector?

```bash
# Example: expose mcp-server-git over SSE on :8000
python3 -m mcpgateway.translate --stdio "uvx mcp-server-git" --expose-sse --port 9002
#   SSE stream:  http://localhost:9002/sse
#   POST back-channel: http://localhost:9002/message
```

Then simply start Inspector:

```bash
npx @modelcontextprotocol/inspector \
  --url http://localhost:9002/sse
```

Translate Bridge handles the bridging; Inspector thinks it is speaking native SSE.
