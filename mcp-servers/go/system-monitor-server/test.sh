#!/bin/bash

# System Monitor Server Test Script
# This script tests the system-monitor-server functionality

set -e

echo "🧪 Testing System Monitor Server..."

# Check if server is running
if ! pgrep -f "system-monitor-server" > /dev/null; then
    echo "❌ Server is not running. Please start it first with: ./start.sh -t http"
    exit 1
fi

# Get the port (default to 8080)
PORT=${1:-8080}
BASE_URL="http://localhost:$PORT"

echo "🔍 Testing server at $BASE_URL"

# Test health endpoint
echo "1. Testing health endpoint..."
HEALTH_RESPONSE=$(curl -s "$BASE_URL/health" || echo "Failed")
if [[ "$HEALTH_RESPONSE" == *"healthy"* ]]; then
    echo "✅ Health check passed"
else
    echo "❌ Health check failed: $HEALTH_RESPONSE"
fi

# Test info endpoint
echo "2. Testing info endpoint..."
INFO_RESPONSE=$(curl -s "$BASE_URL/info" || echo "Failed")
if [[ "$INFO_RESPONSE" == *"tools"* ]]; then
    echo "✅ Info endpoint working"
    echo "📋 Available tools: $(echo "$INFO_RESPONSE" | jq -r '.tools[].name' | tr '\n' ' ')"
else
    echo "❌ Info endpoint failed: $INFO_RESPONSE"
fi

# Test version endpoint
echo "3. Testing version endpoint..."
VERSION_RESPONSE=$(curl -s "$BASE_URL/version" || echo "Failed")
if [[ "$VERSION_RESPONSE" == *"version"* ]]; then
    echo "✅ Version endpoint working"
    echo "📦 Version: $(echo "$VERSION_RESPONSE" | jq -r '.version')"
else
    echo "❌ Version endpoint failed: $VERSION_RESPONSE"
fi

# Test MCP initialization
echo "4. Testing MCP initialization..."
INIT_RESPONSE=$(curl -s -X POST "$BASE_URL/" \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{"roots":{"listChanged":true},"sampling":{}}},"id":1}' || echo "Failed")

if [[ "$INIT_RESPONSE" == *"result"* ]]; then
    echo "✅ MCP initialization successful"
    SESSION_ID=$(echo "$INIT_RESPONSE" | jq -r '.result.serverInfo.sessionId // empty')
    if [ -n "$SESSION_ID" ]; then
        echo "🔑 Session ID: $SESSION_ID"

        # Test tools/list with session
        echo "5. Testing tools/list..."
        TOOLS_RESPONSE=$(curl -s -X POST "$BASE_URL/" \
          -H "Content-Type: application/json" \
          -d "{\"jsonrpc\":\"2.0\",\"method\":\"tools/list\",\"params\":{\"sessionId\":\"$SESSION_ID\"},\"id\":2}" || echo "Failed")

        if [[ "$TOOLS_RESPONSE" == *"tools"* ]]; then
            echo "✅ Tools list working"
            echo "🛠️  Available tools: $(echo "$TOOLS_RESPONSE" | jq -r '.result.tools[].name' | tr '\n' ' ')"
        else
            echo "❌ Tools list failed: $TOOLS_RESPONSE"
        fi

        # Test get_system_metrics
        echo "6. Testing get_system_metrics tool..."
        METRICS_RESPONSE=$(curl -s -X POST "$BASE_URL/" \
          -H "Content-Type: application/json" \
          -d "{\"jsonrpc\":\"2.0\",\"method\":\"tools/call\",\"params\":{\"name\":\"get_system_metrics\",\"arguments\":{},\"sessionId\":\"$SESSION_ID\"},\"id\":3}" || echo "Failed")

        if [[ "$METRICS_RESPONSE" == *"cpu"* ]]; then
            echo "✅ System metrics tool working"
            echo "📊 Sample metrics: $(echo "$METRICS_RESPONSE" | jq -r '.result.content[0].text' | head -c 100)..."
        else
            echo "❌ System metrics tool failed: $METRICS_RESPONSE"
        fi

        # Test list_processes
        echo "7. Testing list_processes tool..."
        PROCESS_RESPONSE=$(curl -s -X POST "$BASE_URL/" \
          -H "Content-Type: application/json" \
          -d "{\"jsonrpc\":\"2.0\",\"method\":\"tools/call\",\"params\":{\"name\":\"list_processes\",\"arguments\":{\"limit\":5},\"sessionId\":\"$SESSION_ID\"},\"id\":4}" || echo "Failed")

        if [[ "$PROCESS_RESPONSE" == *"processes"* ]]; then
            echo "✅ Process listing tool working"
            echo "📋 Found processes: $(echo "$PROCESS_RESPONSE" | jq -r '.result.content[0].text' | head -c 100)..."
        else
            echo "❌ Process listing tool failed: $PROCESS_RESPONSE"
        fi

        # Test get_disk_usage
        echo "8. Testing get_disk_usage tool..."
        DISK_RESPONSE=$(curl -s -X POST "$BASE_URL/" \
          -H "Content-Type: application/json" \
          -d "{\"jsonrpc\":\"2.0\",\"method\":\"tools/call\",\"params\":{\"name\":\"get_disk_usage\",\"arguments\":{},\"sessionId\":\"$SESSION_ID\"},\"id\":5}" || echo "Failed")

        if [[ "$DISK_RESPONSE" == *"disk"* ]]; then
            echo "✅ Disk usage tool working"
            echo "💾 Disk info: $(echo "$DISK_RESPONSE" | jq -r '.result.content[0].text' | head -c 100)..."
        else
            echo "❌ Disk usage tool failed: $DISK_RESPONSE"
        fi

    else
        echo "⚠️  No session ID returned, testing without session..."

        # Test tools/list without session
        echo "5. Testing tools/list (no session)..."
        TOOLS_RESPONSE=$(curl -s -X POST "$BASE_URL/" \
          -H "Content-Type: application/json" \
          -d '{"jsonrpc":"2.0","method":"tools/list","id":2}' || echo "Failed")

        if [[ "$TOOLS_RESPONSE" == *"tools"* ]]; then
            echo "✅ Tools list working (no session)"
            echo "🛠️  Available tools: $(echo "$TOOLS_RESPONSE" | jq -r '.result.tools[].name' | tr '\n' ' ')"
        else
            echo "❌ Tools list failed: $TOOLS_RESPONSE"
        fi
    fi
else
    echo "❌ MCP initialization failed: $INIT_RESPONSE"
fi

echo ""
echo "🎉 Test completed! Check the responses above for any issues."
echo "💡 For manual testing, first initialize:"
echo "   curl -X POST $BASE_URL/ -H 'Content-Type: application/json' -d '{\"jsonrpc\":\"2.0\",\"method\":\"initialize\",\"params\":{\"protocolVersion\":\"2024-11-05\",\"capabilities\":{\"roots\":{\"listChanged\":true},\"sampling\":{}}},\"id\":1}'"
