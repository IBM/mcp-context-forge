#!/bin/bash
# Vault Recovery Script for PostgreSQL Storage
# Run this when you get "barrier reports initialized but no seal configuration found"

set -e

echo "🔧 Vault Recovery: PostgreSQL Storage"
echo "======================================"
echo ""

# Step 1: Stop any running Vault
echo "1️⃣  Stopping any running Vault processes..."
pkill -9 vault 2>/dev/null || echo "   No Vault processes running"
sleep 2

# Step 2: Check PostgreSQL connection
echo ""
echo "2️⃣  Verifying PostgreSQL connection..."
if ! psql -U vault_user -d vault_dev -c "SELECT 1;" >/dev/null 2>&1; then
    echo "   ❌ Cannot connect to PostgreSQL"
    echo "   Run: psql postgres -c 'CREATE DATABASE vault_dev;'"
    exit 1
fi
echo "   ✅ PostgreSQL connected"

# Step 3: Backup existing Vault data
echo ""
echo "3️⃣  Backing up existing Vault storage..."
BACKUP_FILE="$HOME/.vault-config/vault_kv_store_backup_$(date +%Y%m%d_%H%M%S).sql"
psql -U vault_user -d vault_dev -c "COPY vault_kv_store TO STDOUT;" > "$BACKUP_FILE" 2>/dev/null || true
echo "   💾 Backup saved: $BACKUP_FILE"

# Step 4: Drop and recreate storage table (FIXES CORRUPTION)
echo ""
echo "4️⃣  Recreating Vault storage table..."
psql -U vault_user -d vault_dev <<'EOF'
DROP TABLE IF EXISTS vault_kv_store;

CREATE TABLE vault_kv_store (
  parent_path TEXT COLLATE "C" NOT NULL,
  path        TEXT COLLATE "C",
  key         TEXT COLLATE "C",
  value       BYTEA,
  CONSTRAINT pkey PRIMARY KEY (path, key)
);

CREATE INDEX parent_path_idx ON vault_kv_store (parent_path);
EOF
echo "   ✅ Storage table recreated"

# Step 5: Start Vault in background
echo ""
echo "5️⃣  Starting Vault server..."
vault server -config=$HOME/.vault-config/config.hcl > /tmp/vault-server.log 2>&1 &
VAULT_PID=$!
echo "   Vault PID: $VAULT_PID"
sleep 3

# Step 6: Check if Vault started
echo ""
echo "6️⃣  Checking Vault status..."
export VAULT_ADDR="http://127.0.0.1:8200"
if ! curl -s http://127.0.0.1:8200/v1/sys/health >/dev/null 2>&1; then
    echo "   ❌ Vault failed to start"
    echo "   Check logs: tail -50 /tmp/vault-server.log"
    exit 1
fi
echo "   ✅ Vault is responding"

# Step 7: Initialize (if needed)
echo ""
echo "7️⃣  Checking initialization status..."
INIT_STATUS=$(vault status -format=json 2>/dev/null | jq -r .initialized 2>/dev/null || echo "false")

if [ "$INIT_STATUS" = "false" ]; then
    echo "   🔐 Vault not initialized - initializing now..."
    INIT_OUTPUT=$(vault operator init -key-shares=1 -key-threshold=1 -format=json)

    UNSEAL_KEY=$(echo "$INIT_OUTPUT" | jq -r '.unseal_keys_b64[0]')
    ROOT_TOKEN=$(echo "$INIT_OUTPUT" | jq -r '.root_token')

    # Save to keys file
    cat > ~/.vault-config/keys.txt <<EOF
VAULT_UNSEAL_KEY=$UNSEAL_KEY
VAULT_ROOT_TOKEN=$ROOT_TOKEN
EOF
    chmod 600 ~/.vault-config/keys.txt

    echo "   ✅ Vault initialized"
    echo "   🔑 Keys saved to: ~/.vault-config/keys.txt"
else
    echo "   ✅ Vault already initialized"
fi

# Step 8: Unseal
echo ""
echo "8️⃣  Unsealing Vault..."
if [ ! -f ~/.vault-config/keys.txt ]; then
    echo "   ❌ Keys file not found: ~/.vault-config/keys.txt"
    echo "   You need your original VAULT_UNSEAL_KEY"
    exit 1
fi

source ~/.vault-config/keys.txt
vault operator unseal "$VAULT_UNSEAL_KEY" >/dev/null 2>&1
echo "   ✅ Vault unsealed"

# Step 9: Verify token
echo ""
echo "9️⃣  Verifying root token..."
export VAULT_TOKEN="$VAULT_ROOT_TOKEN"
if ! vault token lookup >/dev/null 2>&1; then
    echo "   ❌ Root token invalid"
    exit 1
fi
echo "   ✅ Root token valid"

# Step 10: Re-enable KV v2 (if needed)
echo ""
echo "🔟 Ensuring KV v2 secrets engine..."
if ! vault secrets list -format=json | jq -e '.["secret/"]' >/dev/null 2>&1; then
    vault secrets enable -version=2 -path=secret kv
    echo "   ✅ KV v2 enabled"
else
    echo "   ✅ KV v2 already enabled"
fi

