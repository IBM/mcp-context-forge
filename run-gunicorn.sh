#!/bin/bash
# Author: Mihai Criveti
# Description: Run Gunicorn production server (optionally with TLS)

# Determine script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Attempt to activate a venv if not already active
if [[ -z "$VIRTUAL_ENV" ]]; then
  # If a known venv path exists (like your custom .venv location), activate it
  if [[ -f "${HOME}/.venv/mcpgateway/bin/activate" ]]; then
    echo "🔧  Activating virtual environment: ${HOME}/.venv/mcpgateway"
    source "${HOME}/.venv/mcpgateway/bin/activate"
  elif [[ -f "${SCRIPT_DIR}/.venv/bin/activate" ]]; then
    echo "🔧  Activating virtual environment in script directory"
    source "${SCRIPT_DIR}/.venv/bin/activate"
  else
    echo "⚠️  No virtual environment found! Please activate manually."
    exit 1
  fi
fi

cat << "EOF"
███╗   ███╗ ██████╗██████╗      ██████╗  █████╗ ████████╗███████╗██╗    ██╗ █████╗ ██╗   ██╗
████╗ ████║██╔════╝██╔══██╗    ██╔════╝ ██╔══██╗╚══██╔══╝██╔════╝██║    ██║██╔══██╗╚██╗ ██╔╝
██╔████╔██║██║     ██████╔╝    ██║  ███╗███████║   ██║   █████╗  ██║ █╗ ██║███████║ ╚████╔╝
██║╚██╔╝██║██║     ██╔═══╝     ██║   ██║██╔══██║   ██║   ██╔══╝  ██║███╗██║██╔══██║  ╚██╔╝
██║ ╚═╝ ██║╚██████╗██║         ╚██████╔╝██║  ██║   ██║   ███████╗╚███╔███╔╝██║  ██║   ██║
╚═╝     ╚═╝ ╚═════╝╚═╝          ╚═════╝ ╚═╝  ╚═╝   ╚═╝   ╚══════╝ ╚══╝╚══╝ ╚═╝  ╚═╝   ╚═╝
EOF

# ──────────────────────────────
# Tunables (env-overrideable)
# ──────────────────────────────
GUNICORN_WORKERS=${GUNICORN_WORKERS:-8}
GUNICORN_TIMEOUT=${GUNICORN_TIMEOUT:-600}
GUNICORN_MAX_REQUESTS=${GUNICORN_MAX_REQUESTS:-1000}
GUNICORN_MAX_REQUESTS_JITTER=${GUNICORN_MAX_REQUESTS_JITTER:-100}

# TLS options
SSL=${SSL:-false}                       # true|false
CERT_FILE=${CERT_FILE:-certs/cert.pem}  # path to cert
KEY_FILE=${KEY_FILE:-certs/key.pem}     # path to key

SSL_ARGS=""
if [[ "${SSL}" == "true" ]]; then
    if [[ ! -f "${CERT_FILE}" || ! -f "${KEY_FILE}" ]]; then
        echo "✘  SSL requested but certificate files not found:"
        echo "   CERT_FILE=${CERT_FILE}"
        echo "   KEY_FILE=${KEY_FILE}"
        exit 1
    fi
    SSL_ARGS="--certfile=${CERT_FILE} --keyfile=${KEY_FILE}"
    echo "✓  TLS enabled – using ${CERT_FILE} / ${KEY_FILE}"
fi

# Initialize databases
python -m mcpgateway.db

exec gunicorn -c gunicorn.config.py \
    --worker-class uvicorn.workers.UvicornWorker \
    --workers "${GUNICORN_WORKERS}" \
    --timeout "${GUNICORN_TIMEOUT}" \
    --max-requests "${GUNICORN_MAX_REQUESTS}" \
    --max-requests-jitter "${GUNICORN_MAX_REQUESTS_JITTER}" \
    --access-logfile - \
    --error-logfile - \
    ${SSL_ARGS} \
    "mcpgateway.main:app"
