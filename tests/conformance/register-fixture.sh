#!/usr/bin/env bash
set -euo pipefail

: "${GITHUB_ENV:?GITHUB_ENV must be set}"
: "${MCP_CONFORMANCE_SERVER_ID:?MCP_CONFORMANCE_SERVER_ID must be set}"

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
compose_file="${script_dir}/docker-compose.yml"

bootstrap_token="$({
  docker compose -f "${compose_file}" exec -T control-plane \
    python3 -m mcpgateway.utils.create_jwt_token \
    --username admin@example.com --admin --exp 120
} 2>/dev/null | tail -n 1)"
test -n "${bootstrap_token}"
if [ "${GITHUB_ACTIONS:-}" = "true" ]; then
  echo "::add-mask::${bootstrap_token}"
fi

api_request() {
  local method="$1"
  local path="$2"
  local body="${3-}"
  local args=(
    --silent --show-error --fail-with-body
    --request "${method}"
    --header "Authorization: Bearer ${bootstrap_token}"
    --header "Content-Type: application/json"
    "http://127.0.0.1:4444${path}"
  )
  if [ -n "${body}" ]; then
    args+=(--data "${body}")
  fi
  curl "${args[@]}"
}

gateway="$(api_request POST /gateways '{
  "name": "_",
  "url": "http://fixture-proxy/mcp",
  "transport": "STREAMABLEHTTP",
  "authType": "authheaders",
  "authHeaders": [{"key": "Host", "value": "localhost:3000"}],
  "description": "Official MCP alpha.11 conformance fixture through the test-only Host proxy"
}')"
gateway_id="$(jq --exit-status --raw-output '.id' <<< "${gateway}")"

api_request POST \
  "/gateways/${gateway_id}/tools/refresh?include_resources=true&include_prompts=true" \
  '{}' > /dev/null

tool_ids='[]'
resource_ids='[]'
prompt_ids='[]'
has_tool=0
has_resource=0
has_prompt=0
for _ in $(seq 1 120); do
  tools="$(api_request GET /tools)"
  resources="$(api_request GET /resources)"
  prompts="$(api_request GET /prompts)"

  tool_ids="$(jq --compact-output --arg id "${gateway_id}" \
    '[.[] | select((.gateway_id // .gatewayId) == $id) | .id]' <<< "${tools}")"
  resource_ids="$(jq --compact-output --arg id "${gateway_id}" \
    '[.[] | select((.gateway_id // .gatewayId) == $id) | .id]' <<< "${resources}")"
  prompt_ids="$(jq --compact-output --arg id "${gateway_id}" \
    '[.[] | select((.gateway_id // .gatewayId) == $id) | .id]' <<< "${prompts}")"

  has_tool="$(jq --arg id "${gateway_id}" \
    '[.[] | select((.gateway_id // .gatewayId) == $id and .name == "test_simple_text")] | length' \
    <<< "${tools}")"
  has_resource="$(jq --arg id "${gateway_id}" \
    '[.[] | select((.gateway_id // .gatewayId) == $id and .uri == "test://static-text")] | length' \
    <<< "${resources}")"
  has_prompt="$(jq --arg id "${gateway_id}" \
    '[.[] | select((.gateway_id // .gatewayId) == $id and .name == "test_simple_prompt")] | length' \
    <<< "${prompts}")"
  if [ "${has_tool}" -gt 0 ] && [ "${has_resource}" -gt 0 ] && [ "${has_prompt}" -gt 0 ]; then
    break
  fi
  sleep 0.5
done
test "${has_tool}" -gt 0
test "${has_resource}" -gt 0
test "${has_prompt}" -gt 0

server_payload="$(jq --null-input --compact-output \
  --arg id "${MCP_CONFORMANCE_SERVER_ID}" \
  --argjson tools "${tool_ids}" \
  --argjson resources "${resource_ids}" \
  --argjson prompts "${prompt_ids}" \
  '{server: {
    id: $id,
    name: "Official MCP Conformance Server",
    description: "Virtual server for alpha.11 conformance",
    associated_tools: $tools,
    associated_resources: $resources,
    associated_prompts: $prompts
  }}')"
api_request POST /servers "${server_payload}" > /dev/null

token_response="$(api_request POST /v1/tokens '{
  "name": "MCP conformance CI",
  "description": "Ephemeral built-in Python data-plane token",
  "expires_in_days": 1,
  "user_email": "admin@example.com"
}')"
conformance_token="$(jq --exit-status --raw-output '.access_token' <<< "${token_response}")"
if [ "${GITHUB_ACTIONS:-}" = "true" ]; then
  echo "::add-mask::${conformance_token}"
fi
echo "MCP_CONFORMANCE_TOKEN=${conformance_token}" >> "${GITHUB_ENV}"
