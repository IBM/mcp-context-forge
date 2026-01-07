#!/usr/bin/env bash
#───────────────────────────────────────────────────────────────────────────────
#  Script : run-granian.sh
#  Author : Mihai Criveti
#  Purpose: Launch the MCP Gateway API under Granian (Rust-based ASGI server)
#
#  Description:
#    This script provides a robust way to launch a production API server using
#    Granian with the following features:
#
#    - Rust-based HTTP server (Hyper + Tokio) for high performance
#    - Native HTTP/2 support
#    - Native WebSocket support
#    - Native mTLS support
#    - Portable Python detection across different distros
#    - Virtual environment handling
#    - Configurable via environment variables for CI/CD pipelines
#    - Optional TLS/SSL support for secure connections
#    - Process lock to prevent duplicate instances
#    - Auto-detection of optimal worker count based on CPU cores
#
#  Environment Variables:
#    PYTHON                        : Path to Python interpreter (optional)
#    VIRTUAL_ENV                   : Path to active virtual environment (auto-detected)
#    HOST                         : Bind host (default: 0.0.0.0)
#    PORT                         : Bind port (default: 4444)
#    GRANIAN_WORKERS              : Number of worker processes (default: "auto" = CPU cores, max 16)
#    GRANIAN_RUNTIME_MODE         : Runtime mode: auto, mt, st (default: mt for >8 workers, else st)
#    GRANIAN_RUNTIME_THREADS      : Runtime threads per worker (default: 1)
#    GRANIAN_BLOCKING_THREADS     : Blocking threads per worker (default: 1)
#    GRANIAN_HTTP                 : HTTP version: auto, 1, 2 (default: auto)
#    GRANIAN_LOOP                 : Event loop: uvloop, asyncio, rloop (default: uvloop)
#    GRANIAN_TASK_IMPL            : Task implementation: asyncio, rust (default: auto-detect)
#    GRANIAN_HTTP1_PIPELINE_FLUSH : Enable HTTP/1 pipeline flush (default: true)
#    GRANIAN_HTTP1_BUFFER_SIZE    : HTTP/1 buffer size in bytes (default: 524288)
#    GRANIAN_BACKLOG              : Connection backlog (default: 2048)
#    GRANIAN_BACKPRESSURE         : Max concurrent requests per worker (default: 512)
#    GRANIAN_RESPAWN_FAILED       : Respawn failed workers (default: true)
#    GRANIAN_DEV_MODE             : Enable hot reload (default: false, requires granian[reload])
#    GRANIAN_LOG_LEVEL            : Log level: debug, info, warning, error (default: info)
#    SSL                          : Enable TLS/SSL (true/false, default: false)
#    CERT_FILE                    : Path to SSL certificate (default: certs/cert.pem)
#    KEY_FILE                     : Path to SSL private key (default: certs/key.pem)
#    FORCE_START                  : Force start even if another instance is running (default: false)
#    DISABLE_ACCESS_LOG           : Disable access logging for performance (default: true)
#
#  Usage:
#    ./run-granian.sh                     # Run with defaults
#    SSL=true ./run-granian.sh            # Run with TLS enabled
#    GRANIAN_WORKERS=16 ./run-granian.sh  # Run with 16 workers
#    GRANIAN_HTTP=2 ./run-granian.sh      # Force HTTP/2
#    GRANIAN_DEV_MODE=true ./run-granian.sh # Run with hot reload
#    FORCE_START=true ./run-granian.sh    # Force start (bypass lock check)
#
#  Tuning Profiles (adjust based on workload):
#    # High-throughput (fewer workers, more threads per worker)
#    GRANIAN_WORKERS=4 GRANIAN_RUNTIME_THREADS=4 ./run-granian.sh
#
#    # High-concurrency (more workers, max backpressure)
#    GRANIAN_WORKERS=16 GRANIAN_BACKPRESSURE=1024 GRANIAN_BACKLOG=4096 ./run-granian.sh
#
#    # Memory-constrained (fewer workers)
#    GRANIAN_WORKERS=2 ./run-granian.sh
#───────────────────────────────────────────────────────────────────────────────

