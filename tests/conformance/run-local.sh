#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd -- "${script_dir}/../.." && pwd)"
compose_file="${script_dir}/docker-compose.yml"
suite_patch="${script_dir}/disable-flaky-progress.patch"
suite_patch_applied=false

export MCP_CONFORMANCE_VERSION="${MCP_CONFORMANCE_VERSION:-0.2.0-alpha.11}"
export MCP_CONFORMANCE_SOURCE_SHA="${MCP_CONFORMANCE_SOURCE_SHA:-c321dd32035556e6769d3724a8ee97d87c3faaac}"
export MCP_CONFORMANCE_SPEC_VERSIONS="${MCP_CONFORMANCE_SPEC_VERSIONS:-2025-11-25 2026-07-28}"
export MCP_CONFORMANCE_SERVER_ID="${MCP_CONFORMANCE_SERVER_ID:-3f33286667d34b65a31c3bafd30e4c21}"
export MCP_CONFORMANCE_SUITE_DIR="${MCP_CONFORMANCE_SUITE_DIR:-${repo_root}/.conformance-suite}"
export CF_CONTEXTFORGE_IMAGE="${CF_CONTEXTFORGE_IMAGE:-mcpgateway/mcpgateway:conformance}"
export MCP_CONFORMANCE_COLOR="${MCP_CONFORMANCE_COLOR:-auto}"
log_dir="${repo_root}/conformance-logs"
setup_log="${log_dir}/local-setup.log"
run_lock_dir="${log_dir}/run.lock"

mkdir -p "${log_dir}" "${repo_root}/conformance-results"
if ! mkdir "${run_lock_dir}" 2>/dev/null; then
  echo "Another local conformance run is already active." >&2
  exit 1
fi
progress_enabled=false
progress_pid=""
if [ -t 1 ]; then
  progress_enabled=true
fi

clear_progress() {
  if "${progress_enabled}"; then
    printf '\r\033[2K'
  fi
}

