# Claude Desktop

[Claude Desktop](https://www.anthropic.com/index/claude-desktop) is a desktop application that supports MCP integration via stdio. You can configure it to launch `mcpgateway-wrapper`, enabling Claude to access all tools registered in MCP Gateway.

---

## 🖥️ Where to Configure

Depending on your OS, edit the Claude configuration file:

- **macOS**:
  `~/Library/Application Support/Claude/claude_desktop_config.json`

- **Windows**:
  `%APPDATA%/Claude/claude_desktop_config.json`

---

## ⚙️ Example Configuration

Add this block to the `"mcpServers"` section of your config:

```json
"mcpServers": {
  "mcpgateway-wrapper": {
    "command": "uv",
    "args": [
      "--directory",
      "/path/to/mcpgateway-wrapper",
      "run",
      "mcpgateway-wrapper"
    ],
    "env": {
      "MCP_GATEWAY_BASE_URL": "http://localhost:4444",
      "MCP_SERVER_CATALOG_URLS": "http://localhost:4444/servers/2",
      "MCP_AUTH_TOKEN": "your_bearer_token"
    }
  }
}
```

> 🔁 Adjust `path/to/mcpgateway-wrapper` and server ID as needed.

---

## 🧪 Test it in Claude

Once Claude launches:

1. Choose the `mcpgateway-wrapper` backend
2. Type a tool invocation (e.g., `weather`, `hello`, etc.)
3. The tool should be fetched from the Gateway and executed dynamically

---

## 🚀 Advanced: Pre-installed Wrapper Mode

If you've published the wrapper to PyPI or have it globally installed:

```json
"mcpServers": {
  "mcpgateway-wrapper": {
    "command": "uvx",
    "args": ["mcpgateway-wrapper"]
  }
}
```

This assumes your environment variables are managed globally or set in the terminal session launching Claude.

---