# Exit immediately on error, undefined variable, or pipe failure
set -euo pipefail

#────────────────────────────────────────────────────────────────────────────────
# SECTION 1: Script Location Detection
#────────────────────────────────────────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

cd "${SCRIPT_DIR}" || {
    echo "❌  FATAL: Cannot change to script directory: ${SCRIPT_DIR}"
    exit 1
}

#────────────────────────────────────────────────────────────────────────────────
# SECTION 2: Process Lock Check
#────────────────────────────────────────────────────────────────────────────────
LOCK_FILE="/tmp/mcpgateway-granian.lock"
FORCE_START=${FORCE_START:-false}

check_existing_process() {
    if [[ -f "${LOCK_FILE}" ]]; then
        local pid
        pid=$(<"${LOCK_FILE}")

        if kill -0 "${pid}" 2>/dev/null; then
            echo "⚠️  WARNING: Another instance of MCP Gateway appears to be running (PID: ${pid})"

            if ps -p "${pid}" -o comm= | grep -q granian; then
                if [[ "${FORCE_START}" != "true" ]]; then
                    echo "❌  FATAL: MCP Gateway is already running!"
                    echo "   To stop it: kill ${pid}"
                    echo "   To force start anyway: FORCE_START=true $0"
                    exit 1
                else
                    echo "⚠️  Force starting despite existing process..."
                fi
            else
                echo "🔧  Lock file exists but process ${pid} is not granian. Cleaning up..."
                rm -f "${LOCK_FILE}"
            fi
        else
            echo "🔧  Stale lock file found. Cleaning up..."
            rm -f "${LOCK_FILE}"
        fi
    fi
}

cleanup() {
    if [[ -f "${LOCK_FILE}" ]] && [[ "$(<"${LOCK_FILE}")" == "$$" ]]; then
        rm -f "${LOCK_FILE}"
        echo "🔧  Cleaned up lock file"
    fi
}

trap cleanup INT TERM
check_existing_process
echo $$ > "${LOCK_FILE}"

#────────────────────────────────────────────────────────────────────────────────
# SECTION 3: Virtual Environment Activation
#────────────────────────────────────────────────────────────────────────────────
if [[ -z "${VIRTUAL_ENV:-}" ]]; then
    if [[ -f "${HOME}/.venv/mcpgateway/bin/activate" ]]; then
        echo "🔧  Activating virtual environment: ${HOME}/.venv/mcpgateway"
        # shellcheck disable=SC1090
        source "${HOME}/.venv/mcpgateway/bin/activate"
    elif [[ -f "${SCRIPT_DIR}/.venv/bin/activate" ]]; then
        echo "🔧  Activating virtual environment in script directory"
        # shellcheck disable=SC1090
        source "${SCRIPT_DIR}/.venv/bin/activate"
    else
        echo "⚠️  WARNING: No virtual environment found!"
        echo "   Consider creating one with: python3 -m venv ~/.venv/mcpgateway"
    fi
else
    echo "✓  Virtual environment already active: ${VIRTUAL_ENV}"
fi

#────────────────────────────────────────────────────────────────────────────────
# SECTION 4: Python Interpreter Detection
#────────────────────────────────────────────────────────────────────────────────
if [[ -z "${PYTHON:-}" ]]; then
    if [[ -n "${VIRTUAL_ENV:-}" && -x "${VIRTUAL_ENV}/bin/python" ]]; then
        PYTHON="${VIRTUAL_ENV}/bin/python"
        echo "🐍  Using Python from virtual environment"
    else
        if command -v python3 &> /dev/null; then
            PYTHON="$(command -v python3)"
            echo "🐍  Found system Python3: ${PYTHON}"
        elif command -v python &> /dev/null; then
            PYTHON="$(command -v python)"
            echo "🐍  Found system Python: ${PYTHON}"
        else
            PYTHON=""
        fi
    fi
