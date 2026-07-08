# Local Development — HashiCorp Vault with PostgreSQL

This guide sets up Vault with PostgreSQL storage for local development. Unlike dev mode (in-memory), this configuration persists tokens and secrets across restarts, matching production behavior more closely.

## Prerequisites

- PostgreSQL running locally (e.g., via Homebrew or Docker)
- Vault CLI installed
- ContextForge repository with PostgreSQL configured

---

## Step 1 — Install Vault CLI

```bash
# macOS (Homebrew)
brew tap hashicorp/tap
brew install hashicorp/tap/vault

# Verify installation
vault version
# Expected: Vault v1.17.x or later
```

---

## Step 2 — Set up PostgreSQL database for Vault

```bash
# Connect to PostgreSQL
psql postgres

# Create dedicated database and user for Vault
CREATE DATABASE vault_dev;
CREATE USER vault_user WITH ENCRYPTED PASSWORD 'password';  # pragma: allowlist secret
GRANT ALL PRIVILEGES ON DATABASE vault_dev TO vault_user;
GRANT ALL ON SCHEMA public TO vault_user;
ALTER DATABASE vault_dev OWNER TO vault_user;
\q
```

**Important**: The `GRANT ALL ON SCHEMA public` and `ALTER DATABASE` commands are required so Vault can create its storage tables.

---

## Step 3 — Create Vault server configuration

Create a configuration file that uses PostgreSQL as the storage backend:

```bash
# Create config directory (use .vault-config to avoid conflict with Vault's token helper)
mkdir -p ~/.vault-config

# Create server config file
cat > ~/.vault-config/config.hcl <<'EOF'
storage "postgresql" {
  connection_url = "postgres://vault_user:password@localhost:5432/vault_dev?sslmode=disable"
  table          = "vault_kv_store"
  max_parallel   = 4
}

listener "tcp" {
  address     = "127.0.0.1:8200"
  tls_disable = 1
}

api_addr = "http://127.0.0.1:8200"
ui       = true

log_level = "info"
EOF
```

**Connection URL format**: `postgres://<user>:<password>@<host>:<port>/<database>?sslmode=disable`

**Note**: We use `~/.vault-config` (not `~/.vault`) to avoid conflict with Vault's default token helper, which uses `~/.vault-token` file.

---

## Step 4 — Create PostgreSQL storage table

Before starting Vault, we need to create the storage table manually to avoid initialization loops:

```bash
# Create the vault_kv_store table
psql vault_dev -U vault_user << 'EOF'
CREATE TABLE IF NOT EXISTS vault_kv_store (
  parent_path TEXT COLLATE "C" NOT NULL,
  path        TEXT COLLATE "C",
  key         TEXT COLLATE "C",
  value       BYTEA,
  CONSTRAINT pkey PRIMARY KEY (path, key)
);

CREATE INDEX IF NOT EXISTS parent_path_idx ON vault_kv_store (parent_path);
EOF
```

**Expected output**: `CREATE TABLE` and `CREATE INDEX`

---

## Step 5 — Start Vault server

```bash
# Start Vault with the PostgreSQL config
vault server -config=$HOME/.vault-config/config.hcl

# Server starts on http://127.0.0.1:8200
# Keep this terminal open — server runs in foreground
```

You should see:
```
[INFO]  proxy environment: http_proxy="" https_proxy="" no_proxy=""
```

No more warnings about `vault_kv_store` not existing.

---

## Step 6 — Initialize Vault (first time only)

Open a **new terminal** and initialize Vault. This creates unseal keys and a root token:

```bash
# Set Vault address
export VAULT_ADDR="http://127.0.0.1:8200"

# Initialize Vault (do this ONCE, on first start)
vault operator init -key-shares=1 -key-threshold=1

# Output looks like:
# Unseal Key 1: <UNSEAL_KEY>
# Initial Root Token: <ROOT_TOKEN>
#
# IMPORTANT: Save these values securely!
# You need the unseal key after every Vault restart.
```

