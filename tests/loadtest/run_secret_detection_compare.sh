#!/usr/bin/env bash
# Copyright 2026
# SPDX-License-Identifier: Apache-2.0
#
# Focused secrets-detection benchmark comparing Rust vs Python implementations.
#
# This script performs a two-phase benchmark:
# 1. Run load test with Rust-accelerated secrets detection (baseline)
# 2. Run load test with forced Python fallback (comparison)
#
# The script uses a "shadow module" technique to force Python fallback:
# - Creates a fake secrets_detection_rust module that raises ImportError
# - Mounts it into the container via PYTHONPATH override
# - This forces the plugin to use pure Python implementation
#
# Results are compared to show the performance impact of Rust acceleration.

set -euo pipefail

# ============================================================================
# Configuration and Setup
# ============================================================================

LOCUSTFILE="${SECRET_DETECTION_LOCUSTFILE:-tests/loadtest/locustfile_secret_detection.py}"
SHADOW_DIR="$(pwd)/.tmp/python-shadow"
OVERRIDE_BASE="$(pwd)/.tmp/docker-compose.override.base.yml"
RUST_COMPOSE="$(pwd)/.tmp/docker-compose.rust.yml"
PY_COMPOSE="$(pwd)/.tmp/docker-compose.python.yml"
PY_OVERRIDE="$(pwd)/.tmp/docker-compose.python.override.yml"

# Validate required environment variables with defaults
: "${VENV_DIR:?VENV_DIR must be set}"
: "${COMPOSE_CMD:?COMPOSE_CMD must be set}"
: "${IMAGE_LOCAL_NAME:?IMAGE_LOCAL_NAME must be set}"
: "${SECRET_DETECTION_LOADTEST_HOST:?SECRET_DETECTION_LOADTEST_HOST must be set}"
: "${SECRET_DETECTION_LOADTEST_USERS:=100}"
: "${SECRET_DETECTION_LOADTEST_SPAWN_RATE:=10}"
: "${SECRET_DETECTION_LOADTEST_RUN_TIME:=60s}"

# Validate locustfile exists
if [[ ! -f "${LOCUSTFILE}" ]]; then
  echo "❌ Error: Locustfile not found at ${LOCUSTFILE}" >&2
  echo "   Expected file: ${LOCUSTFILE}" >&2
  exit 1
fi

# ============================================================================
# Helper Functions
# ============================================================================

# Health check configuration
HEALTH_CHECK_MAX_ATTEMPTS=30
HEALTH_CHECK_SLEEP_SECONDS=2

wait_for_health() {
  local url="$1"
  local max_attempts="${HEALTH_CHECK_MAX_ATTEMPTS}"
  local attempt=0

  echo "   ⏳ Waiting for service health at ${url}..."

  while [[ ${attempt} -lt ${max_attempts} ]]; do
    if curl -sf "${url}" >/dev/null 2>&1; then
      echo "   ✅ Service is healthy"
      return 0
    fi
    attempt=$((attempt + 1))
    sleep "${HEALTH_CHECK_SLEEP_SECONDS}"
  done

  echo "   ❌ Error: Service failed to become healthy after ${max_attempts} attempts" >&2
  return 1
}

