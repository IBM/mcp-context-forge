#!/usr/bin/env bash
# ===========================================================================
#  run_plugin_tests.sh — Self-contained runner for plugin E2E integration tests
#
#  Authors: Mihai Criveti
#  Usage:
#    ./run_plugin_tests.sh                          # all plugins, both paths
#    ./run_plugin_tests.sh SQLSanitizer             # one plugin, both paths
#    ./run_plugin_tests.sh SQLSanitizer static      # one plugin, static only
#    ./run_plugin_tests.sh "" binding               # all plugins, binding only
#
#  Environment variables (all optional — defaults shown below):
#    GATEWAY_PORT        Test gateway port              (default: 4444)
#    GATEWAY_HOST        Test gateway host              (default: 127.0.0.1)
#    JWT_SECRET_KEY      Must be >32 bytes              (default: see below)
#    REDIS_HOST          Redis host for redis-requiring plugins  (default: 127.0.0.1)
#    REDIS_PORT          Redis port                     (default: 6379)
#    VENV_DIR              Path to project virtualenv     (default: .venv)
#    FAST_TIME_IMAGE       fast-time-server container image (default: ghcr.io/ibm/cfex-mcp-fast-time-server:5eac210da1c96a5fb2386c82a0c6f543b68fd76a)
#    FAST_TIME_CONTAINER   docker container name            (default: mcpgw-plugin-test-fast-time)
#    FAST_TIME_PORT        fast-time-server host port       (default: 9080)
#    FAST_TIME_SERVER_URL  MCP URL registered with gateway  (default: derived from FAST_TIME_PORT)
# ===========================================================================
set -euo pipefail

# ---------------------------------------------------------------------------
# Resolve project root (directory containing this script's ../../..)
# ---------------------------------------------------------------------------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../../.." && pwd)"

# ---------------------------------------------------------------------------
# Configurable defaults
# ---------------------------------------------------------------------------
GATEWAY_PORT="${GATEWAY_PORT:-4444}"
GATEWAY_HOST="${GATEWAY_HOST:-127.0.0.1}"
GATEWAY_URL="http://${GATEWAY_HOST}:${GATEWAY_PORT}"
JWT_SECRET="${JWT_SECRET_KEY:-my-test-key-but-now-longer-than-32-bytes}"
REDIS_HOST="${REDIS_HOST:-127.0.0.1}"
REDIS_PORT="${REDIS_PORT:-6379}"
VENV_DIR="${VENV_DIR:-${PROJECT_ROOT}/.venv}"
FAST_TIME_PORT="${FAST_TIME_PORT:-9080}"
FAST_TIME_IMAGE="${FAST_TIME_IMAGE:-ghcr.io/ibm/cfex-mcp-fast-time-server:5eac210da1c96a5fb2386c82a0c6f543b68fd76a}"
FAST_TIME_CONTAINER="${FAST_TIME_CONTAINER:-mcpgw-plugin-test-fast-time}"
# URL the gateway federates to. Derived from FAST_TIME_PORT so a single override
# moves both the bound port and the registered URL together.
FAST_TIME_SERVER_URL="${FAST_TIME_SERVER_URL:-http://localhost:${FAST_TIME_PORT}/mcp}"
export FAST_TIME_SERVER_URL

# Args
FILTER_PLUGIN="${1:-}"    # empty = all
FILTER_ENFORCE="${2:-both}"  # static | binding | both

# ---------------------------------------------------------------------------
# Plugin registry
# Each entry: "NAME|TEST_FILE|CONFIG_OVERRIDE|BINDING_SUPPORTED|NEEDS_REDIS"
# CONFIG_OVERRIDE: empty string or a KEY=JSON literal (no outer quotes needed)
# ---------------------------------------------------------------------------
PLUGINS=(
    "SecretsDetection|test_secrets_detection_e2e.py||yes|no"
    "EncodedExfilDetector|test_encoded_exfil_detection_e2e.py||yes|no"
    "URLReputationPlugin|test_url_reputation_e2e.py||no|no"
    "RateLimiterPlugin|test_rate_limiter_e2e.py||yes|yes"
    "RetryWithBackoffPlugin|test_retry_with_backoff_e2e.py||yes|yes"
    "PIIFilterPlugin|test_pii_filter_e2e.py||yes|no"
    "SQLSanitizer|test_sql_sanitizer_e2e.py|fields=[\"sql\",\"query\",\"statement\",\"message\"]|yes|no"
)