**Save the output** — you need:
- **Unseal Key** (to unseal Vault after restart)
- **Root Token** (for admin operations)

For convenience in local dev, save to a file:

```bash
# Save to a local file (DO NOT commit this file)
cat > ~/.vault-config/keys.txt <<EOF
VAULT_UNSEAL_KEY=<paste-unseal-key-here>
VAULT_ROOT_TOKEN=<paste-root-token-here>
EOF

chmod 600 ~/.vault-config/keys.txt
```

---

## Step 7 — Unseal Vault

After initialization (or any restart), Vault starts **sealed** and must be unsealed:

```bash
# Export the unseal key from saved file
source ~/.vault-config/keys.txt

# Unseal Vault
vault operator unseal "$VAULT_UNSEAL_KEY"

# Expected output:
# Sealed: false  ← must show "false"
```

**Note**: You must unseal Vault after **every restart**. In production, use auto-unseal with a cloud KMS.

---

## Step 8 — Authenticate with root token

```bash
# Set root token from saved file
source ~/.vault-config/keys.txt
export VAULT_TOKEN="$VAULT_ROOT_TOKEN"

# Verify you can authenticate
vault token lookup
# Should show token info without errors
```

---

## Step 9 — Enable KV v2 secrets engine

```bash
# Enable KV v2 at "secret/" path
vault secrets enable -version=2 -path=secret kv

# Verify it's mounted
vault secrets list
# Should show:  secret/   kv   kv_2   ...
```

---

## Step 10 — Create ContextForge Vault policy

Create a policy that grants ContextForge access to OAuth token paths:

```bash
# Create policy file
cat > ~/.vault-config/contextforge-policy.hcl <<'EOF'
# Read/write OAuth tokens
path "secret/data/contextforge/oauth/*" {
  capabilities = ["create", "update", "read", "delete"]
}

# Delete metadata and list tokens
path "secret/metadata/contextforge/oauth/*" {
  capabilities = ["delete", "list"]
}
EOF

# Write policy to Vault
vault policy write contextforge ~/.vault-config/contextforge-policy.hcl

# Verify policy exists
vault policy read contextforge
```

---

## Step 11 — Create scoped token for ContextForge

Create a token tied to the `contextforge` policy (not the root token):

```bash
# Create a token with the contextforge policy
vault token create \
  -policy="contextforge" \
  -display-name="contextforge-dev" \
  -ttl="720h" \
  -format=json | jq -r '.auth.client_token'

# Copy the printed token — this is your VAULT_TOKEN for ContextForge
# Example: hvs.CAESIJx...  (starts with hvs.)
```

**Save this token** — you'll use it in `.env`:

```bash
# Append to keys file for easy reference
echo "VAULT_CF_TOKEN=<paste-token-here>" >> ~/.vault-config/keys.txt
```

---

## Step 12 — Test Vault setup (Optional but Recommended)

Before integrating with ContextForge, verify that Vault is working correctly with the ContextForge policy:

```bash
# Switch to ContextForge token (not root token)
source ~/.vault-config/keys.txt
export VAULT_TOKEN="$VAULT_CF_TOKEN"

# Verify you're using the ContextForge token
vault token lookup
# Should show: policies [contextforge default]  (not [root])
```

### Test WRITE operation

```bash
vault kv put secret/contextforge/oauth/test-server/testuser@example.com \
  mcp_url="http://localhost:9000" \
  access_token="test_access_abc123" \
  refresh_token="test_refresh_xyz789" \
  token_type="bearer" \
  expires_in="3600"
```

**Expected output:**
```
====== Secret Path ======
secret/data/contextforge/oauth/test-server/testuser@example.com

======= Metadata =======
Key                Value
---                -----
created_time       2026-07-08T...
...
```

### Test READ operation

```bash
vault kv get secret/contextforge/oauth/test-server/testuser@example.com
```

**Expected output:**
```
====== Data ======
Key              Value
---              -----
access_token     test_access_abc123
expires_in       3600
mcp_url          http://localhost:9000
refresh_token    test_refresh_xyz789
token_type       bearer
```

