#!/bin/bash
# Query OAuth tokens stored in Vault's PostgreSQL backend
#
# Usage:
#   ./query-oauth-tokens.sh list                      # List all teams with tokens
#   ./query-oauth-tokens.sh get <team_id> <email>     # Get specific token
#   ./query-oauth-tokens.sh raw                       # Show raw PostgreSQL data

set -euo pipefail

# Load Vault config from .env
if [ -f .env ]; then
    export $(grep -v '^#' .env | grep 'VAULT_' | xargs)
fi

VAULT_ADDR="${VAULT_ADDR:-http://127.0.0.1:8200}"
VAULT_TOKEN="${VAULT_TOKEN:-}"
KV_PATH="${VAULT_KV_PATH_PREFIX:-contextforge/oauth}"

if [ -z "$VAULT_TOKEN" ]; then
    echo "ERROR: VAULT_TOKEN not set in .env"
    exit 1
fi

case "${1:-list}" in
    list)
        echo "=== OAuth Token Teams ==="
        vault kv list "secret/$KV_PATH/" 2>/dev/null || echo "No tokens found"
        ;;

    get)
        if [ $# -lt 3 ]; then
            echo "Usage: $0 get <team_id> <email>"
            exit 1
        fi
        TEAM_ID="$2"
        EMAIL="$3"

        echo "=== Searching for $EMAIL in team $TEAM_ID ==="

        # List all provider hashes
        PROVIDERS=$(vault kv list -format=json "secret/$KV_PATH/$TEAM_ID/" 2>/dev/null | jq -r '.[]' || echo "")

        if [ -z "$PROVIDERS" ]; then
            echo "No tokens found for team $TEAM_ID"
            exit 1
        fi

        # Search each provider
        for provider in $PROVIDERS; do
            TOKEN_PATH="secret/$KV_PATH/$TEAM_ID/${provider}$EMAIL"
            if vault kv get "$TOKEN_PATH" &>/dev/null; then
                echo "Found token at: $TOKEN_PATH"
                vault kv get -format=json "$TOKEN_PATH" | jq '.data.data'
                exit 0
            fi
        done

        echo "Token not found for $EMAIL in team $TEAM_ID"
        ;;

    raw)
        echo "=== Raw PostgreSQL Data (Encrypted) ==="
        psql "${DATABASE_URL:-postgresql://vault_user:vault_password@localhost:5432/vault_dev}" -c "
            SELECT
                parent_path,
                LEFT(key, 40) as key_prefix,
                LENGTH(value) as encrypted_bytes,
                encode(substring(value from 1 for 32), 'hex') as first_32_bytes
            FROM vault_kv_store
            WHERE parent_path LIKE '/logical/%'
            ORDER BY LENGTH(value) DESC
            LIMIT 10;
        "
        ;;

    *)
        echo "Usage: $0 {list|get|raw}"
        exit 1
        ;;
esac
