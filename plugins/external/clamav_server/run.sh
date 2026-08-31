#!/usr/bin/env bash
set -euo pipefail

# Ensure PLUGINS_CONFIG_PATH points to this project's resources
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export PLUGINS_CONFIG_PATH="${SCRIPT_DIR}/resources/plugins/config.yaml"

exec python -m cpex.framework.external.mcp.server.runtime
