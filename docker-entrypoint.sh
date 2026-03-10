#!/usr/bin/env bash
set -euo pipefail

HTTP_SERVER="${HTTP_SERVER:-gunicorn}"
EXPERIMENTAL_RUST_MCP_RUNTIME_ENABLED="${EXPERIMENTAL_RUST_MCP_RUNTIME_ENABLED:-false}"
EXPERIMENTAL_RUST_MCP_RUNTIME_MANAGED="${EXPERIMENTAL_RUST_MCP_RUNTIME_MANAGED:-true}"
EXPERIMENTAL_RUST_MCP_RUNTIME_URL="${EXPERIMENTAL_RUST_MCP_RUNTIME_URL:-http://127.0.0.1:8787}"
EXPERIMENTAL_RUST_MCP_RUNTIME_UDS="${EXPERIMENTAL_RUST_MCP_RUNTIME_UDS:-}"
CONTEXTFORGE_ENABLE_RUST_BUILD="${CONTEXTFORGE_ENABLE_RUST_BUILD:-false}"
CONTEXTFORGE_ENABLE_RUST_MCP_RMCP_BUILD="${CONTEXTFORGE_ENABLE_RUST_MCP_RMCP_BUILD:-false}"
MCP_RUST_USE_RMCP_UPSTREAM_CLIENT="${MCP_RUST_USE_RMCP_UPSTREAM_CLIENT:-false}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "${SCRIPT_DIR}" || {
    echo "ERROR: Cannot change to script directory: ${SCRIPT_DIR}"
    exit 1
}

RUST_MCP_PID=""
SERVER_PID=""

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

    if [[ "${MCP_RUST_USE_RMCP_UPSTREAM_CLIENT}" = "true" ]]; then
        upstream_client_mode="rmcp"
    fi

    if [[ "${EXPERIMENTAL_RUST_MCP_RUNTIME_ENABLED}" = "true" ]]; then
        if [[ "${EXPERIMENTAL_RUST_MCP_RUNTIME_MANAGED}" = "true" ]]; then
            runtime_mode="rust-managed"
            echo "MCP runtime mode: ${runtime_mode} (sidecar managed in this container, upstream client: ${upstream_client_mode})"
        else
            runtime_mode="rust-external"
            echo "MCP runtime mode: ${runtime_mode} (external sidecar target: ${EXPERIMENTAL_RUST_MCP_RUNTIME_UDS:-${EXPERIMENTAL_RUST_MCP_RUNTIME_URL}}, upstream client: ${upstream_client_mode})"
        fi

        if [[ "${MCP_RUST_USE_RMCP_UPSTREAM_CLIENT}" = "true" && "${CONTEXTFORGE_ENABLE_RUST_MCP_RMCP_BUILD}" != "true" ]]; then
            echo "ERROR: MCP_RUST_USE_RMCP_UPSTREAM_CLIENT=true but this image was built without rmcp support."
            echo "Rebuild with --build-arg ENABLE_RUST_MCP_RMCP=true."
            exit 1
        fi
        return
    fi

    if [[ "${CONTEXTFORGE_ENABLE_RUST_BUILD}" = "true" ]]; then
        runtime_mode="python-rust-built-disabled"
        echo "WARNING: MCP runtime mode: ${runtime_mode}"
        echo "WARNING: Rust MCP artifacts are present in this image, but EXPERIMENTAL_RUST_MCP_RUNTIME_ENABLED=false so /mcp will run on the Python transport."
        echo "WARNING: Set EXPERIMENTAL_RUST_MCP_RUNTIME_ENABLED=true to activate the Rust MCP runtime."
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
        echo "Rebuild with --build-arg ENABLE_RUST=true or set EXPERIMENTAL_RUST_MCP_RUNTIME_MANAGED=false to use an external sidecar."
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
    export MCP_RUST_BACKEND_RPC_URL="${backend_rpc_url}"
    if [[ -n "${rust_database_url}" ]]; then
        export MCP_RUST_DATABASE_URL="${rust_database_url}"
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
