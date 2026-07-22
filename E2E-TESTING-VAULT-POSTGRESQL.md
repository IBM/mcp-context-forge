# End-to-End Testing Guide: Vault Token Storage with PostgreSQL

**Purpose**: Senior management demo preparation - comprehensive testing of pluggable token storage with HashiCorp Vault backend using PostgreSQL.

**Feature**: OAuth tokens stored in Vault (encrypted at rest), ContextForge metadata in PostgreSQL.

---

## Documentation Structure

This guide integrates with other testing documentation:

1. **Vault Infrastructure Setup** → Use [`docs/vault-local-dev-complete-guide.md`](docs/vault-local-dev-complete-guide.md) (Part A)
   - Comprehensive Vault + PostgreSQL setup
   - Production-like configuration with proper policies
   - Data persists across restarts
   
2. **ContextForge E2E Testing** → This document (below)
   - ContextForge-specific configuration
   - OAuth flow testing with Vault backend
   - Verification steps and demo scenarios

3. **Alternative Quick Testing** → [`docs/testing/E2E_MANUAL_TESTING_GUIDE.md`](docs/testing/E2E_MANUAL_TESTING_GUIDE.md)
   - Docker-based Vault (dev mode, no persistence)
   - Faster setup for quick validation
   - **Note**: Use the complete guide (option 1) for production-like testing with PostgreSQL persistence

---

## Prerequisites Checklist

- [ ] PostgreSQL installed and running (`psql --version`)
- [ ] Vault CLI installed (`vault version`)
- [ ] ContextForge repository cloned and dependencies installed
- [ ] **Complete Vault setup** using [`docs/vault-local-dev-complete-guide.md`](docs/vault-local-dev-complete-guide.md) Part A (Steps 1-12)
- [ ] `.env` file configured (see Part 2 below)

---

## Part 1: Infrastructure Setup

**IMPORTANT**: Instead of duplicating Vault setup here, follow the comprehensive guide:

👉 **[`docs/vault-local-dev-complete-guide.md`](docs/vault-local-dev-complete-guide.md) — Part A (Steps 1-12)**

That guide provides:
- PostgreSQL database setup for Vault storage
- Vault server configuration with PostgreSQL backend
- Proper initialization and unsealing
- Scoped policies and tokens
- Verification steps

**Once you complete Part A of that guide, return here for ContextForge-specific configuration.**

### 1.1 PostgreSQL Setup for ContextForge

**Architecture Note**: 

In **production**, you would have:
- **Vault PostgreSQL**: Separate database/server for Vault's encrypted storage backend
- **ContextForge PostgreSQL**: Separate database/server for ContextForge metadata (gateways, tools, etc.)

For **local testing**, we use the **same PostgreSQL server** with **two separate databases**:
- `vault_dev` - Vault's KV storage (created in vault-local-dev-complete-guide.md)
- `contextforge_dev` - ContextForge metadata (created below)

This simulates the production architecture while simplifying local setup.

```
Production Architecture:
┌─────────────────────┐           ┌─────────────────────┐
│  Vault PostgreSQL   │           │ ContextForge PG     │
│  (Separate Server)  │           │ (Separate Server)   │
│                     │           │                     │
│  vault_prod DB      │           │  contextforge_prod  │
│  - vault_kv_store   │           │  - gateways         │
│                     │           │  - tools            │
└─────────────────────┘           │  - users            │
                                  │  - servers          │
                                  └─────────────────────┘

Local Testing (Simplified):
┌──────────────────────────────────────────────────────┐
│       Single PostgreSQL Server (localhost:5432)      │
│                                                       │
│  ┌──────────────────┐    ┌─────────────────────┐    │
│  │  vault_dev       │    │ contextforge_dev    │    │
│  │  - vault_kv_store│    │ - gateways          │    │
│  │  (OAuth tokens)  │    │ - tools             │    │
│  │                  │    │ - users             │    │
│  │  vault_user      │    │ - servers           │    │
│  │                  │    │                     │    │
│  └──────────────────┘    │ contextforge_user   │    │
│                          └─────────────────────┘    │
└──────────────────────────────────────────────────────┘
```

**Key Point**: Even in local testing, OAuth tokens are **never** in `contextforge_dev.oauth_tokens` — they're encrypted in `vault_dev.vault_kv_store`. The `oauth_tokens` table in ContextForge is only used when `OAUTH_TOKEN_BACKEND=database` (not this test).

