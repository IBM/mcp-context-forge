#!/bin/bash
# Test script for streamable HTTP MCP server

set -e

echo "=== Test Streamable HTTP MCP Server ==="
echo ""

# Check if server is running
SERVER_URL="http://localhost:9020"
echo "Checking if server is running at $SERVER_URL..."

if ! curl -s -f "$SERVER_URL/health" > /dev/null 2>&1; then
    echo "Server not running. Starting server..."
    echo "Run in another terminal: python -m test_streamable_http_server --transport http --port 9020"
    exit 1
fi

echo "✓ Server is running"
echo ""

# Test initialize
echo "1. Testing initialize endpoint..."
RESPONSE=$(curl -s -X POST "$SERVER_URL/mcp/v1/initialize" \
    -H "Content-Type: application/json" \
    -d '{
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {
                "name": "test-client",
                "version": "1.0.0"
            }
        }
    }')
echo "Response: $RESPONSE"
echo ""

# Test list tools
echo "2. Testing tools/list endpoint..."
RESPONSE=$(curl -s -X POST "$SERVER_URL/mcp/v1/messages" \
    -H "Content-Type: application/json" \
    -d '{
        "jsonrpc": "2.0",
        "id": 2,
        "method": "tools/list",
        "params": {}
    }')
echo "Response: $RESPONSE"
echo ""

# Test echo tool
echo "3. Testing echo tool..."
RESPONSE=$(curl -s -X POST "$SERVER_URL/mcp/v1/messages" \
    -H "Content-Type: application/json" \
    -d '{
        "jsonrpc": "2.0",
        "id": 3,
        "method": "tools/call",
        "params": {
            "name": "echo",
            "arguments": {
                "message": "Hello from streamable HTTP!"
            }
        }
    }')
echo "Response: $RESPONSE"
echo ""

echo "=== All tests completed ==="

