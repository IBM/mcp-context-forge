#!/usr/bin/env -S bash

set -ueo pipefail

MCPGATEWAY_BEARER_TOKEN="$(uvx --from mcp-contextforge-gateway python -m mcpgateway.utils.create_jwt_token --username admin@example.com --exp 10080 --secret my-test-key)"

PORT="${PORT:-8080}"
SERVER_ID="${SERVER_ID:-9779b6698cbd4b4995ee04a4fab38737}"
URL="http://localhost:${PORT}/servers/${SERVER_ID}/mcp"

AUTH="Bearer $MCPGATEWAY_BEARER_TOKEN"
rm -f out.log

if [[ "${P:=X}" == "P" ]]; then
	EXE=(
		uvx
		--from mcp-contextforge-gateway
		python
		-m
		mcpgateway.wrapper
		--url "$URL"
		--auth "$AUTH"
		--log-level off
	)
else
	EXE=(
		"$(dirname "$0")/../target/release/mcp_stdio_wrapper"
		--url "$URL"
		--auth "$AUTH"
		--log-level debug
		--log-file out.log
	)
fi

INIT='{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"test-client","version":"1.0"}}}'
NOTIFY='{"jsonrpc":"2.0","method":"notifications/initialized"}'
LIST='{"jsonrpc":"2.0","id":2,"method":"tools/list"}'
CALL='{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"fast-time-get-system-time","arguments":{"timezone":"UTC"}}}'

time (
	echo "$INIT"
	sleep ${SLEEP:=0.2}
	echo "$NOTIFY"
	sleep ${SLEEP:=0.2}
	echo "$LIST"
	sleep ${SLEEP:=0.2}
	echo "$CALL"
	sleep ${SLEEP:=0.2}
) | "${EXE[@]}"