---

**Note**: If you followed the complete guide above, you already have PostgreSQL running. Now create the ContextForge database:

```bash
# Connect to PostgreSQL
psql postgres

# Create ContextForge database (separate from vault_dev)
CREATE DATABASE contextforge_dev;
CREATE USER contextforge_user WITH ENCRYPTED PASSWORD 'cf_password123';  # pragma: allowlist secret
GRANT ALL PRIVILEGES ON DATABASE contextforge_dev TO contextforge_user;
GRANT ALL ON SCHEMA public TO contextforge_user;
ALTER DATABASE contextforge_dev OWNER TO contextforge_user;
\q
```

**Verify**:
```bash
psql -h localhost -U contextforge_user -d contextforge_dev -c "SELECT version();"
# Should connect without errors

# Verify you now have TWO separate databases
psql postgres -c "\l" | grep -E "vault_dev|contextforge_dev"
# Expected:
#   contextforge_dev | contextforge_user | ...
#   vault_dev        | vault_user        | ...
```

### 1.2 Quick Vault Status Check

If you completed the Vault setup guide, verify Vault is ready:

```bash
# Load your Vault credentials
source ~/.vault-config/keys.txt
export VAULT_ADDR="http://127.0.0.1:8200"

# Check Vault is unsealed and running
vault status | grep Sealed
# Expected: Sealed          false

# Verify your ContextForge token works
export VAULT_TOKEN="$VAULT_CF_TOKEN"
vault token lookup
# Should show: policies [contextforge default]
```

**If Vault is not running or sealed**, refer back to [`docs/vault-local-dev-complete-guide.md`](docs/vault-local-dev-complete-guide.md) Steps 5-7.

---

## Part 2: ContextForge Configuration (5 minutes)

### 2.1 Configure `.env` File

```bash
cd /Users/rakhidutta/mcp-context-forge

# Backup existing .env
cp .env .env.backup

# Load Vault token from the complete guide setup
source ~/.vault-config/keys.txt

# Update .env with the following settings
cat >> .env <<EOF

# ============================================
# Vault Token Storage Configuration
# ============================================

# OAuth token storage backend
OAUTH_TOKEN_BACKEND=vault

# Vault connection (using token from vault-local-dev-complete-guide.md)
VAULT_ADDR=http://127.0.0.1:8200
VAULT_TOKEN=$VAULT_CF_TOKEN
VAULT_KV_MOUNT=secret
VAULT_KV_PATH_PREFIX=contextforge/oauth

# Vault settings
VAULT_TLS_VERIFY=false
VAULT_TOKEN_CACHE_ENABLED=true
VAULT_TOKEN_CACHE_TTL=300
VAULT_TOKEN_CACHE_MAX_SIZE=1000

# ============================================
# PostgreSQL Configuration for ContextForge
# ============================================

DATABASE_URL=postgresql+psycopg://contextforge_user:cf_password123@localhost:5432/contextforge_dev

# ============================================
# OAuth & Authentication
# ============================================

AUTH_REQUIRED=true
JWT_SECRET_KEY=your-jwt-secret-key-for-testing-minimum-32-chars
AUTH_ENCRYPTION_SECRET=your-auth-encryption-secret-32-chars-min

# ============================================
# Feature Flags
# ============================================

MCPGATEWAY_ADMIN_API_ENABLED=true
MCPGATEWAY_UI_ENABLED=true

EOF
```

### 2.2 Verify Configuration

```bash
# Check that all required env vars are set
grep -E "OAUTH_TOKEN_BACKEND|VAULT_ADDR|VAULT_TOKEN|DATABASE_URL" .env

# Expected output should show:
#   OAUTH_TOKEN_BACKEND=vault
#   VAULT_ADDR=http://127.0.0.1:8200
#   VAULT_TOKEN=hvs.CAE...
#   DATABASE_URL=postgresql+psycopg://...
```

---

## Part 3: Pre-Flight Verification (5 minutes)

### 3.1 Test Vault Connectivity

```bash
# Switch to ContextForge token
source ~/.vault-config/keys.txt
export VAULT_ADDR="http://127.0.0.1:8200"
export VAULT_TOKEN="$VAULT_CF_TOKEN"

# Verify token works
vault token lookup
# Should show: policies [contextforge default]
```

### 3.2 Test Vault Write/Read

