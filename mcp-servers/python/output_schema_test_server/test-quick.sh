#!/bin/bash
# Quick test script for outputSchema implementation

# Generate token
echo "Generating JWT token..."
export TOKEN=$(python3 -m mcpgateway.utils.create_jwt_token --username admin@example.com --exp 0 --secret changeme123 2>/dev/null | head -1)

echo "Token: ${TOKEN:0:50}..."
echo ""

echo "=== Test 1: List tools with outputSchema ==="
curl -s -H "Authorization: Bearer $TOKEN" \
  http://localhost:4444/tools | python3 -c "
import json, sys
tools = json.load(sys.stdin)
for tool in tools:
    if 'add_numbers' in tool.get('name', '') or 'create_user' in tool.get('name', '') or tool.get('name') == 'echo':
        print(f\"{tool['name']}: has_outputSchema={tool.get('outputSchema') is not None}\")
"

echo ""
echo "=== Test 2: View add_numbers with full details ==="
curl -s -H "Authorization: Bearer $TOKEN" \
  http://localhost:4444/tools | python3 -c "
import json, sys
tools = json.load(sys.stdin)
for tool in tools:
    if tool.get('name') == 'add_numbers':
        print('Name:', tool['name'])
        print('Has inputSchema:', 'inputSchema' in tool)
        print('Has outputSchema:', 'outputSchema' in tool)
        if tool.get('outputSchema'):
            print('outputSchema keys:', list(tool['outputSchema'].keys()))
            if 'properties' in tool['outputSchema']:
                print('Output properties:', list(tool['outputSchema']['properties'].keys()))
        break
"

echo ""
echo "=== Test 3: Invoke add_numbers ==="
curl -s -X POST -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  http://localhost:4444/tools/invoke \
  -d '{"name": "add_numbers", "arguments": {"a": 10, "b": 5}}' | python3 -c "
import json, sys
result = json.load(sys.stdin)
if 'content' in result:
    text = json.loads(result['content'][0]['text'])
    print('Result:', json.dumps(text, indent=2))
else:
    print('Error:', result)
"

echo ""
echo "=== Test 4: Check echo tool (should have null outputSchema) ==="
curl -s -H "Authorization: Bearer $TOKEN" \
  http://localhost:4444/tools | python3 -c "
import json, sys
tools = json.load(sys.stdin)
for tool in tools:
    if tool.get('name') == 'echo':
        print('Name:', tool['name'])
        print('outputSchema:', tool.get('outputSchema'))
        break
"

echo ""
echo "=== All Tests Complete ==="
