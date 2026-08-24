#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: report-baseline-diff.sh [--bless] [results-dir [baseline-file [upstream-file]]]

Compare scored MCP conformance checks with the expected-failure baseline.
With --bless, replace the baseline with the current Python data-plane findings.
EOF
}

bless=false
case "${1:-}" in
  --bless)
    bless=true
    shift
    ;;
  --help|-h)
    usage
    exit 0
    ;;
esac

if [ "$#" -gt 3 ]; then
  usage >&2
  exit 2
fi

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd -- "${script_dir}/../.." && pwd)"
results_dir="${1:-${repo_root}/conformance-results}"
suite_dir="${MCP_CONFORMANCE_SUITE_DIR:-${repo_root}/.conformance-suite}"
spec_version="${MCP_CONFORMANCE_SPEC_VERSION:-2026-07-28}"
baseline_file="${2:-${script_dir}/expected-failures-${spec_version}.yml}"
upstream_file="${3:-${script_dir}/upstream-fixture-failures-${spec_version}.yml}"
requirements_file="${suite_dir}/requirements/${spec_version}.yaml"

for command in awk cmp cp cut find grep jq sed sort wc; do
  if ! command -v "${command}" > /dev/null 2>&1; then
    echo "Required command not found: ${command}" >&2
    exit 2
  fi
done

for required_file in "${baseline_file}" "${upstream_file}" "${requirements_file}"; do
  if [ ! -f "${required_file}" ]; then
    echo "Required conformance file not found: ${required_file}" >&2
    exit 2
  fi
done

color_mode="${MCP_CONFORMANCE_COLOR:-${CARGO_TERM_COLOR:-auto}}"
case "${color_mode}" in
  always)
    use_color=true
    ;;
  never)
    use_color=false
    ;;
  auto)
    if [ -t 1 ] && [ "${TERM:-}" != "dumb" ] && [ -z "${NO_COLOR:-}" ]; then
      use_color=true
    else
      use_color=false
    fi
    ;;
  *)
    echo "MCP_CONFORMANCE_COLOR must be auto, always, or never; got: ${color_mode}" >&2
    exit 2
    ;;
esac

if [ -n "${NO_COLOR:-}" ]; then
  use_color=false
fi

if ${use_color}; then
  bold=$'\033[1m'
  dim=$'\033[2m'
  red=$'\033[31m'
  green=$'\033[32m'
  yellow=$'\033[33m'
  cyan=$'\033[36m'
  reset=$'\033[0m'
else
  bold=""
  dim=""
  red=""
  green=""
  yellow=""
  cyan=""
  reset=""
fi

state_dir="$(mktemp -d "${TMPDIR:-/tmp}/contextforge-baseline-diff.XXXXXX")"
actual_checks="${state_dir}/actual-checks.tsv"
actual_findings="${state_dir}/actual-findings.tsv"
actual_keys="${state_dir}/actual-keys.txt"
baseline_entries="${state_dir}/baseline-entries.txt"
upstream_entries="${state_dir}/upstream-entries.txt"
scored_scenarios="${state_dir}/scored-scenarios.txt"
executed_scenarios="${state_dir}/executed-scenarios.txt"
owned_findings="${state_dir}/owned-findings.txt"
expected_entries="${state_dir}/expected-entries.txt"
unexpected_entries="${state_dir}/unexpected-entries.txt"
stale_entries="${state_dir}/stale-entries.txt"
upstream_matches="${state_dir}/upstream-matches.txt"
passing_checks="${state_dir}/passing-checks.txt"
skipped_checks="${state_dir}/skipped-checks.txt"
baseline_candidate="${state_dir}/expected-failures.yml"

cleanup() {
  rm -f -- \
    "${actual_checks}" \
    "${actual_findings}" \
    "${actual_keys}" \
    "${baseline_entries}" \
    "${upstream_entries}" \
    "${scored_scenarios}" \
    "${executed_scenarios}" \
    "${owned_findings}" \
    "${expected_entries}" \
    "${unexpected_entries}" \
    "${stale_entries}" \
    "${upstream_matches}" \
    "${passing_checks}" \
    "${skipped_checks}" \
    "${baseline_candidate}"
  rmdir -- "${state_dir}"
}
trap cleanup EXIT INT TERM