This test uses the **correct ContextForge payload structure** with nested `token` object and proper path format from [`vault-local-dev-complete-guide.md`](docs/vault-local-dev-complete-guide.md) Part B.

**Composite Key Demo**: We'll store a token uniquely identified by `(team_id, mcp_url, email)`:

```bash
# Define the composite key components
TEST_TEAM_ID="default"
TEST_MCP_URL="http://localhost:9000"
TEST_EMAIL="test@example.com"

# Calculate server_id_hash for path (SHA-256 first 8 hex chars of the MCP URL)
SERVER_ID_HASH=$(echo -n "$TEST_MCP_URL" | shasum -a 256 | cut -c1-8)
echo "Composite Key Components:"
echo "  team_id:        $TEST_TEAM_ID"
echo "  mcp_url:        $TEST_MCP_URL"
echo "  server_id_hash: $SERVER_ID_HASH"  # Should be: a1b4e82c
echo "  email:          $TEST_EMAIL (encoded: test%40example.com)"

# Write test secret using HTTP API (vault kv put cannot handle nested objects)
curl -s -X POST \
  -H "X-Vault-Token: $VAULT_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "data": {
      "email":      "test@example.com",
      "team_id":    "default",
      "mcp_url":    "'"$TEST_MCP_URL"'",
      "token": {
        "access_token":  "test_access_token_123",
        "refresh_token": "test_refresh_token_456",
        "scopes":        ["read", "write"]
      },
      "user_id":    "test_user_id",
      "token_type": "Bearer",
      "expires_at": "2026-07-09T18:00:00Z",
      "created_at": "2026-07-09T10:00:00Z",
      "updated_at": "2026-07-09T10:00:00Z"
    }
  }' \
  "${VAULT_ADDR}/v1/secret/data/contextforge/oauth/default/${SERVER_ID_HASH}/test%40example.com" \
  | jq .

# Read it back using HTTP API to verify nested structure
echo -e "\n=== Reading back the secret ==="
curl -s \
  -H "X-Vault-Token: $VAULT_TOKEN" \
  "${VAULT_ADDR}/v1/secret/data/contextforge/oauth/default/${SERVER_ID_HASH}/test%40example.com" \
  | jq '.data.data'

# Expected output should show nested token object:
# {
#   "email": "test@example.com",
#   "team_id": "default",
#   "mcp_url": "http://localhost:9000",
#   "token": {
#     "access_token": "test_access_token_123",
#     "refresh_token": "test_refresh_token_456",
#     "scopes": ["read", "write"]
#   },
#   ...
# }

# List tokens in the test path
echo -e "\n=== Listing tokens ==="
vault kv list secret/contextforge/oauth/default/${SERVER_ID_HASH}

# Clean up
echo -e "\n=== Cleaning up ==="
vault kv delete secret/contextforge/oauth/default/${SERVER_ID_HASH}/test%40example.com
```

**Expected**: 
- Write returns `"version": 1` 
- Read shows nested `token` object intact
- List shows `test%40example.com`
- Delete succeeds without errors

**Path Structure Explanation**:
```
secret/data/contextforge/oauth/<team_id>/<server_id_hash>/<url-encoded-email>
                                 ↓         ↓                ↓
                                 default   a1b4e82c         test%40example.com
```

See [`vault-local-dev-complete-guide.md`](docs/vault-local-dev-complete-guide.md) Part B for detailed path derivation and payload schema.

### 3.3 Initialize ContextForge Database

```bash
cd /Users/rakhidutta/mcp-context-forge

# Run migrations
cd mcpgateway && alembic upgrade head && cd ..

# Verify tables created
psql -h localhost -U contextforge_user -d contextforge_dev -c "\dt" | grep -E "gateways|oauth_tokens|users"
```

---

## Part 4: ContextForge Startup (5 minutes)

### 4.1 Start ContextForge

```bash
cd /Users/rakhidutta/mcp-context-forge

# Start development server
make dev

# Watch for these log lines:
# ✓ Token storage backend: Vault (addr=http://127.0.0.1:8200)
# ✓ Database connection: PostgreSQL (contextforge_dev)
```

**Critical Success Indicators**:
- No connection errors to Vault
- No connection errors to PostgreSQL
- Server starts on port 4444 (or configured port)

### 4.2 Verify Startup Logs

