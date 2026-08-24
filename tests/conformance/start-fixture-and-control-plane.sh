#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd -- "${script_dir}/../.." && pwd)"
suite_dir="${MCP_CONFORMANCE_SUITE_DIR:-${repo_root}/.conformance-suite}"
log_dir="${repo_root}/conformance-logs"

mkdir -p "${log_dir}" "${repo_root}/conformance-results"

(
  cd "${suite_dir}"
  PORT=3000 npm exec -- tsx examples/servers/typescript/everything-server.ts
) > "${log_dir}/reference-server.log" 2>&1 &
echo "$!" > "${log_dir}/reference-server.pid"

docker compose -f "${script_dir}/docker-compose.yml" \
  up -d --wait fixture-proxy control-plane

for _ in $(seq 1 120); do
  if curl --silent --output /dev/null http://127.0.0.1:3000/mcp; then
    exit 0
  fi
  sleep 0.25
done

echo "Timed out waiting for the official conformance fixture" >&2
exit 1
