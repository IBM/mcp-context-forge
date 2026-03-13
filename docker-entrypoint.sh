#!/usr/bin/env bash
set -euo pipefail

HTTP_SERVER="${HTTP_SERVER:-gunicorn}"
RUST_MCP_MODE="${RUST_MCP_MODE:-off}"
RUST_MCP_LOG="${RUST_MCP_LOG:-warn}"
RUST_MCP_SESSION_AUTH_REUSE="${RUST_MCP_SESSION_AUTH_REUSE:-}"
EXPERIMENTAL_RUST_MCP_RUNTIME_ENABLED="${EXPERIMENTAL_RUST_MCP_RUNTIME_ENABLED:-}"
EXPERIMENTAL_RUST_MCP_RUNTIME_MANAGED="${EXPERIMENTAL_RUST_MCP_RUNTIME_MANAGED:-}"
EXPERIMENTAL_RUST_MCP_RUNTIME_URL="${EXPERIMENTAL_RUST_MCP_RUNTIME_URL:-}"
EXPERIMENTAL_RUST_MCP_RUNTIME_UDS="${EXPERIMENTAL_RUST_MCP_RUNTIME_UDS:-}"
EXPERIMENTAL_RUST_MCP_SESSION_CORE_ENABLED="${EXPERIMENTAL_RUST_MCP_SESSION_CORE_ENABLED:-}"
EXPERIMENTAL_RUST_MCP_EVENT_STORE_ENABLED="${EXPERIMENTAL_RUST_MCP_EVENT_STORE_ENABLED:-}"
EXPERIMENTAL_RUST_MCP_RESUME_CORE_ENABLED="${EXPERIMENTAL_RUST_MCP_RESUME_CORE_ENABLED:-}"
EXPERIMENTAL_RUST_MCP_LIVE_STREAM_CORE_ENABLED="${EXPERIMENTAL_RUST_MCP_LIVE_STREAM_CORE_ENABLED:-}"
EXPERIMENTAL_RUST_MCP_AFFINITY_CORE_ENABLED="${EXPERIMENTAL_RUST_MCP_AFFINITY_CORE_ENABLED:-}"
EXPERIMENTAL_RUST_MCP_SESSION_AUTH_REUSE_ENABLED="${EXPERIMENTAL_RUST_MCP_SESSION_AUTH_REUSE_ENABLED:-}"
CONTEXTFORGE_ENABLE_RUST_BUILD="${CONTEXTFORGE_ENABLE_RUST_BUILD:-false}"
CONTEXTFORGE_ENABLE_RUST_MCP_RMCP_BUILD="${CONTEXTFORGE_ENABLE_RUST_MCP_RMCP_BUILD:-false}"
MCP_RUST_LISTEN_HTTP="${MCP_RUST_LISTEN_HTTP:-}"
MCP_RUST_LISTEN_UDS="${MCP_RUST_LISTEN_UDS:-}"
MCP_RUST_PUBLIC_LISTEN_HTTP="${MCP_RUST_PUBLIC_LISTEN_HTTP:-}"
MCP_RUST_LOG="${MCP_RUST_LOG:-}"
MCP_RUST_USE_RMCP_UPSTREAM_CLIENT="${MCP_RUST_USE_RMCP_UPSTREAM_CLIENT:-}"
MCP_RUST_SESSION_CORE_ENABLED="${MCP_RUST_SESSION_CORE_ENABLED:-}"
MCP_RUST_EVENT_STORE_ENABLED="${MCP_RUST_EVENT_STORE_ENABLED:-}"
MCP_RUST_RESUME_CORE_ENABLED="${MCP_RUST_RESUME_CORE_ENABLED:-}"
MCP_RUST_LIVE_STREAM_CORE_ENABLED="${MCP_RUST_LIVE_STREAM_CORE_ENABLED:-}"
MCP_RUST_AFFINITY_CORE_ENABLED="${MCP_RUST_AFFINITY_CORE_ENABLED:-}"
MCP_RUST_SESSION_AUTH_REUSE_ENABLED="${MCP_RUST_SESSION_AUTH_REUSE_ENABLED:-}"
MCP_RUST_SESSION_AUTH_REUSE_TTL_SECONDS="${MCP_RUST_SESSION_AUTH_REUSE_TTL_SECONDS:-}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "${SCRIPT_DIR}" || {
    echo "ERROR: Cannot change to script directory: ${SCRIPT_DIR}"
    exit 1
}

RUST_MCP_PID=""
SERVER_PID=""

