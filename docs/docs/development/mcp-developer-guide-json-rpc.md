# MCP JSON RPC Guide

This comprehensive guide demonstrates how to interact with MCP (Model Context Protocol) servers using raw JSON-RPC commands via `curl` or through STDIO. This is essential for developers who want to understand the MCP protocol at a low level, integrate MCP into custom applications, or debug MCP implementations.

## Overview

The Model Context Protocol (MCP) is a standardized protocol for connecting language models to various data sources and tools. MCP Gateway acts as a federation layer that aggregates multiple MCP servers and provides unified access through various transport mechanisms.

## Prerequisites

Before starting, ensure you have:

- MCP Gateway server running (typically on `http://localhost:4444`)
- `curl` command-line tool installed
- `jq` for JSON formatting (optional but recommended)
- Basic understanding of JSON-RPC 2.0 protocol

## Authentication Setup

MCP Gateway uses JWT Bearer tokens for authentication. Generate a token before making any requests:

```bash
# Generate authentication token
export MCPGATEWAY_BEARER_TOKEN=$(python3 -m mcpgateway.utils.create_jwt_token \
    --username admin@example.com --exp 10080 --secret my-test-key)

# Verify the token was generated
echo "Token: ${MCPGATEWAY_BEARER_TOKEN}"

# Test connectivity
curl -s -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN" \
     http://localhost:4444/health | jq
```

**Expected health response:**
```json
{
  "status": "healthy"
}
```

## Understanding MCP Protocol Flow

MCP follows a specific initialization sequence that must be followed for proper communication:

1. **Initialize** - Establish protocol version and capabilities
2. **Initialized Notification** - Confirm initialization completion
3. **Protocol Operations** - List and call tools, read resources, get prompts

### Transport Methods

MCP Gateway supports multiple transport methods:

- **HTTP JSON-RPC** (`/rpc`) - Standard JSON-RPC 2.0 over HTTP
- **Server-Sent Events** (`/sse`) - Real-time streaming communication
- **Protocol Endpoints** (`/protocol/*`) - Specialized endpoints for specific operations

## MCP Protocol Implementation

### 1. Initialize the Connection

Every MCP session must begin with proper initialization:

#### Method 1: Using Protocol Endpoint (Recommended)

```bash
# Initialize using dedicated protocol endpoint
curl -X POST -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN" \
     -H "Content-Type: application/json" \
     -d '{
           "protocol_version": "2025-03-26",
           "capabilities": {
             "tools": {},
             "resources": {},
             "prompts": {}
           },
           "client_info": {
             "name": "cli-developer",
             "version": "1.0.0"
           }
         }' \
     http://localhost:4444/protocol/initialize | jq
```

#### Method 2: Using JSON-RPC Endpoint

```bash
# Initialize using JSON-RPC endpoint
curl -X POST -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN" \
     -H "Content-Type: application/json" \
     -d '{
           "jsonrpc": "2.0",
           "id": 1,
           "method": "initialize",
           "params": {
             "protocolVersion": "2025-03-26",
             "capabilities": {
               "tools": {},
               "resources": {},
               "prompts": {}
             },
             "clientInfo": {
               "name": "cli-developer",
               "version": "1.0.0"
             }
           }
         }' \
     http://localhost:4444/rpc | jq
```

**Expected Response:**
```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "result": {
    "protocolVersion": "2025-03-26",
    "capabilities": {
      "prompts": {"listChanged": true},
      "resources": {"subscribe": true, "listChanged": true},
      "tools": {"listChanged": true},
      "logging": {}
    },
    "serverInfo": {
      "name": "MCP_Gateway",
      "version": "0.9.0"
    },
    "instructions": "MCP Gateway providing federated tools, resources and prompts. Use /admin interface for configuration."
  }
}
```

### 2. Send Initialized Notification

After successful initialization, send the initialized notification:

```bash
# Send initialized notification
curl -X POST -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN" \
     -H "Content-Type: application/json" \
     -d '{
           "jsonrpc": "2.0",
           "method": "notifications/initialized",
           "params": {}
         }' \
     http://localhost:4444/rpc
```