```bash
# In the make dev output, look for:
# - "Token storage backend: Vault"
# - "VAULT_ADDR" shown in startup config
# - No "VaultConnectionError" or "VaultAuthError"
```

---

## Part 5: End-to-End OAuth Flow Testing (20-30 minutes)

**Important**: This section uses the correct ContextForge Vault payload structure with:
- **Nested `token` object** (not flat fields)
- **Correct path format**: `secret/data/contextforge/oauth/<team_id>/<server_id_hash>/<url-encoded-email>`
- **`server_id_hash`**: First 8 hex chars of SHA-256 hash of the gateway MCP URL

### Composite Lookup Key

Every OAuth token is uniquely identified by **three fields** (composite key):

| Field | Role in Lookup | Example Value |
|-------|----------------|---------------|
| **`team_id`** | Team/tenant isolation | `default`, `engineering`, `sales` |
| **`mcp_url`** | Gateway/system identifier (hashed to `server_id_hash`) | `http://localhost:9000` |
| **`email`** | User identity (URL-encoded in path) | `admin@example.com` → `admin%40example.com` |

**How tokens are retrieved:**

```python
# ContextForge uses these three fields to build the Vault path
team_id = "default"                          # From JWT/session
mcp_url = "http://localhost:9000"            # From gateway record
email = "admin@example.com"                  # From JWT/session

# Derive path components
server_id_hash = sha256(mcp_url)[:8]         # a1b4e82c
encoded_email = urllib.parse.quote(email)    # admin%40example.com

# Final Vault path
path = f"secret/data/contextforge/oauth/{team_id}/{server_id_hash}/{encoded_email}"
#      → secret/data/contextforge/oauth/default/a1b4e82c/admin%40example.com
```

**Why `mcp_url` is stored in the payload:**
1. **Verification** - Confirms you retrieved the token for the correct upstream system
2. **Vault UI** - Shows which MCP server the token is for (human-readable)
3. **Portability** - Token payload is self-describing without needing the database

**Visual Lookup Flow:**

```
User Request: "Alice from engineering team wants to call tools on http://localhost:9000"
                                    ↓
    ┌───────────────────────────────────────────────────────────────┐
    │ Composite Key Components (from JWT + Gateway record)          │
    │ ① team_id:  "engineering"                                     │
    │ ② mcp_url:  "http://localhost:9000"  → hash → "a1b4e82c"     │
    │ ③ email:    "alice@acme.com"         → encode → "alice%40..." │
    └───────────────────────────────────────────────────────────────┘
                                    ↓
    ┌───────────────────────────────────────────────────────────────┐
    │ Vault Path Construction                                        │
    │ secret/data/contextforge/oauth/engineering/a1b4e82c/alice%40..│
    └───────────────────────────────────────────────────────────────┘
                                    ↓
    ┌───────────────────────────────────────────────────────────────┐
    │ Retrieved Payload (nested token object)                       │
    │ {                                                              │
    │   "email": "alice@acme.com",         ← matches lookup key     │
    │   "team_id": "engineering",          ← matches lookup key     │
    │   "mcp_url": "http://localhost:9000",← matches lookup key     │
    │   "token": {                                                   │
    │     "access_token": "gho_Aa1Bb2...",                           │
    │     "refresh_token": "ghr_Rr9Ss8...",                          │
    │     "scopes": ["repo", "read:user"]                            │
    │   },                                                           │
    │   "expires_at": "2026-07-07T18:00:00Z",                        │
    │   ...                                                          │
    │ }                                                              │
    └───────────────────────────────────────────────────────────────┘
```

See [`vault-local-dev-complete-guide.md`](docs/vault-local-dev-complete-guide.md) Part B for detailed schema and path derivation.

---

### 5.1 Create JWT Token for API Access

```bash
export JWT_SECRET_KEY="your-jwt-secret-key-for-testing-minimum-32-chars"

export MCPGATEWAY_BEARER_TOKEN=$(python -m mcpgateway.utils.create_jwt_token \
  --username admin@example.com \
  --exp 10080 \
  --secret "$JWT_SECRET_KEY")

echo "Bearer Token: $MCPGATEWAY_BEARER_TOKEN"
```

### 5.2 Register an OAuth-Enabled Gateway

Create a test OAuth gateway registration:

