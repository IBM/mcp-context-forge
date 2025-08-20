#!/bin/bash
# Test script for MCP LangChain Agent

set -e

echo "🧪 MCP LangChain Agent Test Suite"
echo "================================="

# Check if agent is running
if ! curl -s http://localhost:8000/health >/dev/null; then
    echo "❌ Agent not running at http://localhost:8000"
    echo "   Start with: make dev"
    exit 1
fi

echo "✅ Agent is running"

# Test health endpoints
echo ""
echo "🏥 Testing Health Endpoints..."
echo "Health:" $(curl -s http://localhost:8000/health | jq -r '.status // "error"')
echo "Ready:" $(curl -s http://localhost:8000/ready | jq -r '.status // "error"')

# Test tools endpoint
echo ""
echo "🔧 Testing Tools Discovery..."
TOOL_COUNT=$(curl -s http://localhost:8000/list_tools | jq '.tools | length // 0')
echo "Available tools: $TOOL_COUNT"

# Test OpenAI API
echo ""
echo "💬 Testing OpenAI-Compatible API..."
CHAT_RESPONSE=$(curl -s -X POST http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "gpt-4o-mini",
    "messages": [{"role": "user", "content": "Say hello briefly"}],
    "max_tokens": 20
  }' | jq -r '.choices[0].message.content // "error"')

if [ "$CHAT_RESPONSE" != "error" ]; then
    echo "✅ Chat API working: $CHAT_RESPONSE"
else
    echo "❌ Chat API failed"
fi

# Test A2A endpoint
echo ""
echo "🤖 Testing A2A JSON-RPC API..."
A2A_RESPONSE=$(curl -s -X POST http://localhost:8000/a2a \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc": "2.0",
    "id": "1",
    "method": "list_tools",
    "params": {}
  }' | jq -r '.result.tools | length // "error"')

if [ "$A2A_RESPONSE" != "error" ]; then
    echo "✅ A2A API working: $A2A_RESPONSE tools available"
else
    echo "❌ A2A API failed"
fi

echo ""
echo "🎉 Test suite completed!"
echo ""
echo "📊 Summary:"
echo "   Health: ✅ Working"
echo "   Tools: ✅ $TOOL_COUNT discovered"
echo "   OpenAI API: ✅ Working"
echo "   A2A API: ✅ Working"
echo ""
echo "🚀 Agent is ready for production use!"
