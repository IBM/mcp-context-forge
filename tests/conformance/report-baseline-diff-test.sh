#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
reporter="${script_dir}/report-baseline-diff.sh"
state_dir="$(mktemp -d "${TMPDIR:-/tmp}/contextforge-baseline-test.XXXXXX")"
suite_dir="${state_dir}/suite"
results_dir="${state_dir}/results"
baseline_file="${state_dir}/baseline.yml"
upstream_file="${state_dir}/upstream-fixture-failures.yml"
summary_file="${state_dir}/summary.md"

progress_exclusion_count="$(grep --count '^-[[:space:]]\{2\}- tools-call-with-progress$' "${script_dir}/disable-flaky-progress.patch" || true)"
if [ "${progress_exclusion_count}" -ne 2 ]; then
  echo 'The flaky progress scenario must be excluded from both requirement sets' >&2
  exit 1
fi
for inventory_file in \
  "${script_dir}/baseline-2025-11-25.yml" \
  "${script_dir}/baseline-2026-07-28.yml" \
  "${script_dir}/upstream-fixture-failures-2026-07-28.yml"; do
  if grep --quiet 'tools-call-with-progress' "${inventory_file}"; then
    echo "Excluded progress scenario must not appear in ${inventory_file}" >&2
    exit 1
  fi
done

cleanup() {
  rm -rf -- "${state_dir}"
}
trap cleanup EXIT INT TERM

mkdir -p "${suite_dir}/requirements" "${results_dir}"

cat > "${suite_dir}/requirements/2026-07-28.yaml" <<'EOF'
server:
  - expected-check
  - expected-whole
  - regression
  - xpass-check
  - xpass-whole
  - absent-check
  - upstream
  - duplicate
  - normal-pass
  - skip-only
EOF

cat > "${baseline_file}" <<'EOF'
server:
  - expected-check:known
  - expected-whole
  - xpass-check:fixed
  - xpass-whole
  - absent-check:not-emitted
EOF

cat > "${upstream_file}" <<'EOF'
server:
  - upstream:fixture-defect
EOF

write_checks() {
  scenario="$1"
  checks="$2"
  result_dir="${results_dir}/server-${scenario}-2026-08-18T12-00-00-000Z"
  mkdir -p "${result_dir}"
  printf '%s\n' "${checks}" > "${result_dir}/checks.json"
}

write_checks expected-check '[{"id":"known","status":"FAILURE"}]'
write_checks expected-whole '[{"id":"any-failure","status":"WARNING"}]'
write_checks regression '[{"id":"new-failure","status":"FAILURE"}]'
write_checks xpass-check '[{"id":"fixed","status":"SUCCESS"}]'
write_checks xpass-whole '[{"id":"all-good","status":"SUCCESS"}]'
write_checks absent-check '[{"id":"other","status":"SUCCESS"}]'
write_checks upstream '[{"id":"fixture-defect","status":"FAILURE","errorMessage":"must not be reported as a dataplane failure"}]'
write_checks duplicate '[{"id":"repeated","status":"FAILURE"},{"id":"repeated","status":"SUCCESS"}]'
write_checks normal-pass '[{"id":"good","status":"SUCCESS"},{"id":"not-applicable","status":"SKIPPED"}]'
write_checks skip-only '[{"id":"not-applicable","status":"SKIPPED"}]'

assert_contains() {
  haystack="$1"
  needle="$2"
  if [[ "${haystack}" != *"${needle}"* ]]; then
    echo "Expected output to contain: ${needle}" >&2
    echo "${haystack}" >&2
    exit 1
  fi
}

assert_not_contains() {
  haystack="$1"
  needle="$2"
  if [[ "${haystack}" == *"${needle}"* ]]; then
    echo "Expected output not to contain: ${needle}" >&2
    echo "${haystack}" >&2
    exit 1
  fi
}

assert_status() {
  haystack="$1"
  scenario="$2"
  expected_status="$3"
  matching_line=""
  while IFS= read -r line; do
    if [[ "${line}" == "${scenario}".* ]]; then
      matching_line="${line}"
      break
    fi
  done <<< "${haystack}"
  if [[ "${matching_line}" != *"${expected_status}" ]]; then
    echo "Expected ${scenario} to have status ${expected_status}" >&2
    echo "${haystack}" >&2
    exit 1
  fi
}

set +e
output="$(
  GITHUB_ACTIONS=true \
  GITHUB_STEP_SUMMARY="${summary_file}" \
  MCP_CONFORMANCE_COLOR=never \
  MCP_CONFORMANCE_SUITE_DIR="${suite_dir}" \
    "${reporter}" "${results_dir}" "${baseline_file}" "${upstream_file}" 2>&1
)"
status="$?"
set -e

if [ "${status}" -ne 1 ]; then
  echo "Expected mismatch status 1, got ${status}" >&2
  echo "${output}" >&2
  exit 1
fi

