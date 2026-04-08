#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
LOCUSTFILE="${CORE_AUTH_BENCH_LOCUSTFILE:-${ROOT_DIR}/tests/loadtest/locustfile_core_auth.py}"
PYTHON_HOST="${CORE_AUTH_BENCH_PYTHON_HOST:-}"
RUST_HOST="${CORE_AUTH_BENCH_RUST_HOST:-}"
STUB_HOST="${CORE_AUTH_BENCH_STUB_HOST:-}"
RUST_HEALTH_URL="${CORE_AUTH_BENCH_RUST_HEALTH_URL:-}"
STUB_HEALTH_URL="${CORE_AUTH_BENCH_STUB_HEALTH_URL:-}"
LANE="${CORE_AUTH_BENCH_LANE:-session_jwt}"
USERS="${CORE_AUTH_BENCH_USERS:-125}"
SPAWN_RATE="${CORE_AUTH_BENCH_SPAWN_RATE:-30}"
RUN_TIME="${CORE_AUTH_BENCH_RUN_TIME:-60s}"
HTML_DIR="${CORE_AUTH_BENCH_HTML_DIR:-${ROOT_DIR}/reports/core_auth_endpoint_compare}"
CSV_DIR="${CORE_AUTH_BENCH_CSV_DIR:-${ROOT_DIR}/reports/core_auth_endpoint_compare}"

if [[ -z "${PYTHON_HOST}" || -z "${RUST_HOST}" ]]; then
  echo "CORE_AUTH_BENCH_PYTHON_HOST and CORE_AUTH_BENCH_RUST_HOST are required" >&2
  exit 1
fi

mkdir -p "${HTML_DIR}" "${CSV_DIR}"

read_stats_json() {
  local url="$1"
  if [[ -z "${url}" ]]; then
    return 0
  fi
  curl -fsS "${url}" | python3 -c 'import json,sys; print(json.dumps(json.load(sys.stdin).get("auth_stats", {})))'
}

run_one() {
  local label="$1"
  local host="$2"
  local mode="$3"
  local health_url="${4:-}"
  local before_json=""
  if [[ -n "${health_url}" ]]; then
    before_json="$(read_stats_json "${health_url}")"
  fi
  LOCUST_LOG_LEVEL="${LOCUST_LOG_LEVEL:-ERROR}" \
  CORE_AUTH_BENCH_LANE="${LANE}" \
  CORE_AUTH_BENCH_MODE="${mode}" \
  locust -f "${LOCUSTFILE}" \
    --host="${host}" \
    --headless \
    --users="${USERS}" \
    --spawn-rate="${SPAWN_RATE}" \
    --run-time="${RUN_TIME}" \
    --exit-code-on-error 0 \
    --html "${HTML_DIR}/locust_${label}.html" \
    --csv "${CSV_DIR}/locust_${label}" \
    CoreAuthUser

  if [[ -n "${health_url}" ]]; then
    local after_json
    after_json="$(read_stats_json "${health_url}")"
    BEFORE_JSON="${before_json}" AFTER_JSON="${after_json}" LABEL="${label}" python3 - <<'PY'
import json
import os
import sys

before = json.loads(os.environ["BEFORE_JSON"])
after = json.loads(os.environ["AFTER_JSON"])
label = os.environ["LABEL"]
direct_delta = after.get("direct_auth_responses", 0) - before.get("direct_auth_responses", 0)
proxied_delta = after.get("proxied_auth_responses", 0) - before.get("proxied_auth_responses", 0)
if proxied_delta != 0:
    print(f"{label} benchmark used proxy fallback: proxied delta={proxied_delta}", file=sys.stderr)
    sys.exit(1)
if direct_delta <= 0:
    print(f"{label} benchmark did not record direct auth responses", file=sys.stderr)
    sys.exit(1)
PY
  fi
}

run_one "python" "${PYTHON_HOST}" "python_internal"
run_one "rust" "${RUST_HOST}" "rust_sidecar" "${RUST_HEALTH_URL}"
if [[ -n "${STUB_HOST}" ]]; then
  run_one "stub" "${STUB_HOST}" "rust_sidecar" "${STUB_HEALTH_URL}"
fi

CSV_DIR="${CSV_DIR}" HAVE_STUB="$([[ -n "${STUB_HOST}" ]] && echo 1 || echo 0)" python3 - <<'PY'
import csv
import os
from pathlib import Path

csv_dir = Path(os.environ["CSV_DIR"])

def load_totals(prefix: str):
    stats_path = csv_dir / f"locust_{prefix}_stats.csv"
    with stats_path.open("r", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            if row.get("Name") == "Aggregated":
                return row
    raise RuntimeError(f"missing Aggregated row in {stats_path}")

python = load_totals("python")
rust = load_totals("rust")
stub = load_totals("stub") if os.environ.get("HAVE_STUB") == "1" else None

print("")
print("| Lane | Requests | Failures | RPS | p50 (ms) | p95 (ms) | p99 (ms) | Avg (ms) |")
print("| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |")
rows = [("Python core auth", python), ("Rust auth sidecar", rust)]
if stub:
    rows.append(("No-auth ceiling", stub))
for label, row in rows:
    print(
        f"| {label} | {row.get('Request Count')} | {row.get('Failure Count')} | "
        f"{row.get('Requests/s')} | {row.get('50%')} | {row.get('95%')} | "
        f"{row.get('99%')} | {row.get('Average Response Time')} |"
    )
if stub:
    rust_avg = float(rust.get("Average Response Time") or 0)
    stub_avg = float(stub.get("Average Response Time") or 0)
    if rust_avg > 0:
        auth_share = max(rust_avg - stub_avg, 0.0) / rust_avg * 100.0
        print("")
        print(f"Estimated auth share of Rust lane avg latency: {auth_share:.2f}%")
PY
