# Testing Output Schema with curl

Quick reference for testing the output_schema implementation using curl.

## Setup

First, generate a JWT token and export it:

```bash
export TOKEN=$(python3 -m mcpgateway.utils.create_jwt_token --username admin@example.com --exp 0 --secret changeme123)
```

Or use an existing token:
```bash
export TOKEN="eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJ1c2VybmFtZSI6ImFkbWluQGV4YW1wbGUuY29tIiwiaWF0IjoxNzYwNjQzNTU1LCJpc3MiOiJtY3BnYXRld2F5IiwiYXVkIjoibWNwZ2F0ZXdheS1hcGkiLCJzdWIiOiJhZG1pbkBleGFtcGxlLmNvbSJ9.4qSaXA5D3jEEJNh9VTDvPbQP7CflF9wU_x9EAoXVB8I"
```

## Quick Test Commands

### 1. List All Tools (Check for outputSchema field)

```bash
curl -s -H "Authorization: Bearer $TOKEN" \
  http://localhost:4444/tools | jq '.'
```

### 2. Find a Specific Tool (e.g., add_numbers)

```bash
curl -s -H "Authorization: Bearer $TOKEN" \
  http://localhost:4444/tools | jq '.[] | select(.name == "add_numbers")'
```

### 3. Check outputSchema Field Specifically

```bash
curl -s -H "Authorization: Bearer $TOKEN" \
  http://localhost:4444/tools | \
  jq '.[] | select(.name == "add_numbers") | {name, inputSchema, outputSchema}'
```

**Expected Output**:
```json
{
  "name": "add_numbers",
  "inputSchema": {
    "properties": {
      "a": {
        "description": "First number",
        "title": "A",
        "type": "number"
      },
      "b": {
        "description": "Second number",
        "title": "B",
        "type": "number"
      }
    },
    "required": ["a", "b"],
    "title": "add_numbers",
    "type": "object"
  },
  "outputSchema": {
    "properties": {
      "result": {
        "description": "The calculated result",
        "title": "Result",
        "type": "number"
      },
      "operation": {
        "description": "The operation performed",
        "title": "Operation",
        "type": "string"
      },
      "operands": {
        "description": "The operands used",
        "items": {
          "type": "number"
        },
        "title": "Operands",
        "type": "array"
      },
      "success": {
        "default": true,
        "description": "Whether the calculation succeeded",
        "title": "Success",
        "type": "boolean"
      }
    },
    "required": ["result", "operation", "operands"],
    "title": "CalculationResult",
    "type": "object"
  }
}
```

### 4. Check All Tools for outputSchema Presence

```bash
curl -s -H "Authorization: Bearer $TOKEN" \
  http://localhost:4444/tools | \
  jq '.[] | select(.name | contains("_numbers") or contains("create_user") or contains("validate_email") or . == "echo") | {name, has_output_schema: (.outputSchema != null)}'
```

**Expected Output**:
```json
{"name": "add_numbers", "has_output_schema": true}
{"name": "multiply_numbers", "has_output_schema": true}
{"name": "divide_numbers", "has_output_schema": true}
{"name": "create_user", "has_output_schema": true}
{"name": "validate_email", "has_output_schema": true}
{"name": "echo", "has_output_schema": false}
```

### 5. Invoke a Tool

```bash
curl -s -X POST -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  http://localhost:4444/tools/invoke \
  -d '{
    "name": "add_numbers",
    "arguments": {"a": 10, "b": 5}
  }' | jq '.'
```

**Expected Output**:
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

### 6. Test Complex Tool (create_user)

```bash
curl -s -X POST -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  http://localhost:4444/tools/invoke \
  -d '{
    "name": "create_user",
    "arguments": {
      "name": "John Doe",
      "email": "john@example.com",
      "age": 30,
      "roles": ["admin", "user"]
    }
  }' | jq '.'
```

**Expected Output**:
```json
{
  "content": [
    {
      "type": "text",
      "text": "{\"name\": \"John Doe\", \"email\": \"john@example.com\", \"age\": 30, \"roles\": [\"admin\", \"user\"]}"
    }
  ]
}
```

### 7. Test Tool Without outputSchema (echo)

