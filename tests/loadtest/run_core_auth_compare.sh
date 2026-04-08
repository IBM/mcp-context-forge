#!/usr/bin/env bash
set -euo pipefail

# Focused MCP auth benchmark comparing proxy-only auth vs direct Rust auth.
#
# Reuses the existing MCP protocol Locust workload so the comparison stays on the
# same MCP transport path. Run this against two public MCP hosts:
#   1. proxy/core-only auth
#   2. Rust edge host backed by the auth service with
#      CONTEXTFORGE_AUTH_EXPERIMENTAL_DIRECT_AUTH=true
#
# IMPORTANT:
# MCP_AUTH_COMPARE_DIRECT_HOST must be a Rust edge-mounted public MCP host that
# serves /servers/{server_id}/mcp. A raw standalone runtime port is not a valid
# substitute because internal-dispatch guards will reject that path.
#
# Required env:
#   MCP_AUTH_COMPARE_PROXY_HOST
#   MCP_AUTH_COMPARE_DIRECT_HOST
#
# Optional env:
#   MCP_SERVER_ID
#   MCP_PROTOCOL_LOCUSTFILE
#   MCP_AUTH_COMPARE_USER_CLASS
#   MCP_AUTH_COMPARE_USERS
#   MCP_AUTH_COMPARE_SPAWN_RATE
#   MCP_AUTH_COMPARE_RUN_TIME
#   MCP_AUTH_COMPARE_HTML_DIR
#   MCP_AUTH_COMPARE_CSV_DIR
#   MCP_AUTH_COMPARE_ONLY
#   LOCUST_LOG_LEVEL

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
LOCUSTFILE="${MCP_PROTOCOL_LOCUSTFILE:-${ROOT_DIR}/tests/loadtest/locustfile_mcp_protocol.py}"
PROXY_HOST="${MCP_AUTH_COMPARE_PROXY_HOST:-}"
DIRECT_HOST="${MCP_AUTH_COMPARE_DIRECT_HOST:-}"
STUB_HOST="${MCP_AUTH_COMPARE_STUB_HOST:-}"
SERVER_ID="${MCP_SERVER_ID:-}"
USER_CLASS="${MCP_AUTH_COMPARE_USER_CLASS:-MCPInitializeOnlyUser}"
USERS="${MCP_AUTH_COMPARE_USERS:-125}"
SPAWN_RATE="${MCP_AUTH_COMPARE_SPAWN_RATE:-30}"
RUN_TIME="${MCP_AUTH_COMPARE_RUN_TIME:-60s}"
HTML_DIR="${MCP_AUTH_COMPARE_HTML_DIR:-${ROOT_DIR}/reports/core_auth_compare}"
CSV_DIR="${MCP_AUTH_COMPARE_CSV_DIR:-${ROOT_DIR}/reports/core_auth_compare}"
ONLY_MODE="${MCP_AUTH_COMPARE_ONLY:-}"
LOG_LEVEL="${LOCUST_LOG_LEVEL:-ERROR}"
RUST_AUTH_HEALTH_URL="${MCP_AUTH_COMPARE_RUST_AUTH_HEALTH_URL:-}"
STUB_AUTH_HEALTH_URL="${MCP_AUTH_COMPARE_STUB_AUTH_HEALTH_URL:-}"

if [[ -z "${PROXY_HOST}" && "${ONLY_MODE}" != "direct" ]]; then
  echo "MCP_AUTH_COMPARE_PROXY_HOST is required unless MCP_AUTH_COMPARE_ONLY=direct" >&2
  exit 1
fi

if [[ -z "${DIRECT_HOST}" && "${ONLY_MODE}" != "proxy" ]]; then
  echo "MCP_AUTH_COMPARE_DIRECT_HOST is required unless MCP_AUTH_COMPARE_ONLY=proxy" >&2
  exit 1
fi

if [[ ! -f "${LOCUSTFILE}" ]]; then
  echo "Locustfile not found: ${LOCUSTFILE}" >&2
  exit 1
fi

mkdir -p "${HTML_DIR}" "${CSV_DIR}"

