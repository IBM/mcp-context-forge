# MCP Clients

ContextForge is compatible with any client that speaks the [Model Context Protocol (MCP)](https://modelcontextprotocol.io). This section documents tested clients, their configuration, and any integration tips.

---

## 🔌 Client Types

There are two ways clients typically connect:

- **Direct to Gateway** (HTTP/SSE/WS)
- **Via `mcpgateway-wrapper`** (stdio transport, especially for LLM apps)

---

## ✅ Compatible Clients

| Client | Type | Notes |
|--------|------|-------|
| [Claude Desktop](claude-desktop.md) | UI | Configure to launch `mcpgateway.wrapper` via JSON |
| [Cline](cline.md) | CLI | Supports stdio or direct MCP over HTTP |
| [Continue](continue.md) | VSCode plugin | MCP plugin support |
| [MCP Inspector](mcp-inspector.md) | Web debugger | Great for manual testing and exploring protocol features |

Each of these tools can consume the MCP protocol and dynamically detect tools from the Gateway.

!!! tip "Gateway URL"
    - Direct installs (`uvx`, pip, or `docker run`): `http://localhost:4444`
    - Docker Compose (nginx proxy): `http://localhost:8080`

---

## 📁 What's in This Section

| Page | Description |
|------|-------------|
| [Claude Desktop](claude-desktop.md) | How to connect Claude to ContextForge via wrapper |
| [Cline](cline.md) | Using the CLI tool for invoking tools or prompts |
| [Continue](continue.md) | Integrating with the VSCode plugin |
| [MCP Inspector](mcp-inspector.md) | Launch and test the Gateway or wrapper via a web debugger |

---