## Working with Tools

### List Available Tools

```bash
# List all available tools
curl -X POST -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN" \
     -H "Content-Type: application/json" \
     -d '{
           "jsonrpc": "2.0",
           "id": 2,
           "method": "tools/list",
           "params": {}
         }' \
     http://localhost:4444/rpc | jq
```

**Response with no tools:**
```json
{
  "jsonrpc": "2.0",
  "id": 2,
  "result": {
    "tools": []
  }
}
```

**Response with tools available (e.g. after registering the Fast Time Server example):**
```json
{
  "jsonrpc": "2.0",
  "id": 2,
  "result": {
    "tools": [
      {
        "name": "get_system_time",
        "description": "Get current system time in specified timezone",
        "inputSchema": {
          "type": "object",
          "properties": {
            "timezone": {
              "type": "string",
              "description": "IANA timezone name (e.g., 'America/New_York', 'Europe/London'). Defaults to UTC if not specified."
            }
          }
        }
      },
      {
        "name": "convert_time",
        "description": "Convert time between different timezones",
        "inputSchema": {
          "type": "object",
          "properties": {
            "time": {
              "type": "string",
              "description": "Time to convert in RFC3339 format"
            },
            "source_timezone": {
              "type": "string",
              "description": "Source IANA timezone name"
            },
            "target_timezone": {
              "type": "string",
              "description": "Target IANA timezone name"
            }
          },
          "required": ["time", "source_timezone", "target_timezone"]
        }
      }
    ]
  }
}
```

### Call a Tool

```bash
# Call a tool with arguments
curl -X POST -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN" \
     -H "Content-Type: application/json" \
     -d '{
           "jsonrpc": "2.0",
           "id": 3,
           "method": "tools/call",
           "params": {
             "name": "get_system_time",
             "arguments": {
               "timezone": "Europe/Dublin"
             }
           }
         }' \
     http://localhost:4444/rpc | jq
```

**Expected Response:**
```json
{
  "jsonrpc": "2.0",
  "id": 3,
  "result": {
    "content": [
      {
        "type": "text",
        "text": "{\n  \"timezone\": \"Europe/Dublin\",\n  \"datetime\": \"2025-01-15T16:30:45+00:00\",\n  \"is_dst\": false\n}"
      }
    ],
    "isError": false
  }
}
```

### Tool Call Examples

**Convert Time Between Timezones:**
```bash
curl -X POST -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN" \
     -H "Content-Type: application/json" \
     -d '{
           "jsonrpc": "2.0",
           "id": 4,
           "method": "tools/call",
           "params": {
             "name": "convert_time",
             "arguments": {
               "time": "2025-01-15T10:00:00Z",
               "source_timezone": "UTC",
               "target_timezone": "America/New_York"
             }
           }
         }' \
     http://localhost:4444/rpc | jq
```

## Working with Resources

### List Available Resources

```bash
# List all available resources
curl -X POST -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN" \
     -H "Content-Type: application/json" \
     -d '{
           "jsonrpc": "2.0",
           "id": 5,
           "method": "resources/list",
           "params": {}
         }' \
     http://localhost:4444/rpc | jq
```

**Expected Response:**
```json
{
  "jsonrpc": "2.0",
  "id": 5,
  "result": {
    "resources": [
      {
        "uri": "timezone://info",
        "name": "Timezone Information",
        "description": "Comprehensive timezone information including offsets, DST status, and major cities",
        "mimeType": "application/json"
      },
      {
        "uri": "time://current/world",
        "name": "World Clock",
        "description": "Current time in major cities around the world",
        "mimeType": "application/json"
      }
    ]
  }
}
```

### Read a Specific Resource

```bash
# Read a specific resource
curl -X POST -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN" \
     -H "Content-Type: application/json" \
     -d '{
           "jsonrpc": "2.0",
           "id": 6,
           "method": "resources/read",
           "params": {
             "uri": "timezone://info"
           }
         }' \
     http://localhost:4444/rpc | jq
```

## Working with Prompts

### List Available Prompts