read_baseline() {
  awk '
    /^[[:space:]]*-[[:space:]]+/ {
      line = $0
      sub(/^[[:space:]]*-[[:space:]]+/, "", line)
      sub(/[[:space:]]+#.*$/, "", line)
      print line
    }
  ' "$1" | LC_ALL=C sort -u
}

line_count() {
  wc -l < "$1" | tr -d '[:space:]'
}

print_row() {
  local color="$1"
  local label="$2"
  local message="$3"
  printf '  %b%10s%b %s\n' "${color}${bold}" "${label}" "${reset}" "${message}"
}

emit_error() {
  local title="$1"
  local message="$2"
  if [ "${GITHUB_ACTIONS:-}" = "true" ]; then
    echo "::error title=${title}::${message}"
  fi
}

write_missing_results_summary() {
  local message="$1"
  print_row "${red}" "ERROR" "${message}"
  emit_error "Conformance results missing" "${message}"
  if [ -n "${GITHUB_STEP_SUMMARY:-}" ]; then
    printf '## MCP %s conformance\n\n❌ %s\n' "${spec_version}" "${message}" \
      >> "${GITHUB_STEP_SUMMARY}"
  fi
}

awk '
  /^server:$/ { in_server = 1; next }
  in_server && /^[^[:space:]]/ { exit }
  in_server && /^[[:space:]]*-[[:space:]]+/ {
    line = $0
    sub(/^[[:space:]]*-[[:space:]]+/, "", line)
    print line
  }
' "${requirements_file}" | LC_ALL=C sort -u > "${scored_scenarios}"

read_baseline "${baseline_file}" > "${baseline_entries}"
read_baseline "${upstream_file}" > "${upstream_entries}"

printf '\n%bMCP conformance%b %b(%s)%b\n' "${bold}" "${reset}" "${dim}" "${spec_version}" "${reset}"

if [ ! -d "${results_dir}" ]; then
  write_missing_results_summary "No results directory: ${results_dir}"
  exit 2
fi

: > "${actual_checks}"
: > "${executed_scenarios}"
while IFS= read -r -d '' checks_file; do
  result_name="$(basename -- "$(dirname -- "${checks_file}")")"
  if [[ ! "${result_name}" =~ ^server-(.*)-[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}-[0-9]{2}-[0-9]{2}-[0-9]{3}Z$ ]]; then
    echo "Skipping unrecognized result directory: ${result_name}" >&2
    continue
  fi
  scenario="${BASH_REMATCH[1]}"

  if ! grep --fixed-strings --line-regexp --quiet -- "${scenario}" "${scored_scenarios}"; then
    continue
  fi

  echo "${scenario}" >> "${executed_scenarios}"
  jq --raw-output --arg scenario "${scenario}" '
    def severity($status):
      if $status == "FAILURE" then 3
      elif $status == "WARNING" then 2
      elif $status == "SUCCESS" then 1
      else 0
      end;

    reduce (.[] | select(.status != "INFO")) as $check
      ({};
       ($check.id) as $id |
       if .[$id] == null or severity($check.status) >= severity(.[$id].status)
       then .[$id] = $check
       else .
       end) |
    to_entries[] |
    [($scenario + ":" + .key), .value.status, (.value.errorMessage // "")] |
    @tsv
  ' "${checks_file}" >> "${actual_checks}"
done < <(find "${results_dir}" -type f -name checks.json -print0)

LC_ALL=C sort -u -o "${executed_scenarios}" "${executed_scenarios}"
if [ ! -s "${executed_scenarios}" ]; then
  write_missing_results_summary "No scored conformance results were found in ${results_dir}"
  exit 2
fi

LC_ALL=C sort -u -o "${actual_checks}" "${actual_checks}"
awk -F '\t' '$2 == "FAILURE" || $2 == "WARNING"' "${actual_checks}" > "${actual_findings}"
cut -f 1 "${actual_findings}" | LC_ALL=C sort -u > "${actual_keys}"
awk -F '\t' '$2 == "SUCCESS" { print $1 }' "${actual_checks}" | LC_ALL=C sort -u > "${passing_checks}"
awk -F '\t' '$2 == "SKIPPED" { print $1 }' "${actual_checks}" | LC_ALL=C sort -u > "${skipped_checks}"

# Pinned fixture findings are informational: they neither satisfy the Python
# data-plane baseline nor count as unexpected implementation failures.
awk -v upstream_file="${upstream_entries}" '
  FILENAME == upstream_file {
    upstream[$1] = 1
    next
  }
  {
    scenario = $1
    sub(/:.*/, "", scenario)
    if (($1 in upstream) || (scenario in upstream)) print $1
  }
' "${upstream_entries}" "${actual_keys}" | LC_ALL=C sort -u > "${upstream_matches}"

awk -v upstream_file="${upstream_matches}" '
  FILENAME == upstream_file { upstream[$1] = 1; next }
  !($1 in upstream) { print $1 }
' "${upstream_matches}" "${actual_keys}" > "${owned_findings}"

bless_changed=false
if ${bless}; then
  {
    # shellcheck disable=SC2016 # Backticks are literal Markdown.
    echo '# Generated by `make conformance-bless` from scored Python data-plane findings.'
    echo "# Pinned fixture findings are excluded; see upstream-fixture-failures-${spec_version}.yml."
    if [ -s "${owned_findings}" ]; then
      echo 'server:'
      sed 's/^/  - /' "${owned_findings}"
    else
      echo 'server: []'
    fi
  } > "${baseline_candidate}"

  if ! cmp --silent "${owned_findings}" "${baseline_entries}"; then
    cp "${baseline_candidate}" "${baseline_file}"
    bless_changed=true
  fi
  read_baseline "${baseline_file}" > "${baseline_entries}"
fi

# Match actual owned findings against exact or whole-scenario baseline entries.
awk -v baseline_file="${baseline_entries}" '
  FILENAME == baseline_file {
    baseline[$1] = 1
    if (index($1, ":") == 0) whole[$1] = 1
    next
  }
  {
    scenario = $1
    sub(/:.*/, "", scenario)
    if (scenario in whole) matched[scenario] = 1
    else if ($1 in baseline) matched[$1] = 1
  }
  END {
    for (entry in matched) print entry
  }
' "${baseline_entries}" "${owned_findings}" | LC_ALL=C sort -u > "${expected_entries}"

awk -v baseline_file="${baseline_entries}" '
  FILENAME == baseline_file {
    baseline[$1] = 1
    if (index($1, ":") == 0) whole[$1] = 1
    next
  }
  {
    scenario = $1
    sub(/:.*/, "", scenario)
    if (!(($1 in baseline) || (scenario in whole))) print $1
  }
' "${baseline_entries}" "${owned_findings}" > "${unexpected_entries}"

# An exact baseline entry is stale only after a demonstrated SUCCESS. Missing
# and SKIPPED checks carry no pass signal. A whole-scenario entry is stale when
# the scenario ran without any Python data-plane finding.
awk -F '\t' \
  -v checks_file="${actual_checks}" \
  -v scenarios_file="${executed_scenarios}" \
  -v findings_file="${owned_findings}" '
    FILENAME == checks_file { status[$1] = $2; next }
    FILENAME == scenarios_file { executed[$1] = 1; next }
    FILENAME == findings_file {
      scenario = $1
      sub(/:.*/, "", scenario)
      failed[scenario] = 1
      next
    }
    index($1, ":") == 0 {
      if (($1 in executed) && !($1 in failed)) print $1
      next
    }
    status[$1] == "SUCCESS" { print $1 }
  ' "${actual_checks}" "${executed_scenarios}" "${owned_findings}" "${baseline_entries}" \
  | LC_ALL=C sort -u > "${stale_entries}"

pass_count="$(line_count "${passing_checks}")"
skip_count="$(line_count "${skipped_checks}")"
expected_count="$(line_count "${expected_entries}")"
unexpected_count="$(line_count "${unexpected_entries}")"
stale_count="$(line_count "${stale_entries}")"
upstream_count="$(line_count "${upstream_matches}")"

print_row "${green}" "PASS" "${pass_count} scored checks passed"

while IFS= read -r key; do
  [ -n "${key}" ] || continue
  print_row "${yellow}" "XFAIL" "${key} ${dim}(expected failure reproduced)${reset}"
done < "${expected_entries}"

while IFS= read -r key; do
  [ -n "${key}" ] || continue
  print_row "${cyan}" "UPSTREAM" "${key} ${dim}(ignored pinned-fixture finding)${reset}"
done < "${upstream_matches}"

while IFS= read -r key; do
  [ -n "${key}" ] || continue
  status="$(awk -F '\t' -v key="${key}" '$1 == key { print $2; exit }' "${actual_findings}")"
  print_row "${red}" "FAIL" "${key} ${dim}(expected PASS, got ${status})${reset}"
  emit_error "Expected conformance pass failed" "${key}"
done < "${unexpected_entries}"

while IFS= read -r key; do
  [ -n "${key}" ] || continue
  print_row "${red}" "XPASS" "${key} ${dim}(expected FAILURE, got PASS)${reset}"
  emit_error "Expected conformance failure passed" "${key}"
done < "${stale_entries}"

if [ "${skip_count}" -gt 0 ]; then
  print_row "${dim}" "SKIP" "${skip_count} scored checks skipped"
fi

if ${bless}; then
  if ${bless_changed}; then
    print_row "${green}" "BLESS" "updated ${baseline_file}"
  else
    print_row "${green}" "BLESS" "${baseline_file} was already current"
  fi
fi

printf '\n%bSummary%b: %s passed, %s expected failures, %s upstream findings ignored, %s failed, %s unexpected passes\n' \
  "${bold}" "${reset}" \
  "${pass_count}" "${expected_count}" "${upstream_count}" "${unexpected_count}" "${stale_count}"

if [ -n "${GITHUB_STEP_SUMMARY:-}" ]; then
  {
    echo "## MCP ${spec_version} conformance"
    echo
    echo '| Outcome | Count |'
    echo '| --- | ---: |'
    echo "| Scored checks passed | ${pass_count} |"
    echo "| Expected failures reproduced | ${expected_count} |"
    echo "| Pinned fixture findings ignored | ${upstream_count} |"
    echo "| Expected pass, got failure | ${unexpected_count} |"
    echo "| Expected failure, got pass | ${stale_count} |"
    echo "| Skipped checks | ${skip_count} |"

    if [ "${unexpected_count}" -gt 0 ]; then
      echo
      echo '### Expected pass, got failure'
      while IFS= read -r key; do
        [ -n "${key}" ] || continue
        status="$(awk -F '\t' -v key="${key}" '$1 == key { print $2; exit }' "${actual_findings}")"
        echo "- \`${key}\` — ${status}"
      done < "${unexpected_entries}"
    fi

    if [ "${stale_count}" -gt 0 ]; then
      echo
      echo '### Expected failure, got pass'
      while IFS= read -r key; do
        [ -n "${key}" ] || continue
        echo "- \`${key}\`"
      done < "${stale_entries}"
    fi

    echo
    if ${bless}; then
      echo "✅ Expected-failure baseline updated with ${expected_count} Python data-plane findings."
    elif [ "${unexpected_count}" -eq 0 ] && [ "${stale_count}" -eq 0 ]; then
      echo '✅ Actual Python data-plane findings match the expected-failure baseline.'
    else
      echo '❌ Actual Python data-plane findings do not match the expected-failure baseline.'
    fi
  } >> "${GITHUB_STEP_SUMMARY}"
fi

if ${bless}; then
  exit 0
fi

if [ "${unexpected_count}" -gt 0 ] || [ "${stale_count}" -gt 0 ]; then
  exit 1
fi
