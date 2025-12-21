#!/usr/bin/env bash
#───────────────────────────────────────────────────────────────────────────────
#  Script : run-gunicorn.sh
#  Author : Mihai Criveti
#  Purpose: Launch the MCP Gateway API under Gunicorn with optional TLS support
#
#  Description:
#    This script provides a robust way to launch a production API server using
#    Gunicorn with the following features:
#
#    - Portable Python detection across different distros (python vs python3)
#    - Virtual environment handling (activates project venv if available)
#    - Configurable via environment variables for CI/CD pipelines
#    - Optional TLS/SSL support for secure connections
#    - Comprehensive error handling and user feedback
#    - Process lock to prevent duplicate instances
#    - Auto-detection of optimal worker count based on CPU cores
#    - Support for preloading application code (memory optimization)
#
#  Environment Variables:
#    PYTHON                        : Path to Python interpreter (optional)
#    VIRTUAL_ENV                   : Path to active virtual environment (auto-detected)
#    GUNICORN_WORKERS             : Number of worker processes (default: "auto" = 2*CPU+1, capped at 16)
#    GUNICORN_TIMEOUT             : Worker timeout in seconds (default: 600)
#    GUNICORN_MAX_REQUESTS        : Max requests per worker before restart (default: 100000)
#    GUNICORN_MAX_REQUESTS_JITTER : Random jitter for max requests (default: 100)
#    GUNICORN_PRELOAD_APP         : Preload app before forking workers (default: true)
#    GUNICORN_DEV_MODE            : Enable developer mode with hot reload (default: false)
#    SSL                          : Enable TLS/SSL (true/false, default: false)
#    CERT_FILE                    : Path to SSL certificate (default: certs/cert.pem)
#    KEY_FILE                     : Path to SSL private key (default: certs/key.pem)
#    FORCE_START                  : Force start even if another instance is running (default: false)
#    DISABLE_ACCESS_LOG           : Disable access logging for performance (default: true)
#
#  Usage:
#    ./run-gunicorn.sh                     # Run with defaults
#    SSL=true ./run-gunicorn.sh            # Run with TLS enabled
#    GUNICORN_WORKERS=16 ./run-gunicorn.sh # Run with 16 workers
#    GUNICORN_PRELOAD_APP=true ./run-gunicorn.sh # Preload app for memory optimization
#    GUNICORN_DEV_MODE=true ./run-gunicorn.sh    # Run in developer mode with hot reload
#    FORCE_START=true ./run-gunicorn.sh    # Force start (bypass lock check)
#───────────────────────────────────────────────────────────────────────────────

# Exit immediately on error, undefined variable, or pipe failure
set -euo pipefail

#────────────────────────────────────────────────────────────────────────────────
# SECTION 1: Script Location Detection
# Determine the absolute path to this script's directory for relative path resolution
#────────────────────────────────────────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Change to script directory to ensure relative paths work correctly
# This ensures gunicorn.config.py and cert paths resolve properly
cd "${SCRIPT_DIR}" || {
    echo "❌  FATAL: Cannot change to script directory: ${SCRIPT_DIR}"
    exit 1
}

#────────────────────────────────────────────────────────────────────────────────
# SECTION 2: Process Lock Check
# Prevent multiple instances from running simultaneously unless forced
#────────────────────────────────────────────────────────────────────────────────
LOCK_FILE="/tmp/mcpgateway-gunicorn.lock"
FORCE_START=${FORCE_START:-false}

