# Quick Start - Testing outputSchema with curl

## One-Line Test Commands

Copy and paste these commands to test the outputSchema implementation:

### 1. Generate Token and List Tools
```bash
TOKEN=$(python3 -m mcpgateway.utils.create_jwt_token --username admin@example.com --exp 0 --secret changeme123 2>/dev/null | head -1) && curl -s -H "Authorization: Bearer $TOKEN" http://localhost:4444/tools | python3 -m json.tool | grep -A 30 "add_numbers"
```

### 2. Check for outputSchema Field
```bash
TOKEN=$(python3 -m mcpgateway.utils.create_jwt_token --username admin@example.com --exp 0 --secret changeme123 2>/dev/null | head -1) && curl -s -H "Authorization: Bearer $TOKEN" http://localhost:4444/tools | python3 -m json.tool | grep -B 2 -A 20 "outputSchema"
```

### 3. Invoke add_numbers Tool
```bash
TOKEN=$(python3 -m mcpgateway.utils.create_jwt_token --username admin@example.com --exp 0 --secret changeme123 2>/dev/null | head -1) && curl -s -X POST -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" http://localhost:4444/tools/invoke -d '{"name":"add_numbers","arguments":{"a":10,"b":5}}' | python3 -m json.tool
```

### 4. Export Tools and Check output_schema
```bash
TOKEN=$(python3 -m mcpgateway.utils.create_jwt_token --username admin@example.com --exp 0 --secret changeme123 2>/dev/null | head -1) && curl -s -H "Authorization: Bearer $TOKEN" http://localhost:4444/bulk/export | python3 -m json.tool | grep -B 2 -A 10 "output_schema"
```

### 5. Check Database for output_schema Column
```bash
sqlite3 mcp.db "PRAGMA table_info(tools);" | grep output_schema
```

## Interactive Testing

For easier testing, save the token in your shell:

```bash
# Generate and save token
export TOKEN=$(python3 -m mcpgateway.utils.create_jwt_token --username admin@example.com --exp 0 --secret changeme123 2>/dev/null | head -1)

# Now you can use $TOKEN in commands:
curl -s -H "Authorization: Bearer $TOKEN" http://localhost:4444/tools | python3 -m json.tool

# List specific tool
curl -s -H "Authorization: Bearer $TOKEN" http://localhost:4444/tools | python3 -c "import json,sys; [print(json.dumps(t, indent=2)) for t in json.load(sys.stdin) if t.get('name')=='add_numbers']"

# Invoke tool
curl -s -X POST -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" http://localhost:4444/tools/invoke -d '{"name":"add_numbers","arguments":{"a":10,"b":5}}' | python3 -m json.tool
```

## Verification Steps

### ✅ Step 1: Verify outputSchema in API Response
```bash
export TOKEN=$(python3 -m mcpgateway.utils.create_jwt_token --username admin@example.com --exp 0 --secret changeme123 2>/dev/null | head -1)
curl -s -H "Authorization: Bearer $TOKEN" http://localhost:4444/tools | python3 -c "
import json, sys
tools = json.load(sys.stdin)
for tool in tools:
    if tool.get('name') == 'add_numbers':
        has_output = 'outputSchema' in tool and tool['outputSchema'] is not None
        print(f'✓ add_numbers has outputSchema: {has_output}')
        if has_output:
            print(f'  Properties: {list(tool[\"outputSchema\"].get(\"properties\", {}).keys())}')
"
```

**Expected**: `✓ add_numbers has outputSchema: True` with properties: `['result', 'operation', 'operands', 'success']`

### ✅ Step 2: Verify Tool Invocation
```bash
export TOKEN=$(python3 -m mcpgateway.utils.create_jwt_token --username admin@example.com --exp 0 --secret changeme123 2>/dev/null | head -1)
curl -s -X POST -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  http://localhost:4444/tools/invoke \
  -d '{"name":"add_numbers","arguments":{"a":15,"b":7}}' | python3 -c "
import json, sys
result = json.load(sys.stdin)
if 'content' in result:
    data = json.loads(result['content'][0]['text'])
    print(f'✓ Result: {data[\"result\"]}')
    print(f'✓ Operation: {data[\"operation\"]}')
    print(f'✓ Operands: {data[\"operands\"]}')
    print(f'✓ Success: {data[\"success\"]}')
"
```

