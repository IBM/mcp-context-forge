#!/usr/bin/env bash
#───────────────────────────────────────────────────────────────────────────────
#  Script : docker-entrypoint.sh
#  Purpose: Container entrypoint that allows switching between HTTP servers
#
#  Environment Variables:
#    HTTP_SERVER : Which HTTP server to use (default: gunicorn)
#                  - gunicorn : Python-based with Uvicorn workers (default)
#                  - granian  : Rust-based HTTP server (alternative)
#
#  Usage:
#    # Run with Gunicorn (default)
#    docker run -e HTTP_SERVER=gunicorn mcpgateway
#
#    # Run with Granian
#    docker run -e HTTP_SERVER=granian mcpgateway
#───────────────────────────────────────────────────────────────────────────────

set -euo pipefail

HTTP_SERVER="${HTTP_SERVER:-gunicorn}"

case "${HTTP_SERVER}" in
    granian)
        echo "Starting MCP Gateway with Granian (Rust-based HTTP server)..."
        exec ./run-granian.sh "$@"
        ;;
    gunicorn)
        echo "Starting MCP Gateway with Gunicorn + Uvicorn..."
        exec ./run-gunicorn.sh "$@"
        ;;
    *)
        echo "ERROR: Unknown HTTP_SERVER value: ${HTTP_SERVER}"
        echo "Valid options: granian, gunicorn"
        exit 1
        ;;
esac
