# MCP Gateway Translate Module

The `mcpgateway.translate` module provides a transport-translation bridge that enables bidirectional communication between MCP servers using different transport protocols. It bridges local JSON-RPC stdio servers to HTTP/SSE endpoints and vice versa, making MCP servers accessible via web-friendly protocols.

## Overview

The translate module serves as a lightweight bridge for exposing MCP servers over different transports:

- **stdio → SSE**: Expose a local stdio MCP server over HTTP/SSE
- **SSE → stdio**: Bridge a remote SSE endpoint to local stdio (experimental)

This enables browser-based clients, web applications, and other HTTP-based tools to interact with MCP servers that traditionally only support stdio communication.

## Installation

The translate module is included with the MCP Gateway installation:

```bash
pip install mcpgateway
```

## Quick Start

### Exposing a stdio MCP Server via HTTP/SSE

```bash
# Start the bridge to expose mcp-server-git at http://localhost:9000/sse
python3 -m mcpgateway.translate --stdio "uvx mcp-server-git" --expose-sse --port 9000

# The server is now accessible at:
# - SSE endpoint: http://localhost:9000/sse
# - Message endpoint: http://localhost:9000/message
# - Health check: http://localhost:9000/healthz
```

### Testing the Bridge

1. **Subscribe to the SSE stream** (in another terminal):
```bash
curl -N http://localhost:9000/sse
```

2. **Send an MCP initialization request**:
```bash
curl -X POST http://localhost:9000/message \
     -H 'Content-Type: application/json' \
     -d '{
       "jsonrpc": "2.0",
       "id": 1,
       "method": "initialize",
       "params": {
         "protocolVersion": "2025-03-26",
         "capabilities": {},
         "clientInfo": {
           "name": "demo",
           "version": "0.0.1"
         }
       }
     }'
```

3. **List available tools**:
```bash
curl -X POST http://localhost:9000/message \
     -H 'Content-Type: application/json' \
     -d '{"jsonrpc":"2.0","id":2,"method":"tools/list"}'
```

## Command Line Interface

### Basic Usage

```bash
python3 -m mcpgateway.translate [OPTIONS]
```

### Options

#### Local Server Options
| Option | Description | Default |
|--------|-------------|---------|
| `--stdio <command>` | Command to run as stdio subprocess | Required for local server |
| `--expose-sse` | Expose stdio server via SSE protocol | False |
| `--expose-streamable-http` | Expose stdio server via streamable HTTP | False |

#### Remote Connection Options
| Option | Description | Default |
|--------|-------------|---------|
| `--connect-sse <url>` | Connect to remote SSE endpoint | None |
| `--connect-streamable-http <url>` | Connect to remote streamable HTTP endpoint | None |
| `--stdioCommand <cmd>` | Local command for remote connections | None |

#### Configuration Options
| Option | Description | Default |
|--------|-------------|---------|
| `--port <port>` | HTTP port to bind | 8000 |
| `--host <host>` | Host interface to bind | 127.0.0.1 |
| `--logLevel <level>` | Log level (debug, info, warning, error, critical) | info |
| `--cors <origins>` | CORS allowed origins (can specify multiple) | None |
| `--oauth2Bearer <token>` | OAuth2 Bearer token for authentication | None |
| `--ssePath <path>` | SSE endpoint path | /sse |
| `--messagePath <path>` | Message endpoint path | /message |
| `--keepAlive <seconds>` | Keep-alive interval in seconds | 30 |
| `--stateless` | Use stateless mode (streamable HTTP) | False |
| `--jsonResponse` | Return JSON responses (streamable HTTP) | False |

**Note**: You must specify either `--stdio` with exposure flags OR a remote connection option

### Examples

#### Basic stdio to SSE Bridge
```bash
python3 -m mcpgateway.translate --stdio "uvx mcp-server-git" --expose-sse --port 9000
```

#### With CORS Support
```bash
python3 -m mcpgateway.translate \
    --stdio "uvx mcp-server-git" \
    --port 9000 \
    --cors "https://app.example.com" "http://localhost:3000"
```

#### Custom Endpoints
```bash
python3 -m mcpgateway.translate \
    --stdio "uvx mcp-server-git" \
    --port 9000 \
    --ssePath "/events" \
    --messagePath "/send"
```

#### Bind to All Interfaces
```bash
python3 -m mcpgateway.translate \
    --stdio "uvx mcp-server-git" \
    --port 9000 \
    --host 0.0.0.0
```

#### Debug Logging
```bash
python3 -m mcpgateway.translate \
    --stdio "uvx mcp-server-git" \
    --port 9000 \
    --logLevel debug
```

