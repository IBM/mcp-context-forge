#!/usr/bin/env bash
set -euo pipefail

: "${MCP_CONFORMANCE_SERVER_ID:?MCP_CONFORMANCE_SERVER_ID must be set}"

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd -- "${script_dir}/../.." && pwd)"
log_dir="${repo_root}/conformance-logs"
conformance_port="${MCP_CONFORMANCE_PORT:-8080}"

docker compose -f "${script_dir}/docker-compose.yml" up -d --wait nginx

endpoint="http://127.0.0.1:${conformance_port}/servers/${MCP_CONFORMANCE_SERVER_ID}/mcp"
request='{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "initialize",
  "params": {
    "protocolVersion": "2025-11-25",
    "capabilities": {},
    "clientInfo": {
      "name": "ci-route-probe",
      "version": "1.0.0"
    }
  }
}'

for _ in $(seq 1 120); do
  curl --silent --show-error \
    --dump-header "${log_dir}/route-probe-headers.txt" \
    --output "${log_dir}/route-probe-body.txt" \
    --request POST \
    --header 'Content-Type: application/json' \
    --header 'Accept: application/json, text/event-stream' \
    --header 'MCP-Protocol-Version: 2025-11-25' \
    --header 'MCP-Method: initialize' \
    --data "${request}" \
    "${endpoint}" || true
  if grep --ignore-case --quiet '^X-CF-Conformance-Backend: python-builtin' \
    "${log_dir}/route-probe-headers.txt" \
    && (
      jq --exit-status '.result.protocolVersion == "2025-11-25"' \
        "${log_dir}/route-probe-body.txt" > /dev/null 2>&1 \
      || sed -n 's/^data: //p' "${log_dir}/route-probe-body.txt" \
        | jq --exit-status '.result.protocolVersion == "2025-11-25"' \
          > /dev/null 2>&1
    ); then
    exit 0
  fi
  sleep 0.5
done

echo "MCP route did not reach the built-in Python data plane through nginx" >&2
cat "${log_dir}/route-probe-headers.txt" >&2
cat "${log_dir}/route-probe-body.txt" >&2
exit 1
