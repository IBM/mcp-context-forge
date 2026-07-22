#!/usr/bin/env bash
# -*- coding: utf-8 -*-
# Location: ./scripts/test-oauth-vault.sh
# Copyright 2026
# SPDX-License-Identifier: Apache-2.0
# Authors: Rakhi Dutta
#
# Helper script to test OAuth Authorization Code flow with Vault token storage.
#
# Usage:
#   ./scripts/test-oauth-vault.sh setup          # Setup Vault and environment
#   ./scripts/test-oauth-vault.sh create-gateway # Create test gateway
#   ./scripts/test-oauth-vault.sh list-tokens    # List tokens in Vault
#   ./scripts/test-oauth-vault.sh get-token      # Get specific token
#   ./scripts/test-oauth-vault.sh delete-token   # Delete specific token
#   ./scripts/test-oauth-vault.sh cleanup        # Cleanup all test data

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Configuration
VAULT_ADDR="${VAULT_ADDR:-http://127.0.0.1:8200}"
VAULT_TOKEN="${VAULT_TOKEN:-test-root-token}"
GATEWAY_URL="${TEST_GATEWAY_URL:-https://mcp.github.example.com}"
USER_EMAIL="${TEST_USER_EMAIL:-user2@example.com}"
TEAM_ID="${TEST_TEAM_ID:-team1}"
JWT_SECRET="${JWT_SECRET_KEY:-your-secret-key-here}"

# Calculate server_id (first 8 chars of SHA-256 hash of gateway URL)
SERVER_ID=$(echo -n "$GATEWAY_URL" | sha256sum | cut -c1-8)
EMAIL_ENCODED=$(python3 -c "from urllib.parse import quote; print(quote('$USER_EMAIL', safe=''))")

info() {
    echo -e "${BLUE}ℹ️  $1${NC}"
}

success() {
    echo -e "${GREEN}✅ $1${NC}"
}

error() {
    echo -e "${RED}❌ $1${NC}"
}

warn() {
    echo -e "${YELLOW}⚠️  $1${NC}"
}

# Check prerequisites
check_prerequisites() {
    info "Checking prerequisites..."

    # Check if vault CLI is available
    if ! command -v vault &> /dev/null; then
        warn "vault CLI not found. Install from https://www.vaultproject.io/downloads"
        warn "Falling back to curl for Vault operations"
    fi

    # Check if jq is available
    if ! command -v jq &> /dev/null; then
        error "jq is required but not installed. Install with: brew install jq (macOS) or apt-get install jq (Linux)"
        exit 1
    fi

    # Check if python3 is available
    if ! command -v python3 &> /dev/null; then
        error "python3 is required but not installed"
        exit 1
    fi

    success "Prerequisites check passed"
}

# Check Vault connectivity
check_vault() {
    info "Checking Vault connectivity at $VAULT_ADDR..."

    if curl -s -f "$VAULT_ADDR/v1/sys/health" > /dev/null 2>&1; then
        success "Vault is running at $VAULT_ADDR"
    else
        error "Vault is not accessible at $VAULT_ADDR"
        info "Start Vault with: docker-compose -f docker-compose.vault-test.yml up -d"
        exit 1
    fi
}

# Setup Vault and environment
setup() {
    check_prerequisites
    check_vault

    info "Setting up Vault environment..."
    export VAULT_ADDR="$VAULT_ADDR"
    export VAULT_TOKEN="$VAULT_TOKEN"

    # Enable KV v2 secrets engine if not already enabled
    if command -v vault &> /dev/null; then
        vault secrets enable -version=2 -path=secret kv 2>/dev/null || true
        success "KV v2 secrets engine enabled at 'secret/'"
    fi

    info "Configuration:"
    echo "  VAULT_ADDR:    $VAULT_ADDR"
    echo "  VAULT_TOKEN:   ${VAULT_TOKEN:0:10}..."
    echo "  Gateway URL:   $GATEWAY_URL"
    echo "  Server ID:     $SERVER_ID"
    echo "  User Email:    $USER_EMAIL"
    echo "  Team ID:       $TEAM_ID"
    echo ""
    info "Vault path will be: secret/data/contextforge/oauth/$TEAM_ID/$SERVER_ID/$EMAIL_ENCODED"
}

