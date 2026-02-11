#!/usr/bin/env -S bash

# test for rust-sdk server sample
# traffic check with tcpdump:
# sudo tcpdump -i lo -s 0 -w mcp_debug.pcap tcp port 8080

set -ueo pipefail

rm -f out.log

EXE=(
	mcp_stdio_wrapper
	--url "http://localhost:8000/mcp"
	--log-level debug
	--log-file out.log
)

INIT='{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"test-client","version":"1.0"}}}'
NOTIFY='{"jsonrpc":"2.0","method":"notifications/initialized"}'
LIST='{"jsonrpc":"2.0","id":2,"method":"tools/list"}'

CALL='{
  "jsonrpc": "2.0",
  "id": 4,
  "method": "tools/call",
  "params": {
    "name": "say_hello",
    "arguments": {},
    "_meta": {
      "progressToken": 0
    }
  }
}'

(
	echo "$INIT"
	sleep 0.2
	echo "$NOTIFY"
	sleep 0.2
	echo "$LIST"
	sleep 0.2
	echo "$CALL" | yq -o json -M -I 0
) | "${EXE[@]}"
