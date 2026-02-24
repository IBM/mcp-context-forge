#!/usr/bin/env bash
#───────────────────────────────────────────────────────────────────────────────
#  Script : run-server.sh
#  Purpose: Launch ContextForge's Plugin API
#
#  Description:
#    This script launches a plugin API server supporting multiple transports:
#    - MCP (HTTP/stdio) - Default, uses JSON-RPC over HTTP or stdio
#    - gRPC - High-performance binary protocol (requires grpc extras)
#    - Unix Socket - High-performance local IPC (requires grpc extras for protobuf)
#
#  Environment Variables:
#    PLUGINS_TRANSPORT             : Transport type: 'http', 'stdio', 'grpc', 'unix' (default: http)
#    PLUGINS_CONFIG_PATH           : Path to the plugin config (default: ./resources/plugins/config.yaml)
#
#    # gRPC-specific settings:
#    PLUGINS_GRPC_SERVER_HOST      : gRPC server host (default: 0.0.0.0)
#    PLUGINS_GRPC_SERVER_PORT      : gRPC server port (default: 50051)
#    PLUGINS_GRPC_SERVER_SSL_ENABLED  : Enable TLS (true/false, required to enable TLS)
#    PLUGINS_GRPC_SERVER_SSL_CERTFILE : Path to server certificate (required when SSL_ENABLED=true)
#    PLUGINS_GRPC_SERVER_SSL_KEYFILE  : Path to server private key (required when SSL_ENABLED=true)
#    PLUGINS_GRPC_SERVER_SSL_CA_CERTS : Path to CA bundle for client verification (enables mTLS)
#    PLUGINS_GRPC_SERVER_SSL_CLIENT_AUTH : Client auth mode: 'none', 'optional', 'require' (default: require)
#
#    # Unix socket-specific settings:
#    UNIX_SOCKET_PATH              : Path to Unix socket file (default: /tmp/mcpgateway-plugins.sock)
#
#  Usage:
#    ./run-server.sh                          # Run with default transport (http)
#    PLUGINS_TRANSPORT=grpc ./run-server.sh   # Run with gRPC transport
#    PLUGINS_TRANSPORT=unix ./run-server.sh   # Run with Unix socket transport
#───────────────────────────────────────────────────────────────────────────────

# Exit immediately on error, undefined variable, or pipe failure
set -euo pipefail

#────────────────────────────────────────────────────────────────────────────────
# SECTION 1: Configuration
#────────────────────────────────────────────────────────────────────────────────
PLUGINS_CONFIG_PATH=${PLUGINS_CONFIG_PATH:-./resources/plugins/config.yaml}
PLUGINS_TRANSPORT=${PLUGINS_TRANSPORT:-http}

echo "✓  Plugin config: ${PLUGINS_CONFIG_PATH}"
echo "✓  Transport: ${PLUGINS_TRANSPORT}"

#────────────────────────────────────────────────────────────────────────────────
# SECTION 2: Transport Selection
#────────────────────────────────────────────────────────────────────────────────
case "${PLUGINS_TRANSPORT}" in
    http|stdio)
        # MCP transport (HTTP or stdio)
        if [[ -z "${API_SERVER_SCRIPT:-}" ]]; then
            API_SERVER_SCRIPT="$(python -c 'import mcpgateway.plugins.framework.external.mcp.server.runtime as server; print(server.__file__)')"
            echo "✓  MCP server script: ${API_SERVER_SCRIPT}"
        fi
        python "${API_SERVER_SCRIPT}"
        ;;

    grpc)
        # gRPC transport (requires grpc extras)
        # Set sensible defaults for gRPC if not already configured
        export PLUGINS_GRPC_SERVER_HOST="${PLUGINS_GRPC_SERVER_HOST:-0.0.0.0}"
        export PLUGINS_GRPC_SERVER_PORT="${PLUGINS_GRPC_SERVER_PORT:-50051}"

        echo "✓  Starting gRPC plugin server..."
        echo "   Host: ${PLUGINS_GRPC_SERVER_HOST}"
        echo "   Port: ${PLUGINS_GRPC_SERVER_PORT}"
        if [[ -n "${PLUGINS_GRPC_SERVER_UDS:-}" ]]; then
            echo "   UDS: ${PLUGINS_GRPC_SERVER_UDS}"
        fi

        python -c "import grpc" 2>/dev/null || {
            echo "ERROR: gRPC dependencies not installed. Install with: pip install .[grpc]"
            exit 1
        }
        python -m mcpgateway.plugins.framework.external.grpc.server.runtime
        ;;

    unix)
        # Unix socket transport (requires protobuf from grpc extras)
        echo "✓  Starting Unix socket plugin server..."
        python -c "import google.protobuf" 2>/dev/null || {
            echo "ERROR: Protobuf dependencies not installed. Install with: pip install .[grpc]"
            exit 1
        }
        python -m mcpgateway.plugins.framework.external.unix.server.runtime
        ;;

    *)
        echo "ERROR: Unknown transport '${PLUGINS_TRANSPORT}'"
        echo "Valid options: http, stdio, grpc, unix"
        exit 1
        ;;
esac