# ---------------------------------------------------------------------------
# Colour helpers
# ---------------------------------------------------------------------------
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
CYAN='\033[0;36m'; BOLD='\033[1m'; RESET='\033[0m'
info()    { echo -e "${CYAN}[info]${RESET} $*"; }
success() { echo -e "${GREEN}[pass]${RESET} $*"; }
warn()    { echo -e "${YELLOW}[warn]${RESET} $*"; }
error()   { echo -e "${RED}[fail]${RESET} $*"; }

# ---------------------------------------------------------------------------
# Cleanup state
# ---------------------------------------------------------------------------
GATEWAY_PID=""
REDIS_CONTAINER=""

cleanup() {
    info "Cleaning up…"
    [[ -n "${GATEWAY_PID}"     ]] && kill -9 "${GATEWAY_PID}"     2>/dev/null || true
    docker rm -f "${FAST_TIME_CONTAINER}" 2>/dev/null || true
    [[ -n "${REDIS_CONTAINER}" ]] && docker rm -f "${REDIS_CONTAINER}" 2>/dev/null || true
}
trap cleanup EXIT

# ---------------------------------------------------------------------------
# Helper: wait for an HTTP health endpoint
# ---------------------------------------------------------------------------
wait_for_health() {
    local url="$1" label="$2" retries="${3:-40}"
    for i in $(seq 1 "${retries}"); do
        # Require a 2xx status: a plain "got a response" check is fooled by an
        # unrelated proxy (e.g. nginx/docker on the same port) returning 502.
        local code
        code="$(curl -s -o /dev/null -w '%{http_code}' "${url}" 2>/dev/null || true)"
        if [[ "${code}" =~ ^2[0-9][0-9]$ ]]; then
            info "${label} is up"
            return 0
        fi
        sleep 1
    done
    error "${label} did not become healthy at ${url}"
    return 1
}

# ---------------------------------------------------------------------------
# Step 1: Start fast-time-server container (once for the whole run)
# ---------------------------------------------------------------------------
start_fast_time_server() {
    docker rm -f "${FAST_TIME_CONTAINER}" 2>/dev/null || true
    info "Pulling fast-time-server image: ${FAST_TIME_IMAGE}"
    docker pull "${FAST_TIME_IMAGE}" || {
        error "docker pull failed for ${FAST_TIME_IMAGE}"
        return 1
    }
    docker run --detach \
        --name "${FAST_TIME_CONTAINER}" \
        --publish "127.0.0.1:${FAST_TIME_PORT}:9080" \
        "${FAST_TIME_IMAGE}"
    wait_for_health "http://localhost:${FAST_TIME_PORT}/health" "fast-time-server" 30
}

# ---------------------------------------------------------------------------
# Step 3: Redis — auto-start if needed and not already running
# ---------------------------------------------------------------------------
ensure_redis() {
    if redis-cli -h "${REDIS_HOST}" -p "${REDIS_PORT}" ping >/dev/null 2>&1; then
        info "Redis already running at ${REDIS_HOST}:${REDIS_PORT} — reusing"
        return 0
    fi
    info "Starting Redis container (redis:7-alpine) on port ${REDIS_PORT}…"
    REDIS_CONTAINER=$(docker run -d --rm \
        --name "mcpgw-plugin-test-redis-$$" \
        -p "${REDIS_PORT}:6379" \
        redis:7-alpine)
    # Wait for it to accept connections
    for i in $(seq 1 20); do
        redis-cli -h "${REDIS_HOST}" -p "${REDIS_PORT}" ping >/dev/null 2>&1 && {
            info "Redis ready"
            return 0
        }
        sleep 1
    done
    error "Redis did not become ready"
    return 1
}