apply_rust_mcp_mode_defaults() {
    local normalized_mode="${RUST_MCP_MODE,,}"
    local runtime_enabled_default="false"
    local managed_default="true"
    local session_core_default="false"
    local event_store_default="false"
    local resume_core_default="false"
    local live_stream_core_default="false"
    local affinity_core_default="false"
    local session_auth_reuse_default="false"

    case "${normalized_mode}" in
        ""|off)
            ;;
        shadow)
            runtime_enabled_default="true"
            ;;
        edge)
            runtime_enabled_default="true"
            session_auth_reuse_default="true"
            ;;
        full)
            runtime_enabled_default="true"
            session_core_default="true"
            event_store_default="true"
            resume_core_default="true"
            live_stream_core_default="true"
            affinity_core_default="true"
            session_auth_reuse_default="true"
            ;;
        *)
            echo "ERROR: Unknown RUST_MCP_MODE value: ${RUST_MCP_MODE}"
            echo "Valid options: off, shadow, edge, full"
            exit 1
            ;;
    esac

    if [[ -z "${EXPERIMENTAL_RUST_MCP_RUNTIME_ENABLED}" ]]; then
        EXPERIMENTAL_RUST_MCP_RUNTIME_ENABLED="${runtime_enabled_default}"
    fi
    if [[ -z "${EXPERIMENTAL_RUST_MCP_RUNTIME_MANAGED}" ]]; then
        EXPERIMENTAL_RUST_MCP_RUNTIME_MANAGED="${managed_default}"
    fi
    if [[ -z "${EXPERIMENTAL_RUST_MCP_RUNTIME_URL}" ]]; then
        EXPERIMENTAL_RUST_MCP_RUNTIME_URL="http://127.0.0.1:8787"
    fi
    if [[ -z "${EXPERIMENTAL_RUST_MCP_SESSION_CORE_ENABLED}" ]]; then
        EXPERIMENTAL_RUST_MCP_SESSION_CORE_ENABLED="${session_core_default}"
    fi
    if [[ -z "${EXPERIMENTAL_RUST_MCP_EVENT_STORE_ENABLED}" ]]; then
        EXPERIMENTAL_RUST_MCP_EVENT_STORE_ENABLED="${event_store_default}"
    fi
    if [[ -z "${EXPERIMENTAL_RUST_MCP_RESUME_CORE_ENABLED}" ]]; then
        EXPERIMENTAL_RUST_MCP_RESUME_CORE_ENABLED="${resume_core_default}"
    fi
    if [[ -z "${EXPERIMENTAL_RUST_MCP_LIVE_STREAM_CORE_ENABLED}" ]]; then
        EXPERIMENTAL_RUST_MCP_LIVE_STREAM_CORE_ENABLED="${live_stream_core_default}"
    fi
    if [[ -z "${EXPERIMENTAL_RUST_MCP_AFFINITY_CORE_ENABLED}" ]]; then
        EXPERIMENTAL_RUST_MCP_AFFINITY_CORE_ENABLED="${affinity_core_default}"
    fi
    if [[ -z "${EXPERIMENTAL_RUST_MCP_SESSION_AUTH_REUSE_ENABLED}" ]]; then
        if [[ -n "${RUST_MCP_SESSION_AUTH_REUSE}" ]]; then
            EXPERIMENTAL_RUST_MCP_SESSION_AUTH_REUSE_ENABLED="${RUST_MCP_SESSION_AUTH_REUSE}"
        else
            EXPERIMENTAL_RUST_MCP_SESSION_AUTH_REUSE_ENABLED="${session_auth_reuse_default}"
        fi
    fi
    if [[ -z "${EXPERIMENTAL_RUST_MCP_RUNTIME_UDS}" && "${EXPERIMENTAL_RUST_MCP_RUNTIME_ENABLED}" = "true" && "${EXPERIMENTAL_RUST_MCP_RUNTIME_MANAGED}" = "true" ]]; then
        EXPERIMENTAL_RUST_MCP_RUNTIME_UDS="/tmp/contextforge-mcp-rust.sock"
    fi
    if [[ -z "${MCP_RUST_LISTEN_HTTP}" ]]; then
        MCP_RUST_LISTEN_HTTP="127.0.0.1:8787"
    fi
    if [[ -z "${MCP_RUST_PUBLIC_LISTEN_HTTP}" \
          && "${EXPERIMENTAL_RUST_MCP_RUNTIME_ENABLED}" = "true" \
          && "${EXPERIMENTAL_RUST_MCP_RUNTIME_MANAGED}" = "true" \
          && "${EXPERIMENTAL_RUST_MCP_SESSION_AUTH_REUSE_ENABLED}" = "true" ]]; then
        MCP_RUST_PUBLIC_LISTEN_HTTP="0.0.0.0:8787"
    fi
    if [[ -z "${MCP_RUST_LISTEN_UDS}" && -n "${EXPERIMENTAL_RUST_MCP_RUNTIME_UDS}" ]]; then
        MCP_RUST_LISTEN_UDS="${EXPERIMENTAL_RUST_MCP_RUNTIME_UDS}"
    fi
    if [[ -z "${MCP_RUST_USE_RMCP_UPSTREAM_CLIENT}" ]]; then
        if [[ "${CONTEXTFORGE_ENABLE_RUST_MCP_RMCP_BUILD}" = "true" ]]; then
            MCP_RUST_USE_RMCP_UPSTREAM_CLIENT="true"
        else
            MCP_RUST_USE_RMCP_UPSTREAM_CLIENT="false"
        fi
    fi
    if [[ -z "${MCP_RUST_LOG}" ]]; then
        MCP_RUST_LOG="${RUST_MCP_LOG}"
    fi
    if [[ -z "${MCP_RUST_SESSION_CORE_ENABLED}" ]]; then
        MCP_RUST_SESSION_CORE_ENABLED="${EXPERIMENTAL_RUST_MCP_SESSION_CORE_ENABLED}"
    fi
    if [[ -z "${MCP_RUST_EVENT_STORE_ENABLED}" ]]; then
        MCP_RUST_EVENT_STORE_ENABLED="${EXPERIMENTAL_RUST_MCP_EVENT_STORE_ENABLED}"
    fi
    if [[ -z "${MCP_RUST_RESUME_CORE_ENABLED}" ]]; then
        MCP_RUST_RESUME_CORE_ENABLED="${EXPERIMENTAL_RUST_MCP_RESUME_CORE_ENABLED}"
    fi
    if [[ -z "${MCP_RUST_LIVE_STREAM_CORE_ENABLED}" ]]; then
        MCP_RUST_LIVE_STREAM_CORE_ENABLED="${EXPERIMENTAL_RUST_MCP_LIVE_STREAM_CORE_ENABLED}"
    fi
    if [[ -z "${MCP_RUST_AFFINITY_CORE_ENABLED}" ]]; then
        MCP_RUST_AFFINITY_CORE_ENABLED="${EXPERIMENTAL_RUST_MCP_AFFINITY_CORE_ENABLED}"
    fi
    if [[ -z "${MCP_RUST_SESSION_AUTH_REUSE_ENABLED}" ]]; then
        MCP_RUST_SESSION_AUTH_REUSE_ENABLED="${EXPERIMENTAL_RUST_MCP_SESSION_AUTH_REUSE_ENABLED}"
    fi
    if [[ -z "${MCP_RUST_SESSION_AUTH_REUSE_TTL_SECONDS}" ]]; then
        MCP_RUST_SESSION_AUTH_REUSE_TTL_SECONDS="30"
    fi

    export RUST_MCP_MODE
    export RUST_MCP_LOG
    export RUST_MCP_SESSION_AUTH_REUSE
    export EXPERIMENTAL_RUST_MCP_RUNTIME_ENABLED
    export EXPERIMENTAL_RUST_MCP_RUNTIME_MANAGED
    export EXPERIMENTAL_RUST_MCP_RUNTIME_URL
    export EXPERIMENTAL_RUST_MCP_RUNTIME_UDS
    export EXPERIMENTAL_RUST_MCP_SESSION_CORE_ENABLED
    export EXPERIMENTAL_RUST_MCP_EVENT_STORE_ENABLED
    export EXPERIMENTAL_RUST_MCP_RESUME_CORE_ENABLED
    export EXPERIMENTAL_RUST_MCP_LIVE_STREAM_CORE_ENABLED
    export EXPERIMENTAL_RUST_MCP_AFFINITY_CORE_ENABLED
    export EXPERIMENTAL_RUST_MCP_SESSION_AUTH_REUSE_ENABLED
    export MCP_RUST_LISTEN_HTTP
    export MCP_RUST_LISTEN_UDS
    export MCP_RUST_PUBLIC_LISTEN_HTTP
    export MCP_RUST_LOG
    export MCP_RUST_USE_RMCP_UPSTREAM_CLIENT
    export MCP_RUST_SESSION_CORE_ENABLED
    export MCP_RUST_EVENT_STORE_ENABLED
    export MCP_RUST_RESUME_CORE_ENABLED
    export MCP_RUST_LIVE_STREAM_CORE_ENABLED
    export MCP_RUST_AFFINITY_CORE_ENABLED
    export MCP_RUST_SESSION_AUTH_REUSE_ENABLED
    export MCP_RUST_SESSION_AUTH_REUSE_TTL_SECONDS
}