```bash
curl -X POST http://localhost:4444/gateways \
  -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "test-oauth-gateway",
    "url": "http://localhost:9000/sse",
    "transport": "sse",
    "description": "Test OAuth gateway with Vault storage",
    "auth_type": "oauth",
    "oauth_config": {
      "grant_type": "authorization_code",
      "client_id": "test_client_id",
      "client_secret": "test_client_secret",
      "authorization_url": "https://accounts.google.com/o/oauth2/v2/auth",
      "token_url": "https://oauth2.googleapis.com/token",
      "redirect_uri": "http://localhost:4444/oauth/callback",
      "scopes": ["openid", "email", "profile"]
    }
  }'

# Save the gateway ID from response
# Example response: {"id": "550e8400-e29b-41d4-a716-446655440000", ...}
export GATEWAY_ID="<paste-gateway-id-here>"
```

### 5.3 Test OAuth Authorization Initiation

```bash
# Initiate OAuth flow
curl -i -X GET "http://localhost:4444/oauth/authorize/$GATEWAY_ID" \
  -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN"

# Expected: 302 redirect to Google OAuth consent page
# Look for: Location: https://accounts.google.com/o/oauth2/v2/auth?...
```

### 5.4 Simulate OAuth Callback (Manual Token Storage)

Since we can't complete a real OAuth flow in CLI, we'll manually store tokens to test the Vault backend using the **correct ContextForge payload structure**:

```bash
# Get the gateway's MCP URL for Vault path construction
GATEWAY_URL=$(curl -s "http://localhost:4444/gateways/$GATEWAY_ID" \
  -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN" | jq -r '.url')

echo "Gateway URL: $GATEWAY_URL"

# Compute server_id_hash (SHA-256 first 8 hex chars of gateway URL)
SERVER_ID_HASH=$(echo -n "$GATEWAY_URL" | shasum -a 256 | cut -c1-8)
echo "Server ID Hash: $SERVER_ID_HASH"

# Get current timestamp
TIMESTAMP=$(date -u +%Y-%m-%dT%H:%M:%SZ)

# Manually store test tokens in Vault using HTTP API (nested token object)
# This simulates what ContextForge writes during OAuth callback
curl -s -X POST \
  -H "X-Vault-Token: $VAULT_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "data": {
      "email":      "admin@example.com",
      "team_id":    "default",
      "mcp_url":    "'"$GATEWAY_URL"'",
      "token": {
        "access_token":  "ya29.test_access_token_simulated",
        "refresh_token": "1//test_refresh_token_simulated",
        "scopes":        ["openid", "email", "profile"]
      },
      "user_id":    "test_user_id_12345",
      "token_type": "Bearer",
      "expires_at": "2026-07-09T18:00:00Z",
      "created_at": "'"$TIMESTAMP"'",
      "updated_at": "'"$TIMESTAMP"'"
    }
  }' \
  "${VAULT_ADDR}/v1/secret/data/contextforge/oauth/default/${SERVER_ID_HASH}/admin%40example.com" \
  | jq '.'

echo -e "\n✓ Token stored in Vault with correct nested structure"
```

### 5.5 Verify Token Stored in Vault

```bash
# Read the token back from Vault using HTTP API to see nested structure
curl -s \
  -H "X-Vault-Token: $VAULT_TOKEN" \
  "${VAULT_ADDR}/v1/secret/data/contextforge/oauth/default/${SERVER_ID_HASH}/admin%40example.com" \
  | jq '.data.data'

# Expected output (nested token object):
# {
#   "created_at": "2026-07-09T10:00:00Z",
#   "email": "admin@example.com",
#   "expires_at": "2026-07-09T18:00:00Z",
#   "mcp_url": "http://localhost:9000/sse",
#   "team_id": "default",
#   "token": {
#     "access_token": "ya29.test_access_token_simulated",
#     "refresh_token": "1//test_refresh_token_simulated",
#     "scopes": ["openid", "email", "profile"]
#   },
#   "token_type": "Bearer",
#   "updated_at": "2026-07-09T10:00:00Z",
#   "user_id": "test_user_id_12345"
# }

# Alternative: Use vault CLI for simpler view (flattens nested objects)
vault kv get "secret/contextforge/oauth/default/${SERVER_ID_HASH}/admin%40example.com"
```

### 5.6 Verify PostgreSQL Does NOT Store Tokens

```bash
# Check oauth_tokens table (should be empty or not contain our test token)
psql -h localhost -U contextforge_user -d contextforge_dev -c "SELECT COUNT(*) FROM oauth_tokens WHERE gateway_id = '$GATEWAY_ID';"

# Expected: count = 0 (tokens are in Vault, not PostgreSQL)
```