# ---------------------------------------------------------------------------
# Step 4: Boot the gateway with a given config file
# ---------------------------------------------------------------------------
boot_gateway() {
    local config_file="$1"
    # Kill any stale gateway
    pkill -9 -f "python -m mcpgateway" 2>/dev/null || true
    sleep 1

    # Stamp the Alembic migration cursor to the current codebase head.
    # This is a no-op when the DB is already in sync, and recovers gracefully
    # from the common branch-switching case where the DB has a revision the
    # current codebase doesn't know about (e.g. switching from a release branch
    # back to main). No new dependencies required — alembic ships with the gateway.
    "${VENV_DIR}/bin/alembic" -c "${PROJECT_ROOT}/mcpgateway/alembic.ini" stamp head --purge 2>/dev/null \
        || "${VENV_DIR}/bin/alembic" -c "${PROJECT_ROOT}/mcpgateway/alembic.ini" stamp head 2>/dev/null \
        || warn "alembic stamp head failed — gateway may still start if DB is already in sync"

    # REDIS_URL is set so that Jinja templates in plugin configs resolve to
    # localhost instead of the docker-compose service name "redis".
    PLUGIN_CONFIG_FILE="${config_file}" \
    PLUGINS_CONFIG_FILE="${config_file}" \
    PLUGINS_ENABLED=true \
    REDIS_URL="redis://${REDIS_HOST}:${REDIS_PORT}/0" \
    MCPGATEWAY_UI_ENABLED=true \
    MCPGATEWAY_ADMIN_API_ENABLED=true \
    SSRF_PROTECTION_ENABLED=false \
    JWT_SECRET_KEY="${JWT_SECRET}" \
    ADMIN_REQUIRE_PASSWORD_CHANGE_ON_BOOTSTRAP=false \
    PASSWORD_CHANGE_ENFORCEMENT_ENABLED=false \
    LOG_LEVEL=WARNING \
    HOST="${GATEWAY_HOST}" \
    PORT="${GATEWAY_PORT}" \
    nohup "${VENV_DIR}/bin/python" -m mcpgateway > /tmp/gateway-plugin-tests.log 2>&1 &
    GATEWAY_PID=$!
    wait_for_health "${GATEWAY_URL}/health" "gateway" 40
}