```bash
# List all available prompts
curl -X POST -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN" \
     -H "Content-Type: application/json" \
     -d '{
           "jsonrpc": "2.0",
           "id": 7,
           "method": "prompts/list",
           "params": {}
         }' \
     http://localhost:4444/rpc | jq
```

### Get a Specific Prompt

```bash
# Get a prompt with arguments
curl -X POST -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN" \
     -H "Content-Type: application/json" \
     -d '{
           "jsonrpc": "2.0",
           "id": 8,
           "method": "prompts/get",
           "params": {
             "name": "compare_timezones",
             "arguments": {
               "timezones": "UTC,America/New_York,Europe/London",
               "reference_time": "2025-01-15T12:00:00Z"
             }
           }
         }' \
     http://localhost:4444/rpc | jq
```

## Server-Sent Events (SSE) Transport

For real-time communication and better handling of long-running operations, use the SSE transport:

### Establishing SSE Connection

```bash
# Terminal 1: Start SSE connection (keeps connection open)
curl -N -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN" \
     http://localhost:4444/sse
```

The first event emitted by the stream is an `endpoint` payload with the per-session POST URL:

```text
event: endpoint
data: http://localhost:4444/message?session_id=7bfbf2a4-...
```

Copy that value (it changes each run) into an environment variable used by your second terminal:

```bash
export MCP_SSE_ENDPOINT="http://localhost:4444/message?session_id=7bfbf2a4-..."
```

### Sending Messages via SSE

Now send JSON-RPC messages to the captured endpoint:

```bash
# Initialize via SSE
curl -X POST -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN" \
     -H "Content-Type: application/json" \
     -d '{
           "jsonrpc": "2.0",
           "id": 1,
           "method": "initialize",
           "params": {
             "protocolVersion": "2025-03-26",
             "capabilities": {},
             "clientInfo": {"name": "sse-client", "version": "1.0"}
           }
         }' \
     "$MCP_SSE_ENDPOINT"

# List tools via SSE
curl -X POST -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN" \
     -H "Content-Type: application/json" \
     -d '{
           "jsonrpc": "2.0",
           "id": 2,
           "method": "tools/list"
         }' \
     "$MCP_SSE_ENDPOINT"

# Call a tool via SSE (after registering one)
curl -X POST -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN" \
     -H "Content-Type: application/json" \
     -d '{
           "jsonrpc": "2.0",
           "id": 3,
           "method": "tools/call",
           "params": {
             "name": "get_system_time",
             "arguments": {"timezone": "Asia/Tokyo"}
           }
         }' \
     "$MCP_SSE_ENDPOINT"
```

## Utility Operations

### Ping the Server

```bash
# Test server responsiveness
curl -X POST -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN" \
     -H "Content-Type: application/json" \
     -d '{
           "jsonrpc": "2.0",
           "id": 9,
           "method": "ping"
         }' \
     http://localhost:4444/rpc | jq
```

**Expected Response:**
```json
{
  "jsonrpc": "2.0",
  "id": 9,
  "result": {}
}
```

## STDIO Transport

For command-line integration and desktop client compatibility, use the STDIO wrapper:

### Setting Up STDIO Environment

```bash
# Configure environment variables
export MCP_AUTH="Bearer ${MCPGATEWAY_BEARER_TOKEN}"
export MCP_SERVER_URL="http://localhost:4444/servers/your-server-id"
export MCP_TOOL_CALL_TIMEOUT=120
export MCP_WRAPPER_LOG_LEVEL=INFO

# Run the wrapper
python3 -m mcpgateway.wrapper
```

### STDIO Communication

Feed multiple JSON-RPC messages in one stream (the wrapper exits when STDIN closes):

```bash
python3 -m mcpgateway.wrapper <<'EOF'
{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-03-26","capabilities":{},"clientInfo":{"name":"stdio-client","version":"1.0"}}}
{"jsonrpc":"2.0","method":"notifications/initialized","params":{}}
{"jsonrpc":"2.0","id":2,"method":"tools/list"}
EOF
```

Run it interactively (without the here-doc) if you prefer to type requests by hand.