check_existing_process() {
    if [[ -f "${LOCK_FILE}" ]]; then
        local pid
        pid=$(<"${LOCK_FILE}")

        # Check if the process is actually running
        if kill -0 "${pid}" 2>/dev/null; then
            echo "⚠️  WARNING: Another instance of MCP Gateway appears to be running (PID: ${pid})"

            # Check if it's actually gunicorn
            if ps -p "${pid}" -o comm= | grep -q gunicorn; then
                if [[ "${FORCE_START}" != "true" ]]; then
                    echo "❌  FATAL: MCP Gateway is already running!"
                    echo "   To stop it: kill ${pid}"
                    echo "   To force start anyway: FORCE_START=true $0"
                    exit 1
                else
                    echo "⚠️  Force starting despite existing process..."
                fi
            else
                echo "🔧  Lock file exists but process ${pid} is not gunicorn. Cleaning up..."
                rm -f "${LOCK_FILE}"
            fi
        else
            echo "🔧  Stale lock file found. Cleaning up..."
            rm -f "${LOCK_FILE}"
        fi
    fi
}

# Create cleanup function
cleanup() {
    # Only clean up if we're the process that created the lock
    if [[ -f "${LOCK_FILE}" ]] && [[ "$(<"${LOCK_FILE}")" == "$" ]]; then
        rm -f "${LOCK_FILE}"
        echo "🔧  Cleaned up lock file"
    fi
}

# Set up signal handlers for cleanup (but not EXIT - let gunicorn manage that)
trap cleanup INT TERM

# Check for existing process
check_existing_process

# Create lock file with current PID (will be updated with gunicorn PID later)
echo $$ > "${LOCK_FILE}"

#────────────────────────────────────────────────────────────────────────────────
# SECTION 3: Virtual Environment Activation
# Check if a virtual environment is already active. If not, try to activate one
# from known locations. This ensures dependencies are properly isolated.
#────────────────────────────────────────────────────────────────────────────────
if [[ -z "${VIRTUAL_ENV:-}" ]]; then
    # Check for virtual environment in user's home directory (preferred location)
    if [[ -f "${HOME}/.venv/mcpgateway/bin/activate" ]]; then
        echo "🔧  Activating virtual environment: ${HOME}/.venv/mcpgateway"
        # shellcheck disable=SC1090
        source "${HOME}/.venv/mcpgateway/bin/activate"

    # Check for virtual environment in script directory (development setup)
    elif [[ -f "${SCRIPT_DIR}/.venv/bin/activate" ]]; then
        echo "🔧  Activating virtual environment in script directory"
        # shellcheck disable=SC1090
        source "${SCRIPT_DIR}/.venv/bin/activate"

    # No virtual environment found - warn but continue
    else
        echo "⚠️  WARNING: No virtual environment found!"
        echo "   This may lead to dependency conflicts."
        echo "   Consider creating a virtual environment with:"
        echo "   python3 -m venv ~/.venv/mcpgateway"

        # Optional: Uncomment the following lines to enforce virtual environment usage
        # echo "❌  FATAL: Virtual environment required for production deployments"
        # echo "   This ensures consistent dependency versions."
        # exit 1
    fi
else
    echo "✓  Virtual environment already active: ${VIRTUAL_ENV}"
fi

#────────────────────────────────────────────────────────────────────────────────
# SECTION 4: Python Interpreter Detection
# Locate a suitable Python interpreter with the following precedence:
#   1. User-provided PYTHON environment variable
#   2. 'python' binary in active virtual environment
#   3. 'python3' binary on system PATH
#   4. 'python' binary on system PATH
#────────────────────────────────────────────────────────────────────────────────
if [[ -z "${PYTHON:-}" ]]; then
    # If virtual environment is active, prefer its Python binary
    if [[ -n "${VIRTUAL_ENV:-}" && -x "${VIRTUAL_ENV}/bin/python" ]]; then
        PYTHON="${VIRTUAL_ENV}/bin/python"
        echo "🐍  Using Python from virtual environment"

    # Otherwise, search for Python in system PATH
    else
        # Try python3 first (more common on modern systems)
        if command -v python3 &> /dev/null; then
            PYTHON="$(command -v python3)"
            echo "🐍  Found system Python3: ${PYTHON}"

        # Fall back to python if python3 not found
        elif command -v python &> /dev/null; then
            PYTHON="$(command -v python)"
            echo "🐍  Found system Python: ${PYTHON}"

        # No Python found at all
        else
            PYTHON=""
        fi
    fi
