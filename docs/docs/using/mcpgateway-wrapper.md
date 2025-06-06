# STDIO Wrapper

`mcpgateway-wrapper` acts as a lightweight **MCP-compatible stdio server** that dynamically mirrors tools from a live [MCP Gateway](../overview/index.md). It allows any client that supports the MCP protocol — such as Claude Desktop, Cline, or Continue — to invoke tools directly via the Gateway.

---

## 🔑 Key Features

- **Dynamic Tool Access**
  Automatically fetches all tools from a given MCP Gateway server catalog in real time.

- **Centralized Gateway Integration**
  Exposes all tools managed by your MCP Gateway under a single stdio-compatible interface.

- **Full MCP Protocol Support**
  Responds to `initialize`, `ping`, `notify`, `complete`, and `createMessage` via stdio transport.

- **Tool Invocation**
  All tool calls are proxied to the Gateway's tool registry via HTTP.

- **Extensible**
  Future support for Prompts and Resources is planned.

---

## ⚙️ Components

### ✅ Tools
Fetched from the configured server catalog (`/servers/{id}`) and exposed dynamically.

### 🚧 Resources (Coming Soon)
Will mirror resources registered on the Gateway.

### 🚧 Prompts (Coming Soon)
Will fetch and expose prompt templates via the MCP interface.

---

## 🚀 Quickstart

### 1. Change to the wrapper directory

```bash
cd mcpgateway-wrapper
```

### 2. Integrate with Claude Desktop

On macOS:

```bash
~/Library/Application Support/Claude/claude_desktop_config.json
```

On Windows:

```bash
%APPDATA%/Claude/claude_desktop_config.json
```

Add a new server block:

```json
 {
  "mcpServers": {
    "mcpgateway-wrapper": {
      "command": "uv",
      "args": [
        "--directory",
        "path-to-folder/mcpgateway-wrapper",
        "run",
        "mcpgateway-wrapper"
      ],
      "env": {
        "MCP_SERVER_CATALOG_URLS": "http://localhost:4444/servers/1",
        "MCP_AUTH_TOKEN": "your_bearer_token"
      }
    }
  }
}
```


> Replace `path-to-mcpgateway-wrapper` with the actual folder path.

### ✅ Environment Variables

| Variable                  | Purpose                                            |
| ------------------------- | -------------------------------------------------- |
| `MCP_SERVER_CATALOG_URLS` | One or more `/servers/{id}` catalog URLs           |
| `MCP_AUTH_TOKEN`          | Bearer Token Authentication                        |


---

## 🐍 Local Development

To run locally:

```bash
uv run mcpgateway-wrapper
```

Or debug using the MCP Inspector:

```bash
npx @modelcontextprotocol/inspector uv --directory "path-to-wrapper" run mcpgateway-wrapper
```

---

## 🏗 Build

Use [`uv`](https://github.com/astral-sh/uv) to manage builds:

```bash
uv sync       # Install dependencies
```

---

## 📝 Example Use Case

Once launched, any MCP-compatible client (e.g. Claude Desktop or Cline) can call:

```json
{
  "method": "hello_world",
  "params": { "name": "Alice" }
}
```

And the wrapper will:

1. Match the method to a tool in the Gateway's registry
2. Send a tool invocation request to the Gateway
3. Return the result via stdout

---

## 🔮 Planned Features

* Prompt rendering support
* Resource URI fetching
* Token caching for long-lived auth
* Federation fallback if the Gateway is unreachable
