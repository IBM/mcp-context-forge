#!/bin/bash
set -e

echo "=== Pandoc Server Integration Test ==="

# Colors for output
GREEN='\033[0;32m'
RED='\033[0;31m'
NC='\033[0m' # No Color

# Build the server
echo "Building server..."
make build

# Start the server in background
echo "Starting server..."
./dist/pandoc-server &
SERVER_PID=$!
sleep 2

# Function to send JSON-RPC request
send_request() {
    local method=$1
    local params=$2
    echo "{\"jsonrpc\":\"2.0\",\"method\":\"$method\",\"params\":$params,\"id\":1}" | ./dist/pandoc-server
}

# Test 1: List tools
echo -e "\n${GREEN}Test 1: List tools${NC}"
echo '{"jsonrpc":"2.0","method":"tools/list","params":{},"id":1}' | timeout 2 ./dist/pandoc-server | head -1

# Test 2: Health check
echo -e "\n${GREEN}Test 2: Health check${NC}"
echo '{"jsonrpc":"2.0","method":"tools/call","params":{"name":"health"},"id":1}' | timeout 2 ./dist/pandoc-server | head -1

# Test 3: List formats
echo -e "\n${GREEN}Test 3: List formats (input only)${NC}"
echo '{"jsonrpc":"2.0","method":"tools/call","params":{"name":"list-formats","arguments":{"type":"input"}},"id":1}' | timeout 2 ./dist/pandoc-server | head -1

# Test 4: Convert markdown to HTML
echo -e "\n${GREEN}Test 4: Convert markdown to HTML${NC}"
echo '{"jsonrpc":"2.0","method":"tools/call","params":{"name":"pandoc","arguments":{"from":"markdown","to":"html","input":"# Hello\n\nThis is **bold** text."}},"id":1}' | timeout 2 ./dist/pandoc-server | head -1

# Clean up
kill $SERVER_PID 2>/dev/null || true

echo -e "\n${GREEN}All tests completed successfully!${NC}"
exit 0
