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
#    • Portable Python detection across different distros (python vs python3)
#    • Virtual environment handling (activates project venv if available)
#    • Configurable via environment variables for CI/CD pipelines
#    • Optional TLS/SSL support for secure connections
#    • Database initialization before server start
#    • Comprehensive error handling and user feedback
#
#  Environment Variables:
#    PYTHON                        : Path to Python interpreter (optional)
#    VIRTUAL_ENV                   : Path to active virtual environment (auto-detected)
#    GUNICORN_WORKERS             : Number of worker processes (default: 2 × CPU cores + 1)
#    GUNICORN_TIMEOUT             : Worker timeout in seconds (default: 600)
#    GUNICORN_MAX_REQUESTS        : Max requests per worker before restart (default: 1000)
#    GUNICORN_MAX_REQUESTS_JITTER : Random jitter for max requests (default: 100)
#    SSL                          : Enable TLS/SSL (true/false, default: false)
#    CERT_FILE                    : Path to SSL certificate (default: certs/cert.pem)
#    KEY_FILE                     : Path to SSL private key (default: certs/key.pem)
#
#  Usage:
#    ./run-gunicorn.sh                     # Run with defaults
#    SSL=true ./run-gunicorn.sh            # Run with TLS enabled
#    GUNICORN_WORKERS=16 ./run-gunicorn.sh # Run with 16 workers
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
# SECTION 2: Virtual Environment Activation
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
# SECTION 3: Python Interpreter Detection
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
# SECTION 4: Display Application Banner
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
# SECTION 5: Configure Gunicorn Settings
# Set up Gunicorn parameters with sensible defaults that can be overridden
# via environment variables for different deployment scenarios
#────────────────────────────────────────────────────────────────────────────────

# Number of worker processes (adjust based on CPU cores and expected load)
# Default: 2 × CPU cores + 1 (automatically detected)
if [[ -z "${GUNICORN_WORKERS:-}" ]]; then
    # Try to detect CPU count
    if command -v nproc &>/dev/null; then
        CPU_COUNT=$(nproc)
    elif command -v sysctl &>/dev/null && sysctl -n hw.ncpu &>/dev/null; then
        CPU_COUNT=$(sysctl -n hw.ncpu)
    else
        CPU_COUNT=4  # Fallback to reasonable default
    fi
    GUNICORN_WORKERS=$((CPU_COUNT * 2 + 1))
fi

# Worker timeout in seconds (increase for long-running requests)
GUNICORN_TIMEOUT=${GUNICORN_TIMEOUT:-600}

# Maximum requests a worker will process before restarting (prevents memory leaks)
GUNICORN_MAX_REQUESTS=${GUNICORN_MAX_REQUESTS:-1000}

# Random jitter for max requests (prevents all workers restarting simultaneously)
GUNICORN_MAX_REQUESTS_JITTER=${GUNICORN_MAX_REQUESTS_JITTER:-100}

echo "📊  Gunicorn Configuration:"
echo "   Workers: ${GUNICORN_WORKERS}"
echo "   Timeout: ${GUNICORN_TIMEOUT}s"
echo "   Max Requests: ${GUNICORN_MAX_REQUESTS} (±${GUNICORN_MAX_REQUESTS_JITTER})"

#────────────────────────────────────────────────────────────────────────────────
# SECTION 6: Configure TLS/SSL Settings
# Handle optional TLS configuration for secure HTTPS connections
#────────────────────────────────────────────────────────────────────────────────

# SSL/TLS configuration
SSL=${SSL:-false}                        # Enable/disable SSL (default: false)
CERT_FILE=${CERT_FILE:-certs/cert.pem}  # Path to SSL certificate file
KEY_FILE=${KEY_FILE:-certs/key.pem}     # Path to SSL private key file

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

    echo "✓  TLS enabled – using:"
    echo "   Certificate: ${CERT_FILE}"
    echo "   Private Key: ${KEY_FILE}"
else
    echo "🔓  Running without TLS (HTTP only)"
fi

#────────────────────────────────────────────────────────────────────────────────
# SECTION 7: Database Initialization
# Run database setup/migrations before starting the server
#────────────────────────────────────────────────────────────────────────────────
echo "🗄️  Initializing database..."
if ! "${PYTHON}" -m mcpgateway.db; then
    echo "❌  FATAL: Database initialization failed!"
    echo "   Please check your database configuration and connection."
    exit 1
fi
echo "✓  Database initialized successfully"

#────────────────────────────────────────────────────────────────────────────────
# SECTION 8: Launch Gunicorn Server
# Start the Gunicorn server with all configured options
# Using 'exec' replaces this shell process with Gunicorn for cleaner process management
#────────────────────────────────────────────────────────────────────────────────
echo "🚀  Starting Gunicorn server..."
echo "─────────────────────────────────────────────────────────────────────"

# Check if gunicorn is available
if ! command -v gunicorn &> /dev/null; then
    echo "❌  FATAL: gunicorn command not found!"
    echo "   Please install it with: pip install gunicorn"
    exit 1
fi

# Build command array to handle spaces in paths properly
cmd=(
    gunicorn
    -c gunicorn.config.py
    --worker-class uvicorn.workers.UvicornWorker
    --workers              "${GUNICORN_WORKERS}"
    --timeout              "${GUNICORN_TIMEOUT}"
    --max-requests         "${GUNICORN_MAX_REQUESTS}"
    --max-requests-jitter  "${GUNICORN_MAX_REQUESTS_JITTER}"
    --access-logfile -
    --error-logfile -
)

# Add SSL arguments if enabled
if [[ "${SSL}" == "true" ]]; then
    cmd+=( --certfile "${CERT_FILE}" --keyfile "${KEY_FILE}" )
fi

# Add the application module
cmd+=( "mcpgateway.main:app" )

# Launch Gunicorn with all configured options
exec "${cmd[@]}"