assert_status "${output}" expected-check:known XFail
assert_status "${output}" expected-whole:any-failure XFail
assert_status "${output}" regression:new-failure Failed
assert_status "${output}" xpass-check:fixed Failed
assert_status "${output}" xpass-whole:all-good Failed
assert_status "${output}" absent-check:other Passed
assert_status "${output}" upstream:fixture-defect Upstream
assert_status "${output}" duplicate:repeated Failed
assert_status "${output}" normal-pass:good Passed
assert_status "${output}" normal-pass:not-applicable Skipped
assert_status "${output}" skip-only:not-applicable Skipped
assert_contains "${output}" '2 passed, 2 xfailed, 4 failed, 1 upstream, 2 skipped (2 baselined)'
assert_not_contains "${output}" '::error title=Expected conformance pass failed::upstream:fixture-defect'

set +e
color_output="$(
  NO_COLOR='' \
  MCP_CONFORMANCE_COLOR=always \
  MCP_CONFORMANCE_SUITE_DIR="${suite_dir}" \
    "${reporter}" "${results_dir}" "${baseline_file}" "${upstream_file}" 2>&1
)"
color_status="$?"
set -e
if [ "${color_status}" -ne 1 ]; then
  echo "Expected color-output mismatch status 1, got ${color_status}" >&2
  exit 1
fi
assert_contains "${color_output}" $'\033[32mPassed\033[0m'
assert_contains "${color_output}" $'\033[31mFailed\033[0m'
assert_contains "${color_output}" $'\033[33mXFail\033[0m'
assert_contains "${color_output}" $'\033[36mUpstream\033[0m'

summary="$(cat "${summary_file}")"
assert_contains "${summary}" '| Pinned fixture findings ignored | 1 |'
assert_not_contains "${summary}" 'upstream:fixture-defect'

cat > "${state_dir}/unmatched-upstream.yml" <<'EOF'
server:
  - never-seen:fixture-defect
EOF
set +e
unmatched_upstream_output="$(
  MCP_CONFORMANCE_COLOR=never \
  MCP_CONFORMANCE_SUITE_DIR="${suite_dir}" \
    "${reporter}" \
      "${results_dir}" \
      "${baseline_file}" \
      "${state_dir}/unmatched-upstream.yml" 2>&1
)"
unmatched_upstream_status="$?"
set -e
if [ "${unmatched_upstream_status}" -ne 1 ]; then
  echo "Expected unmatched-upstream status 1, got ${unmatched_upstream_status}" >&2
  exit 1
fi
assert_status "${unmatched_upstream_output}" upstream:fixture-defect Failed

echo 'server: []' > "${state_dir}/empty-baseline.yml"
set +e
empty_baseline_output="$(
  MCP_CONFORMANCE_COLOR=never \
  MCP_CONFORMANCE_SUITE_DIR="${suite_dir}" \
    "${reporter}" \
      "${results_dir}" \
      "${state_dir}/empty-baseline.yml" \
      "${upstream_file}" 2>&1
)"
empty_baseline_status="$?"
set -e
if [ "${empty_baseline_status}" -ne 1 ]; then
  echo "Expected empty-baseline status 1, got ${empty_baseline_status}" >&2
  exit 1
fi
assert_status "${empty_baseline_output}" regression:new-failure Failed

bless_output="$(
  MCP_CONFORMANCE_COLOR=never \
  MCP_CONFORMANCE_SUITE_DIR="${suite_dir}" \
    "${reporter}" --bless "${results_dir}" "${baseline_file}" "${upstream_file}"
)"
assert_status "${bless_output}" expected-check:known XFail
assert_status "${bless_output}" regression:new-failure XFail
assert_contains "${bless_output}" '4 passed, 4 xfailed, 0 failed, 1 upstream, 2 skipped (4 baselined)'

cat > "${state_dir}/expected-after-bless.yml" <<'EOF'
# Generated by `make conformance-bless` from scored Python data-plane findings.
# Pinned fixture findings are excluded; see upstream-fixture-failures-2026-07-28.yml.
server:
  - duplicate:repeated
  - expected-check:known
  - expected-whole:any-failure
  - regression:new-failure
EOF
diff -u "${state_dir}/expected-after-bless.yml" "${baseline_file}"

MCP_CONFORMANCE_COLOR=never \
MCP_CONFORMANCE_SUITE_DIR="${suite_dir}" \
  "${reporter}" "${results_dir}" "${baseline_file}" "${upstream_file}" > /dev/null

baseline_before_missing="$(cat "${baseline_file}")"
set +e
MCP_CONFORMANCE_COLOR=never \
MCP_CONFORMANCE_SUITE_DIR="${suite_dir}" \
  "${reporter}" --bless "${state_dir}/missing" "${baseline_file}" "${upstream_file}" > /dev/null 2>&1
missing_status="$?"
set -e

if [ "${missing_status}" -ne 2 ]; then
  echo "Expected missing-results status 2, got ${missing_status}" >&2
  exit 1
fi
if [ "$(cat "${baseline_file}")" != "${baseline_before_missing}" ]; then
  echo 'Bless changed the baseline without results' >&2
  exit 1
fi

echo 'conformance reporter tests passed'
