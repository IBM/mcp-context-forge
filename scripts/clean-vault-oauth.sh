#!/usr/bin/env bash
# Clean up all OAuth tokens from Vault KV v2

set -e

VAULT_ADDR="${VAULT_ADDR:-http://localhost:8200}"
VAULT_TOKEN="${VAULT_TOKEN:-test-root-token}"

export VAULT_ADDR
export VAULT_TOKEN

echo "🧹 Cleaning up OAuth tokens in Vault..."
echo "VAULT_ADDR: $VAULT_ADDR"
echo ""

# Function to recursively delete a path
delete_path() {
    local path=$1
    echo "  🗑️  Deleting: $path"

    # Try to list subpaths first
    local subpaths=$(vault kv list -mount=secret "$path" 2>/dev/null | tail -n +3 || echo "")

    if [ ! -z "$subpaths" ]; then
        # Has subdirectories, recurse
        while IFS= read -r subpath; do
            subpath=${subpath%/}
            if [ ! -z "$subpath" ]; then
                delete_path "$path/$subpath"
            fi
        done <<< "$subpaths"
    fi

    # Delete metadata (this removes the path from listings)
    vault kv metadata delete -mount=secret "$path" 2>/dev/null || true

    # Also try to delete data versions (belt and suspenders)
    vault kv delete -mount=secret "$path" 2>/dev/null || true
}

# Main cleanup
if vault kv list -mount=secret contextforge/oauth/ &>/dev/null; then
    echo "Found OAuth paths to clean:"
    vault kv list -mount=secret contextforge/oauth/ 2>/dev/null | tail -n +3 || true
    echo ""

    # Delete each top-level path
    vault kv list -mount=secret contextforge/oauth/ 2>/dev/null | tail -n +3 | while read path; do
        path=${path%/}
        if [ ! -z "$path" ]; then
            delete_path "contextforge/oauth/$path"
        fi
    done

    # Final cleanup of the parent directory
    vault kv metadata delete -mount=secret "contextforge/oauth" 2>/dev/null || true
else
    echo "No OAuth paths found in Vault"
fi

echo ""
echo "✅ Cleanup complete!"
echo ""
echo "Verification:"
if vault kv list -mount=secret contextforge/oauth/ &>/dev/null; then
    echo "❌ Still found paths:"
    vault kv list -mount=secret contextforge/oauth/
else
    echo "✅ All OAuth data deleted - Vault is clean!"
fi