cleanup() {
    local pids=()

    if [[ -n "${SERVER_PID}" ]] && kill -0 "${SERVER_PID}" 2>/dev/null; then
        pids+=("${SERVER_PID}")
    fi
    if [[ -n "${RUST_MCP_PID}" ]] && kill -0 "${RUST_MCP_PID}" 2>/dev/null; then
        pids+=("${RUST_MCP_PID}")
    fi

    if [[ ${#pids[@]} -gt 0 ]]; then
        kill "${pids[@]}" 2>/dev/null || true
        wait "${pids[@]}" 2>/dev/null || true
    fi
}

print_mcp_runtime_mode() {
    local runtime_mode="python"
    local upstream_client_mode="native"
    local session_core_mode="python"
    local event_store_mode="python"
    local resume_core_mode="python"
    local live_stream_core_mode="python"
    local affinity_core_mode="python"
    local session_auth_reuse_mode="python"

    if [[ "${MCP_RUST_USE_RMCP_UPSTREAM_CLIENT}" = "true" ]]; then
        upstream_client_mode="rmcp"
    fi
    if [[ "${MCP_RUST_SESSION_CORE_ENABLED}" = "true" && "${EXPERIMENTAL_RUST_MCP_RUNTIME_ENABLED}" = "true" ]]; then
        session_core_mode="rust"
    fi
    if [[ "${MCP_RUST_EVENT_STORE_ENABLED}" = "true" && "${EXPERIMENTAL_RUST_MCP_RUNTIME_ENABLED}" = "true" ]]; then
        event_store_mode="rust"
    fi
    if [[ "${MCP_RUST_RESUME_CORE_ENABLED}" = "true" && "${EXPERIMENTAL_RUST_MCP_RUNTIME_ENABLED}" = "true" ]]; then
        resume_core_mode="rust"
    fi
    if [[ "${MCP_RUST_LIVE_STREAM_CORE_ENABLED}" = "true" && "${EXPERIMENTAL_RUST_MCP_RUNTIME_ENABLED}" = "true" ]]; then
        live_stream_core_mode="rust"
    fi
    if [[ "${MCP_RUST_AFFINITY_CORE_ENABLED}" = "true" && "${EXPERIMENTAL_RUST_MCP_RUNTIME_ENABLED}" = "true" ]]; then
        affinity_core_mode="rust"
    fi
    if [[ "${MCP_RUST_SESSION_AUTH_REUSE_ENABLED}" = "true" && "${EXPERIMENTAL_RUST_MCP_RUNTIME_ENABLED}" = "true" ]]; then
        session_auth_reuse_mode="rust"
    fi

    if [[ "${EXPERIMENTAL_RUST_MCP_RUNTIME_ENABLED}" = "true" ]]; then
        if [[ "${EXPERIMENTAL_RUST_MCP_RUNTIME_MANAGED}" = "true" ]]; then
            runtime_mode="rust-managed"
            echo "MCP runtime mode: ${runtime_mode} (sidecar managed in this container, upstream client: ${upstream_client_mode}, session core: ${session_core_mode}, event store: ${event_store_mode}, resume core: ${resume_core_mode}, live stream core: ${live_stream_core_mode}, affinity core: ${affinity_core_mode}, session auth reuse: ${session_auth_reuse_mode})"
        else
            runtime_mode="rust-external"
            echo "MCP runtime mode: ${runtime_mode} (external sidecar target: ${EXPERIMENTAL_RUST_MCP_RUNTIME_UDS:-${EXPERIMENTAL_RUST_MCP_RUNTIME_URL}}, upstream client: ${upstream_client_mode}, session core: ${session_core_mode}, event store: ${event_store_mode}, resume core: ${resume_core_mode}, live stream core: ${live_stream_core_mode}, affinity core: ${affinity_core_mode}, session auth reuse: ${session_auth_reuse_mode})"
        fi

        if [[ "${MCP_RUST_USE_RMCP_UPSTREAM_CLIENT}" = "true" && "${CONTEXTFORGE_ENABLE_RUST_MCP_RMCP_BUILD}" != "true" ]]; then
            echo "ERROR: MCP_RUST_USE_RMCP_UPSTREAM_CLIENT=true but this image was built without rmcp support."
            echo "Rebuild with RUST_MCP_BUILD=1 or --build-arg ENABLE_RUST_MCP_RMCP=true."
            exit 1
        fi
        return
    fi

    if [[ "${CONTEXTFORGE_ENABLE_RUST_BUILD}" = "true" ]]; then
        runtime_mode="python-rust-built-disabled"
        echo "WARNING: MCP runtime mode: ${runtime_mode}"
        echo "WARNING: Rust MCP artifacts are present in this image, but EXPERIMENTAL_RUST_MCP_RUNTIME_ENABLED=false so /mcp will run on the Python transport."
        echo "WARNING: Set RUST_MCP_MODE=shadow, RUST_MCP_MODE=edge, or RUST_MCP_MODE=full to activate the Rust MCP runtime."
        return
    fi

    echo "MCP runtime mode: ${runtime_mode} (Rust MCP artifacts not built into this image)"
}

build_server_command() {
    case "${HTTP_SERVER}" in
        granian)
            echo "Starting ContextForge with Granian (Rust-based HTTP server)..."
            SERVER_CMD=(./run-granian.sh "$@")
            ;;
        gunicorn)
            echo "Starting ContextForge with Gunicorn + Uvicorn..."
            SERVER_CMD=(./run-gunicorn.sh "$@")
            ;;
        *)
            echo "ERROR: Unknown HTTP_SERVER value: ${HTTP_SERVER}"
            echo "Valid options: granian, gunicorn"
            exit 1
            ;;
    esac
}

