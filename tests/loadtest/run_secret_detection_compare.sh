#!/usr/bin/env bash

set -euo pipefail

: "${VENV_DIR:?VENV_DIR must be set}"
: "${COMPOSE_CMD:?COMPOSE_CMD must be set}"
: "${IMAGE_LOCAL_NAME:?IMAGE_LOCAL_NAME must be set}"
: "${SECRET_DETECTION_LOADTEST_HOST:?SECRET_DETECTION_LOADTEST_HOST must be set}"
: "${SECRET_DETECTION_LOADTEST_USERS:?SECRET_DETECTION_LOADTEST_USERS must be set}"
: "${SECRET_DETECTION_LOADTEST_SPAWN_RATE:?SECRET_DETECTION_LOADTEST_SPAWN_RATE must be set}"
: "${SECRET_DETECTION_LOADTEST_RUN_TIME:?SECRET_DETECTION_LOADTEST_RUN_TIME must be set}"
: "${SECRET_DETECTION_BENCH_GATEWAY_REPLICAS:?SECRET_DETECTION_BENCH_GATEWAY_REPLICAS must be set}"
: "${SECRET_DETECTION_BENCH_GUNICORN_WORKERS:?SECRET_DETECTION_BENCH_GUNICORN_WORKERS must be set}"
: "${SECRET_DETECTION_BENCH_CPU_LIMIT:?SECRET_DETECTION_BENCH_CPU_LIMIT must be set}"
: "${SECRET_DETECTION_BENCH_CPU_RESERVATION:?SECRET_DETECTION_BENCH_CPU_RESERVATION must be set}"
: "${SECRET_DETECTION_BENCH_MEM_LIMIT:?SECRET_DETECTION_BENCH_MEM_LIMIT must be set}"
: "${SECRET_DETECTION_BENCH_MEM_RESERVATION:?SECRET_DETECTION_BENCH_MEM_RESERVATION must be set}"

ROOT_DIR="$(pwd)"
SHADOW_DIR="${ROOT_DIR}/reports/secret_detection_python_shadow"
RUST_COMPOSE="/tmp/contextforge_secret_detection_rust.compose.yml"
PY_COMPOSE="/tmp/contextforge_secret_detection_python.compose.yml"
OVERRIDE_BASE="/tmp/contextforge_secret_detection_bench.override.yml"
PY_OVERRIDE="/tmp/contextforge_secret_detection_python.override.yml"
LOCUSTFILE="tests/loadtest/locustfile_secret_detection.py"

wait_for_health() {
  local url="$1"
  HEALTHCHECK_URL="$url" "${VENV_DIR}/bin/python" - <<'PY'
import json
import os
import time
import urllib.request

url = os.environ["HEALTHCHECK_URL"]
for _ in range(180):
    try:
        with urllib.request.urlopen(url, timeout=5) as response:
            data = json.loads(response.read())
            if data.get("status") == "healthy":
                break
    except Exception:
        pass
    time.sleep(2)
else:
    raise SystemExit(f"Stack did not become healthy in time: {url}")
PY
}

show_rust_flag() {
  local compose_file="$1"
  local gateway_cid
  gateway_cid="$(${COMPOSE_CMD} -f "${compose_file}" ps -q gateway)"
  docker exec "${gateway_cid}" /app/.venv/bin/python -c "import plugins.secrets_detection.secrets_detection as s; print('RUST_AVAILABLE', getattr(s, '_RUST_AVAILABLE', None))"
}

run_locust() {
  local html_report="$1"
  local csv_prefix="$2"
  source "${VENV_DIR}/bin/activate"
  locust -f "${LOCUSTFILE}" \
    --host="${SECRET_DETECTION_LOADTEST_HOST}" \
    --users="${SECRET_DETECTION_LOADTEST_USERS}" \
    --spawn-rate="${SECRET_DETECTION_LOADTEST_SPAWN_RATE}" \
    --run-time="${SECRET_DETECTION_LOADTEST_RUN_TIME}" \
    --headless \
    --html="${html_report}" \
    --csv="${csv_prefix}" \
    --only-summary || true
}

restore_rust_stack() {
  echo "   ▶ Restoring Rust-capable stack"
  ${COMPOSE_CMD} -f "${RUST_COMPOSE}" down --remove-orphans >/dev/null 2>&1 || true
  IMAGE_LOCAL="${IMAGE_LOCAL_NAME}" ${COMPOSE_CMD} -f "${RUST_COMPOSE}" up -d >/dev/null
  wait_for_health "${SECRET_DETECTION_LOADTEST_HOST}/health"
  show_rust_flag "${RUST_COMPOSE}"
}

