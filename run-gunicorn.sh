#!/bin/bash
# Author: Mihai Criveti
# Description: Run Gunicorn production server (optionally with TLS)

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