## Complete Session Examples

### HTTP JSON-RPC Complete Session

```bash
#!/bin/bash
# Complete MCP Gateway session via HTTP JSON-RPC

# Setup
export MCPGATEWAY_BEARER_TOKEN=$(python3 -m mcpgateway.utils.create_jwt_token \
    --username admin@example.com --exp 10080 --secret my-test-key)

# Function to make authenticated JSON-RPC calls
make_call() {
    curl -s -X POST -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN" \
         -H "Content-Type: application/json" \
         -d "$1" \
         http://localhost:4444/rpc | jq
}

# Function for protocol-specific calls
make_protocol_call() {
    curl -s -X POST -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN" \
         -H "Content-Type: application/json" \
         -d "$1" \
         http://localhost:4444/protocol/initialize | jq
}

echo "=== MCP Gateway Complete Session ==="

# 1. Test connectivity
echo "=== Testing Connectivity ==="
curl -s -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN" \
     http://localhost:4444/health | jq

# 2. Initialize (using protocol endpoint for reliability)
echo "=== Initializing Session ==="
make_protocol_call '{
  "protocol_version": "2025-03-26",
  "capabilities": {
    "tools": {},
    "resources": {},
    "prompts": {}
  },
  "client_info": {
    "name": "complete-session-demo",
    "version": "1.0"
  }
}'

# 3. Send initialized notification
echo "=== Sending Initialized Notification ==="
make_call '{
  "jsonrpc": "2.0",
  "method": "notifications/initialized",
  "params": {}
}'

# 4. List available tools
echo "=== Listing Available Tools ==="
make_call '{
  "jsonrpc": "2.0",
  "id": 2,
  "method": "tools/list",
  "params": {}
}'

# 5. List available resources
echo "=== Listing Available Resources ==="
make_call '{
  "jsonrpc": "2.0",
  "id": 3,
  "method": "resources/list",
  "params": {}
}'

# 6. List available prompts
echo "=== Listing Available Prompts ==="
make_call '{
  "jsonrpc": "2.0",
  "id": 4,
  "method": "prompts/list",
  "params": {}
}'

# 7. Call a tool (if available)
echo "=== Calling Tool (get_system_time) ==="
make_call '{
  "jsonrpc": "2.0",
  "id": 5,
  "method": "tools/call",
  "params": {
    "name": "get_system_time",
    "arguments": {
      "timezone": "UTC"
    }
  }
}'

# 8. Read a resource (if available)
echo "=== Reading Resource ==="
make_call '{
  "jsonrpc": "2.0",
  "id": 6,
  "method": "resources/read",
  "params": {
    "uri": "timezone://info"
  }
}'

# 9. Test ping
echo "=== Testing Ping ==="
make_call '{
  "jsonrpc": "2.0",
  "id": 7,
  "method": "ping"
}'

echo "=== Session Complete ==="
```

### SSE Complete Session

```bash
#!/bin/bash
# Complete MCP Gateway session via Server-Sent Events

# Setup
export MCPGATEWAY_BEARER_TOKEN=$(python3 -m mcpgateway.utils.create_jwt_token \
    --username admin@example.com --exp 10080 --secret my-test-key)

echo "=== Starting SSE Session ==="

# Start SSE connection in background
curl -N -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN" \
     http://localhost:4444/sse &
SSE_PID=$!

# Give SSE time to connect
sleep 2

# Function to send messages via SSE
send_sse_message() {
    curl -s -X POST -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN" \
         -H "Content-Type: application/json" \
         -d "$1" \
         http://localhost:4444/message
    sleep 1  # Allow time for response
}

echo "=== Sending Initialize Message ==="
send_sse_message '{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "initialize",
  "params": {
    "protocolVersion": "2025-03-26",
    "capabilities": {},
    "clientInfo": {
      "name": "sse-session-demo",
      "version": "1.0"
    }
  }
}'

echo "=== Sending Initialized Notification ==="
send_sse_message '{
  "jsonrpc": "2.0",
  "method": "notifications/initialized",
  "params": {}
}'

echo "=== Listing Tools ==="
send_sse_message '{
  "jsonrpc": "2.0",
  "id": 2,
  "method": "tools/list"
}'

echo "=== Calling Tool ==="
send_sse_message '{
  "jsonrpc": "2.0",
  "id": 3,
  "method": "tools/call",
  "params": {
    "name": "get_system_time",
    "arguments": {
      "timezone": "Europe/Dublin"
    }
  }
}'

echo "=== Testing Ping ==="
send_sse_message '{
  "jsonrpc": "2.0",
  "id": 4,
  "method": "ping"
}'

# Allow time for final responses
sleep 3

# Clean up
kill $SSE_PID 2>/dev/null
echo "=== SSE Session Complete ==="
```

