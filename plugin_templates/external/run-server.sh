#!/usr/bin/env bash
#───────────────────────────────────────────────────────────────────────────────
#  Script : run-server.sh
#  Purpose: Launch the MCP Gateway's Plugin API
#
#  Description:
#    This script launches an API server using
#    chuck runtime.
#
#  Environment Variables:
#    API_SERVER_SCRIPT              : Path to the server script (optional, auto-detected)
#    CFMCP_PLUGIN_CONFIG            : Path to the plugin config (optional, default: ./resources/plugins/config.yaml)
#    CHUK_MCP_CONFIG_PATH           : Path to the chuck-mcp-runtime config (optional, default: ./resources/runtime/config.yaml)
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
    API_SERVER_SCRIPT="$(python -c 'import mcpgateway.plugins.framework.external.mcp.server as server; print(server.__file__)')"
    echo "✓  API server script path auto-detected: ${API_SERVER_SCRIPT}"
else
    echo "✓  Using provided API server script path: ${API_SERVER_SCRIPT}"
fi

#────────────────────────────────────────────────────────────────────────────────
# SECTION 2: Run the API server
# Run the API server from configuration
#────────────────────────────────────────────────────────────────────────────────

CFMCP_PLUGIN_CONFIG=${CFMCP_PLUGIN_CONFIG:-./resources/plugins/config.yaml}
CHUK_MCP_CONFIG_PATH=${CHUK_MCP_CONFIG_PATH:-./resources/runtime/config.yaml}

echo "✓  Using plugin config from: ${CFMCP_PLUGIN_CONFIG}"
echo "✓  Running API server with config from: ${CHUK_MCP_CONFIG_PATH}"
python ${API_SERVER_SCRIPT}