# ---------------------------------------------------------------------------
# Step 5: Run pytest for one plugin / one enforcement mode
# Returns 0 on pass, 1 on fail; appends result to RESULTS array
# ---------------------------------------------------------------------------
run_test() {
    local plugin="$1" test_file="$2" enforcement="$3"
    info "Running ${plugin} [${enforcement}]…"

    local log_file="/tmp/pytest-${plugin}-${enforcement}.log"
    local rc=0
    MCP_CLI_BASE_URL="${GATEWAY_URL}" \
    JWT_SECRET_KEY="${JWT_SECRET}" \
    PLUGIN_ENFORCEMENT="${enforcement}" \
        "${VENV_DIR}/bin/python" -m pytest \
            "${SCRIPT_DIR}/${test_file}" \
            -q --tb=short -ra \
            > "${log_file}" 2>&1 || rc=$?
    if [[ ${rc} -eq 0 ]]; then
        local summary
        summary=$(grep -E "passed|failed|error" "${log_file}" | tail -1 || echo "ok")
        success "${plugin} [${enforcement}] — ${summary}"
        RESULTS+=("PASS  ${plugin}  ${enforcement}")
    else
        error "${plugin} [${enforcement}] — FAILED (log: ${log_file})"
        # Print the tail of the log inline so it's visible without opening the file
        echo "---------- pytest output (last 30 lines) ----------"
        tail -30 "${log_file}"
        echo "----------------------------------------------------"
        RESULTS+=("FAIL  ${plugin}  ${enforcement}")
        FAILED=1
    fi
}

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
main() {
    cd "${PROJECT_ROOT}"

    # Activate venv
    # shellcheck disable=SC1091
    source "${VENV_DIR}/bin/activate"

    info "Plugin integration test runner"
    info "  Filter plugin  : ${FILTER_PLUGIN:-<all>}"
    info "  Enforcement    : ${FILTER_ENFORCE}"
    info "  Gateway        : ${GATEWAY_URL}"
    echo

    # Pull + start fast-time-server container (stays up for the whole run)
    start_fast_time_server

    RESULTS=()
    FAILED=0

    # Track whether any redis-requiring plugin will actually run
    REDIS_NEEDED=false
    for entry in "${PLUGINS[@]}"; do
        IFS='|' read -r pname test_file cfg_override binding_ok needs_redis <<< "${entry}"
        [[ -n "${FILTER_PLUGIN}" && "${pname}" != "${FILTER_PLUGIN}" ]] && continue
        [[ "${needs_redis}" == "yes" ]] && REDIS_NEEDED=true
    done
    "${REDIS_NEEDED}" && ensure_redis || true

    # ── Per-plugin loop ─────────────────────────────────────────────────────
    for entry in "${PLUGINS[@]}"; do
        IFS='|' read -r pname test_file cfg_override binding_ok needs_redis <<< "${entry}"

        # Skip if a specific plugin was requested and this isn't it
        [[ -n "${FILTER_PLUGIN}" && "${pname}" != "${FILTER_PLUGIN}" ]] && continue

        echo -e "${BOLD}══ ${pname} ══${RESET}"

        # ── Determine which enforcement paths to run ─────────────────────
        local_enforcements=()
        if [[ "${FILTER_ENFORCE}" == "both" || "${FILTER_ENFORCE}" == "static" ]]; then
            local_enforcements+=("static")
        fi
        if [[ "${FILTER_ENFORCE}" == "both" || "${FILTER_ENFORCE}" == "binding" ]]; then
            if [[ "${binding_ok}" == "yes" ]]; then
                local_enforcements+=("binding")
            else
                warn "${pname}: binding path not supported — skipping binding leg"
            fi
        fi

        # ── Run each enforcement leg ──────────────────────────────────────
        for enforcement in "${local_enforcements[@]}"; do
            # Derive the enforce config
            local cfg_file="/tmp/plugin-test-${pname}-${enforcement}.yaml"
            local extra_args=()
            [[ "${enforcement}" == "binding" ]] && extra_args+=(--all-disabled)
            [[ -n "${cfg_override}" ]] && extra_args+=(--config-override "${cfg_override}")

            if ! "${VENV_DIR}/bin/python" \
                    "${SCRIPT_DIR}/make_enforce_config.py" \
                    --source "${PROJECT_ROOT}/plugins/config.yaml" \
                    --plugin "${pname}" \
                    --output "${cfg_file}" \
                    "${extra_args[@]}"; then
                error "${pname} [${enforcement}]: make_enforce_config failed — skipping"
                RESULTS+=("FAIL  ${pname}  ${enforcement}")
                FAILED=1
                continue
            fi

            # Boot gateway with this config
            boot_gateway "${cfg_file}"

            # Run the test
            run_test "${pname}" "${test_file}" "${enforcement}"
        done

        echo
    done

    # ── Summary ─────────────────────────────────────────────────────────────
    echo -e "${BOLD}══ Summary ══${RESET}"
    for r in "${RESULTS[@]}"; do
        if [[ "${r}" == PASS* ]]; then
            echo -e "  ${GREEN}${r}${RESET}"
        else
            echo -e "  ${RED}${r}${RESET}"
        fi
    done

    local total=${#RESULTS[@]}
    local passed
    passed=$(printf '%s\n' "${RESULTS[@]}" | grep -c '^PASS' || true)
    local failed=$(( total - passed ))
    echo
    echo -e "  ${BOLD}${passed}/${total} passed${RESET}$([ "${failed}" -gt 0 ] && echo -e ", ${RED}${failed} failed${RESET}" || true)"

    return "${FAILED}"
}

main "$@"