## Error Handling and Troubleshooting

### Common Error Responses

MCP follows JSON-RPC 2.0 error handling standards:

**Authentication Error:**
```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "error": {
    "code": -32000,
    "message": "Authentication required",
    "data": "Missing or invalid authorization header"
  }
}
```

**Invalid Parameters:**
```json
{
  "jsonrpc": "2.0",
  "id": 2,
  "error": {
    "code": -32602,
    "message": "Invalid params",
    "data": "Missing required parameter: name"
  }
}
```

**Method Not Found:**
```json
{
  "jsonrpc": "2.0",
  "id": 3,
  "error": {
    "code": -32601,
    "message": "Method not found",
    "data": "Unknown method: invalid_method"
  }
}
```

### Standard JSON-RPC Error Codes

| Code | Meaning | Description |
|------|---------|-------------|
| -32700 | Parse error | Invalid JSON was received |
| -32600 | Invalid Request | The JSON sent is not a valid Request object |
| -32601 | Method not found | The method does not exist / is not available |
| -32602 | Invalid params | Invalid method parameter(s) |
| -32603 | Internal error | Internal JSON-RPC error |
| -32000 to -32099 | Server error | Reserved for implementation-defined server-errors |

!!! note
    For parse errors (-32700), the response `id` is null per JSON-RPC. Some SDKs use
    a placeholder like `"server-error"`; clients should not rely on an ID for parse
    errors.

### Troubleshooting Common Issues

#### 1. Authentication Problems

**Symptoms:**

- 401 Unauthorized responses
- "Authentication required" errors

**Solutions:**
```bash
# Verify token generation
export MCPGATEWAY_BEARER_TOKEN=$(python3 -m mcpgateway.utils.create_jwt_token \
    --username admin@example.com --exp 10080 --secret my-test-key)

# Test token validity
curl -s -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN" \
     http://localhost:4444/health

# Check token expiration
echo $MCPGATEWAY_BEARER_TOKEN | cut -d'.' -f2 | base64 -d | jq .exp
```

#### 2. Connection Issues

**Symptoms:**

- Connection refused errors
- Timeout errors

**Solutions:**
```bash
# Check if MCP Gateway is running
curl -f http://localhost:4444/health || echo "Gateway not running"

# Check port availability
lsof -i :4444

# Verify network connectivity
ping localhost
```

#### 3. Initialize Method Errors

**Known Issue:** `'coroutine' object has no attribute 'model_dump'`

**Workaround:**
```bash
# Use protocol endpoint instead of /rpc for initialization
curl -X POST -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN" \
     -H "Content-Type: application/json" \
     -d '{
           "protocol_version": "2025-03-26",
           "capabilities": {},
           "client_info": {"name": "workaround", "version": "1.0"}
         }' \
     http://localhost:4444/protocol/initialize
```

#### 4. Empty Tool/Resource Lists

**Symptoms:**

- `tools/list` returns empty array
- `resources/list` returns empty array

**Solutions:**
```bash
# Check if MCP servers are registered
curl -s -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN" \
     http://localhost:4444/gateways | jq

# Verify virtual servers are configured
curl -s -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN" \
     http://localhost:4444/servers | jq

# Check individual server status
curl -s -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN" \
     http://localhost:4444/servers/{server-id} | jq
```

#### 5. Tool Call Failures

**Symptoms:**

- Tool calls return `isError: true`
- Timeout errors

