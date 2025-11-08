#!/bin/bash
# Cleanup script for development environment
# Kills all running servers and cleans up database locks

set -e

echo "🧹 Cleaning up development environment..."

# Kill all running server processes
echo "  Stopping all server processes..."
pkill -9 -f "uvicorn" 2>/dev/null || true
pkill -9 -f "python.*mcpgateway" 2>/dev/null || true
pkill -9 -f "make dev" 2>/dev/null || true

# Kill processes on port 8000
echo "  Freeing port 8000..."
lsof -ti:8000 | xargs kill -9 2>/dev/null || true

sleep 2

# Clean up SQLite WAL files
echo "  Removing SQLite lock files..."
rm -f mcp.db-shm mcp.db-wal

echo "✓ Cleanup complete!"
echo ""
echo "You can now run: make dev"