show_rust_flag() {
  local compose_file="$1"
  echo "   🔍 Checking Rust availability..."

  # Extract and run a Python check in the container
  local rust_check
  local exit_code=0
  rust_check=$(${COMPOSE_CMD} -f "${compose_file}" exec -T gateway python3 -c \
    "try:
    import secrets_detection_rust
    print('✅ Rust secrets detection: AVAILABLE')
except ImportError as e:
    print(f'⚠️  Rust secrets detection: NOT AVAILABLE ({e})')" 2>&1) || exit_code=$?

  if [[ ${exit_code} -ne 0 ]]; then
    echo "   ❌ Failed to check Rust availability (exit code: ${exit_code})"
    echo "   ⚠️  Warning: Benchmark results may be unreliable"
    return 1
  fi

  echo "   ${rust_check}"
  return 0
}

run_locust() {
  local html_report="$1"
  local csv_prefix="$2"
  local exit_code=0

  echo "   🚀 Running Locust load test..."
  echo "      Report: ${html_report}"
  echo "      CSV: ${csv_prefix}"

  source "${VENV_DIR}/bin/activate"

  # Run locust and capture exit code (allow non-zero for analysis)
  locust -f "${LOCUSTFILE}" \
    --host="${SECRET_DETECTION_LOADTEST_HOST}" \
    --users="${SECRET_DETECTION_LOADTEST_USERS}" \
    --spawn-rate="${SECRET_DETECTION_LOADTEST_SPAWN_RATE}" \
    --run-time="${SECRET_DETECTION_LOADTEST_RUN_TIME}" \
    --headless \
    --html="${html_report}" \
    --csv="${csv_prefix}" \
    --only-summary || exit_code=$?

  if [[ ${exit_code} -ne 0 ]]; then
    echo "   ⚠️  Warning: Locust exited with code ${exit_code}" >&2
    echo "      This may indicate test failures or timeouts" >&2
    echo "      Check ${html_report} for details" >&2
  fi

  return 0  # Continue with comparison even if tests had failures
}

restore_rust_stack() {
  echo "   ▶ Restoring Rust-capable stack"
  ${COMPOSE_CMD} -f "${RUST_COMPOSE}" down --remove-orphans >/dev/null 2>&1 || true
  IMAGE_LOCAL="${IMAGE_LOCAL_NAME}" ${COMPOSE_CMD} -f "${RUST_COMPOSE}" up -d \
    --scale gateway="${SECRET_DETECTION_BENCH_GATEWAY_REPLICAS}" >/dev/null
  wait_for_health "${SECRET_DETECTION_LOADTEST_HOST}/health"
  show_rust_flag "${RUST_COMPOSE}"
}

# ============================================================================
# Shadow Module Setup (Forces Python Fallback)
# ============================================================================

echo "   📦 Creating shadow module to force Python fallback..."

# Only create shadow module if it doesn't exist or needs updating
if [[ ! -f "${SHADOW_DIR}/secrets_detection_rust/__init__.py" ]]; then
  mkdir -p "${SHADOW_DIR}/secrets_detection_rust"

  # Create a fake Rust module that raises ImportError
  # This forces the secrets detection plugin to use pure Python implementation
  cat > "${SHADOW_DIR}/secrets_detection_rust/__init__.py" <<'EOF'
# Shadow package to force Python fallback for benchmarking
raise ImportError("forced python fallback for benchmark")
EOF

  cat > "${SHADOW_DIR}/secrets_detection_rust/secrets_detection_rust.py" <<'EOF'
# Shadow module to force Python fallback for benchmarking
raise ImportError("forced python fallback for benchmark")
EOF
  echo "   ✅ Shadow module created"
else
  echo "   ✅ Shadow module already exists"
fi

# ============================================================================
# Docker Compose Configuration
# ============================================================================

echo "   📝 Generating Docker Compose configurations..."

# Base configuration with resource limits
cat > "${OVERRIDE_BASE}" <<EOF
services:
  nginx:
    cpus: '${SECRET_DETECTION_BENCH_CPU_LIMIT}'
    mem_limit: 1G
    mem_reservation: 512M
  gateway:
    environment:
      GUNICORN_WORKERS: '${SECRET_DETECTION_BENCH_GUNICORN_WORKERS}'
    cpus: '${SECRET_DETECTION_BENCH_CPU_LIMIT}'
    mem_limit: ${SECRET_DETECTION_BENCH_MEM_LIMIT}
    mem_reservation: ${SECRET_DETECTION_BENCH_MEM_RESERVATION}
  postgres:
    cpus: '${SECRET_DETECTION_BENCH_CPU_LIMIT}'
    mem_limit: 4G
    mem_reservation: 2G
EOF

# Python fallback configuration (adds shadow module via PYTHONPATH)
cat > "${PY_OVERRIDE}" <<EOF
services:
  gateway:
    environment:
      PYTHONPATH: /app/python-shadow
    volumes:
      - ${SHADOW_DIR}:/app/python-shadow:ro
EOF

# Generate final compose files
${COMPOSE_CMD} -f docker-compose.yml -f "${OVERRIDE_BASE}" config > "${RUST_COMPOSE}"
${COMPOSE_CMD} -f docker-compose.yml -f "${OVERRIDE_BASE}" -f "${PY_OVERRIDE}" config > "${PY_COMPOSE}"

# ============================================================================
# Cleanup Handler
# ============================================================================

trap restore_rust_stack EXIT

# ============================================================================
# Phase 1: Rust-Backed Run (Baseline)
# ============================================================================

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "Phase 1: Rust-Backed Secrets Detection (Baseline)"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

echo "   ▶ Starting Rust-capable stack..."
${COMPOSE_CMD} -f "${RUST_COMPOSE}" down --remove-orphans >/dev/null 2>&1 || true
IMAGE_LOCAL="${IMAGE_LOCAL_NAME}" ${COMPOSE_CMD} -f "${RUST_COMPOSE}" up -d \
  --scale gateway="${SECRET_DETECTION_BENCH_GATEWAY_REPLICAS}" >/dev/null

wait_for_health "${SECRET_DETECTION_LOADTEST_HOST}/health"
show_rust_flag "${RUST_COMPOSE}"

mkdir -p reports
run_locust "reports/locust_secret_focus_rust.html" "reports/locust_secret_focus_rust"

# ============================================================================
# Phase 2: Python Fallback Run (Comparison)
# ============================================================================

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "Phase 2: Python Fallback Secrets Detection (Comparison)"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

echo "   ▶ Starting Python-only stack (Rust disabled via shadow module)..."
${COMPOSE_CMD} -f "${PY_COMPOSE}" down --remove-orphans >/dev/null 2>&1 || true
IMAGE_LOCAL="${IMAGE_LOCAL_NAME}" ${COMPOSE_CMD} -f "${PY_COMPOSE}" up -d \
  --scale gateway="${SECRET_DETECTION_BENCH_GATEWAY_REPLICAS}" >/dev/null

wait_for_health "${SECRET_DETECTION_LOADTEST_HOST}/health"
show_rust_flag "${PY_COMPOSE}"

run_locust "reports/locust_secret_focus_python.html" "reports/locust_secret_focus_python"

# ============================================================================
# Results Comparison
# ============================================================================

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "Performance Comparison Results"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

"${VENV_DIR}/bin/python" - <<'PY'
import csv
from pathlib import Path

def rows(path: str) -> dict[str, dict[str, str]]:
    """Load CSV stats into a dict keyed by endpoint name."""
    try:
        return {row["Name"]: row for row in csv.DictReader(Path(path).open())}
    except FileNotFoundError:
        print(f"❌ Error: CSV file not found: {path}")
        return {}
    except Exception as e:
        print(f"❌ Error reading CSV: {e}")
        return {}

rust = rows("reports/locust_secret_focus_rust_stats.csv")
python_rows = rows("reports/locust_secret_focus_python_stats.csv")

if not rust or not python_rows:
    print("\n❌ Failed to load benchmark results")
    exit(1)

print("")
print("Focused Secrets Detection Comparison")
print("=" * 100)

# Compare key endpoints
for name in ["/rpc prompts/get [clean]", "/rpc prompts/get [secret-blocked]", "Aggregated"]:
    if name not in rust or name not in python_rows:
        print(f"\n⚠️  Warning: Missing data for endpoint: {name}")
        continue

    print(f"\n{name}")
    print("-" * 100)

    rust_row = rust[name]
    python_row = python_rows[name]

    for key in ["Requests/s", "Average Response Time", "95%", "99%"]:
        try:
            rust_value = float(rust_row[key])
            python_value = float(python_row[key])

            # Calculate percentage difference (positive = Python slower)
            if rust_value > 0:
                delta_pct = ((python_value - rust_value) / rust_value * 100.0)
            else:
                delta_pct = 0.0

            # Format with color indicators
            indicator = "🔴" if delta_pct > 10 else "🟡" if delta_pct > 5 else "🟢"

            print(f"  {key:25s}: rust={rust_row[key]:>10s}  python={python_row[key]:>10s}  "
                  f"delta={delta_pct:>6.2f}% {indicator}")
        except (ValueError, KeyError) as e:
            print(f"  {key:25s}: ⚠️  Error: {e}")

print("")
print("=" * 100)
print("\n📊 Detailed Reports:")
print("   Rust:   reports/locust_secret_focus_rust.html")
print("   Python: reports/locust_secret_focus_python.html")
print("")
PY

echo "✅ Benchmark complete!"