**Solutions:**
```bash
# Check tool schema and required parameters
curl -X POST -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN" \
     -H "Content-Type: application/json" \
     -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}' \
     http://localhost:4444/rpc | jq '.result.tools[0].inputSchema'

# Verify argument types match schema
# Increase timeout for long-running tools
export MCP_TOOL_CALL_TIMEOUT=300
```

## Integration Examples

### Python Client Implementation

```python
import json
import requests
import subprocess
from typing import Dict, Any, Optional

class MCPGatewayClient:
    def __init__(self, base_url: str = "http://localhost:4444", auth_token: Optional[str] = None):
        self.base_url = base_url
        self.session = requests.Session()
        self.request_id = 0

        if auth_token:
            self.session.headers.update({
                "Authorization": f"Bearer {auth_token}",
                "Content-Type": "application/json"
            })

    def _make_request(self, method: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Make a JSON-RPC request to the gateway."""
        self.request_id += 1

        payload = {
            "jsonrpc": "2.0",
            "id": self.request_id,
            "method": method
        }

        if params is not None:
            payload["params"] = params

        response = self.session.post(f"{self.base_url}/rpc", json=payload)
        response.raise_for_status()

        return response.json()

    def initialize(self) -> Dict[str, Any]:
        """Initialize the MCP session."""
        # Use protocol endpoint for reliable initialization
        payload = {
            "protocol_version": "2025-03-26",
            "capabilities": {
                "tools": {},
                "resources": {},
                "prompts": {}
            },
            "client_info": {
                "name": "python-mcp-client",
                "version": "1.0.0"
            }
        }

        response = self.session.post(f"{self.base_url}/protocol/initialize", json=payload)
        response.raise_for_status()

        # Send initialized notification
        self._make_request("notifications/initialized", {})

        return response.json()

    def list_tools(self) -> Dict[str, Any]:
        """List available tools."""
        return self._make_request("tools/list")

    def call_tool(self, name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Call a specific tool with arguments."""
        return self._make_request("tools/call", {
            "name": name,
            "arguments": arguments
        })

    def list_resources(self) -> Dict[str, Any]:
        """List available resources."""
        return self._make_request("resources/list")

    def read_resource(self, uri: str) -> Dict[str, Any]:
        """Read a specific resource."""
        return self._make_request("resources/read", {"uri": uri})

    def list_prompts(self) -> Dict[str, Any]:
        """List available prompts."""
        return self._make_request("prompts/list")

    def get_prompt(self, name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Get a specific prompt with arguments."""
        return self._make_request("prompts/get", {
            "name": name,
            "arguments": arguments
        })

    def ping(self) -> Dict[str, Any]:
        """Test server connectivity."""
        return self._make_request("ping")

# Usage example
def main():
    # Generate authentication token
    result = subprocess.run([
        "python3", "-m", "mcpgateway.utils.create_jwt_token",
        "--username", "admin", "--exp", "10080", "--secret", "my-test-key"
    ], capture_output=True, text=True)

    if result.returncode != 0:
        raise Exception(f"Failed to generate token: {result.stderr}")

    auth_token = result.stdout.strip()

    # Create client and initialize
    client = MCPGatewayClient(auth_token=auth_token)

    try:
        # Initialize session
        init_result = client.initialize()
        print("Initialized:", json.dumps(init_result, indent=2))

        # List available tools
        tools = client.list_tools()
        print("Tools:", json.dumps(tools, indent=2))

        # Call a tool if available
        if tools["result"]["tools"]:
            tool_name = tools["result"]["tools"][0]["name"]
            result = client.call_tool(tool_name, {"timezone": "UTC"})
            print(f"Tool result:", json.dumps(result, indent=2))

        # Test ping
        ping_result = client.ping()
        print("Ping:", json.dumps(ping_result, indent=2))

    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    main()
```

### Node.js Client Implementation

