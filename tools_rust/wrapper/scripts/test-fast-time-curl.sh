#!/usr/bin/env -S bash

set -ueo pipefail

MCPGATEWAY_BEARER_TOKEN="$(uv --project ~/prj/mcp-context-forge run -m mcpgateway.utils.create_jwt_token --username admin@example.com --exp 10080 --secret my-test-key 2>/dev/null)"
echo -n $MCPGATEWAY_BEARER_TOKEN >~/.local/mcpgateway-bearer-token.txt

URL="http://localhost:8080/servers/9779b6698cbd4b4995ee04a4fab38737/mcp"

INIT='{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-03-26","capabilities":{},"clientInfo":{"name":"demo","version":"0.0.1"}}}'

NOTIFY='{"jsonrpc": "2.0","method": "notifications/initialized"}'
LIST='{"jsonrpc":"2.0","id":2,"method":"tools/list"}'
CALL='{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"fast-time-get-system-time","arguments":{"timezone":"UTC"}}}'

HEADERS=(
	-H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN"
	-H "Content-Type: application/json; charset=utf-8"
	-H "Accept: application/json, application/x-ndjson, text/event-stream"
)

curl  -N  "$URL" "${HEADERS[@]}" -d "$INIT"
printf "\n---\n"
curl  -N  "$URL" "${HEADERS[@]}" -d "$NOTIFY"
printf  "\n---\n"
curl  -N  "$URL" "${HEADERS[@]}" -d "$LIST"
printf "\n---\n"
curl  -N  "$URL" "${HEADERS[@]}" -d "$CALL"

