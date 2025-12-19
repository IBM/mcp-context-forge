#!/bin/bash
# Cleanup script for development environment
# Kills all running servers and cleans up database locks

set -euo pipefail

PORT=8000
DB_FILE=mcp.db

kill_gracefully() {
    local pattern="$1"
    if pgrep -f "$pattern" &>/dev/null; then
        echo "  Stopping: $pattern"
        pkill -f "$pattern" 2>/dev/null || true
        sleep 1
        pkill -9 -f "$pattern" 2>/dev/null || true
    fi
}

echo "🧹 Cleaning up development environment..."

kill_gracefully "uvicorn"
kill_gracefully "python.*mcpgateway"
kill_gracefully "make dev"

echo "  Freeing port $PORT..."
lsof -ti:$PORT | xargs kill -9 2>/dev/null || true

sleep 2

echo "  Removing SQLite lock files..."
rm -f "${DB_FILE}-shm" "${DB_FILE}-wal"

echo "✓ Cleanup complete!"
echo ""
echo "You can now run: make dev"
