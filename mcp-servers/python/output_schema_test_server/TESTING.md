# Testing Output Schema Support

This document provides step-by-step instructions for testing the `outputSchema` field implementation using the output-schema-test-server.

## Setup

1. **Install the server**:
   ```bash
   cd mcp-servers/python/output_schema_test_server
   make install
   ```

2. **Start ContextForge** (in separate terminal):
   ```bash
   cd /home/cmihai/github/mcp-context-forge
   make dev
   ```

## Test Method 1: Using mcpgateway.translate (Recommended)

This method is easiest for testing as it wraps the stdio server in an SSE endpoint.

### 1. Start the test server with translate

```bash
cd mcp-servers/python/output_schema_test_server
python3 -m mcpgateway.translate \
  --stdio "python3 -m output_schema_test_server.server_fastmcp" \
  --host 0.0.0.0 \
  --port 9100 \
  --expose-sse
```

### 2. Register with ContextForge

```bash
curl -X POST http://localhost:4444/gateways \
  -H "Content-Type: application/json" \
  -d '{
    "name": "output-schema-test",
    "slug": "output-schema-test",
    "url": "http://localhost:9100/sse",
    "description": "Test server for output schemas",
    "transport": "SSE",
    "auth_type": "none"
  }'
```

### 3. List tools from gateway

```bash
# Should show outputSchema field
curl -s http://localhost:4444/tools | jq '.[] | select(.name | contains("add_numbers")) | {name, inputSchema, outputSchema}'
```

**Expected output**:
```json
{
  "name": "add_numbers",
  "inputSchema": {
    "type": "object",
    "properties": {
      "a": {
        "type": "number",
        "description": "First number"
      },
      "b": {
        "type": "number",
        "description": "Second number"
      }
    },
    "required": ["a", "b"]
  },
  "outputSchema": {
    "type": "object",
    "properties": {
      "result": {
        "type": "number",
        "description": "The calculated result"
      },
      "operation": {
        "type": "string",
        "description": "The operation performed"
      },
      "operands": {
        "type": "array",
        "items": {
          "type": "number"
        },
        "description": "The operands used"
      },
      "success": {
        "type": "boolean",
        "description": "Whether the calculation succeeded"
      }
    },
    "required": ["result", "operation", "operands", "success"]
  }
}
```

### 4. Invoke a tool

```bash
curl -X POST http://localhost:4444/tools/invoke \
  -H "Content-Type: application/json" \
  -d '{
    "name": "add_numbers",
    "arguments": {"a": 10, "b": 5}
  }' | jq
```

**Expected output**:
```json
{
  "content": [
    {
      "type": "text",
      "text": "{\"result\": 15.0, \"operation\": \"addition\", \"operands\": [10.0, 5.0], \"success\": true}"
    }
  ]
}
```

### 5. Test Export/Import

```bash
# Export tools (should include outputSchema)
curl -s http://localhost:4444/bulk/export > /tmp/tools-export.json

# Check that output_schema is present
jq '.tools[] | select(.name == "add_numbers") | has("output_schema")' /tmp/tools-export.json

# Should output: true

# View the output_schema
jq '.tools[] | select(.name == "add_numbers") | .output_schema' /tmp/tools-export.json
```

## Test Method 2: Direct stdio Testing (Advanced)

### Using mcp client (Python)

```python
import asyncio
import json
from mcp.client.session import ClientSession
from mcp.client.stdio import stdio_client

async def test_output_schemas():
    """Test outputSchema support via stdio transport."""

    # Start the server
    server_params = {
        "command": "python3",
        "args": ["-m", "output_schema_test_server.server_fastmcp"]
    }

    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            # Initialize
            await session.initialize()

            # List tools
            tools = await session.list_tools()

            # Check for outputSchema
            for tool in tools:
                print(f"\nTool: {tool.name}")
                if hasattr(tool, 'outputSchema') and tool.outputSchema:
                    print(f"  Has outputSchema: ✓")
                    print(f"  Schema: {json.dumps(tool.outputSchema, indent=2)}")
                else:
                    print(f"  Has outputSchema: ✗")

            # Call a tool
            result = await session.call_tool("add_numbers", {"a": 5, "b": 3})
            print(f"\nTool call result: {result}")

if __name__ == "__main__":
    asyncio.run(test_output_schemas())
```

## Validation Checklist

Use this checklist to verify outputSchema support:

- [ ] **Database**: output_schema column exists in tools table
- [ ] **API - List Tools**: outputSchema field appears in GET /tools response
- [ ] **API - Get Tool**: outputSchema field appears in GET /tools/{id} response
- [ ] **Gateway Discovery**: outputSchema preserved when discovering tools from peer gateway
- [ ] **Export**: output_schema included in bulk export JSON
- [ ] **Import**: output_schema restored from bulk import JSON
- [ ] **Admin UI**: outputSchema displayed in tool details page
- [ ] **FastMCP Integration**: Pydantic models generate correct outputSchema
- [ ] **Mixed Types**: Tools with and without outputSchema both work
- [ ] **Null Handling**: Tools without outputSchema have `null` (not empty object)

## Expected Output Schemas

### add_numbers, multiply_numbers
```json
{
  "type": "object",
  "properties": {
    "result": {"type": "number"},
    "operation": {"type": "string"},
    "operands": {"type": "array", "items": {"type": "number"}},
    "success": {"type": "boolean"}
  },
  "required": ["result", "operation", "operands", "success"]
}
```

### create_user
```json
{
  "type": "object",
  "properties": {
    "name": {"type": "string"},
    "email": {"type": "string"},
    "age": {"type": "integer", "minimum": 0, "maximum": 150},
    "roles": {"type": "array", "items": {"type": "string"}}
  },
  "required": ["name", "email", "age", "roles"]
}
```

### validate_email
```json
{
  "type": "object",
  "properties": {
    "valid": {"type": "boolean"},
    "errors": {"type": "array", "items": {"type": "string"}},
    "cleaned_value": {"type": "string"}
  },
  "required": ["valid", "errors", "cleaned_value"]
}
```

### echo
```json
null
```
(No outputSchema - simple string return)

## Troubleshooting

### Server won't start
```bash
# Check if port is in use
lsof -i :9100

# Try a different port
python3 -m mcpgateway.translate \
  --stdio "python3 -m output_schema_test_server.server_fastmcp" \
  --port 9101
```

### Gateway not discovering tools
```bash
# Check gateway registration
curl http://localhost:4444/gateways | jq

# Check gateway connectivity
curl http://localhost:9100/sse

# Check gateway logs
tail -f logs/mcpgateway.log
```

### outputSchema missing in response
```bash
# Verify database migration ran
sqlite3 mcp.db "PRAGMA table_info(tools);" | grep output_schema

# Check tool in database
sqlite3 mcp.db "SELECT name, output_schema FROM tools WHERE name='add_numbers';"
```

## Clean Up

```bash
# Stop the test server
pkill -f "output_schema_test_server"

# Remove gateway registration
curl -X DELETE http://localhost:4444/gateways/{gateway-id}
```