fi

# Verify Python interpreter exists and is executable
if [[ -z "${PYTHON}" ]] || [[ ! -x "${PYTHON}" ]]; then
    echo "❌  FATAL: Could not locate a Python interpreter!"
    echo "   Searched for: python3, python"
    echo "   Please install Python 3.x or set the PYTHON environment variable."
    echo "   Example: PYTHON=/usr/bin/python3.9 $0"
    exit 1
fi

# Display Python version for debugging
PY_VERSION="$("${PYTHON}" --version 2>&1)"
echo "📋  Python version: ${PY_VERSION}"

# Verify this is Python 3.x (not Python 2.x)
if ! "${PYTHON}" -c "import sys; sys.exit(0 if sys.version_info[0] >= 3 else 1)" 2>/dev/null; then
    echo "❌  FATAL: Python 3.x is required, but Python 2.x was found!"
    echo "   Please install Python 3.x or update the PYTHON environment variable."
    exit 1
fi

#────────────────────────────────────────────────────────────────────────────────
# SECTION 5: Display Application Banner
# Show a fancy ASCII art banner for the MCP Gateway
#────────────────────────────────────────────────────────────────────────────────
cat <<'EOF'
███╗   ███╗ ██████╗██████╗      ██████╗  █████╗ ████████╗███████╗██╗    ██╗ █████╗ ██╗   ██╗
████╗ ████║██╔════╝██╔══██╗    ██╔════╝ ██╔══██╗╚══██╔══╝██╔════╝██║    ██║██╔══██╗╚██╗ ██╔╝
██╔████╔██║██║     ██████╔╝    ██║  ███╗███████║   ██║   █████╗  ██║ █╗ ██║███████║ ╚████╔╝
██║╚██╔╝██║██║     ██╔═══╝     ██║   ██║██╔══██║   ██║   ██╔══╝  ██║███╗██║██╔══██║  ╚██╔╝
██║ ╚═╝ ██║╚██████╗██║         ╚██████╔╝██║  ██║   ██║   ███████╗╚███╔███╔╝██║  ██║   ██║
╚═╝     ╚═╝ ╚═════╝╚═╝          ╚═════╝ ╚═╝  ╚═╝   ╚═╝   ╚══════╝ ╚══╝╚══╝ ╚═╝  ╚═╝   ╚═╝
EOF

#────────────────────────────────────────────────────────────────────────────────
# SECTION 6: Configure Gunicorn Settings
# Set up Gunicorn parameters with sensible defaults that can be overridden
# via environment variables for different deployment scenarios
#────────────────────────────────────────────────────────────────────────────────

# Number of worker processes (adjust based on CPU cores and expected load)
# Default: 2 (safe default for most systems)
# Set to "auto" for automatic detection based on CPU cores
if [[ -z "${GUNICORN_WORKERS:-}" || "${GUNICORN_WORKERS}" == "auto" ]]; then
    # Auto-detect workers based on CPU cores (default behavior)
    # Try to detect CPU count
    if command -v nproc &>/dev/null; then
        CPU_COUNT=$(nproc)
    elif command -v sysctl &>/dev/null && sysctl -n hw.ncpu &>/dev/null; then
        CPU_COUNT=$(sysctl -n hw.ncpu)
    else
        CPU_COUNT=4  # Fallback to reasonable default
    fi

    # Use a more conservative formula: min(2*CPU+1, 16) to avoid too many workers
    CALCULATED_WORKERS=$((CPU_COUNT * 2 + 1))
    GUNICORN_WORKERS=$((CALCULATED_WORKERS > 16 ? 16 : CALCULATED_WORKERS))

    echo "🔧  Auto-detected CPU cores: ${CPU_COUNT}"
    echo "   Calculated workers: ${CALCULATED_WORKERS} → Capped at: ${GUNICORN_WORKERS}"
fi

# Worker timeout in seconds (increase for long-running requests)
GUNICORN_TIMEOUT=${GUNICORN_TIMEOUT:-600}