fi

if [[ -z "${PYTHON}" ]] || [[ ! -x "${PYTHON}" ]]; then
    echo "❌  FATAL: Could not locate a Python interpreter!"
    exit 1
fi

PY_VERSION="$("${PYTHON}" --version 2>&1)"
echo "📋  Python version: ${PY_VERSION}"

if ! "${PYTHON}" -c "import sys; sys.exit(0 if sys.version_info[0] >= 3 else 1)" 2>/dev/null; then
    echo "❌  FATAL: Python 3.x is required!"
    exit 1
fi

#────────────────────────────────────────────────────────────────────────────────
# SECTION 5: Display Application Banner
#────────────────────────────────────────────────────────────────────────────────
cat <<'EOF'
███╗   ███╗ ██████╗██████╗      ██████╗  █████╗ ████████╗███████╗██╗    ██╗ █████╗ ██╗   ██╗
████╗ ████║██╔════╝██╔══██╗    ██╔════╝ ██╔══██╗╚══██╔══╝██╔════╝██║    ██║██╔══██╗╚██╗ ██╔╝
██╔████╔██║██║     ██████╔╝    ██║  ███╗███████║   ██║   █████╗  ██║ █╗ ██║███████║ ╚████╔╝
██║╚██╔╝██║██║     ██╔═══╝     ██║   ██║██╔══██║   ██║   ██╔══╝  ██║███╗██║██╔══██║  ╚██╔╝
██║ ╚═╝ ██║╚██████╗██║         ╚██████╔╝██║  ██║   ██║   ███████╗╚███╔███╔╝██║  ██║   ██║
╚═╝     ╚═╝ ╚═════╝╚═╝          ╚═════╝ ╚═╝  ╚═╝   ╚═╝   ╚══════╝ ╚══╝╚══╝ ╚═╝  ╚═╝   ╚═╝
                                                                    ⚡ Powered by Granian
EOF

#────────────────────────────────────────────────────────────────────────────────
# SECTION 6: Configure Granian Settings
#────────────────────────────────────────────────────────────────────────────────

# Host and port configuration
HOST=${HOST:-0.0.0.0}
PORT=${PORT:-4444}

# Worker configuration
if [[ -z "${GRANIAN_WORKERS:-}" || "${GRANIAN_WORKERS}" == "auto" ]]; then
    if command -v nproc &>/dev/null; then
        CPU_COUNT=$(nproc)
    elif command -v sysctl &>/dev/null && sysctl -n hw.ncpu &>/dev/null; then
        CPU_COUNT=$(sysctl -n hw.ncpu)
    else
        CPU_COUNT=4
    fi
    # Granian recommends 1 worker per CPU core (it's more efficient than Gunicorn)
    GRANIAN_WORKERS=$((CPU_COUNT > 16 ? 16 : CPU_COUNT))
    echo "🔧  Auto-detected CPU cores: ${CPU_COUNT} → Workers: ${GRANIAN_WORKERS}"
fi

# Threading configuration
GRANIAN_RUNTIME_THREADS=${GRANIAN_RUNTIME_THREADS:-1}
GRANIAN_BLOCKING_THREADS=${GRANIAN_BLOCKING_THREADS:-1}

# Runtime mode: auto, mt (multi-threaded), st (single-threaded)
# mt mode scales better with many CPUs (>8 cores)
if [[ -z "${GRANIAN_RUNTIME_MODE:-}" ]]; then
    if [[ "${GRANIAN_WORKERS}" -gt 8 ]]; then
        GRANIAN_RUNTIME_MODE="mt"
    else
        GRANIAN_RUNTIME_MODE="st"
    fi
fi

# HTTP version: auto, 1, 2
GRANIAN_HTTP=${GRANIAN_HTTP:-auto}