# Create test gateway
create_gateway() {
    info "Creating test gateway..."

    # Generate JWT token
    BEARER_TOKEN=$(python3 -m mcpgateway.utils.create_jwt_token \
        --username "$USER_EMAIL" \
        --exp 10080 \
        --secret "$JWT_SECRET" \
        --teams "[\"$TEAM_ID\"]" 2>/dev/null)

    # Create gateway
    RESPONSE=$(curl -s -X POST "http://localhost:8000/gateways" \
        -H "Authorization: Bearer $BEARER_TOKEN" \
        -H "Content-Type: application/json" \
        -d "{
            \"name\": \"Test OAuth Gateway\",
            \"url\": \"$GATEWAY_URL\",
            \"description\": \"Test gateway for OAuth + Vault integration\",
            \"team_id\": \"$TEAM_ID\",
            \"visibility\": \"team\",
            \"oauth_config\": {
                \"grant_type\": \"authorization_code\",
                \"client_id\": \"test-client-id\",
                \"client_secret\": \"test-client-secret\",
                \"authorization_url\": \"https://github.com/login/oauth/authorize\",
                \"token_url\": \"https://github.com/login/oauth/access_token\",
                \"redirect_uri\": \"http://localhost:8000/oauth/callback\",
                \"scopes\": [\"read:org\", \"repo\"],
                \"resource\": \"$GATEWAY_URL\"
            }
        }")

    if echo "$RESPONSE" | jq -e '.id' > /dev/null 2>&1; then
        GATEWAY_ID=$(echo "$RESPONSE" | jq -r '.id')
        success "Gateway created with ID: $GATEWAY_ID"
        echo ""
        info "Next steps:"
        echo "  1. Visit: http://localhost:8000/oauth/authorize/$GATEWAY_ID"
        echo "  2. Complete OAuth authorization"
        echo "  3. Run: ./scripts/test-oauth-vault.sh list-tokens"
    else
        error "Failed to create gateway"
        echo "$RESPONSE" | jq '.'
        exit 1
    fi
}

# List tokens in Vault
list_tokens() {
    info "Listing OAuth tokens in Vault..."

    # List all teams
    if command -v vault &> /dev/null; then
        TEAMS=$(vault kv list -mount=secret contextforge/oauth/ 2>&1 | tail -n +3 || echo "")

        if [ -z "$TEAMS" ]; then
            warn "No teams found with OAuth tokens"
            return
        fi

        echo ""
        for team in $TEAMS; do
            team=${team%/}
            if [ -z "$team" ]; then
                continue
            fi

            info "Team: $team"

            # List server_ids
            SERVERS=$(vault kv list -mount=secret "contextforge/oauth/$team/" 2>&1 | tail -n +3 || echo "")
            for server in $SERVERS; do
                server=${server%/}
                if [ -z "$server" ]; then
                    continue
                fi

                echo "  Server ID: $server"

                # List users
                USERS=$(vault kv list -mount=secret "contextforge/oauth/$team/$server/" 2>&1 | tail -n +3 || echo "")
                for user in $USERS; do
                    user=${user%/}
                    if [ -z "$user" ]; then
                        continue
                    fi
                    echo "    👤 $user"
                done
            done
            echo ""
        done
    else
        # Fallback to curl
        warn "Using curl (vault CLI not available)"
        curl -s -H "X-Vault-Token: $VAULT_TOKEN" \
            "$VAULT_ADDR/v1/secret/metadata/contextforge/oauth?list=true" | jq -r '.data.keys[]?' || true
    fi
}

# Get specific token
get_token() {
    info "Getting token for $USER_EMAIL from team $TEAM_ID, server $SERVER_ID..."

    VAULT_PATH="secret/data/contextforge/oauth/$TEAM_ID/$SERVER_ID/$EMAIL_ENCODED"

    if command -v vault &> /dev/null; then
        vault kv get -mount=secret "contextforge/oauth/$TEAM_ID/$SERVER_ID/$EMAIL_ENCODED"
    else
        # Fallback to curl
        RESPONSE=$(curl -s -H "X-Vault-Token: $VAULT_TOKEN" \
            "$VAULT_ADDR/v1/$VAULT_PATH")

        if echo "$RESPONSE" | jq -e '.data.data' > /dev/null 2>&1; then
            success "Token found"
            echo "$RESPONSE" | jq '.data.data'
        else
            error "Token not found"
            echo "$RESPONSE" | jq '.'
        fi
    fi
}