```bash
curl -s -H "Authorization: Bearer $TOKEN" \
  http://localhost:4444/tools | \
  jq '.[] | select(.name == "echo") | {name, outputSchema}'
```

**Expected Output**:
```json
{
  "name": "echo",
  "outputSchema": null
}
```

## Export/Import Testing

### 8. Export Tools with outputSchema

```bash
curl -s -H "Authorization: Bearer $TOKEN" \
  http://localhost:4444/bulk/export > /tmp/tools-export.json

# Check the export
jq '.tools[] | select(.name == "add_numbers") | {name, has_output_schema: (.output_schema != null)}' /tmp/tools-export.json
```

**Expected Output**:
```json
{
  "name": "add_numbers",
  "has_output_schema": true
}
```

### 9. View Exported outputSchema

```bash
jq '.tools[] | select(.name == "add_numbers") | .output_schema' /tmp/tools-export.json
```

### 10. Count Tools with outputSchema

```bash
curl -s -H "Authorization: Bearer $TOKEN" \
  http://localhost:4444/tools | \
  jq '[.[] | select(.outputSchema != null)] | length'
```

## Database Validation

### 11. Check Database Schema

```bash
sqlite3 mcp.db "PRAGMA table_info(tools);" | grep output_schema
```

**Expected Output**:
```
12|output_schema|JSON|1||0
```

### 12. Query outputSchema from Database

```bash
sqlite3 mcp.db "SELECT name, output_schema FROM tools WHERE name='add_numbers';"
```

## Complete Test Script

Save this as `test-output-schema.sh`:

```bash
#!/bin/bash

# Generate token
export TOKEN=$(python3 -m mcpgateway.utils.create_jwt_token --username admin@example.com --exp 0 --secret changeme123 2>/dev/null | head -1)

echo "=== Testing outputSchema Implementation ==="
echo ""

echo "1. Listing all tools with outputSchema status..."
curl -s -H "Authorization: Bearer $TOKEN" \
  http://localhost:4444/tools | \
  jq '.[] | select(.name | contains("_numbers") or contains("create_user") or contains("validate") or . == "echo") | {name, has_outputSchema: (.outputSchema != null)}'

echo ""
echo "2. Viewing add_numbers outputSchema..."
curl -s -H "Authorization: Bearer $TOKEN" \
  http://localhost:4444/tools | \
  jq '.[] | select(.name == "add_numbers") | .outputSchema | keys'

echo ""
echo "3. Invoking add_numbers tool..."
curl -s -X POST -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  http://localhost:4444/tools/invoke \
  -d '{"name": "add_numbers", "arguments": {"a": 10, "b": 5}}' | jq '.content[0].text | fromjson'

echo ""
echo "4. Invoking create_user tool..."
curl -s -X POST -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  http://localhost:4444/tools/invoke \
  -d '{"name": "create_user", "arguments": {"name": "Test User", "email": "test@example.com", "age": 25, "roles": ["user"]}}' | jq '.content[0].text | fromjson'

echo ""
echo "5. Checking export includes outputSchema..."
curl -s -H "Authorization: Bearer $TOKEN" \
  http://localhost:4444/bulk/export | \
  jq '.tools[] | select(.name == "add_numbers") | has("output_schema")'

echo ""
echo "=== All Tests Complete ==="
```

Run it:
```bash
chmod +x test-output-schema.sh
./test-output-schema.sh
```

## Troubleshooting

### Token expired or invalid
```bash
# Generate new token
export TOKEN=$(python3 -m mcpgateway.utils.create_jwt_token --username admin@example.com --exp 0 --secret changeme123 2>/dev/null | head -1)
```

### Gateway not running
```bash
# Check if gateway is running
curl -s http://localhost:4444/health

# Start gateway
make dev
```

### Tools not showing up
```bash
# Check gateway registration
curl -s -H "Authorization: Bearer $TOKEN" \
  http://localhost:4444/gateways | jq '.'

# Check if test server is running
ps aux | grep output_schema_test_server
```

### outputSchema is null when it shouldn't be
```bash
# Check database migration
sqlite3 mcp.db "SELECT sql FROM sqlite_master WHERE name='tools';" | grep output_schema

# Re-discover tools from gateway
curl -X POST -H "Authorization: Bearer $TOKEN" \
  http://localhost:4444/gateways/{gateway-id}/refresh
```
