# mcp-servers/AGENTS.md

MCP server implementation guidance for AI coding assistants.

## Directory Structure

```
mcp-servers/
├── go/                         # Go MCP server template
│   ├── main.go
│   ├── go.mod
│   ├── Makefile
│   └── README.md
├── python/                     # Python MCP server template
│   ├── src/
│   ├── tests/
│   ├── pyproject.toml
│   ├── Makefile
│   └── README.md
├── rust/                       # Rust MCP server template
│   ├── src/
│   ├── Cargo.toml
│   └── README.md
├── templates/                  # Scaffolding templates
├── scaffold-go-server.sh       # Go server scaffolding script
└── scaffold-python-server.sh   # Python server scaffolding script
```

## Scaffolding New Servers

### Go Server

```bash
./mcp-servers/scaffold-go-server.sh my-server
cd my-server
make build
make run
```

### Python Server

```bash
./mcp-servers/scaffold-python-server.sh my-server
cd my-server
make install-dev
make run
```

## Go Server Development

From `mcp-servers/go/`:

```bash
make build            # Build the server
make run              # Run the server
make test             # Run tests
make lint             # Run linter
```

### Key Files

- `main.go` - Server entry point
- `go.mod` - Go module definition
- `Makefile` - Build automation

### Example Tool Implementation

```go
func (s *Server) handleToolCall(name string, args map[string]interface{}) (interface{}, error) {
    switch name {
    case "my_tool":
        return s.myTool(args)
    default:
        return nil, fmt.Errorf("unknown tool: %s", name)
    }
}
```

## Python Server Development

From `mcp-servers/python/`:

```bash
make install-dev      # Install with dev dependencies
make run              # Run the server
make test             # Run tests
make lint             # Run linters
make format           # Format code
```

### Key Files

- `src/server.py` - Server implementation
- `pyproject.toml` - Project configuration
- `Makefile` - Build automation

### Example Tool Implementation

```python
from mcp.server import Server
from mcp.types import Tool, TextContent

server = Server("my-server")

@server.tool()
async def my_tool(arg1: str, arg2: int) -> list[TextContent]:
    """Tool description."""
    result = process(arg1, arg2)
    return [TextContent(type="text", text=str(result))]
```

## Rust Server Development

From `mcp-servers/rust/`:

```bash
cargo build           # Build the server
cargo run             # Run the server
cargo test            # Run tests
```

### Key Files

- `src/main.rs` - Server entry point
- `Cargo.toml` - Rust dependencies

## Exposing Servers via Gateway

After building your MCP server:

```bash
# Expose stdio server via HTTP/SSE
python -m mcpgateway.translate --stdio "./my-server" --port 9000

# Register with gateway
curl -X POST http://localhost:4444/gateways \
  -H "Content-Type: application/json" \
  -d '{"url": "http://localhost:9000", "name": "my-server"}'
```

## Testing Servers

### Unit Tests

Each language template includes test scaffolding:

```bash
# Go
cd mcp-servers/go && make test

# Python
cd mcp-servers/python && make test

# Rust
cd mcp-servers/rust && cargo test
```

### Integration Testing

Test server tools via MCP client:

```python
from mcp import ClientSession
from mcp.client.stdio import stdio_client

async def test_tool():
    async with stdio_client("./my-server") as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool("my_tool", {"arg1": "value"})
            assert result is not None
```

## Key Documentation

- `llms/mcp-server-go.md` - Detailed Go server guidance (for end-users)
- `llms/mcp-server-python.md` - Detailed Python server guidance (for end-users)
- `docs/docs/using/servers/` - Server integration guides