#### SSE to stdio Bridge (Experimental)
```bash
# Simple mode - just prints SSE messages to stdout
python3 -m mcpgateway.translate \
    --sse "https://remote.example.com/mcp" \
    --oauth2Bearer "your-token-here"

# With stdio command for bidirectional communication
python3 -m mcpgateway.translate \
    --sse "https://remote.example.com/mcp" \
    --stdioCommand "uvx mcp-client" \
    --oauth2Bearer "your-token-here"
```

## SSE Protocol

The translate module implements the MCP SSE protocol specification:

### Event Types

1. **`endpoint`** - Initial bootstrap event containing the message posting URL
   ```
   event: endpoint
   data: http://localhost:9000/message?session_id=abc123
   ```

2. **`message`** - JSON-RPC messages from the MCP server
   ```
   event: message
   data: {"jsonrpc":"2.0","result":{"protocolVersion":"2025-03-26"},"id":1}
   ```

3. **`keepalive`** - Periodic keep-alive events to prevent timeouts
   ```
   event: keepalive
   data: {}
   ```

### Message Flow

1. Client connects to `/sse` endpoint
2. Server sends `endpoint` event with unique session URL
3. Server sends immediate `keepalive` to confirm stream is active
4. Client POSTs JSON-RPC requests to the message endpoint
5. Server forwards requests to stdio subprocess
6. Server streams responses back via SSE `message` events
7. Server sends periodic `keepalive` events (default: every 30s)

## Programmatic Usage

The translate module can also be used programmatically:

```python
import asyncio
from mcpgateway.translate import start_stdio

# Start a stdio to SSE bridge programmatically
asyncio.run(start_stdio(
    cmd="uvx mcp-server-git",
    port=9000,
    log_level="info",
    cors=["https://app.example.com"],
    host="127.0.0.1"
))
```

## Security Considerations

### Network Binding
- By default, binds to `127.0.0.1` (localhost only)
- Use `--host 0.0.0.0` to allow external connections
- Consider firewall rules when exposing to network

### CORS Configuration
- No CORS headers by default (same-origin only)
- Use `--cors` to specify allowed origins explicitly
- Avoid using `--cors "*"` in production

### Authentication
- No built-in authentication for stdio→SSE mode
- Use `--oauth2Bearer` for SSE→stdio authentication
- Consider adding reverse proxy with auth for production

### Process Isolation
- Each stdio subprocess runs with the same permissions as the bridge
- Consider running in containers or with limited user privileges
- Monitor subprocess resource usage

## Environment Variables

The translate module respects the following environment variables:

| Variable | Description | Default |
|----------|-------------|---------|
| `SSE_KEEPALIVE_INTERVAL` | Keep-alive interval in seconds | 30 |
| `SSE_KEEPALIVE_ENABLED` | Enable/disable keep-alive events | true |

## Troubleshooting

### Common Issues

#### Port Already in Use
```
ERROR: [Errno 48] Address already in use
```
**Solution**: Choose a different port with `--port <port>`

#### Subprocess Not Found
```
ERROR: Command 'xyz' not found
```
**Solution**: Ensure the command in `--stdio` is installed and in PATH

#### CORS Errors in Browser
```
Access to EventSource blocked by CORS policy
```
**Solution**: Add the origin with `--cors "https://your-app.com"`

#### SSE Connection Drops
**Symptoms**: Client disconnects after ~30-60 seconds
**Solution**: Keep-alive events are sent by default. Check proxy/firewall timeouts.

### Debug Mode

Enable debug logging to see detailed message flow:
```bash
python3 -m mcpgateway.translate \
    --stdio "uvx mcp-server-git" \
    --port 9000 \
    --logLevel debug
```

This shows:
- All JSON-RPC messages sent/received
- SSE event generation
- Client connections/disconnections
- Subprocess lifecycle events

## Integration Examples

### JavaScript/Browser Client

```javascript
// Connect to SSE endpoint
const eventSource = new EventSource('http://localhost:9000/sse');
let messageEndpoint = null;

// Handle events
eventSource.addEventListener('endpoint', (event) => {
    messageEndpoint = event.data;
    console.log('Message endpoint:', messageEndpoint);
});

eventSource.addEventListener('message', (event) => {
    const response = JSON.parse(event.data);
    console.log('MCP Response:', response);
});

eventSource.addEventListener('keepalive', (event) => {
    console.log('Keep-alive received');
});

// Send MCP request
async function sendRequest(request) {
    if (!messageEndpoint) {
        throw new Error('No message endpoint yet');
    }

    const response = await fetch(messageEndpoint, {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(request)
    });

    if (!response.ok) {
        throw new Error(`HTTP ${response.status}`);
    }
}

// Initialize MCP session
sendRequest({
    jsonrpc: '2.0',
    id: 1,
    method: 'initialize',
    params: {
        protocolVersion: '2025-03-26',
        capabilities: {},
        clientInfo: {
            name: 'web-client',
            version: '1.0.0'
        }
    }
});
```

### Python Client