# Event loop: auto, asyncio, uvloop, rloop
# uvloop provides best performance on Linux/macOS (installed via granian[uvloop])
GRANIAN_LOOP=${GRANIAN_LOOP:-uvloop}

# Task implementation: asyncio or rust
# rust provides faster async task scheduling but only works on Python < 3.12
# Auto-detect: use rust on Python < 3.12, asyncio otherwise
if [[ -z "${GRANIAN_TASK_IMPL:-}" ]]; then
    PY_MINOR=$("${PYTHON}" -c "import sys; print(sys.version_info.minor)")
    if [[ "${PY_MINOR}" -lt 12 ]]; then
        GRANIAN_TASK_IMPL="rust"
    else
        GRANIAN_TASK_IMPL="asyncio"
    fi
fi

# HTTP/1 optimizations
GRANIAN_HTTP1_PIPELINE_FLUSH=${GRANIAN_HTTP1_PIPELINE_FLUSH:-true}
GRANIAN_HTTP1_BUFFER_SIZE=${GRANIAN_HTTP1_BUFFER_SIZE:-524288}

# Backlog and backpressure for high concurrency
GRANIAN_BACKLOG=${GRANIAN_BACKLOG:-2048}
GRANIAN_BACKPRESSURE=${GRANIAN_BACKPRESSURE:-512}

# Developer mode with hot reload (requires granian[reload])
GRANIAN_DEV_MODE=${GRANIAN_DEV_MODE:-false}

# Respawn failed workers automatically (recommended for production)
GRANIAN_RESPAWN_FAILED=${GRANIAN_RESPAWN_FAILED:-true}

# Log level
GRANIAN_LOG_LEVEL=${GRANIAN_LOG_LEVEL:-info}

echo "📊  Granian Configuration:"
echo "   Host: ${HOST}:${PORT}"
echo "   Workers: ${GRANIAN_WORKERS}"
echo "   Runtime mode: ${GRANIAN_RUNTIME_MODE}"
echo "   Runtime threads per worker: ${GRANIAN_RUNTIME_THREADS}"
echo "   Blocking threads: ${GRANIAN_BLOCKING_THREADS}"
echo "   HTTP version: ${GRANIAN_HTTP}"
echo "   Event loop: ${GRANIAN_LOOP}"
echo "   Task implementation: ${GRANIAN_TASK_IMPL}"
echo "   HTTP/1 pipeline flush: ${GRANIAN_HTTP1_PIPELINE_FLUSH}"
echo "   HTTP/1 buffer size: ${GRANIAN_HTTP1_BUFFER_SIZE}"
echo "   Backlog: ${GRANIAN_BACKLOG}"
echo "   Backpressure: ${GRANIAN_BACKPRESSURE}"
echo "   Respawn failed workers: ${GRANIAN_RESPAWN_FAILED}"
echo "   Developer Mode: ${GRANIAN_DEV_MODE}"
echo "   Log Level: ${GRANIAN_LOG_LEVEL}"

#────────────────────────────────────────────────────────────────────────────────
# SECTION 7: Configure TLS/SSL Settings
#────────────────────────────────────────────────────────────────────────────────
SSL=${SSL:-false}
CERT_FILE=${CERT_FILE:-certs/cert.pem}
KEY_FILE=${KEY_FILE:-certs/key.pem}

if [[ "${SSL}" == "true" ]]; then
    echo "🔐  Configuring TLS/SSL..."

    if [[ ! -f "${CERT_FILE}" ]]; then
        echo "❌  FATAL: SSL certificate file not found: ${CERT_FILE}"
        exit 1
    fi

    if [[ ! -f "${KEY_FILE}" ]]; then
        echo "❌  FATAL: SSL private key file not found: ${KEY_FILE}"
        exit 1
    fi

    echo "✓  TLS enabled - using:"
    echo "   Certificate: ${CERT_FILE}"
    echo "   Private Key: ${KEY_FILE}"
else
    echo "🔓  Running without TLS (HTTP only)"
fi

