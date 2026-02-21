#!/usr/bin/env bash
#───────────────────────────────────────────────────────────────────────────────
#  Script : run-server.sh
#  Purpose: Launch the ContextForge's Plugin API
#
#  Description:
#    This script launches an API server using
#    chuck runtime.
#
#  Environment Variables:
#    API_SERVER_SCRIPT              : Path to the server script (optional, auto-detected)
#    PLUGINS_CONFIG_PATH            : Path to the plugin config (optional, default: ./resources/plugins/config.yaml)
#    CHUK_MCP_CONFIG_PATH           : Path to the chuck-mcp-runtime config (optional, default: ./resources/runtime/config.yaml)
#    POLICY_PATH                    : Path to the repo policy file (optional, default: ./opaserver/rego/policy.rego)
#
#  Usage:
#    ./run-server.sh                # Run server
#───────────────────────────────────────────────────────────────────────────────

# Exit immediately on error, undefined variable, or pipe failure
set -euo pipefail

#────────────────────────────────────────────────────────────────────────────────
# SECTION 1: Script Location Detection
# Determine the absolute path of the API server script
#────────────────────────────────────────────────────────────────────────────────
if [[ -z "${API_SERVER_SCRIPT:-}" ]]; then
    API_SERVER_SCRIPT="$(python -c 'import mcpgateway.plugins.framework.external.mcp.server.runtime as server; print(server.__file__)')"
    echo "✓  API server script path auto-detected: ${API_SERVER_SCRIPT}"
else
    echo "✓  Using provided API server script path: ${API_SERVER_SCRIPT}"
fi

#────────────────────────────────────────────────────────────────────────────────
# SECTION 1.1: Run OPA server
# Run OPA server with a policy rego file
#────────────────────────────────────────────────────────────────────────────────

echo "Running OPA server"
opa run --server "${POLICY_PATH:-opaserver/rego/policy.rego}" &

#────────────────────────────────────────────────────────────────────────────────
# SECTION 2: Run the API server
# Run the API server from configuration
#────────────────────────────────────────────────────────────────────────────────

PLUGINS_CONFIG_PATH=${PLUGINS_CONFIG_PATH:-./resources/plugins/config.yaml}
CHUK_MCP_CONFIG_PATH=${CHUK_MCP_CONFIG_PATH:-./resources/runtime/config.yaml}

echo "✓  Using plugin config from: ${PLUGINS_CONFIG_PATH}"
echo "✓  Running API server with config from: ${CHUK_MCP_CONFIG_PATH}"
python "${API_SERVER_SCRIPT}"