# Maximum requests a worker will process before restarting (prevents memory leaks)
GUNICORN_MAX_REQUESTS=${GUNICORN_MAX_REQUESTS:-100000}

# Random jitter for max requests (prevents all workers restarting simultaneously)
GUNICORN_MAX_REQUESTS_JITTER=${GUNICORN_MAX_REQUESTS_JITTER:-100}

# Preload application before forking workers (saves memory but slower reload)
GUNICORN_PRELOAD_APP=${GUNICORN_PRELOAD_APP:-true}

# Developer mode with hot reload (disables preload, enables file watching)
GUNICORN_DEV_MODE=${GUNICORN_DEV_MODE:-false}

# Check for conflicting options
if [[ "${GUNICORN_DEV_MODE}" == "true" && "${GUNICORN_PRELOAD_APP}" == "true" ]]; then
    echo "⚠️  WARNING: Developer mode disables application preloading"
    GUNICORN_PRELOAD_APP="false"
fi

echo "📊  Gunicorn Configuration:"
echo "   Workers: ${GUNICORN_WORKERS}"
echo "   Timeout: ${GUNICORN_TIMEOUT}s"
echo "   Max Requests: ${GUNICORN_MAX_REQUESTS} (±${GUNICORN_MAX_REQUESTS_JITTER})"
echo "   Preload App: ${GUNICORN_PRELOAD_APP}"
echo "   Developer Mode: ${GUNICORN_DEV_MODE}"

#────────────────────────────────────────────────────────────────────────────────
# SECTION 7: Configure TLS/SSL Settings
# Handle optional TLS configuration for secure HTTPS connections
#────────────────────────────────────────────────────────────────────────────────

# SSL/TLS configuration
SSL=${SSL:-false}                        # Enable/disable SSL (default: false)
CERT_FILE=${CERT_FILE:-certs/cert.pem}  # Path to SSL certificate file
KEY_FILE=${KEY_FILE:-certs/key.pem}     # Path to SSL private key file
KEY_FILE_PASSWORD=${KEY_FILE_PASSWORD:-}  # Optional passphrase for encrypted key
CERT_PASSPHRASE=${CERT_PASSPHRASE:-}      # Alternative name for passphrase

# Use CERT_PASSPHRASE if KEY_FILE_PASSWORD is not set (for compatibility)
if [[ -z "${KEY_FILE_PASSWORD}" && -n "${CERT_PASSPHRASE}" ]]; then
    KEY_FILE_PASSWORD="${CERT_PASSPHRASE}"
fi

# Verify SSL settings if enabled
if [[ "${SSL}" == "true" ]]; then
    echo "🔐  Configuring TLS/SSL..."

    # Verify certificate files exist
    if [[ ! -f "${CERT_FILE}" ]]; then
        echo "❌  FATAL: SSL certificate file not found: ${CERT_FILE}"
        exit 1
    fi

    if [[ ! -f "${KEY_FILE}" ]]; then
        echo "❌  FATAL: SSL private key file not found: ${KEY_FILE}"
        exit 1
    fi

    # Verify certificate and key files are readable
    if [[ ! -r "${CERT_FILE}" ]]; then
        echo "❌  FATAL: Cannot read SSL certificate file: ${CERT_FILE}"
        exit 1
    fi

    if [[ ! -r "${KEY_FILE}" ]]; then
        echo "❌  FATAL: Cannot read SSL private key file: ${KEY_FILE}"
        exit 1
    fi

    # Check if passphrase is provided
    if [[ -n "${KEY_FILE_PASSWORD}" ]]; then
        echo "🔑  Passphrase-protected key detected"
        echo "   Note: Key will be decrypted by Python SSL key manager"
        # Export for Python to access
        export SSL_KEY_PASSWORD="${KEY_FILE_PASSWORD}"
    fi

    echo "✓  TLS enabled - using:"
    echo "   Certificate: ${CERT_FILE}"
    echo "   Private Key: ${KEY_FILE}"
    if [[ -n "${KEY_FILE_PASSWORD}" ]]; then
        echo "   Passphrase: ******** (protected)"
    else
        echo "   Passphrase: (none)"
    fi