run_one() {
  local label="$1"
  local host="$2"
  local health_url="${3:-}"
  local html_out="${HTML_DIR}/locust_${label}.html"
  local csv_prefix="${CSV_DIR}/locust_${label}"
  local before_json=""

  echo ""
  local display_label="${label}"
  if [[ "${label}" == "stub" ]]; then
    display_label="no-auth ceiling"
  fi

  echo "=== Running ${display_label} benchmark ==="
  echo "Host: ${host}"
  echo "User class: ${USER_CLASS}"
  echo "Users: ${USERS}"
  echo "Spawn rate: ${SPAWN_RATE}"
  echo "Run time: ${RUN_TIME}"

  if [[ -n "${health_url}" ]]; then
    before_json="$(curl -fsS "${health_url}" | python3 -c 'import json,sys; print(json.dumps(json.load(sys.stdin).get("auth_stats", {})))')"
  fi

  LOCUST_LOG_LEVEL="${LOG_LEVEL}" \
  MCP_SERVER_ID="${SERVER_ID}" \
  locust -f "${LOCUSTFILE}" \
    --host="${host}" \
    --headless \
    --users="${USERS}" \
    --spawn-rate="${SPAWN_RATE}" \
    --run-time="${RUN_TIME}" \
    --exit-code-on-error 0 \
    --html "${html_out}" \
    --csv "${csv_prefix}" \
    "${USER_CLASS}"

  if [[ -n "${health_url}" ]]; then
    local after_json
    after_json="$(curl -fsS "${health_url}" | python3 -c 'import json,sys; print(json.dumps(json.load(sys.stdin).get("auth_stats", {})))')"
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

if [[ "${ONLY_MODE}" != "direct" ]]; then
  run_one "proxy" "${PROXY_HOST}"
fi

if [[ "${ONLY_MODE}" != "proxy" ]]; then
  run_one "direct" "${DIRECT_HOST}" "${RUST_AUTH_HEALTH_URL}"
fi

if [[ -n "${STUB_HOST}" && "${ONLY_MODE}" != "proxy" ]]; then
  run_one "stub" "${STUB_HOST}" "${STUB_AUTH_HEALTH_URL}"
fi

CSV_DIR="${CSV_DIR}" HAVE_STUB="$([[ -n "${STUB_HOST}" ]] && echo 1 || echo 0)" ONLY_MODE="${ONLY_MODE}" python3 - <<'PY'
import csv
import os
from pathlib import Path

csv_dir = Path(os.environ["CSV_DIR"])
only_mode = os.environ.get("ONLY_MODE", "")

def load_totals(prefix: str):
    stats_path = csv_dir / f"locust_{prefix}_stats.csv"
    if not stats_path.exists():
        return None
    with stats_path.open("r", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            if row.get("Name") == "Aggregated":
                return row
    return None

proxy = None if only_mode == "direct" else load_totals("proxy")
direct = None if only_mode == "proxy" else load_totals("direct")
stub = load_totals("stub") if os.environ.get("HAVE_STUB") == "1" and only_mode != "proxy" else None

print("")
print("=== Core auth benchmark summary ===")
if proxy:
    print(
        "proxy : "
        f"rps={proxy.get('Requests/s')} "
        f"p95={proxy.get('95%')} "
        f"p99={proxy.get('99%')} "
        f"failures={proxy.get('Failure Count')}"
    )
if direct:
    print(
        "direct: "
        f"rps={direct.get('Requests/s')} "
        f"p95={direct.get('95%')} "
        f"p99={direct.get('99%')} "
        f"failures={direct.get('Failure Count')}"
    )
if stub:
    print(
        "ceiling: "
        f"rps={stub.get('Requests/s')} "
        f"p95={stub.get('95%')} "
        f"p99={stub.get('99%')} "
        f"failures={stub.get('Failure Count')}"
    )
    direct_avg = float(direct.get("Average Response Time") or 0) if direct else 0.0
    stub_avg = float(stub.get("Average Response Time") or 0)
    if direct_avg > 0:
        auth_share = max(direct_avg - stub_avg, 0.0) / direct_avg * 100.0
        print(f"estimated auth share of direct MCP avg latency: {auth_share:.2f}%")
PY
