# Developing Your MCP Server

???+ abstract
    This guide walks you through creating a minimal but functional MCP server using Python and the official MCP SDK. You'll build an echo server that demonstrates the key concepts and patterns for MCP development.

    For more information on Development best practices see this [MCP Server Best Practices Guide](./mcp-best-practices.md)

---

## 1. Prerequisites

!!! note "Environment setup"
    Create a new virtual environment for your project to keep dependencies isolated.

```bash title="Create virtual environment"
# Create and manage virtual environments
uv venv mcp-server-example
source mcp-server-example/bin/activate  # Linux/macOS
# mcp-server-example\Scripts\activate   # Windows
```

### 1.1 Install MCP SDK

```bash title="Install MCP SDK"
uv add "mcp[cli]"
# or with pip: pip install "mcp[cli]"
```

### 1.2 Verify Installation

```bash title="Verify MCP installation"
python -c "import mcp; print('MCP SDK installed successfully')"
```

---

## 2. Write a Minimal Echo Server

### 2.1 Basic Server Structure

!!! example "Simple echo server implementation"
    Create `my_echo_server.py` with this minimal implementation:

```python title="my_echo_server.py"
from mcp.server.fastmcp import FastMCP

# Create an MCP server
mcp = FastMCP("my_echo_server", port="8000")

@mcp.tool()
def echo(text: str) -> str:
    """Echo the provided text back to the caller"""
    return text

if __name__ == "__main__":
    mcp.run()  # STDIO mode by default
```

### 2.2 Understanding the Code

!!! info "Code breakdown"

    - **FastMCP**: Main application class that handles MCP protocol
    - **@mcp.tool()**: Decorator that registers the function as an MCP tool
    - **Type hints**: Python type hints define input/output schemas automatically
    - **mcp.run()**: Starts the server (defaults to STDIO transport)

### 2.3 Test STDIO Mode

```bash title="Start server in STDIO mode"
python my_echo_server.py            # waits on stdin/stdout
```

!!! tip "Testing with MCP CLI"
    Use the built-in development tools for easier testing:

```bash title="Test with MCP Inspector"
# Test with the MCP development tools
uv run mcp dev my_echo_server.py
```

---

## 3. Switch to HTTP Transport

### 3.1 Enable HTTP Mode

!!! tip "Streamable HTTP transport"
    Update the main block to use HTTP transport for network accessibility:

```python title="Enable HTTP transport"
if __name__ == "__main__":
    mcp.run(transport="streamable-http")
```

### 3.2 Start HTTP Server

```bash title="Run HTTP server"
python my_echo_server.py            # now at http://localhost:8000/mcp
```

### 3.3 Test HTTP Endpoint

!!! example "Direct HTTP testing"
    Test the server directly with curl:

```bash title="Test HTTP endpoint"
curl -X POST http://localhost:8000/mcp \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","method":"tools/list","id":1}'
```

---

## 4. Register with the Gateway

### 4.1 Server Registration

!!! example "Register your server with the gateway"
    Use the gateway API to register your running server:

```bash title="Register server with gateway"
curl -X POST http://127.0.0.1:4444/gateways \
  -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"name":"my_echo_server","url":"http://127.0.0.1:8000/mcp","transport":"streamablehttp"}'
```