### 5.7 Test Token Retrieval via API

```bash
# Trigger a gateway connection that uses the stored OAuth token
# This will call token_storage_service.get_user_token() internally
curl -X POST "http://localhost:4444/gateways/$GATEWAY_ID/tools/fetch" \
  -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN" \
  -H "Content-Type: application/json"

# Expected behavior:
#   - ContextForge retrieves token from Vault
#   - Attempts to connect to gateway with OAuth token
#   - May fail connection (since gateway isn't real), but should show:
#     "Using decrypted OAuth token for gateway test-oauth-gateway" in logs
```

### 5.8 Check ContextForge Logs

```bash
# Look for these log messages in your make dev terminal:
# - "Token storage backend: Vault"
# - "Using decrypted OAuth token for gateway test-oauth-gateway"
# - No "Failed to retrieve token from Vault" errors
```

### 5.9 Test Token Listing

```bash
# List all tokens for the gateway (use server_id_hash from 5.4)
vault kv list "secret/contextforge/oauth/default/${SERVER_ID_HASH}"

# Expected output:
# Keys
# ----
# admin%40example.com
```

### 5.10 Test Token Revocation

```bash
# Delete the token
vault kv delete "secret/contextforge/oauth/default/${SERVER_ID_HASH}/admin%40example.com"

# Verify deletion using HTTP API
curl -s \
  -H "X-Vault-Token: $VAULT_TOKEN" \
  "${VAULT_ADDR}/v1/secret/data/contextforge/oauth/default/${SERVER_ID_HASH}/admin%40example.com" \
  | jq '.data'

# Expected: null (token has been deleted)

# Or verify with vault CLI
vault kv get "secret/contextforge/oauth/default/${SERVER_ID_HASH}/admin%40example.com"
# Expected: "No value found at secret/data/..."
```

---

## Part 6: Verify PostgreSQL Persistence (5 minutes)

This section confirms the **separation of concerns**: gateway metadata in ContextForge DB, OAuth tokens in Vault's DB.

### 6.1 Check ContextForge PostgreSQL for Gateway Metadata (✓ Should Exist)

```bash
# Verify gateway metadata is in ContextForge database
psql -h localhost -U contextforge_user -d contextforge_dev -c "
SELECT id, name, url, auth_type, transport 
FROM gateways 
WHERE id = '$GATEWAY_ID';"

# Expected: Shows the gateway record with oauth_config
```

### 6.2 Verify OAuth Tokens are NOT in ContextForge Database (✗ Should Be Empty)

```bash
# CRITICAL CHECK: Confirm oauth_tokens table is empty (tokens are in Vault, not here)
psql -h localhost -U contextforge_user -d contextforge_dev -c "
SELECT COUNT(*) AS token_count 
FROM oauth_tokens 
WHERE gateway_id = '$GATEWAY_ID';"

# Expected: token_count = 0
# (If > 0, you're not using Vault backend - check OAUTH_TOKEN_BACKEND in .env)
```

### 6.3 Verify OAuth Tokens ARE in Vault's PostgreSQL Storage (✓ Should Exist)

```bash
# Verify Vault stored our tokens in its own PostgreSQL database
psql -h localhost -U vault_user -d vault_dev -c "
SELECT COUNT(*) AS vault_entries
FROM vault_kv_store 
WHERE path LIKE '%contextforge/oauth%';"

# Expected: vault_entries > 0 (Vault's encrypted storage)

# Optional: See the encrypted storage structure (don't try to read 'value' - it's encrypted binary)
psql -h localhost -U vault_user -d vault_dev -c "
SELECT 
  substring(parent_path from 1 for 60) as parent_path_preview,
  substring(path from 1 for 80) as path_preview,
  length(value) as encrypted_bytes
FROM vault_kv_store 
WHERE path LIKE '%contextforge/oauth%'
LIMIT 5;"
```

**Summary Verification**:
```
✓ Gateway metadata     → contextforge_dev.gateways       (ContextForge DB)
✗ OAuth tokens         → contextforge_dev.oauth_tokens   (EMPTY - correct!)
✓ OAuth tokens         → vault_dev.vault_kv_store        (Vault DB - encrypted)
```

---

## Part 7: Restart Persistence Test (5 minutes)