#────────────────────────────────────────────────────────────────────────────────
# SECTION 8: Verify Granian Installation
#────────────────────────────────────────────────────────────────────────────────
if ! command -v granian &> /dev/null; then
    echo "❌  FATAL: granian command not found!"
    echo "   Please install it with: pip install 'mcpgateway[granian]'"
    echo "   Or: pip install granian"
    exit 1
fi

GRANIAN_VERSION=$(granian --version 2>&1 || echo "unknown")
echo "✓  Granian found: $(command -v granian) (${GRANIAN_VERSION})"

#────────────────────────────────────────────────────────────────────────────────
# SECTION 9: Launch Granian Server
#────────────────────────────────────────────────────────────────────────────────
echo "🚀  Starting Granian server..."
echo "─────────────────────────────────────────────────────────────────────"

# Build command array with performance-optimized settings
cmd=(
    granian
    --interface asgi
    --host "${HOST}"
    --port "${PORT}"
    --workers "${GRANIAN_WORKERS}"
    --runtime-mode "${GRANIAN_RUNTIME_MODE}"
    --runtime-threads "${GRANIAN_RUNTIME_THREADS}"
    --blocking-threads "${GRANIAN_BLOCKING_THREADS}"
    --loop "${GRANIAN_LOOP}"
    --task-impl "${GRANIAN_TASK_IMPL}"
    --http "${GRANIAN_HTTP}"
    --http1-buffer-size "${GRANIAN_HTTP1_BUFFER_SIZE}"
    --backlog "${GRANIAN_BACKLOG}"
    --backpressure "${GRANIAN_BACKPRESSURE}"
    --log-level "${GRANIAN_LOG_LEVEL}"
)

# HTTP/1 pipeline flush (experimental - aggregates flushes for pipelined responses)
if [[ "${GRANIAN_HTTP1_PIPELINE_FLUSH}" == "true" ]]; then
    cmd+=( --http1-pipeline-flush )
fi

# Process naming (optional - requires granian[pname] and setproctitle)
if "${PYTHON}" -c "import setproctitle" 2>/dev/null; then
    cmd+=( --process-name "mcpgateway" )
    echo "✓  Process naming enabled"
fi

# WebSocket support (enabled by default)
cmd+=( --ws )

# Respawn failed workers (recommended for production)
if [[ "${GRANIAN_RESPAWN_FAILED}" == "true" ]]; then
    cmd+=( --respawn-failed-workers )
fi

# Access logging
DISABLE_ACCESS_LOG=${DISABLE_ACCESS_LOG:-true}
if [[ "${DISABLE_ACCESS_LOG}" == "true" ]]; then
    cmd+=( --no-access-log )
    echo "🚫  Access logging disabled for performance"
else
    cmd+=( --access-log )
fi

# Developer mode with hot reload (requires granian[reload])
if [[ "${GRANIAN_DEV_MODE}" == "true" ]]; then
    cmd+=( --reload )
    echo "🔧  Developer mode enabled - hot reload active"

    # In dev mode, reduce workers for better debugging
    if [[ "${GRANIAN_WORKERS}" -gt 2 ]]; then
        echo "   Reducing workers to 2 for developer mode (was ${GRANIAN_WORKERS})"
        # Update workers in command array
        for i in "${!cmd[@]}"; do
            if [[ "${cmd[$i]}" == "--workers" ]]; then
                cmd[$((i+1))]=2
                break
            fi
        done
    fi
fi

# SSL/TLS configuration
if [[ "${SSL}" == "true" ]]; then
    cmd+=( --ssl-certificate "${CERT_FILE}" --ssl-keyfile "${KEY_FILE}" )
fi

# Add the application module (Granian uses module:app format)
cmd+=( "mcpgateway.main:app" )

# Display final command for debugging
echo "📋  Command: ${cmd[*]}"
echo "─────────────────────────────────────────────────────────────────────"

# Launch Granian
trap - EXIT
exec "${cmd[@]}"
