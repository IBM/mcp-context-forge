#!/bin/bash
# Test live RSS search server

cd "$(dirname "$0")"

echo "🚀 Starting MCP RSS Search Server..."
echo ""

# Activate virtual environment and start server in background
. /home/cmihai/.venv/mcpgateway/bin/activate
python3 -m mcp_rss_search.server_fastmcp --transport http --host 127.0.0.1 --port 9100 > /tmp/rss_server.log 2>&1 &
SERVER_PID=$!

# Wait for server to start
echo "⏳ Waiting for server to start..."
sleep 3

echo ""
echo "📋 Testing tools/list endpoint..."
curl -s -X POST -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}' \
  http://127.0.0.1:9100/mcp/ | python3 -m json.tool | head -60

echo ""
echo ""
echo "📰 Testing fetch_rss with NPR News feed..."
curl -s -X POST -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"fetch_rss","arguments":{"url":"https://feeds.npr.org/1001/rss.xml","use_cache":false}}}' \
  http://127.0.0.1:9100/mcp/ | python3 -m json.tool | head -80

echo ""
echo ""
echo "🛑 Stopping server (PID: $SERVER_PID)..."
kill $SERVER_PID 2>/dev/null

echo "✅ Test complete!"