### 7.1 Restart ContextForge

```bash
# Stop ContextForge (Ctrl+C in make dev terminal)

# Restart
make dev

# Verify logs show:
# - "Token storage backend: Vault"
# - No errors connecting to Vault or PostgreSQL
```

### 7.2 Verify Gateway Still Exists

```bash
curl -s "http://localhost:4444/gateways/$GATEWAY_ID" \
  -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN" | jq '.name'

# Expected: "test-oauth-gateway"
```

### 7.3 Restart Vault (Unseal Test)

```bash
# Stop Vault (Ctrl+C in vault server terminal)

# Restart Vault
vault server -config=$HOME/.vault-config/config.hcl

# Unseal in new terminal
source ~/.vault-config/keys.txt
export VAULT_ADDR="http://127.0.0.1:8200"
vault operator unseal "$VAULT_UNSEAL_KEY"

# Verify data persisted
vault kv list secret/contextforge/oauth/
# Should show the same paths as before restart
```

---

## Part 8: Performance & Cache Testing (Optional, 10 minutes)

### 8.1 Enable Vault Token Cache

Already enabled in `.env`:
```
VAULT_TOKEN_CACHE_ENABLED=true
VAULT_TOKEN_CACHE_TTL=300
```

### 8.2 Test Cache Hit

```bash
# Get current timestamp
TIMESTAMP=$(date -u +%Y-%m-%dT%H:%M:%SZ)

# Store a token using correct nested structure
curl -s -X POST \
  -H "X-Vault-Token: $VAULT_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "data": {
      "email":      "cache-test@example.com",
      "team_id":    "default",
      "mcp_url":    "'"$GATEWAY_URL"'",
      "token": {
        "access_token":  "cached_token_123",
        "refresh_token": "refresh_cached_456",
        "scopes":        ["read"]
      },
      "user_id":    "cache_test_user",
      "token_type": "Bearer",
      "expires_at": "2026-07-09T18:00:00Z",
      "created_at": "'"$TIMESTAMP"'",
      "updated_at": "'"$TIMESTAMP"'"
    }
  }' \
  "${VAULT_ADDR}/v1/secret/data/contextforge/oauth/default/${SERVER_ID_HASH}/cache-test%40example.com" \
  | jq '.'

# First call (cache miss - will fetch from Vault)
curl -X POST "http://localhost:4444/gateways/$GATEWAY_ID/tools/fetch" \
  -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN"

# Second call within 300s (cache hit - no Vault call)
curl -X POST "http://localhost:4444/gateways/$GATEWAY_ID/tools/fetch" \
  -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN"

# Check logs for cache hit message (if enabled)
```

---

## Part 9: Cleanup (5 minutes)

### 9.1 Remove Test Tokens

```bash
# List all test tokens (use server_id_hash from testing)
vault kv list secret/contextforge/oauth/default/${SERVER_ID_HASH}

# Delete test tokens (using URL-encoded email addresses)
vault kv delete "secret/contextforge/oauth/default/${SERVER_ID_HASH}/admin%40example.com"
vault kv delete "secret/contextforge/oauth/default/${SERVER_ID_HASH}/cache-test%40example.com"

# Verify cleanup
vault kv list secret/contextforge/oauth/default/${SERVER_ID_HASH}
# Expected: "No value found" or empty list
```

### 9.2 Remove Test Gateway

```bash
curl -X DELETE "http://localhost:4444/gateways/$GATEWAY_ID" \
  -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN"
```

### 9.3 Optional: Full Cleanup

```bash
# Stop ContextForge
# Stop Vault

# Drop databases (CAUTION: This deletes all data)
psql postgres -c "DROP DATABASE contextforge_dev;"
psql postgres -c "DROP DATABASE vault_dev;"
```

---

## Success Criteria Checklist for Demo

### Infrastructure
- [ ] PostgreSQL running without errors
- [ ] Vault server running and unsealed
- [ ] ContextForge connects to both Vault and PostgreSQL

### Token Storage
- [ ] OAuth tokens stored in Vault (verified with `vault kv get`)
- [ ] OAuth tokens NOT in PostgreSQL oauth_tokens table
- [ ] Gateway metadata stored in PostgreSQL gateways table
- [ ] Tokens persist across ContextForge restarts
- [ ] Tokens persist across Vault restarts (unseal required)