### Test LIST operation

```bash
vault kv list secret/contextforge/oauth/test-server
```

**Expected output:**
```
Keys
----
testuser@example.com
```

### Test DELETE operation

```bash
vault kv delete secret/contextforge/oauth/test-server/testuser@example.com
```

**Expected output:**
```
Success! Data deleted (if it existed) at: secret/data/contextforge/oauth/test-server/testuser@example.com
```

### Verify deletion

```bash
vault kv get secret/contextforge/oauth/test-server/testuser@example.com
```

**Expected output:**
```
No value found at secret/data/contextforge/oauth/test-server/testuser@example.com
```

**✅ If all commands above work, your Vault setup is complete and ready for ContextForge integration!**

### Verify PostgreSQL Storage (Optional)

Confirm that secrets are actually stored in PostgreSQL, not just in memory:

```bash
# Step 1: Check row count BEFORE writing
psql vault_dev -U vault_user -c "SELECT COUNT(*) FROM vault_kv_store;"
# Note the count (e.g., 51 rows)

# Step 2: Write a NEW test secret
vault kv put secret/contextforge/oauth/verify-test/newuser@example.com \
  mcp_url="http://localhost:9002" \
  access_token="verify_token_abc"

# Step 3: Check row count AFTER writing
psql vault_dev -U vault_user -c "SELECT COUNT(*) FROM vault_kv_store;"
# Count should increase by 2-3 rows (metadata + version data)

# Step 4: View the logical backend storage (where KV secrets are stored)
psql vault_dev -U vault_user << 'EOF'
SELECT 
    substring(path from 1 for 50) as path,
    substring(key from 1 for 40) as key_hash,
    length(value) as value_bytes
FROM vault_kv_store
WHERE path LIKE '/logical/%'
ORDER BY path DESC
LIMIT 10;
EOF
```

**Expected output** for Step 4:
```
                      path                        |                key_hash                | value_bytes
--------------------------------------------------+----------------------------------------+-------------
/logical/de382bba-9ad1-d453-168d-db7c4e5fcc91/... | 2fc623887a6893ce04e706bede8ce08e...    | 201
/logical/de382bba-9ad1-d453-168d-db7c4e5fcc91/... | 38REM5BOsIW4lGM4UFTP86S0is54Nm8q...    | 396
...
```

**Key observations:**
- Secrets are stored under `/logical/<mount-uuid>/...` paths
- Keys and paths are encrypted/hashed by Vault for security
- Each secret creates multiple rows (metadata, version data, etc.)
- Data persists across Vault restarts (PostgreSQL backend)

```bash
# Step 5: Verify you can read it back
vault kv get secret/contextforge/oauth/verify-test/newuser@example.com

# Step 6: Clean up test secret
vault kv delete secret/contextforge/oauth/verify-test/newuser@example.com
```

**✅ PostgreSQL verification complete!** Data flows correctly: `vault kv` commands → PostgreSQL storage → retrieval.

---

## Step 13 — Configure ContextForge `.env`

Add Vault configuration to your `.env` file:

```bash
# OAuth token storage backend
OAUTH_TOKEN_BACKEND=vault

# Vault connection
VAULT_ADDR=http://127.0.0.1:8200
VAULT_TOKEN=<token-from-step-10>     # pragma: allowlist secret
VAULT_KV_MOUNT=secret
VAULT_KV_PATH_PREFIX=contextforge/oauth

# TLS verification (disabled for local dev)
VAULT_TLS_VERIFY=false

# Optional: install hvac client (recommended)
# pip install 'contextforge[vault]'
```

---

## Step 14 — Smoke test Vault integration with ContextForge

Test that Vault can store and retrieve secrets:

```bash
# Export Vault env vars
export VAULT_ADDR="http://127.0.0.1:8200"
export VAULT_TOKEN="<your-contextforge-token>"

# Write a test secret
vault kv put secret/contextforge/oauth/test/dev@example.com \
  mcp_url="http://localhost:9000" \
  access_token="test_abc123" \
  refresh_token="refresh_xyz789" \
  token_type="bearer" \
  expires_in="3600"

# Read it back
vault kv get secret/contextforge/oauth/test/dev@example.com

# Expected output shows the stored values

# List secrets under the prefix
vault kv list secret/contextforge/oauth/test

# Clean up test secret
vault kv delete secret/contextforge/oauth/test/dev@example.com
```

---

## Step 15 — Install ContextForge with Vault support

```bash
# Install with vault extra (includes hvac client)
pip install -e ".[vault]"

# Or if already installed, add the extra
pip install hvac
```

---

## Step 16 — Start ContextForge and verify

```bash
# Start development server
make dev

# Look for startup log indicating Vault is reachable:
#   INFO  oauth_token_backend=vault  vault_addr=http://127.0.0.1:8200  ✓ reachable
```

Test the OAuth authorize endpoint:

```bash
# Get a ContextForge bearer token
export MCPGATEWAY_BEARER_TOKEN=$(python -m mcpgateway.utils.create_jwt_token \
  --username admin@example.com --exp 0 --secret <your-jwt-secret>)

# Test authorize endpoint (replace <server_id> with actual server UUID)
curl -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN" \
  "http://localhost:4444/vault/authorize/<server_id>"

# Expected responses:
#   - 302 redirect to IdP if OAuth gateway configured
#   - 400 if no OAuth gateway on that server
#   - 404 if server doesn't exist
```

---

## Daily Workflow

### Starting Vault

```bash
# Terminal 1: Start Vault server
vault server -config=$HOME/.vault-config/config.hcl

# Terminal 2: Unseal Vault (required after every restart)
source ~/.vault-config/keys.txt
export VAULT_ADDR="http://127.0.0.1:8200"
vault operator unseal "$VAULT_UNSEAL_KEY"
```

### Restarting Vault

PostgreSQL storage persists data, so you only need to:

1. Stop the Vault server (Ctrl+C)
2. Restart: `vault server -config=$HOME/.vault-config/config.hcl`
3. Unseal: `vault operator unseal "$VAULT_UNSEAL_KEY"`

**No re-initialization needed** — policies, tokens, and secrets persist in PostgreSQL.

---

## Troubleshooting

### "connection refused" errors

- Ensure Vault server is running: `ps aux | grep vault`
- Check `VAULT_ADDR` matches listener address in config: `http://127.0.0.1:8200`

### "Vault is sealed" errors

- Unseal Vault: `vault operator unseal "$VAULT_UNSEAL_KEY"`
- Check seal status: `vault status`

### "permission denied" errors

- Verify you're using the ContextForge token (not root token): `vault token lookup`
- Check policy grants correct capabilities: `vault policy read contextforge`

### PostgreSQL connection errors

- Verify PostgreSQL is running: `psql -h localhost -U vault_user -d vault_dev`
- Check connection URL in `~/.vault-config/config.hcl` matches your PostgreSQL credentials
- Ensure `sslmode=disable` for local dev without TLS
- Verify password in config matches the one set in Step 2

### Tokens not persisting

- Confirm you're using the PostgreSQL config, not dev mode (`-dev` flag)
- Check `vault_kv_store` table exists: `psql vault_dev -c "\dt"`

---

## Security Notes (Local Dev)

- **Unseal key**: Stored in `~/.vault-config/keys.txt` (600 permissions). Do not commit.
- **Root token**: Only use for initial setup. Use scoped tokens for applications.
- **TLS disabled**: `tls_disable = 1` is acceptable for local dev. Enable in production.
- **Passwords**: Default password shown here (`password`) is for local dev only.
- **Directory naming**: We use `~/.vault-config` to avoid conflict with Vault's token helper file at `~/.vault-token`.

---

## Next Steps

- For production deployment, see `docs/vault-production-deployment.md`
- Enable TLS with proper certificates
- Use auto-unseal with cloud KMS (AWS, Azure, GCP)
- Configure high-availability PostgreSQL backend
- Implement token rotation policies
- Set up audit logging