else
    echo "🔓  Running without TLS (HTTP only)"
fi

#────────────────────────────────────────────────────────────────────────────────
# SECTION 8: Verify Gunicorn Installation
# Check that gunicorn is available before attempting to start
#────────────────────────────────────────────────────────────────────────────────
if ! command -v gunicorn &> /dev/null; then
    echo "❌  FATAL: gunicorn command not found!"
    echo "   Please install it with: pip install gunicorn"
    exit 1
fi

echo "✓  Gunicorn found: $(command -v gunicorn)"

#────────────────────────────────────────────────────────────────────────────────
# SECTION 9: Launch Gunicorn Server
# Start the Gunicorn server with all configured options
# Using 'exec' replaces this shell process with Gunicorn for cleaner process management
#────────────────────────────────────────────────────────────────────────────────
echo "🚀  Starting Gunicorn server..."
echo "─────────────────────────────────────────────────────────────────────"

# Build command array to handle spaces in paths properly
# Note: UvicornWorker automatically uses uvloop and httptools when available
# (installed via uvicorn[standard] extras for 15-30% better performance)
cmd=(
    gunicorn
    -c gunicorn.config.py
    --worker-class uvicorn.workers.UvicornWorker
    --workers              "${GUNICORN_WORKERS}"
    --timeout              "${GUNICORN_TIMEOUT}"
    --max-requests         "${GUNICORN_MAX_REQUESTS}"
    --max-requests-jitter  "${GUNICORN_MAX_REQUESTS_JITTER}"
)

# Configure access logging based on DISABLE_ACCESS_LOG setting
# For performance testing, disable access logs which cause significant I/O overhead
DISABLE_ACCESS_LOG=${DISABLE_ACCESS_LOG:-true}
if [[ "${DISABLE_ACCESS_LOG}" == "true" ]]; then
    cmd+=( --access-logfile /dev/null )
    echo "🚫  Access logging disabled for performance"
else
    cmd+=( --access-logfile - )
fi

cmd+=(
    --error-logfile -
    --forwarded-allow-ips="*"
    --pid "${LOCK_FILE}"  # Use lock file as PID file
)

# Add developer mode flags if enabled
if [[ "${GUNICORN_DEV_MODE}" == "true" ]]; then
    cmd+=( --reload --reload-extra-file gunicorn.config.py )
    echo "🔧  Developer mode enabled - hot reload active"
    echo "   Watching for changes in Python files and gunicorn.config.py"

    # In dev mode, reduce workers to 1 for better debugging
    if [[ "${GUNICORN_WORKERS}" -gt 2 ]]; then
        echo "   Reducing workers to 2 for developer mode (was ${GUNICORN_WORKERS})"
        cmd[5]=2  # Update the workers argument
    fi
fi

# Add preload flag if enabled (and not in dev mode)
if [[ "${GUNICORN_PRELOAD_APP}" == "true" && "${GUNICORN_DEV_MODE}" != "true" ]]; then
    cmd+=( --preload )
    echo "✓  Application preloading enabled"
fi

# Add SSL arguments if enabled
if [[ "${SSL}" == "true" ]]; then
    cmd+=( --certfile "${CERT_FILE}" --keyfile "${KEY_FILE}" )
    # If passphrase is set, it will be available to Python via SSL_KEY_PASSWORD env var
fi

# Add the application module
cmd+=( "mcpgateway.main:app" )

# Display final command for debugging
echo "📋  Command: ${cmd[*]}"
echo "─────────────────────────────────────────────────────────────────────"

# Launch Gunicorn with all configured options
# Remove EXIT trap before exec - let gunicorn handle its own cleanup
trap - EXIT
# exec replaces this shell with gunicorn, so cleanup trap won't fire on normal exit
# The PID file will be managed by gunicorn itself
exec "${cmd[@]}"
