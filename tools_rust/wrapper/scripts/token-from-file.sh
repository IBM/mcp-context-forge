#!/usr/bin/env -S bash

set -ueo pipefail

TOKEN_FILE="$HOME/.local/mcpgateway-bearer-token.txt"
if [ ! -f "$TOKEN_FILE" ]; then
    AUTH="$(uv --project "${MCP_CONTEXT_FORGE_DIR}" run -m mcpgateway.utils.create_jwt_token --username admin@example.com --exp 10080 --secret my-test-key)"
    echo -n "$AUTH" >$TOKEN_FILE
fi

AUTH="Bearer $(tr -d '\r\n' <"$TOKEN_FILE")"