```javascript
const axios = require('axios');
const { execSync } = require('child_process');

class MCPGatewayClient {
    constructor(baseUrl = 'http://localhost:4444', authToken = null) {
        this.baseUrl = baseUrl;
        this.requestId = 0;

        this.axiosInstance = axios.create({
            baseURL: baseUrl,
            headers: {
                'Content-Type': 'application/json',
                ...(authToken && { 'Authorization': `Bearer ${authToken}` })
            }
        });
    }

    async makeRequest(method, params = null) {
        this.requestId++;

        const payload = {
            jsonrpc: '2.0',
            id: this.requestId,
            method
        };

        if (params !== null) {
            payload.params = params;
        }

        const response = await this.axiosInstance.post('/rpc', payload);
        return response.data;
    }

    async initialize() {
        // Use protocol endpoint for reliable initialization
        const payload = {
            protocol_version: '2025-03-26',
            capabilities: {
                tools: {},
                resources: {},
                prompts: {}
            },
            client_info: {
                name: 'nodejs-mcp-client',
                version: '1.0.0'
            }
        };

        const response = await this.axiosInstance.post('/protocol/initialize', payload);

        // Send initialized notification
        await this.makeRequest('notifications/initialized', {});

        return response.data;
    }

    async listTools() {
        return this.makeRequest('tools/list');
    }

    async callTool(name, arguments) {
        return this.makeRequest('tools/call', { name, arguments });
    }

    async listResources() {
        return this.makeRequest('resources/list');
    }

    async readResource(uri) {
        return this.makeRequest('resources/read', { uri });
    }

    async listPrompts() {
        return this.makeRequest('prompts/list');
    }

    async getPrompt(name, arguments) {
        return this.makeRequest('prompts/get', { name, arguments });
    }

    async ping() {
        return this.makeRequest('ping');
    }
}

// Usage example
async function main() {
    try {
        // Generate authentication token
        const authToken = execSync(
            'python3 -m mcpgateway.utils.create_jwt_token --username admin@example.com --exp 10080 --secret my-test-key',
            { encoding: 'utf8' }
        ).trim();

        // Create client and initialize
        const client = new MCPGatewayClient('http://localhost:4444', authToken);

        // Initialize session
        const initResult = await client.initialize();
        console.log('Initialized:', JSON.stringify(initResult, null, 2));

        // List available tools
        const tools = await client.listTools();
        console.log('Tools:', JSON.stringify(tools, null, 2));

        // Call a tool if available
        if (tools.result.tools.length > 0) {
            const toolName = tools.result.tools[0].name;
            const result = await client.callTool(toolName, { timezone: 'UTC' });
            console.log('Tool result:', JSON.stringify(result, null, 2));
        }

        // Test ping
        const pingResult = await client.ping();
        console.log('Ping:', JSON.stringify(pingResult, null, 2));

    } catch (error) {
        console.error('Error:', error.message);
        if (error.response) {
            console.error('Response:', error.response.data);
        }
    }
}

if (require.main === module) {
    main();
}

module.exports = MCPGatewayClient;
```

## Best Practices

### 1. Session Management

- Always initialize before making other requests
- Send the initialized notification after successful initialization
- Use unique request IDs for correlation
- Handle errors gracefully and implement retry logic

### 2. Authentication

- Store tokens securely and refresh them before expiration
- Use environment variables for token management
- Implement proper token validation and error handling

### 3. Transport Selection

- Use HTTP JSON-RPC for simple request-response patterns
- Use SSE for real-time communication and long-running operations
- Use STDIO for desktop client integration

### 4. Error Handling

- Check for JSON-RPC error objects in all responses
- Implement appropriate retry strategies for transient errors
- Log errors with sufficient context for debugging

### 5. Performance Optimization

- Reuse HTTP connections when possible
- Implement proper timeout configurations
- Cache tool schemas and capabilities to reduce redundant calls

## Further Reading

- [MCP Protocol Specification](https://modelcontextprotocol.io/)
- [JSON-RPC 2.0 Specification](https://www.jsonrpc.org/specification)
- [MCP Gateway Documentation](https://ibm.github.io/mcp-context-forge/)
- [MCP Gateway Admin UI Guide](../manage/index.md)
- [MCP Gateway Wrapper Documentation](../using/mcpgateway-wrapper.md)
