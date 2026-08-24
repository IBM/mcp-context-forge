#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd -- "${script_dir}/../.." && pwd)"
compose_file="${script_dir}/docker-compose.yml"

export MCP_CONFORMANCE_VERSION="${MCP_CONFORMANCE_VERSION:-0.2.0-alpha.11}"
export MCP_CONFORMANCE_SOURCE_SHA="${MCP_CONFORMANCE_SOURCE_SHA:-c321dd32035556e6769d3724a8ee97d87c3faaac}"
export MCP_CONFORMANCE_SPEC_VERSIONS="${MCP_CONFORMANCE_SPEC_VERSIONS:-2025-11-25 2026-07-28}"
export MCP_CONFORMANCE_SERVER_ID="${MCP_CONFORMANCE_SERVER_ID:-3f33286667d34b65a31c3bafd30e4c21}"
export MCP_CONFORMANCE_SUITE_DIR="${MCP_CONFORMANCE_SUITE_DIR:-${repo_root}/.conformance-suite}"
export CF_CONTEXTFORGE_IMAGE="${CF_CONTEXTFORGE_IMAGE:-mcpgateway/mcpgateway:conformance}"
export MCP_CONFORMANCE_COLOR="${MCP_CONFORMANCE_COLOR:-auto}"

for command in curl docker git jq node npm; do
  if ! command -v "${command}" > /dev/null 2>&1; then
    echo "Required command not found: ${command}" >&2
    exit 1
  fi
done
docker compose version > /dev/null

if [ -e "${MCP_CONFORMANCE_SUITE_DIR}" ] && [ ! -d "${MCP_CONFORMANCE_SUITE_DIR}/.git" ]; then
  echo "MCP_CONFORMANCE_SUITE_DIR is not a git checkout: ${MCP_CONFORMANCE_SUITE_DIR}" >&2
  exit 1
fi

if [ ! -d "${MCP_CONFORMANCE_SUITE_DIR}/.git" ]; then
  echo "Checking out the official conformance suite."
  git clone --filter=blob:none \
    https://github.com/modelcontextprotocol/conformance.git \
    "${MCP_CONFORMANCE_SUITE_DIR}"
  git -C "${MCP_CONFORMANCE_SUITE_DIR}" checkout --detach "${MCP_CONFORMANCE_SOURCE_SHA}"
fi

suite_sha="$(git -C "${MCP_CONFORMANCE_SUITE_DIR}" rev-parse HEAD)"
if [ "${suite_sha}" != "${MCP_CONFORMANCE_SOURCE_SHA}" ]; then
  echo "Conformance checkout is at ${suite_sha}; expected ${MCP_CONFORMANCE_SOURCE_SHA}." >&2
  echo "Use a checkout at the pinned commit or set MCP_CONFORMANCE_SUITE_DIR." >&2
  exit 1
fi

(
  echo "Installing official conformance dependencies."
  cd "${MCP_CONFORMANCE_SUITE_DIR}"
  test "$(node -p "require('./package.json').version")" = "${MCP_CONFORMANCE_VERSION}"
  npm ci --ignore-scripts
)

state_dir="$(mktemp -d "${TMPDIR:-/tmp}/contextforge-conformance.XXXXXX")"
export GITHUB_ENV="${state_dir}/github-env"
export GITHUB_OUTPUT="${state_dir}/github-output"
touch "${GITHUB_ENV}" "${GITHUB_OUTPUT}"
mkdir -p "${repo_root}/conformance-results"

# shellcheck disable=SC2329 # Invoked by the trap below.
cleanup() {
  local status="$?"
  trap - EXIT INT TERM
  if [ "${status}" -ne 0 ]; then
    echo "Conformance run failed; printing live stack logs." >&2
    MCP_CONFORMANCE_TOKEN=diagnostics-only \
      docker compose -f "${compose_file}" logs --no-color || true
    if [ -f "${repo_root}/conformance-logs/reference-server.log" ]; then
      echo "Official fixture log:" >&2
      sed -n '1,240p' "${repo_root}/conformance-logs/reference-server.log" >&2
    fi
  fi
  MCP_CONFORMANCE_TOKEN="${MCP_CONFORMANCE_TOKEN:-cleanup-only}" \
    "${script_dir}/stop-live-stack.sh" || true
  rm -f -- "${GITHUB_ENV}" "${GITHUB_OUTPUT}"
  rmdir -- "${state_dir}"
  exit "${status}"
}
trap cleanup EXIT INT TERM

MCP_CONFORMANCE_TOKEN=pull-only \
  docker compose -f "${compose_file}" pull fixture-proxy nginx
echo "Starting the fixture and control plane."
MCP_CONFORMANCE_TOKEN=bootstrap-only \
  "${script_dir}/start-fixture-and-control-plane.sh"
echo "Registering the fixture through the control plane."
MCP_CONFORMANCE_TOKEN=bootstrap-only \
  "${script_dir}/register-fixture.sh"

set -a
# shellcheck disable=SC1090
source "${GITHUB_ENV}"
set +a

echo "Starting the built-in Python data plane and nginx."
"${script_dir}/start-builtin-dataplane-and-nginx.sh"
read -r -a spec_versions <<< "${MCP_CONFORMANCE_SPEC_VERSIONS}"
overall_status=0
for spec_version in "${spec_versions[@]}"; do
  export MCP_CONFORMANCE_SPEC_VERSION="${spec_version}"
  export MCP_CONFORMANCE_RESULTS_DIR
  MCP_CONFORMANCE_RESULTS_DIR="$(mktemp -d "${repo_root}/conformance-results/${spec_version}.XXXXXX")"
  : > "${GITHUB_OUTPUT}"

  echo "Running MCP ${MCP_CONFORMANCE_SPEC_VERSION} conformance."
  "${script_dir}/run-conformance.sh"

  runner_status="$(sed -n 's/^status=//p' "${GITHUB_OUTPUT}" | tail -n 1)"
  if [ -z "${runner_status}" ]; then
    echo "Conformance runner did not report a status for ${MCP_CONFORMANCE_SPEC_VERSION}." >&2
    exit 1
  fi

  set +e
  if [ "${MCP_CONFORMANCE_BLESS:-false}" = "true" ]; then
    "${script_dir}/report-baseline-diff.sh" --bless "${MCP_CONFORMANCE_RESULTS_DIR}"
  else
    "${script_dir}/report-baseline-diff.sh" "${MCP_CONFORMANCE_RESULTS_DIR}"
  fi
  report_status="$?"
  set -e

  if [ "${runner_status}" -ne 0 ] && [ "${report_status}" -eq 0 ]; then
    echo "Official runner status ${runner_status} contained no Python data-plane baseline mismatch for ${MCP_CONFORMANCE_SPEC_VERSION}."
  fi
  if [ "${report_status}" -ne 0 ]; then
    overall_status="${report_status}"
  fi
done
exit "${overall_status}"