For instructions on registering your server via the UI, please see [Gateway Integration](../using/servers/index.md#gateway-integration).

### 4.2 Verify Registration

```bash title="Check registered gateways"
curl -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN" \
     http://127.0.0.1:4444/gateways
```

!!! success "Expected response"
    You should see your server listed as active:

```json title="Server registration response"
{
  "servers": [
    {
      "name": "my_echo_server",
      "url": "http://127.0.0.1:8000/mcp",
      "status": "active"
    }
  ]
}
```

---

## 5. End-to-End Validation

### 5.1 Test with mcp-cli

!!! example "Test complete workflow"
    Verify the full chain from CLI to gateway to your server:

```bash title="List and call tools"
# List tools to see your echo tool
mcp-cli tools --server gateway

# Call the echo tool
mcp-cli cmd --server gateway \
  --tool echo \
  --tool-args '{"text":"Round-trip success!"}'
```

### 5.2 Test with curl

!!! example "Direct gateway testing"
    Test the gateway RPC endpoint directly:

```bash title="Test via gateway RPC"
curl -X POST http://127.0.0.1:4444/rpc \
  -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","method":"my-echo-server-echo","params":{"text":"Hello!"},"id":1}'
```

### 5.3 Expected Response

!!! success "Validation complete"
    If you see this response, the full path (CLI → Gateway → Echo Server) is working correctly:

```json title="Successful echo response"
{
  "jsonrpc": "2.0",
  "id": 1,
  "result": {
    "content": [
      {
        "type": "text",
        "text": "Hello!"
      }
    ]
  }
}
```

---

## 6. Enhanced Server Features

### 6.1 Multiple Tools

!!! example "Multi-tool server"
    Extend your server with additional functionality:

```python title="Enhanced server with multiple tools"
from mcp.server.fastmcp import FastMCP
import datetime

# Create an MCP server
mcp = FastMCP("my_enhanced_server", port="8000")

@mcp.tool()
def echo(text: str) -> str:
    """Echo the provided text back to the caller"""
    return text

@mcp.tool()
def get_timestamp() -> str:
    """Get the current timestamp"""
    return datetime.datetime.now().isoformat()

@mcp.tool()
def calculate(a: float, b: float, operation: str) -> float:
    """Perform basic math operations: add, subtract, multiply, divide"""
    operations = {
        "add": a + b,
        "subtract": a - b,
        "multiply": a * b,
        "divide": a / b if b != 0 else float('inf')
    }

    if operation not in operations:
        raise ValueError(f"Unknown operation: {operation}")

    return operations[operation]

if __name__ == "__main__":
    mcp.run(transport="streamable-http")
```

!!! info "Update the MCP Server in the Gateway"
    Delete the current Server and register the new Server:

```bash title="Register server with gateway"
curl -X POST http://127.0.0.1:4444/gateways \
  -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"name":"my_echo_server","url":"http://127.0.0.1:8000/mcp","transport":"streamablehttp"}'
```

### 6.2 Structured Output with Pydantic

!!! tip "Rich data structures"
    Use Pydantic models for complex structured responses:

```python title="Structured output server"
from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel, Field
import datetime

mcp = FastMCP("structured_server", port="8000")

class EchoResponse(BaseModel):
    """Response structure for echo tool"""
    original_text: str = Field(description="The original input text")
    echo_text: str = Field(description="The echoed text")
    length: int = Field(description="Length of the text")
    timestamp: str = Field(description="When the echo was processed")

@mcp.tool()
def structured_echo(text: str) -> EchoResponse:
    """Echo with structured response data"""
    return EchoResponse(
        original_text=text,
        echo_text=text,
        length=len(text),
        timestamp=datetime.datetime.now().isoformat()
    )

if __name__ == "__main__":
    mcp.run(transport="streamable-http")
```

### 6.3 Error Handling and Validation

!!! warning "Production considerations"
    Add proper error handling and validation for production use:

```python title="Robust error handling"
from mcp.server.fastmcp import FastMCP
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

mcp = FastMCP("robust_server", port="8000")

@mcp.tool()
def safe_echo(text: str) -> str:
    """Echo with validation and error handling"""
    try:
        # Log the request
        logger.info(f"Processing echo request for text of length {len(text)}")

        # Validate input
        if not text.strip():
            raise ValueError("Text cannot be empty")

        if len(text) > 1000:
            raise ValueError("Text too long (max 1000 characters)")

        # Process and return
        return text

    except Exception as e:
        logger.error(f"Error in safe_echo: {e}")
        raise

if __name__ == "__main__":
    mcp.run(transport="streamable-http")
```

---

## 7. Testing Your Server

### 7.1 Development Testing

!!! tip "Interactive development"
    Use the MCP Inspector for rapid testing and debugging:

```bash title="Development testing with MCP Inspector"
# Use the built-in development tools
uv run mcp dev my_echo_server.py

# Test with dependencies
uv run mcp dev my_echo_server.py --with pandas --with numpy
```

### 7.2 Unit Testing

!!! note "Testing considerations"
    For unit testing, focus on business logic rather than MCP protocol:

```python title="test_echo_server.py"
import pytest
from my_echo_server import mcp

@pytest.mark.asyncio
async def test_echo_tool():
    """Test the echo tool directly"""
    # This would require setting up the MCP server context
    # For integration testing, use the MCP Inspector instead
    pass

def test_basic_functionality():
    """Test basic server setup"""
    assert mcp.name == "my_echo_server"
    # Add more server validation tests
```

### 7.3 Integration Testing

!!! example "End-to-end testing"
    Test the complete workflow with a simple script:

```bash title="Integration test script"
#!/bin/bash

# Start server in background
python my_echo_server.py &
SERVER_PID=$!

# Wait for server to start
sleep 2

# Test server registration
echo "Testing server registration..."
curl -X POST http://127.0.0.1:4444/servers \
  -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"name":"test_echo_server","url":"http://127.0.0.1:8000/mcp"}'

# Test tool call
echo "Testing tool call..."
mcp-cli cmd --server gateway \
  --tool echo \
  --tool-args '{"text":"Integration test success!"}'

# Cleanup
kill $SERVER_PID
```

---

## 8. Deployment Considerations

### 8.1 Production Configuration

!!! tip "Environment-based configuration"
    Use environment variables for production settings:

```python title="Production-ready server"
import os
from mcp.server.fastmcp import FastMCP

# Configuration from environment
SERVER_NAME = os.getenv("MCP_SERVER_NAME", "my_echo_server")
PORT = os.getenv("MCP_SERVER_PORT", "8000")
DEBUG_MODE = os.getenv("MCP_DEBUG", "false").lower() == "true"

mcp = FastMCP(SERVER_NAME, port=PORT)

@mcp.tool()
def echo(text: str) -> str:
    """Echo the provided text"""
    if DEBUG_MODE:
        print(f"Debug: Processing text of length {len(text)}")
    return text

if __name__ == "__main__":
    transport = os.getenv("MCP_TRANSPORT", "streamable-http")
    print(f"Starting {SERVER_NAME} with {transport} transport")
    mcp.run(transport=transport)
```

### 8.2 Container (Podman/Docker) Support

!!! example "Containerization"
    Package your server for easy deployment by creating a Containerfile:

```dockerfile title="Dockerfile"
FROM python:3.11-slim

WORKDIR /app

# Install uv
RUN pip install uv

# Copy requirements
COPY pyproject.toml .
RUN uv pip install --system -e .

COPY my_echo_server.py .

EXPOSE 8000

CMD ["python", "my_echo_server.py"]
```

```toml title="pyproject.toml"
[project]
name = "my-echo-server"
version = "0.1.0"
dependencies = [
    "mcp[cli]",
]

[project.scripts]
echo-server = "my_echo_server:main"
```

---

## 9. Advanced Features

### 9.1 Resources

!!! info "Exposing data via resources"
    Resources provide contextual data to LLMs:

```python title="Server with resources"
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("resource_server", port="8000")

@mcp.resource("config://settings")
def get_settings() -> str:
    """Provide server configuration as a resource"""
    return """{
  "server_name": "my_echo_server",
  "version": "1.0.0",
  "features": ["echo", "timestamp"]
}"""

@mcp.resource("status://health")
def get_health() -> str:
    """Provide server health status"""
    return "Server is running normally"

@mcp.tool()
def echo(text: str) -> str:
    """Echo the provided text"""
    return text

if __name__ == "__main__":
    mcp.run(transport="streamable-http")
```

### 9.2 Context and Logging

!!! tip "Enhanced observability"
    Use context for logging and progress tracking:

```python title="Server with context and logging"
from mcp.server.fastmcp import FastMCP, Context

mcp = FastMCP("context_server", port="8000")

@mcp.tool()
async def echo_with_logging(text: str, ctx: Context) -> str:
    """Echo with context logging"""
    await ctx.info(f"Processing echo request for: {text[:50]}...")
    await ctx.debug(f"Full text length: {len(text)}")

    result = text

    await ctx.info("Echo completed successfully")
    return result

if __name__ == "__main__":
    mcp.run(transport="streamable-http")
```

---

## 10. Installation and Distribution

### 10.1 Install in Claude Desktop

!!! success "Claude Desktop integration"
    Install your server directly in Claude Desktop:

```bash title="Claude Desktop installation"
# Install your server in Claude Desktop
uv run mcp install my_echo_server.py --name "My Echo Server"

# With environment variables
uv run mcp install my_echo_server.py -v DEBUG=true -v LOG_LEVEL=info
```

### 10.2 Package Distribution

!!! tip "Creating distributable packages"
    Build packages for easy distribution:

```bash title="Package building and distribution"
# Build distributable package
uv build

# Install from package
pip install dist/my_echo_server-0.1.0-py3-none-any.whl
```

---

## 11. Troubleshooting

### 11.1 Common Issues

!!! warning "Import errors"
    ```
    ModuleNotFoundError: No module named 'mcp'
    ```
    **Solution:** Install MCP SDK: `uv add "mcp[cli]"`

!!! warning "Port conflicts"
    ```
    OSError: [Errno 48] Address already in use
    ```
    **Solution:** The default port is 8000. Change it or kill the process using the port

!!! warning "Registration failures"
    ```
    Error registering server with gateway
    ```
    **Solution:** Ensure gateway is running, listening on the correct port and the server URL is correct (`/mcp` endpoint)

### 11.2 Debugging Tips

!!! tip "Debugging strategies"
    Use these approaches for troubleshooting:

```bash title="Debug your server"
# Use the MCP Inspector for interactive debugging
uv run mcp dev my_echo_server.py

# Enable debug logging
MCP_DEBUG=true python my_echo_server.py
```

---