start_managed_rust_mcp_runtime() {
    local runtime_bin="/app/bin/contextforge-mcp-runtime"
    local rust_listen_http="${MCP_RUST_LISTEN_HTTP:-127.0.0.1:8787}"
    local rust_listen_uds="${MCP_RUST_LISTEN_UDS:-${EXPERIMENTAL_RUST_MCP_RUNTIME_UDS:-}}"
    local app_root_path="${APP_ROOT_PATH:-}"
    local backend_rpc_url="${MCP_RUST_BACKEND_RPC_URL:-http://127.0.0.1:${PORT:-4444}${app_root_path}/_internal/mcp/rpc}"
    local rust_database_url="${MCP_RUST_DATABASE_URL:-}"
    local rust_redis_url="${MCP_RUST_REDIS_URL:-${REDIS_URL:-}}"
    local rust_cache_prefix="${MCP_RUST_CACHE_PREFIX:-${CACHE_PREFIX:-mcpgw:}}"
    local rust_event_store_max="${MCP_RUST_EVENT_STORE_MAX_EVENTS_PER_STREAM:-${STREAMABLE_HTTP_MAX_EVENTS_PER_STREAM:-100}}"
    local rust_event_store_ttl="${MCP_RUST_EVENT_STORE_TTL_SECONDS:-${STREAMABLE_HTTP_EVENT_TTL:-3600}}"

    if [[ -z "${rust_database_url}" && -n "${DATABASE_URL:-}" ]]; then
        case "${DATABASE_URL}" in
            postgresql+psycopg://*)
                rust_database_url="${DATABASE_URL/postgresql+psycopg:\/\//postgresql://}"
                ;;
            postgresql://*|postgres://*)
                rust_database_url="${DATABASE_URL}"
                ;;
        esac
    fi

    if [[ "${CONTEXTFORGE_ENABLE_RUST_BUILD}" != "true" ]]; then
        echo "ERROR: EXPERIMENTAL_RUST_MCP_RUNTIME_ENABLED=true but this image was built without Rust artifacts."
        echo "Rebuild with RUST_MCP_BUILD=1 or --build-arg ENABLE_RUST=true, or set EXPERIMENTAL_RUST_MCP_RUNTIME_MANAGED=false to use an external sidecar."
        exit 1
    fi

    if [[ ! -x "${runtime_bin}" ]]; then
        echo "ERROR: Rust MCP runtime binary not found at ${runtime_bin}"
        exit 1
    fi

    export MCP_RUST_LISTEN_HTTP="${rust_listen_http}"
    if [[ -n "${rust_listen_uds}" ]]; then
        export MCP_RUST_LISTEN_UDS="${rust_listen_uds}"
    else
        unset MCP_RUST_LISTEN_UDS || true
        unset EXPERIMENTAL_RUST_MCP_RUNTIME_UDS || true
    fi
    if [[ -n "${MCP_RUST_PUBLIC_LISTEN_HTTP:-}" ]]; then
        export MCP_RUST_PUBLIC_LISTEN_HTTP="${MCP_RUST_PUBLIC_LISTEN_HTTP}"
    else
        unset MCP_RUST_PUBLIC_LISTEN_HTTP || true
    fi
    export MCP_RUST_BACKEND_RPC_URL="${backend_rpc_url}"
    export MCP_RUST_SESSION_CORE_ENABLED="${MCP_RUST_SESSION_CORE_ENABLED}"
    export MCP_RUST_EVENT_STORE_ENABLED="${MCP_RUST_EVENT_STORE_ENABLED}"
    export MCP_RUST_RESUME_CORE_ENABLED="${MCP_RUST_RESUME_CORE_ENABLED}"
    export MCP_RUST_LIVE_STREAM_CORE_ENABLED="${MCP_RUST_LIVE_STREAM_CORE_ENABLED}"
    export MCP_RUST_SESSION_AUTH_REUSE_ENABLED="${MCP_RUST_SESSION_AUTH_REUSE_ENABLED}"
    export MCP_RUST_SESSION_AUTH_REUSE_TTL_SECONDS="${MCP_RUST_SESSION_AUTH_REUSE_TTL_SECONDS}"
    export MCP_RUST_CACHE_PREFIX="${rust_cache_prefix}"
    export MCP_RUST_EVENT_STORE_MAX_EVENTS_PER_STREAM="${rust_event_store_max}"
    export MCP_RUST_EVENT_STORE_TTL_SECONDS="${rust_event_store_ttl}"
    if [[ -n "${rust_database_url}" ]]; then
        export MCP_RUST_DATABASE_URL="${rust_database_url}"
    fi
    if [[ -n "${rust_redis_url}" ]]; then
        export MCP_RUST_REDIS_URL="${rust_redis_url}"
    fi

    if [[ -n "${rust_listen_uds}" ]]; then
        echo "Starting experimental Rust MCP runtime on unix://${MCP_RUST_LISTEN_UDS} (backend: ${MCP_RUST_BACKEND_RPC_URL})..."
    else
        echo "Starting experimental Rust MCP runtime on ${MCP_RUST_LISTEN_HTTP} (backend: ${MCP_RUST_BACKEND_RPC_URL})..."
    fi
    "${runtime_bin}" &
    RUST_MCP_PID=$!

    python3 - <<'PY'
import httpx
import os
import sys
import time
import urllib.error
import urllib.request

base_url = os.environ.get("EXPERIMENTAL_RUST_MCP_RUNTIME_URL", "http://127.0.0.1:8787").rstrip("/")
health_url = f"{base_url}/health"
uds_path = os.environ.get("EXPERIMENTAL_RUST_MCP_RUNTIME_UDS") or os.environ.get("MCP_RUST_LISTEN_UDS")

for _ in range(60):
    if uds_path:
        try:
            with httpx.Client(transport=httpx.HTTPTransport(uds=uds_path), timeout=2.0) as client:
                response = client.get(health_url)
                if response.status_code == 200:
                    sys.exit(0)
        except OSError:
            time.sleep(0.5)
        except httpx.HTTPError:
            time.sleep(0.5)
    else:
        try:
            with urllib.request.urlopen(health_url, timeout=2) as response:
                if response.status == 200:
                    sys.exit(0)
        except (OSError, urllib.error.URLError):
            time.sleep(0.5)

print(f"ERROR: Experimental Rust MCP runtime failed health check at {health_url}", file=sys.stderr)
sys.exit(1)
PY
}

apply_rust_mcp_mode_defaults
build_server_command "$@"
print_mcp_runtime_mode

if [[ "${EXPERIMENTAL_RUST_MCP_RUNTIME_ENABLED}" = "true" && "${EXPERIMENTAL_RUST_MCP_RUNTIME_MANAGED}" = "true" ]]; then
    trap cleanup EXIT INT TERM
    start_managed_rust_mcp_runtime
    "${SERVER_CMD[@]}" &
    SERVER_PID=$!

    set +e
    wait -n "${SERVER_PID}" "${RUST_MCP_PID}"
    STATUS=$?
    set -e

    exit "${STATUS}"
fi

exec "${SERVER_CMD[@]}"