start_progress() {
  local description="$1"
  if ! "${progress_enabled}"; then
    return
  fi

  (
    trap 'exit 0' INT TERM
    local frames=('⠋' '⠙' '⠹' '⠸' '⠼' '⠴' '⠦' '⠧' '⠇' '⠏')
    local frame_index=0
    while true; do
      printf '\r\033[2KConformance %s %s' "${frames[frame_index]}" "${description}"
      frame_index=$(((frame_index + 1) % ${#frames[@]}))
      sleep 0.15
    done
  ) &
  progress_pid="$!"
}

stop_progress() {
  if [ -n "${progress_pid}" ]; then
    kill "${progress_pid}" 2>/dev/null || true
    wait "${progress_pid}" 2>/dev/null || true
    progress_pid=""
  fi
  clear_progress
}

# shellcheck disable=SC2329 # Invoked by the EXIT and cleanup traps below.
release_run_lock() {
  rmdir -- "${run_lock_dir}" 2>/dev/null || true
}
# shellcheck disable=SC2329 # Invoked by the initial EXIT trap below.
initial_cleanup() {
  stop_progress
  release_run_lock
}
trap initial_cleanup EXIT INT TERM
: > "${setup_log}"

run_with_progress() {
  local description="$1"
  local output_file="$2"
  local status
  shift 2

  start_progress "${description}"
  if "$@" >> "${output_file}" 2>&1; then
    status=0
  else
    status="$?"
  fi
  stop_progress
  return "${status}"
}

run_quiet() {
  local description="$1"
  shift
  if ! run_with_progress "${description}" "${setup_log}" "$@"; then
    echo "Conformance setup failed while ${description}. See ${setup_log}." >&2
    exit 1
  fi
}

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
  run_quiet "checking out the official conformance suite" \
    git clone --filter=blob:none \
      https://github.com/modelcontextprotocol/conformance.git \
      "${MCP_CONFORMANCE_SUITE_DIR}"
  run_quiet "pinning the official conformance suite" \
    git -C "${MCP_CONFORMANCE_SUITE_DIR}" checkout --detach "${MCP_CONFORMANCE_SOURCE_SHA}"
fi

suite_sha="$(git -C "${MCP_CONFORMANCE_SUITE_DIR}" rev-parse HEAD)"
if [ "${suite_sha}" != "${MCP_CONFORMANCE_SOURCE_SHA}" ]; then
  echo "Conformance checkout is at ${suite_sha}; expected ${MCP_CONFORMANCE_SOURCE_SHA}." >&2
  echo "Use a checkout at the pinned commit or set MCP_CONFORMANCE_SUITE_DIR." >&2
  exit 1
fi

# shellcheck disable=SC2329 # Passed to run_quiet below.
install_suite_dependencies() (
  cd "${MCP_CONFORMANCE_SUITE_DIR}"
  test "$(node -p "require('./package.json').version")" = "${MCP_CONFORMANCE_VERSION}"
  npm ci --ignore-scripts
)
run_quiet "installing official dependencies" install_suite_dependencies

state_dir="$(mktemp -d "${TMPDIR:-/tmp}/contextforge-conformance.XXXXXX")"
export GITHUB_ENV="${state_dir}/github-env"
export GITHUB_OUTPUT="${state_dir}/github-output"
touch "${GITHUB_ENV}" "${GITHUB_OUTPUT}"

# shellcheck disable=SC2329 # Invoked by the trap below.
cleanup() {
  local status="$?"
  trap - EXIT INT TERM
  stop_progress
  if [ "${status}" -ne 0 ]; then
    MCP_CONFORMANCE_TOKEN=diagnostics-only \
      docker compose -f "${compose_file}" logs --no-color \
      > "${log_dir}/live-stack.log" 2>&1 || true
  fi
  MCP_CONFORMANCE_TOKEN="${MCP_CONFORMANCE_TOKEN:-cleanup-only}" \
    "${script_dir}/stop-live-stack.sh" >> "${setup_log}" 2>&1 || true
  if "${suite_patch_applied}"; then
    git -C "${MCP_CONFORMANCE_SUITE_DIR}" apply --reverse "${suite_patch}" \
      >> "${setup_log}" 2>&1 || true
  fi
  rm -f -- "${GITHUB_ENV}" "${GITHUB_OUTPUT}"
  rmdir -- "${state_dir}"
  release_run_lock
  exit "${status}"
}
trap cleanup EXIT INT TERM

if git -C "${MCP_CONFORMANCE_SUITE_DIR}" apply --check "${suite_patch}" \
  >> "${setup_log}" 2>&1; then
  git -C "${MCP_CONFORMANCE_SUITE_DIR}" apply "${suite_patch}" \
    >> "${setup_log}" 2>&1
  suite_patch_applied=true
elif ! git -C "${MCP_CONFORMANCE_SUITE_DIR}" apply --reverse --check "${suite_patch}" \
  >> "${setup_log}" 2>&1; then
  echo "Conformance scenario patch does not apply cleanly to ${MCP_CONFORMANCE_SOURCE_SHA}." >&2
  exit 1
fi

run_quiet "pulling conformance images" \
  env MCP_CONFORMANCE_TOKEN=pull-only \
  docker compose -f "${compose_file}" pull fixture-proxy nginx
run_quiet "starting the fixture and control plane" \
  env MCP_CONFORMANCE_TOKEN=bootstrap-only \
  "${script_dir}/start-fixture-and-control-plane.sh"
run_quiet "registering the fixture" \
  env MCP_CONFORMANCE_TOKEN=bootstrap-only \
  "${script_dir}/register-fixture.sh"

set -a
# shellcheck disable=SC1090
source "${GITHUB_ENV}"
set +a

run_quiet "starting the Python data plane" \
  "${script_dir}/start-builtin-dataplane-and-nginx.sh"
read -r -a spec_versions <<< "${MCP_CONFORMANCE_SPEC_VERSIONS}"
overall_status=0
for spec_version in "${spec_versions[@]}"; do
  export MCP_CONFORMANCE_SPEC_VERSION="${spec_version}"
  export MCP_CONFORMANCE_RESULTS_DIR
  MCP_CONFORMANCE_RESULTS_DIR="$(mktemp -d "${repo_root}/conformance-results/${spec_version}.XXXXXX")"
  : > "${GITHUB_OUTPUT}"

  if ! run_with_progress \
    "running MCP ${MCP_CONFORMANCE_SPEC_VERSION} checks" \
    "${log_dir}/runner-${MCP_CONFORMANCE_SPEC_VERSION}.log" \
    "${script_dir}/run-conformance.sh"; then
    echo "Conformance runner failed for ${MCP_CONFORMANCE_SPEC_VERSION}. See ${log_dir}/runner-${MCP_CONFORMANCE_SPEC_VERSION}.log." >&2
    exit 1
  fi

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

  if [ "${report_status}" -ne 0 ]; then
    overall_status="${report_status}"
  fi
done
exit "${overall_status}"