```python
import httpx
import json
import asyncio
from typing import AsyncIterator

async def connect_to_mcp_bridge(url: str):
    """Connect to MCP translate bridge via SSE."""
    message_endpoint = None

    async with httpx.AsyncClient() as client:
        # Connect to SSE stream
        async with client.stream('GET', f'{url}/sse') as response:
            async for line in response.aiter_lines():
                if line.startswith('event: endpoint'):
                    # Next line contains the data
                    continue
                elif line.startswith('data: '):
                    data = line[6:]  # Remove 'data: ' prefix

                    if message_endpoint is None:
                        # First data is the endpoint URL
                        message_endpoint = data
                        print(f'Message endpoint: {message_endpoint}')

                        # Send initialization
                        await send_request(
                            client,
                            message_endpoint,
                            {
                                'jsonrpc': '2.0',
                                'id': 1,
                                'method': 'initialize',
                                'params': {
                                    'protocolVersion': '2025-03-26',
                                    'capabilities': {},
                                    'clientInfo': {
                                        'name': 'python-client',
                                        'version': '1.0.0'
                                    }
                                }
                            }
                        )
                    else:
                        # Parse JSON-RPC response
                        try:
                            response_data = json.loads(data)
                            print(f'MCP Response: {response_data}')
                        except json.JSONDecodeError:
                            pass  # Might be keepalive

async def send_request(client: httpx.AsyncClient, endpoint: str, request: dict):
    """Send JSON-RPC request to message endpoint."""
    response = await client.post(
        endpoint,
        json=request,
        headers={'Content-Type': 'application/json'}
    )
    response.raise_for_status()

# Usage
asyncio.run(connect_to_mcp_bridge('http://localhost:9000'))
```

### curl Examples

```bash
# Subscribe to SSE stream and save session ID
SESSION_URL=$(curl -s -N http://localhost:9000/sse | \
    grep "^data: http" | head -1 | cut -d' ' -f2-)

# Initialize MCP session
curl -X POST "$SESSION_URL" \
    -H 'Content-Type: application/json' \
    -d '{
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2025-03-26",
            "capabilities": {},
            "clientInfo": {"name": "curl", "version": "1.0"}
        }
    }'

# List available tools
curl -X POST "$SESSION_URL" \
    -H 'Content-Type: application/json' \
    -d '{"jsonrpc":"2.0","id":2,"method":"tools/list"}'

# Call a tool (example with mcp-server-git)
curl -X POST "$SESSION_URL" \
    -H 'Content-Type: application/json' \
    -d '{
        "jsonrpc": "2.0",
        "id": 3,
        "method": "tools/call",
        "params": {
            "name": "git_status",
            "arguments": {}
        }
    }'
```

## Architecture

### Components

1. **StdIOEndpoint**: Manages subprocess lifecycle and I/O
   - Spawns and manages the stdio subprocess
   - Pumps stdout to internal pub/sub system
   - Forwards stdin from HTTP requests

2. **PubSub**: Simple fan-out message distribution
   - Distributes subprocess output to multiple SSE clients
   - Automatically removes dead/full queues

3. **FastAPI Application**: HTTP/SSE server
   - `/sse` - SSE streaming endpoint
   - `/message` - JSON-RPC message posting endpoint
   - `/healthz` - Health check endpoint

4. **SSEEvent Parser**: Handles SSE protocol
   - Parses incoming SSE events (for SSE→stdio mode)
   - Formats outgoing SSE events (for stdio→SSE mode)

### Data Flow

```
stdio→SSE Mode:
Client → POST /message → stdin → subprocess → stdout → PubSub → SSE → Client

SSE→stdio Mode:
Remote SSE → SSEEvent Parser → stdin → subprocess → stdout → POST /message → Remote
```

## Limitations

### Current Limitations

1. **SSE to stdio mode**: Experimental, limited testing
2. **WebSocket support**: Not yet implemented
3. **Streamable HTTP**: Not yet implemented
4. **Multiple servers**: Each bridge instance handles one server
5. **No clustering**: Single process, no horizontal scaling

### Known Issues

- Windows signal handling may not work properly (graceful shutdown)
- Large message payloads may cause buffering issues
- No automatic reconnection in SSE→stdio mode

## Contributing

The translate module is part of the MCP Gateway project. To contribute:

1. Check existing issues on GitHub
2. Write tests for new functionality
3. Follow the existing code style
4. Update documentation as needed

### Running Tests

```bash
# Run translate-specific tests
pytest tests/unit/mcpgateway/test_translate.py -v

# Run with coverage
pytest tests/unit/mcpgateway/test_translate.py --cov=mcpgateway.translate

# Run all gateway tests
make test
```

## See Also

- [MCP Gateway Documentation](https://docs.mcpgateway.com)
- [MCP Protocol Specification](https://modelcontextprotocol.io)
- [Server-Sent Events (SSE) Specification](https://html.spec.whatwg.org/multipage/server-sent-events.html)
