# MCP Gateway Wrapper

This mcp wrapper allows you to access and use all the tools present in the MCP gateway through any client that supports the MCP protocol, such as Claude and Cline. It connects to the server catalog in mcp gateway and dynamically retrieves tools from it and makes tool calls as required.
If an MCP client doesn't support SSE but does support stdio, use this wrapper to connect to the gateway and access all of the gateway's features within the MCP client.

# Key Features
1. Dynamic Tool Access: Connects to the server catalog and fetches available tools in real time.
2. MCP Compatibility: Works seamlessly with any client supporting the MCP protocol (e.g., Claude, Cline).
3. Centralized Management: A single interface to manage and utilize all tools available via the MCP gateway.
4. stdio transport : Uses stdio transport for communication between MCP client and the mcpgateway


## Components

### Tools

The server extends tools from the server catalogs of mcp gateway

### Resources 

The server fetched resources from the server catalogs of mcp gateway

### Prompts

The server fetched prompts from the server catalogs of mcp gateway





## Quickstart

### Install

#### Claude Desktop

On MacOS: `~/Library/Application\ Support/Claude/claude_desktop_config.json`
On Windows: `%APPDATA%/Claude/claude_desktop_config.json`

# Running the server from local source
1. Clone the repository
2. Go to cline/claude config file
3. Add the following JSON configuration to the config file, and edit the following parameters:
   - Path to the `mcpgateway-wrapper` folder.
   - All necessary environment variables.


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


### MCP_SERVER_CATALOG_URLS
This parameter specifies one or more URLs pointing to the MCP server catalog. URLs can be provided individually or as a comma-separated list.

3.1 Specific Server:
```bash
"MCP_SERVER_CATALOG_URLS": "http://localhost:4444/servers/1"
```

3.2 Multiple Servers (comma separated servers):
```bash
"MCP_SERVER_CATALOG_URLS": "http://localhost:4444/servers/1,http://localhost:4444/servers/2,http://localhost:4444/servers/3"
```
3.3 All tools, prompts, resources (gateway URL): 
```bash
"MCP_SERVER_CATALOG_URLS": "http://localhost:4444"
```






# TODO: Published Servers Configuration
```json
  "mcpServers": {
    "mcpgateway-wrapper": {
      "command": "uvx",
      "args": [
        "mcpgateway-wrapper"
      ]
    }
  }
```

## Development

### Building and Publishing

To prepare the package for distribution:

1. Sync dependencies and update lockfile:
```bash
uv sync
```

2. Build package distributions:
```bash
uv build
```

This will create source and wheel distributions in the `dist/` directory.

3. Publish to PyPI:
```bash
uv publish
```

Note: You'll need to set PyPI credentials via environment variables or command flags:
- Token: `--token` or `UV_PUBLISH_TOKEN`
- Or username/password: `--username`/`UV_PUBLISH_USERNAME` and `--password`/`UV_PUBLISH_PASSWORD`

### Debugging


You can launch the MCP Inspector via [`npm`](https://docs.npmjs.com/downloading-and-installing-node-js-and-npm) with this command:

```bash
npx @modelcontextprotocol/inspector uv --directory "path to mcpgateway-wrapper" run mcpgateway-wrapper
```


Upon launching, the Inspector will display a URL that you can access in your browser to begin debugging.