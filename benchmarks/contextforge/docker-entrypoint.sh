#!/usr/bin/env bash

set -euo pipefail

HTTP_SERVER="${HTTP_SERVER:-gunicorn}"

case "${HTTP_SERVER}" in
    granian)
        echo "Starting ContextForge benchmark image with Granian..."
        exec ./run-granian.sh "$@"
        ;;
    gunicorn)
        echo "Starting ContextForge benchmark image with Gunicorn..."
        exec ./run-gunicorn.sh "$@"
        ;;
    uvicorn)
        echo "Starting ContextForge benchmark image with Uvicorn..."
        exec ./benchmarks/contextforge/run-uvicorn.sh "$@"
        ;;
    *)
        echo "ERROR: Unknown HTTP_SERVER value: ${HTTP_SERVER}"
        echo "Valid options: granian, gunicorn, uvicorn"
        exit 1
        ;;
esac