### OAuth Flow
- [ ] Gateway registration with oauth_config succeeds
- [ ] OAuth authorization initiation returns 302 redirect
- [ ] Manual token storage in Vault succeeds
- [ ] Token retrieval from Vault succeeds
- [ ] Token revocation from Vault succeeds

### Observability
- [ ] Startup logs show "Token storage backend: Vault"
- [ ] No VaultConnectionError or VaultAuthError in logs
- [ ] Token operations logged appropriately

---

## Demo Talking Points

### Architecture Benefits
1. **Separation of Concerns**: 
   - OAuth tokens (sensitive) → Vault (encrypted at rest)
   - Gateway metadata (non-sensitive) → PostgreSQL (relational integrity)

2. **Security**:
   - Vault encrypts tokens at rest
   - ContextForge never sees unencrypted tokens in its DB
   - Scoped Vault policies limit ContextForge access

3. **Scalability**:
   - Vault KV v2 supports versioning and metadata
   - PostgreSQL handles high-volume gateway operations
   - Cache layer reduces Vault API calls

4. **Operational Excellence**:
   - Vault token rotation without ContextForge downtime
   - PostgreSQL backup/restore for gateway config
   - Independent scaling of storage backends

### Risk Mitigation
- Vault unavailable? ContextForge degrades gracefully (OAuth flows fail, but core operations continue)
- PostgreSQL unavailable? ContextForge can't start (by design - need gateway metadata)
- Token cache reduces Vault dependency for read-heavy workloads

---

## Troubleshooting Reference

### "Vault is sealed"
```bash
vault operator unseal "$VAULT_UNSEAL_KEY"
```

### "connection refused" to Vault
```bash
# Check if Vault is running
ps aux | grep vault
# Restart if needed
vault server -config=$HOME/.vault-config/config.hcl
```

### "permission denied" from Vault
```bash
# Verify using ContextForge token (not root)
vault token lookup
# Should show: policies [contextforge default]
```

### ContextForge can't connect to PostgreSQL
```bash
# Verify DATABASE_URL in .env
grep DATABASE_URL .env

# Test connection manually
psql -h localhost -U contextforge_user -d contextforge_dev -c "SELECT 1;"
```

---

## Documentation References

### Primary References (Use These)
- **Vault + PostgreSQL Setup**: [`docs/vault-local-dev-complete-guide.md`](docs/vault-local-dev-complete-guide.md) — Production-like setup with persistence
- **This Document**: End-to-end ContextForge testing with Vault backend

### Alternative Quick Testing
- **Docker-based Vault Testing**: [`docs/testing/E2E_MANUAL_TESTING_GUIDE.md`](docs/testing/E2E_MANUAL_TESTING_GUIDE.md) — Fast dev-mode setup (no persistence)

### Related Documentation
- **OAuth Configuration**: `docs/docs/manage/oauth.md`
- **Troubleshooting**: `docs/docs/manage/oauth-troubleshooting.md`
- **Architecture**: `docs/docs/architecture/oauth-design.md`

---

## Testing Path Summary

```
┌─────────────────────────────────────────────────────────────┐
│ Goal: Test ContextForge with Vault + PostgreSQL            │
└─────────────────────────────────────────────────────────────┘
                            │
                            ▼
    ┌───────────────────────────────────────────────┐
    │ Option 1: Production-like with Persistence    │
    │ (Recommended for this test)                   │
    └───────────────────────────────────────────────┘
                            │
            ┌───────────────┴───────────────┐
            ▼                               ▼
    [vault-local-dev-      [This Document:
     complete-guide.md]     E2E-TESTING-VAULT-
     Part A (Steps 1-12)    POSTGRESQL.md]
     ↓                      ↓
     Vault + PG setup       ContextForge config
                            + Testing
```

```
┌─────────────────────────────────────────────────────────────┐
│ Alternative: Quick Docker Testing (No Persistence)          │
└─────────────────────────────────────────────────────────────┘
                            │
                            ▼
            [E2E_MANUAL_TESTING_GUIDE.md]
            Scenario B (Docker Vault)
            ↓
            Fast validation only
```

---

**Estimated Total Time**: 
- **With vault-local-dev-complete-guide.md**: 60-75 minutes (includes Vault setup)
- **Vault already set up**: 30-40 minutes (ContextForge testing only)
- **Minimum Demo Time**: 20 minutes (Parts 4-5 only)

Good luck with your senior management demo! 🚀
