#!/usr/bin/env -S bash


#export MCP_LOG_FILE=/tmp/mcp.log 
#export RUST_LOG=debug
# update exe to required executable
EXE="mcp_stdio_wrapper"


#commands

INIT='{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"test-client","version":"1.0"}}}'
NOTIFY='{"jsonrpc":"2.0","method":"notifications/initialized"}'
LIST='{"jsonrpc":"2.0","id":2,"method":"tools/list"}'

CALL='{
  "jsonrpc": "2.0",
  "id": 3,
  "method": "tools/call",
  "params": {
    "name": "getSum",
    "arguments": {
          "a": 15,
          "b": 27
   }}
}'

# echo $CALL | yq -o json -M -I 0

(
  echo "$INIT"
  sleep 0.1
  echo "$NOTIFY"
  sleep 0.1
  echo "$LIST"
  sleep 0.1
  #echo "$(echo $CALL | yq -o json -M -I 0 )"
  #sleep 0.1
) | $EXE
