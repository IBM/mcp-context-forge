#!/bin/bash
# Graceful Vault shutdown script
# Use this INSTEAD of Ctrl+C or pkill -9

echo "🛑 Stopping Vault gracefully..."

VAULT_PID=$(pgrep -f "vault server -config")

if [ -z "$VAULT_PID" ]; then
    echo "   ℹ️  No Vault process running"
    exit 0
fi

echo "   Found Vault PID: $VAULT_PID"

# Send SIGTERM (graceful shutdown signal)
kill -TERM "$VAULT_PID"

# Wait up to 10 seconds for graceful shutdown
for i in {1..10}; do
    if ! ps -p "$VAULT_PID" > /dev/null 2>&1; then
        echo "   ✅ Vault stopped gracefully"
        exit 0
    fi
    echo "   ⏳ Waiting for Vault to stop... ($i/10)"
    sleep 1
done

# Force kill if still running
if ps -p "$VAULT_PID" > /dev/null 2>&1; then
    echo "   ⚠️  Force killing Vault (still running after 10s)"
    kill -9 "$VAULT_PID"
fi

echo "   ✅ Vault stopped"
