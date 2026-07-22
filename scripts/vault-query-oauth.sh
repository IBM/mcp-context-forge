#!/bin/bash
# Query OAuth tokens from Vault
# Usage: ./vault-query-oauth.sh [command] [args...]

set -euo pipefail

# Load from .env or use defaults
if [ -f .env ]; then
    export $(grep -v '^#' .env | grep 'VAULT_' | xargs 2>/dev/null || true)
fi

VAULT_ADDR="${VAULT_ADDR:-http://127.0.0.1:8200}"
VAULT_TOKEN="${VAULT_TOKEN:-}"

if [ -z "$VAULT_TOKEN" ]; then
    echo "ERROR: VAULT_TOKEN not set"
    echo "Set in .env or export VAULT_TOKEN=..."
    exit 1
fi

# Commands
list_teams() {
    echo "=== All Teams ==="
    curl -s \
        -H "X-Vault-Token: $VAULT_TOKEN" \
        "${VAULT_ADDR}/v1/secret/metadata/contextforge/oauth?list=true" \
        | jq -r '.data.keys[]? // empty' | sed 's/\/$//'
}

list_providers() {
    local team_id="$1"
    echo "=== Providers for team: ${team_id} ==="
    curl -s \
        -H "X-Vault-Token: $VAULT_TOKEN" \
        "${VAULT_ADDR}/v1/secret/metadata/contextforge/oauth/${team_id}?list=true" \
        | jq -r '.data.keys[]? // empty' | sed 's/\/$//'
}

list_users() {
    local team_id="$1"
    local provider="$2"
    echo "=== Users for team: ${team_id}, provider: ${provider} ==="
    curl -s \
        -H "X-Vault-Token: $VAULT_TOKEN" \
        "${VAULT_ADDR}/v1/secret/metadata/contextforge/oauth/${team_id}/${provider}?list=true" \
        | jq -r '.data.keys[]? // empty'
}

get_token() {
    local team_id="$1"
    local provider="$2"
    local email="$3"
    echo "=== Token for ${email} (team: ${team_id}, provider: ${provider}) ==="
    curl -s \
        -H "X-Vault-Token: $VAULT_TOKEN" \
        "${VAULT_ADDR}/v1/secret/data/contextforge/oauth/${team_id}/${provider}/${email}" \
        | jq '.data.data'
}

get_team_all() {
    local team_id="$1"
    echo "=== All tokens for team: ${team_id} ==="

    # Get all providers
    local providers=$(curl -s \
        -H "X-Vault-Token: $VAULT_TOKEN" \
        "${VAULT_ADDR}/v1/secret/metadata/contextforge/oauth/${team_id}?list=true" \
        | jq -r '.data.keys[]? // empty' | sed 's/\/$//')

    if [ -z "$providers" ]; then
        echo "No tokens found"
        return
    fi

    # For each provider
    for provider in $providers; do
        echo ""
        echo "Provider: $provider"
        echo "----------------------------------------"

        # Get all users
        local users=$(curl -s \
            -H "X-Vault-Token: $VAULT_TOKEN" \
            "${VAULT_ADDR}/v1/secret/metadata/contextforge/oauth/${team_id}/${provider}?list=true" \
            | jq -r '.data.keys[]? // empty')

        if [ -z "$users" ]; then
            echo "  No users"
            continue
        fi

        # For each user
        for user in $users; do
            echo ""
            echo "  User: $user"

            local data=$(curl -s \
                -H "X-Vault-Token: $VAULT_TOKEN" \
                "${VAULT_ADDR}/v1/secret/data/contextforge/oauth/${team_id}/${provider}/${user}")

            echo "    Access Token: $(echo "$data" | jq -r '.data.data.token.access_token // "N/A"' | head -c 20)..."
            echo "    User ID: $(echo "$data" | jq -r '.data.data.user_id // "N/A"')"
            echo "    MCP URL: $(echo "$data" | jq -r '.data.data.mcp_url // "N/A"')"
            echo "    Created: $(echo "$data" | jq -r '.data.data.created_at // "N/A"')"
        done
    done
}

# Main command dispatch
case "${1:-help}" in
    teams)
        list_teams
        ;;

    providers)
        if [ $# -lt 2 ]; then
            echo "Usage: $0 providers <team_id>"
            exit 1
        fi
        list_providers "$2"
        ;;

    users)
        if [ $# -lt 3 ]; then
            echo "Usage: $0 users <team_id> <provider>"
            exit 1
        fi
        list_users "$2" "$3"
        ;;

    get)
        if [ $# -lt 4 ]; then
            echo "Usage: $0 get <team_id> <provider> <email>"
            exit 1
        fi
        get_token "$2" "$3" "$4"
        ;;

    team)
        if [ $# -lt 2 ]; then
            echo "Usage: $0 team <team_id>"
            exit 1
        fi
        get_team_all "$2"
        ;;

    help|*)
        cat <<EOF
Vault OAuth Token Query Tool

Usage: $0 <command> [args...]

Commands:
  teams                           List all teams with OAuth tokens
  providers <team_id>             List providers for a team
  users <team_id> <provider>      List users for a team+provider
  get <team_id> <provider> <email> Get specific user token
  team <team_id>                  Get all tokens for a team

Examples:
  $0 teams
  $0 providers d855a360a0f24f56ac2b5a1ab54cbb70
  $0 users d855a360a0f24f56ac2b5a1ab54cbb70 ca602dd4
  $0 get d855a360a0f24f56ac2b5a1ab54cbb70 ca602dd4 user2@example.com
  $0 team d855a360a0f24f56ac2b5a1ab54cbb70

Environment:
  VAULT_ADDR   Vault server URL (default: http://127.0.0.1:8200)
  VAULT_TOKEN  Vault authentication token (required)

EOF
        ;;
esac
