#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
cd "${APP_ROOT}" || exit 1

if [[ -z "${VIRTUAL_ENV:-}" && -f "${APP_ROOT}/.venv/bin/activate" ]]; then
    # shellcheck disable=SC1090
    source "${APP_ROOT}/.venv/bin/activate"
fi

PYTHON="${PYTHON:-}"
if [[ -z "${PYTHON}" ]]; then
    if [[ -n "${VIRTUAL_ENV:-}" && -x "${VIRTUAL_ENV}/bin/python" ]]; then
        PYTHON="${VIRTUAL_ENV}/bin/python"
    elif command -v python3 >/dev/null 2>&1; then
        PYTHON="$(command -v python3)"
    else
        PYTHON="$(command -v python)"
    fi
fi

HOST="${HOST:-0.0.0.0}"
PORT="${PORT:-4444}"
UVICORN_WORKERS="${UVICORN_WORKERS:-1}"
UVICORN_LOOP="${UVICORN_LOOP:-auto}"
UVICORN_HTTP="${UVICORN_HTTP:-auto}"
UVICORN_BACKLOG="${UVICORN_BACKLOG:-2048}"
UVICORN_TIMEOUT_KEEP_ALIVE="${UVICORN_TIMEOUT_KEEP_ALIVE:-5}"
UVICORN_LIMIT_MAX_REQUESTS="${UVICORN_LIMIT_MAX_REQUESTS:-0}"
LOG_LEVEL="${LOG_LEVEL:-error}"
DEVELOPER_MODE="${DEVELOPER_MODE:-false}"
DISABLE_ACCESS_LOG="${DISABLE_ACCESS_LOG:-true}"

args=(
    -m uvicorn
    mcpgateway.main:app
    --host "${HOST}"
    --port "${PORT}"
    --workers "${UVICORN_WORKERS}"
    --loop "${UVICORN_LOOP}"
    --http "${UVICORN_HTTP}"
    --backlog "${UVICORN_BACKLOG}"
    --timeout-keep-alive "${UVICORN_TIMEOUT_KEEP_ALIVE}"
    --log-level "${LOG_LEVEL}"
    --proxy-headers
)

if [[ "${UVICORN_LIMIT_MAX_REQUESTS}" != "0" ]]; then
    args+=(--limit-max-requests "${UVICORN_LIMIT_MAX_REQUESTS}")
fi

if [[ "${DISABLE_ACCESS_LOG}" == "true" ]]; then
    args+=(--no-access-log)
fi

if [[ "${DEVELOPER_MODE}" == "true" ]]; then
    args+=(--reload)
fi

exec "${PYTHON}" "${args[@]}"