**Expected**: Result: 22.0, Operation: addition, etc.

### ✅ Step 3: Verify Export Includes output_schema
```bash
export TOKEN=$(python3 -m mcpgateway.utils.create_jwt_token --username admin@example.com --exp 0 --secret changeme123 2>/dev/null | head -1)
curl -s -H "Authorization: Bearer $TOKEN" http://localhost:4444/bulk/export | python3 -c "
import json, sys
data = json.load(sys.stdin)
for tool in data.get('tools', []):
    if tool.get('name') == 'add_numbers':
        has_schema = 'output_schema' in tool and tool['output_schema'] is not None
        print(f'✓ Export includes output_schema: {has_schema}')
"
```

**Expected**: `✓ Export includes output_schema: True`

### ✅ Step 4: Verify Database Column
```bash
sqlite3 mcp.db "SELECT name, CASE WHEN output_schema IS NOT NULL THEN 'HAS SCHEMA' ELSE 'NULL' END as schema_status FROM tools WHERE name='add_numbers';"
```

**Expected**: `add_numbers|HAS SCHEMA`

### ✅ Step 5: Compare Tool With and Without Schema
```bash
export TOKEN=$(python3 -m mcpgateway.utils.create_jwt_token --username admin@example.com --exp 0 --secret changeme123 2>/dev/null | head -1)
curl -s -H "Authorization: Bearer $TOKEN" http://localhost:4444/tools | python3 -c "
import json, sys
tools = json.load(sys.stdin)
for name in ['add_numbers', 'echo']:
    for tool in tools:
        if tool.get('name') == name:
            has_schema = tool.get('outputSchema') is not None
            print(f'{name:20} outputSchema: {\"✓ Present\" if has_schema else \"✗ Null (expected)\"}')
            break
"
```

**Expected**:
```
add_numbers          outputSchema: ✓ Present
echo                 outputSchema: ✗ Null (expected)
```

## Troubleshooting

### No tools showing up
```bash
# Check gateway registration
export TOKEN=$(python3 -m mcpgateway.utils.create_jwt_token --username admin@example.com --exp 0 --secret changeme123 2>/dev/null | head -1)
curl -s -H "Authorization: Bearer $TOKEN" http://localhost:4444/gateways | python3 -m json.tool
```

### Authorization errors
```bash
# Regenerate token
export TOKEN=$(python3 -m mcpgateway.utils.create_jwt_token --username admin@example.com --exp 0 --secret changeme123 2>/dev/null | head -1)
echo "New token: $TOKEN"
```

### outputSchema is null
```bash
# Check if migration ran
sqlite3 mcp.db "PRAGMA table_info(tools);" | grep output_schema

# Check tool was discovered correctly
curl -s -H "Authorization: Bearer $TOKEN" http://localhost:4444/tools | python3 -m json.tool | grep -C 5 "add_numbers"
```

## Summary

The key curl commands you need:

1. **List tools**: `curl -H "Authorization: Bearer $TOKEN" http://localhost:4444/tools`
2. **Invoke tool**: `curl -X POST -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" http://localhost:4444/tools/invoke -d '{"name":"TOOL_NAME","arguments":{...}}'`
3. **Export**: `curl -H "Authorization: Bearer $TOKEN" http://localhost:4444/bulk/export`
4. **Get gateways**: `curl -H "Authorization: Bearer $TOKEN" http://localhost:4444/gateways`

Always set `$TOKEN` first:
```bash
export TOKEN=$(python3 -m mcpgateway.utils.create_jwt_token --username admin@example.com --exp 0 --secret changeme123 2>/dev/null | head -1)
```
