#!/usr/bin/env bash
set -euo pipefail

: "${GITHUB_OUTPUT:?GITHUB_OUTPUT must be set}"
: "${MCP_CONFORMANCE_SERVER_ID:?MCP_CONFORMANCE_SERVER_ID must be set}"
: "${MCP_CONFORMANCE_SPEC_VERSION:?MCP_CONFORMANCE_SPEC_VERSION must be set}"

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd -- "${script_dir}/../.." && pwd)"
suite_dir="${MCP_CONFORMANCE_SUITE_DIR:-${repo_root}/.conformance-suite}"
conformance_port="${MCP_CONFORMANCE_PORT:-8080}"
results_dir="${MCP_CONFORMANCE_RESULTS_DIR:-${repo_root}/conformance-results}"
baseline_file="${MCP_CONFORMANCE_BASELINE_FILE:-${script_dir}/expected-failures-${MCP_CONFORMANCE_SPEC_VERSION}.yml}"
if [[ "${results_dir}" != /* ]]; then
  results_dir="${repo_root}/${results_dir}"
fi

set +e
(
  cd "${suite_dir}"
  npm start -- \
    server \
    --url "http://127.0.0.1:${conformance_port}/servers/${MCP_CONFORMANCE_SERVER_ID}/mcp" \
    --requirements "${MCP_CONFORMANCE_SPEC_VERSION}" \
    --expected-failures "${baseline_file}" \
    --output-dir "${results_dir}"
)
runner_status="$?"
set -e

echo "status=${runner_status}" >> "${GITHUB_OUTPUT}"
