#!/usr/bin/env bash
# Quick debug script to inspect Vault OAuth token structure

set -e

VAULT_ADDR="${VAULT_ADDR:-http://127.0.0.1:8200}"
VAULT_TOKEN="${VAULT_TOKEN:-test-root-token}"

echo "🔍 Vault OAuth Token Debug"
echo "=========================="
echo ""

# List top-level structure
echo "📁 Top-level paths:"
vault kv list -mount=secret contextforge/oauth/ 2>/dev/null || echo "  (none found)"
echo ""

# For each path found, show structure
vault kv list -mount=secret contextforge/oauth/ 2>/dev/null | tail -n +3 | while read path; do
    path=${path%/}
    if [ -z "$path" ]; then
        continue
    fi

    echo "📂 Path: $path"

    # Try to list contents
    vault kv list -mount=secret "contextforge/oauth/$path/" 2>/dev/null | tail -n +3 | while read subpath; do
        subpath=${subpath%/}
        if [ -z "$subpath" ]; then
            continue
        fi

        echo "  📄 $subpath"

        # Try to get the actual token data
        vault kv get -format=json -mount=secret "contextforge/oauth/$path/$subpath" 2>/dev/null | \
            jq -r '.data.data | keys[]' 2>/dev/null | while read key; do
            echo "    - $key"
        done
    done
    echo ""
done

# Try to get full token data for the first found token
echo "📝 Sample Token Data:"
FIRST_PATH=$(vault kv list -mount=secret contextforge/oauth/ 2>/dev/null | tail -n +3 | head -1 | tr -d '/')
if [ ! -z "$FIRST_PATH" ]; then
    FIRST_EMAIL=$(vault kv list -mount=secret "contextforge/oauth/$FIRST_PATH/" 2>/dev/null | tail -n +3 | head -1 | tr -d '/')
    if [ ! -z "$FIRST_EMAIL" ]; then
        echo "  Path: contextforge/oauth/$FIRST_PATH/$FIRST_EMAIL"
        vault kv get -format=json -mount=secret "contextforge/oauth/$FIRST_PATH/$FIRST_EMAIL" | jq '.data.data'
    fi
fi