# Delete specific token
delete_token() {
    warn "Deleting token for $USER_EMAIL from team $TEAM_ID, server $SERVER_ID..."

    read -p "Are you sure? [y/N]: " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        info "Cancelled"
        return
    fi

    if command -v vault &> /dev/null; then
        vault kv delete -mount=secret "contextforge/oauth/$TEAM_ID/$SERVER_ID/$EMAIL_ENCODED"
        success "Token deleted"
    else
        # Fallback to curl
        curl -s -X DELETE -H "X-Vault-Token: $VAULT_TOKEN" \
            "$VAULT_ADDR/v1/secret/data/contextforge/oauth/$TEAM_ID/$SERVER_ID/$EMAIL_ENCODED"
        success "Token deleted"
    fi
}

# Delete all tokens for a user across all teams
delete_user_tokens() {
    warn "Deleting ALL tokens for $USER_EMAIL across all teams..."

    read -p "Are you sure? [y/N]: " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        info "Cancelled"
        return
    fi

    if command -v vault &> /dev/null; then
        vault kv list -mount=secret contextforge/oauth/ 2>&1 | tail -n +3 | while read team; do
            team=${team%/}
            if [ -z "$team" ]; then
                continue
            fi

            vault kv delete -mount=secret "contextforge/oauth/$team/$SERVER_ID/$EMAIL_ENCODED" 2>/dev/null && \
                success "Deleted token for team: $team" || true
        done
    else
        error "Bulk deletion requires vault CLI"
    fi
}

# Cleanup all test data
cleanup() {
    warn "Cleaning up all OAuth test data from Vault..."

    read -p "This will delete ALL OAuth tokens. Are you sure? [y/N]: " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        info "Cancelled"
        return
    fi

    if command -v vault &> /dev/null; then
        vault kv metadata delete -mount=secret "contextforge/oauth"
        success "All OAuth tokens deleted"
    else
        # Fallback to curl
        curl -s -X DELETE -H "X-Vault-Token: $VAULT_TOKEN" \
            "$VAULT_ADDR/v1/secret/metadata/contextforge/oauth"
        success "All OAuth tokens deleted"
    fi
}

# Show help
show_help() {
    cat << EOF
${BLUE}OAuth + Vault Testing Helper${NC}

Usage:
  $0 <command>

Commands:
  ${GREEN}setup${NC}              Setup Vault and verify connectivity
  ${GREEN}create-gateway${NC}    Create test gateway with OAuth config
  ${GREEN}list-tokens${NC}       List all OAuth tokens in Vault
  ${GREEN}get-token${NC}         Get specific token for configured user
  ${GREEN}delete-token${NC}      Delete specific token for configured user
  ${GREEN}delete-user-tokens${NC} Delete all tokens for configured user (all teams)
  ${GREEN}cleanup${NC}           Delete all OAuth tokens from Vault
  ${GREEN}help${NC}              Show this help message

Environment Variables:
  VAULT_ADDR           Vault address (default: http://127.0.0.1:8200)
  VAULT_TOKEN          Vault token (default: test-root-token)
  TEST_GATEWAY_URL     Gateway URL (default: https://mcp.github.example.com)
  TEST_USER_EMAIL      User email (default: user2@example.com)
  TEST_TEAM_ID         Team ID (default: team1)
  JWT_SECRET_KEY       JWT secret (default: your-secret-key-here)

Example Workflow:
  # 1. Setup and verify Vault
  $0 setup

  # 2. Start ContextForge
  make dev

  # 3. Create test gateway
  $0 create-gateway

  # 4. Visit OAuth URL printed above and complete authorization

  # 5. List stored tokens
  $0 list-tokens

  # 6. Get specific token
  $0 get-token

  # 7. Cleanup when done
  $0 cleanup

Documentation:
  See docs/testing-oauth-vault.md for detailed guide
EOF
}

# Main command dispatch
case "${1:-help}" in
    setup)
        setup
        ;;
    create-gateway)
        create_gateway
        ;;
    list-tokens)
        list_tokens
        ;;
    get-token)
        get_token
        ;;
    delete-token)
        delete_token
        ;;
    delete-user-tokens)
        delete_user_tokens
        ;;
    cleanup)
        cleanup
        ;;
    help|--help|-h)
        show_help
        ;;
    *)
        error "Unknown command: $1"
        echo ""
        show_help
        exit 1
        ;;
esac