mkdir -p "${SHADOW_DIR}/secrets_detection_rust"
printf '# shadow package to force Python fallback\n' > "${SHADOW_DIR}/secrets_detection_rust/__init__.py"
printf 'raise ImportError("forced python fallback for benchmark")\n' > "${SHADOW_DIR}/secrets_detection_rust/secrets_detection_rust.py"

cat > "${OVERRIDE_BASE}" <<EOF
services:
  nginx:
    deploy:
      resources:
        limits:
          cpus: '${SECRET_DETECTION_BENCH_CPU_LIMIT}'
          memory: 1G
        reservations:
          cpus: '${SECRET_DETECTION_BENCH_CPU_RESERVATION}'
          memory: 512M
  gateway:
    environment:
      GUNICORN_WORKERS: '${SECRET_DETECTION_BENCH_GUNICORN_WORKERS}'
    deploy:
      mode: replicated
      replicas: ${SECRET_DETECTION_BENCH_GATEWAY_REPLICAS}
      resources:
        limits:
          cpus: '${SECRET_DETECTION_BENCH_CPU_LIMIT}'
          memory: ${SECRET_DETECTION_BENCH_MEM_LIMIT}
        reservations:
          cpus: '${SECRET_DETECTION_BENCH_CPU_RESERVATION}'
          memory: ${SECRET_DETECTION_BENCH_MEM_RESERVATION}
  postgres:
    deploy:
      resources:
        limits:
          cpus: '${SECRET_DETECTION_BENCH_CPU_LIMIT}'
          memory: 4G
        reservations:
          cpus: '${SECRET_DETECTION_BENCH_CPU_RESERVATION}'
          memory: 2G
EOF

cat > "${PY_OVERRIDE}" <<EOF
services:
  gateway:
    environment:
      PYTHONPATH: /app/python-shadow
    volumes:
      - ${SHADOW_DIR}:/app/python-shadow:ro
EOF

${COMPOSE_CMD} -f docker-compose.yml -f "${OVERRIDE_BASE}" config > "${RUST_COMPOSE}"
${COMPOSE_CMD} -f docker-compose.yml -f "${OVERRIDE_BASE}" -f "${PY_OVERRIDE}" config > "${PY_COMPOSE}"

trap restore_rust_stack EXIT

echo "   ▶ Rust-backed run"
${COMPOSE_CMD} -f "${RUST_COMPOSE}" down --remove-orphans >/dev/null 2>&1 || true
IMAGE_LOCAL="${IMAGE_LOCAL_NAME}" ${COMPOSE_CMD} -f "${RUST_COMPOSE}" up -d >/dev/null
wait_for_health "${SECRET_DETECTION_LOADTEST_HOST}/health"
show_rust_flag "${RUST_COMPOSE}"
run_locust "reports/locust_secret_focus_rust.html" "reports/locust_secret_focus_rust"

echo "   ▶ Python fallback run"
${COMPOSE_CMD} -f "${PY_COMPOSE}" down --remove-orphans >/dev/null 2>&1 || true
IMAGE_LOCAL="${IMAGE_LOCAL_NAME}" ${COMPOSE_CMD} -f "${PY_COMPOSE}" up -d >/dev/null
wait_for_health "${SECRET_DETECTION_LOADTEST_HOST}/health"
show_rust_flag "${PY_COMPOSE}"
run_locust "reports/locust_secret_focus_python.html" "reports/locust_secret_focus_python"

"${VENV_DIR}/bin/python" - <<'PY'
import csv
from pathlib import Path


def rows(path: str) -> dict[str, dict[str, str]]:
    return {row["Name"]: row for row in csv.DictReader(Path(path).open())}


rust = rows("reports/locust_secret_focus_rust_stats.csv")
python_rows = rows("reports/locust_secret_focus_python_stats.csv")

print("")
print("Focused Secrets Detection Comparison")
print("===================================")
for name in ["/rpc prompts/get [clean]", "/rpc prompts/get [secret-blocked]", "Aggregated"]:
    print(name)
    rust_row = rust[name]
    python_row = python_rows[name]
    for key in ["Requests/s", "Average Response Time", "95%", "99%"]:
        rust_value = float(rust_row[key])
        python_value = float(python_row[key])
        delta_pct = ((python_value - rust_value) / rust_value * 100.0) if rust_value else 0.0
        print(f"  {key}: rust={rust_row[key]} python={python_row[key]} delta_pct={delta_pct:.2f}")

print("")
print("Reports:")
print("  reports/locust_secret_focus_rust.html")
print("  reports/locust_secret_focus_python.html")
PY
