#!/usr/bin/env bash
set -euo pipefail

# Focused MCP auth benchmark comparing proxy-only auth vs direct Rust auth.
#
# Reuses the existing MCP protocol Locust workload so the comparison stays on the
# same MCP transport path. Run this against two stacks:
#   1. proxy/core-only auth
#   2. auth service with CONTEXTFORGE_AUTH_EXPERIMENTAL_DIRECT_AUTH=true
#
# Required env:
#   MCP_AUTH_COMPARE_PROXY_HOST
#   MCP_AUTH_COMPARE_DIRECT_HOST
#
# Optional env:
#   MCP_SERVER_ID
#   MCP_PROTOCOL_LOCUSTFILE
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
SERVER_ID="${MCP_SERVER_ID:-}"
USERS="${MCP_AUTH_COMPARE_USERS:-125}"
SPAWN_RATE="${MCP_AUTH_COMPARE_SPAWN_RATE:-30}"
RUN_TIME="${MCP_AUTH_COMPARE_RUN_TIME:-60s}"
HTML_DIR="${MCP_AUTH_COMPARE_HTML_DIR:-${ROOT_DIR}/reports/core_auth_compare}"
CSV_DIR="${MCP_AUTH_COMPARE_CSV_DIR:-${ROOT_DIR}/reports/core_auth_compare}"
ONLY_MODE="${MCP_AUTH_COMPARE_ONLY:-}"
LOG_LEVEL="${LOCUST_LOG_LEVEL:-ERROR}"

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
  local html_out="${HTML_DIR}/locust_${label}.html"
  local csv_prefix="${CSV_DIR}/locust_${label}"

  echo ""
  echo "=== Running ${label} auth benchmark ==="
  echo "Host: ${host}"
  echo "Users: ${USERS}"
  echo "Spawn rate: ${SPAWN_RATE}"
  echo "Run time: ${RUN_TIME}"

  LOCUST_LOG_LEVEL="${LOG_LEVEL}" \
  MCP_SERVER_ID="${SERVER_ID}" \
  locust -f "${LOCUSTFILE}" \
    --host="${host}" \
    --headless \
    --users="${USERS}" \
    --spawn-rate="${SPAWN_RATE}" \
    --run-time="${RUN_TIME}" \
    --html "${html_out}" \
    --csv "${csv_prefix}"
}

if [[ "${ONLY_MODE}" != "direct" ]]; then
  run_one "proxy" "${PROXY_HOST}"
fi

if [[ "${ONLY_MODE}" != "proxy" ]]; then
  run_one "direct" "${DIRECT_HOST}"
fi

python3 - <<'PY'
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
PY