# Step 11: Re-create policy and token (if needed)
echo ""
echo "1️⃣1️⃣  Ensuring ContextForge policy..."
cat > /tmp/contextforge-policy.hcl <<'EOF'
# Allow listing the root secret/ path
path "secret/metadata" {
  capabilities = ["list"]
}

# Allow listing contextforge/ and oauth/ directories
path "secret/metadata/contextforge" {
  capabilities = ["list"]
}

path "secret/metadata/contextforge/oauth" {
  capabilities = ["list"]
}

# Full access to OAuth tokens
path "secret/data/contextforge/oauth/*" {
  capabilities = ["create", "update", "read", "delete", "list"]
}

path "secret/metadata/contextforge/oauth/*" {
  capabilities = ["create", "update", "read", "delete", "list"]
}
EOF

vault policy write contextforge /tmp/contextforge-policy.hcl >/dev/null
echo "   ✅ Policy created"

# Step 12: Create/refresh ContextForge token
echo ""
echo "1️⃣2️⃣  Setting up ContextForge token..."

# Always create a fresh token after restart
CF_TOKEN=$(vault token create \
  -policy="contextforge" \
  -display-name="contextforge-dev" \
  -ttl="720h" \
  -format=json | jq -r .auth.client_token)

# Update keys file (remove old CF token line first)
grep -v "VAULT_CF_TOKEN" ~/.vault-config/keys.txt > ~/.vault-config/keys.txt.tmp 2>/dev/null || true
mv ~/.vault-config/keys.txt.tmp ~/.vault-config/keys.txt
echo "VAULT_CF_TOKEN=$CF_TOKEN" >> ~/.vault-config/keys.txt

echo "   ✅ Token created: $CF_TOKEN"

# Step 13: Update .env file
echo ""
echo "1️⃣3️⃣  Updating .env file..."
ENV_FILE="$HOME/mcp-context-forge/.env"

if [ -f "$ENV_FILE" ]; then
    # Create backup
    cp "$ENV_FILE" "${ENV_FILE}.backup.$(date +%Y%m%d_%H%M%S)"

    # Update VAULT_TOKEN in .env
    if grep -q "^VAULT_TOKEN=" "$ENV_FILE"; then
        # Use | as delimiter to avoid conflicts with token content
        sed -i.bak "s|^VAULT_TOKEN=.*|VAULT_TOKEN=$CF_TOKEN|" "$ENV_FILE"
        rm -f "${ENV_FILE}.bak"
        echo "   ✅ Updated VAULT_TOKEN in .env"
    else
        echo "VAULT_TOKEN=$CF_TOKEN" >> "$ENV_FILE"
        echo "   ✅ Added VAULT_TOKEN to .env"
    fi
else
    echo "   ⚠️  .env file not found at: $ENV_FILE"
fi

# Step 14: Create source-able environment file
VAULT_ENV_FILE="$HOME/.vault-config/vault-env.sh"
cat > "$VAULT_ENV_FILE" <<EOF
# Source this file to configure Vault environment:
#   source ~/.vault-config/vault-env.sh

export VAULT_ADDR=http://127.0.0.1:8200
export VAULT_TOKEN=$CF_TOKEN

echo "✅ Vault environment configured:"
echo "   VAULT_ADDR=\$VAULT_ADDR"
echo "   VAULT_TOKEN=\${VAULT_TOKEN:0:20}..."
EOF
chmod +x "$VAULT_ENV_FILE"

# Step 15: Add vault-auth alias to shell rc file (if not already present)
echo ""
echo "1️⃣5️⃣  Configuring shell aliases..."
SHELL_RC="$HOME/.zshrc"
if [ ! -f "$SHELL_RC" ]; then
    touch "$SHELL_RC"
fi

ALIAS_LINE="alias vault-auth='source ~/.vault-config/keys.txt && export VAULT_ADDR=http://127.0.0.1:8200 && export VAULT_TOKEN=\$VAULT_CF_TOKEN && echo \"✅ Vault environment configured\"'"

if ! grep -q "alias vault-auth=" "$SHELL_RC"; then
    echo "" >> "$SHELL_RC"
    echo "# Vault authentication helper (added by restart-vault.sh)" >> "$SHELL_RC"
    echo "$ALIAS_LINE" >> "$SHELL_RC"
    echo "   ✅ Added vault-auth alias to $SHELL_RC"
else
    echo "   ✅ vault-auth alias already exists in $SHELL_RC"
fi

echo ""
echo "✅ Vault recovery complete!"
echo ""
echo "📋 Summary:"
echo "   - Vault server PID: $VAULT_PID"
echo "   - Status: Unsealed"
echo "   - Token: ${CF_TOKEN:0:20}..."
echo "   - Logs: /tmp/vault-server.log"
echo "   - Keys: ~/.vault-config/keys.txt"
echo "   - .env updated: $ENV_FILE"
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "⚠️  IMPORTANT: Run this in your current shell:"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "   source ~/.vault-config/vault-env.sh"
echo ""
echo "Or reload your shell and use:"
echo ""
echo "   source ~/.zshrc"
echo "   vault-auth"
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "🧪 Then test Vault access:"
echo "   vault kv list secret"
echo "   vault status"
echo ""
echo "⚠️  Note: Previous OAuth tokens were backed up to:"
echo "   $BACKUP_FILE"
echo "   (Restoration requires re-authorization)"
echo ""
echo "💡 The vault-auth alias is now available in new terminal sessions!"
