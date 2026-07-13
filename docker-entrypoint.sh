#!/usr/bin/env bash
set -euo pipefail

# s390x: Force protobuf to use pure-Python implementation.
# The UPB C extension (google._upb._message) segfaults on s390x when
# importing OpenTelemetry protobuf definitions.
if [ "$(uname -m)" = "s390x" ]; then
    export PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION=python
fi
APP_ROOT="${APP_ROOT:-/app}"

build_server_command() {
    echo "Starting ContextForge with Gunicorn + Uvicorn..."
    SERVER_CMD=(./run-gunicorn.sh "$@")
}

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "${SCRIPT_DIR}" || {
    echo "ERROR: Cannot change to script directory: ${SCRIPT_DIR}"
    exit 1
}

SERVER_PID=""

cleanup() {
    if [[ -n "${SERVER_PID}" ]] && kill -0 "${SERVER_PID}" 2>/dev/null; then
        kill "${SERVER_PID}" 2>/dev/null || true
        wait "${SERVER_PID}" 2>/dev/null || true
    fi
}

install_plugin_requirements() {
    RELOAD_PLUGIN_REQUIREMENTS_TXT="${RELOAD_PLUGIN_REQUIREMENTS_TXT:-false}"
    PLUGIN_REQUIREMENTS_TXT_PATH="${PLUGIN_REQUIREMENTS_TXT_PATH:-${APP_ROOT}/plugins/requirements.txt}"

    if [[ "${RELOAD_PLUGIN_REQUIREMENTS_TXT}" != "true" ]]; then
        return 0
    fi

    # Resolve both APP_ROOT and the requested path to their canonical forms, then
    # require the requested path to live inside APP_ROOT. Canonicalizing APP_ROOT too
    # handles the case where /app is itself a symlink (uncommon in this repo's
    # Containerfiles, but defensive). This prevents env-controlled path
    # injection like PLUGIN_REQUIREMENTS_TXT_PATH=/tmp/evil-requirements.txt.
    local app_root resolved_path
    app_root="$(readlink -f "${APP_ROOT}" 2>/dev/null)"
    if [[ -z "${app_root}" ]]; then
        echo "❌ ${APP_ROOT} could not be resolved; refusing to start with RELOAD_PLUGIN_REQUIREMENTS_TXT=true"
        return 1
    fi
    local requirements_dir requirements_file
    requirements_dir="$(dirname "${PLUGIN_REQUIREMENTS_TXT_PATH}")"
    requirements_file="$(basename "${PLUGIN_REQUIREMENTS_TXT_PATH}")"
    if ! resolved_path="$(readlink -f "${requirements_dir}" 2>/dev/null)"; then
        echo "❌ PLUGIN_REQUIREMENTS_TXT_PATH=${PLUGIN_REQUIREMENTS_TXT_PATH} could not be resolved; refusing to start"
        return 1
    fi
    resolved_path="${resolved_path}/${requirements_file}"
    if [[ "${resolved_path}" != "${app_root}/"* ]]; then
        echo "❌ PLUGIN_REQUIREMENTS_TXT_PATH must resolve under ${app_root}/ (got ${resolved_path}); refusing to start"
        return 1
    fi
    if [[ ! -f "${resolved_path}" ]]; then
        echo "❌ Plugin requirements file ${resolved_path} not found; refusing to start with RELOAD_PLUGIN_REQUIREMENTS_TXT=true"
        return 1
    fi

    local requirement_count
    requirement_count="$(grep -cve '^\s*$' -e '^\s*#' "${resolved_path}" || true)"
    echo "🧩 Installing ${requirement_count} plugin package requirement(s) from ${resolved_path}"

    local max_retries=3
    local retry_delay="${PLUGIN_REQUIREMENTS_RETRY_DELAY_SECONDS:-2}"
    if [[ ! "${retry_delay}" =~ ^[0-9]+(\.[0-9]+)?$ ]]; then
        echo "⚠️  PLUGIN_REQUIREMENTS_RETRY_DELAY_SECONDS=${retry_delay} is not a non-negative number; falling back to 2s"
        retry_delay=2
    fi
    local attempt=1
    while (( attempt <= max_retries )); do
        if "${app_root}/.venv/bin/pip" install --no-cache-dir -r "${resolved_path}"; then
            return 0
        fi
        echo "⚠️  Plugin package install attempt ${attempt}/${max_retries} failed"
        (( attempt++ ))
        (( attempt <= max_retries )) && sleep "${retry_delay}"
    done
    echo "❌ Plugin package install failed after ${max_retries} attempts; refusing to start with incomplete plugin dependencies"
    return 1
}

if [[ "${CONTEXTFORGE_TEST_ONLY_SOURCE:-false}" = "true" ]]; then
    return 0 2>/dev/null || exit 0
fi

install_plugin_requirements
build_server_command "$@"

exec "${SERVER_CMD[@]}"
