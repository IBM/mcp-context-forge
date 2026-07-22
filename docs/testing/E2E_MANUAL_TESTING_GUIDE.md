# End-to-End Manual Testing Guide
# Pluggable OAuth Token Storage — Database & Vault Backends

This guide covers the complete flow for senior management demo readiness.
Two independent scenarios: **Scenario A** (database backend — default) and **Scenario B** (Vault backend).
Complete Scenario A first to confirm baseline works, then Scenario B for the Vault demo.

---

## Prerequisites

```bash
# 1. Activate virtual environment
source .venv/bin/activate

# 2. Verify all unit tests pass (must be green before manual testing)
pytest tests/unit/mcpgateway/services/test_token_storage_facade.py \
       tests/unit/mcpgateway/services/test_vault_token_backend.py -q
# Expected: all passed, no errors

# 3. Generate your JWT token (keep this — used in every curl command)
export JWT_SECRET=my-test-salt       # must match AUTH_ENCRYPTION_SECRET in .env
export TOKEN=$(python -m mcpgateway.utils.create_jwt_token \
  --username admin@example.com --exp 0 --secret "$JWT_SECRET")
echo "TOKEN=$TOKEN"
```

---

## Scenario A — Database Backend (Default)

### A1. Configure .env

```bash
# In your .env file, set (or verify these are set):
OAUTH_TOKEN_BACKEND=database
MCPGATEWAY_UI_ENABLED=true
MCPGATEWAY_ADMIN_API_ENABLED=true
AUTH_REQUIRED=true
SSRF_ALLOW_LOCALHOST=true
```

### A2. Start ContextForge

```bash
make dev
# Server starts at http://localhost:8000
# Verify startup log shows:
#   Token storage backend: Database
```

### A3. Register an OAuth-protected Gateway

```bash
# Replace token_url and authorization_url with your real OAuth provider
# (GitHub, Google, Keycloak, etc.)
# For demo purposes, use a mock OAuth provider or real one you control.

curl -s -X POST http://localhost:8000/gateways \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "demo-oauth-gateway",
    "url": "http://localhost:9000",
    "auth_type": "oauth",
    "oauth_config": {
      "grant_type": "authorization_code",
      "client_id": "my-client-id",
      "client_secret": "my-client-secret",
      "authorization_url": "https://your-idp.example.com/oauth/authorize",
      "token_url": "https://your-idp.example.com/oauth/token",
      "redirect_uri": "http://localhost:8000/oauth/callback",
      "scopes": ["read", "write"]
    }
  }' | python -m json.tool

# Save the gateway ID from the response
export GATEWAY_ID="<id-from-response>"
echo "GATEWAY_ID=$GATEWAY_ID"
```

### A4. Initiate OAuth Authorization Flow

```bash
# Open this URL in your browser — it will redirect you to the OAuth provider
echo "Open in browser: http://localhost:8000/oauth/authorize/$GATEWAY_ID"
```

**What to verify:**
- Browser redirects to the OAuth provider's login page ✅
- After login, provider redirects back to `http://localhost:8000/oauth/callback` ✅
- ContextForge shows success page: "OAuth Authorization Successful" ✅

### A5. Verify Token was Stored in Database

```bash
# Check token status via API
curl -s http://localhost:8000/oauth/status/$GATEWAY_ID \
  -H "Authorization: Bearer $TOKEN" | python -m json.tool

# Expected response:
# {
#   "status": "valid",          ← token is stored and valid
#   "scopes": [...],
#   "expires_at": "...",
#   "updated_at": "..."
# }
```

### A6. Verify Token Used for Tool Invocation

```bash
# Register a server linked to the OAuth gateway
curl -s -X POST http://localhost:8000/servers \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "demo-server",
    "description": "Demo server for E2E testing"
  }' | python -m json.tool

# Expected: server created with an ID
export SERVER_ID="<id-from-response>"

# Invoke a tool through the gateway — should use stored OAuth token automatically
# (ContextForge fetches token from DB and adds Authorization: Bearer <token> header)
curl -s http://localhost:8000/servers/$SERVER_ID/tools \
  -H "Authorization: Bearer $TOKEN" | python -m json.tool
```

### A7. Verify Token Revocation

```bash
# Admin revoke via DELETE
curl -s -X DELETE "http://localhost:8000/oauth/status/$GATEWAY_ID" \
  -H "Authorization: Bearer $TOKEN"

# Re-check status — should now return 404 or null
curl -s http://localhost:8000/oauth/status/$GATEWAY_ID \
  -H "Authorization: Bearer $TOKEN" | python -m json.tool
# Expected: null or {"status": null}
```

**✅ Scenario A complete — database backend working end to end.**

---

## Scenario B — Vault Backend

### B1. Start Docker / Colima (macOS)

```bash
# macOS only — start Colima if not running
colima start

# Verify Docker is up
docker ps
```

### B2. Start Vault (Dev Mode — fast, in-memory, no unseal needed)

```bash
docker-compose -f docker-compose.vault-test.yml up -d

# Wait for Vault to be ready
sleep 10

# Confirm Vault is healthy
curl -s http://localhost:8200/v1/sys/health | python -m json.tool
# Expected: "initialized": true, "sealed": false

# Confirm authentication works
curl -s -H "X-Vault-Token: test-root-token" \
  http://localhost:8200/v1/auth/token/lookup-self | python -m json.tool
# Expected: 200 OK with token details
```

### B3. Configure .env for Vault Backend

```bash
# Edit .env — change these values:
OAUTH_TOKEN_BACKEND=vault
VAULT_ADDR=http://127.0.0.1:8200
VAULT_TOKEN=test-root-token
VAULT_KV_MOUNT=secret
VAULT_KV_PATH_PREFIX=contextforge/oauth
VAULT_TLS_VERIFY=false
VAULT_TOKEN_CACHE_ENABLED=false
```

### B4. Start ContextForge (Vault mode)

```bash
# Stop any running instance first
pkill -f "uvicorn mcpgateway" 2>/dev/null || true
sleep 2

make dev
# Verify startup log shows:
#   Token storage backend: Vault (addr=http://127.0.0.1:8200)
#   Vault OAuth router included (oauth_token_backend=vault ...)
```

### B5. Register the Same OAuth Gateway

```bash
curl -s -X POST http://localhost:8000/gateways \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "vault-demo-gateway",
    "url": "http://localhost:9000",
    "auth_type": "oauth",
    "oauth_config": {
      "grant_type": "authorization_code",
      "client_id": "my-client-id",
      "client_secret": "my-client-secret",
      "authorization_url": "https://your-idp.example.com/oauth/authorize",
      "token_url": "https://your-idp.example.com/oauth/token",
      "redirect_uri": "http://localhost:8000/vault/callback",
      "scopes": ["read", "write"]
    }
  }' | python -m json.tool

export GATEWAY_ID_VAULT="<id-from-response>"
```

### B6. Register a Virtual Server (for vault/authorize endpoint)

```bash
curl -s -X POST http://localhost:8000/servers \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "vault-demo-server",
    "description": "Vault backend demo server"
  }' | python -m json.tool

export SERVER_ID_VAULT="<id-from-response>"
```

### B7. Initiate OAuth via Vault Endpoint

```bash
# The vault/authorize endpoint takes virtual server ID (not gateway ID)
# This is the NEW endpoint introduced by this feature
echo "Open in browser: http://localhost:8000/vault/authorize/$SERVER_ID_VAULT"
```

**What to verify:**
- Browser redirects to OAuth provider login page ✅
- After login, redirects to `http://localhost:8000/vault/callback` ✅
- ContextForge shows success page: **"Your credentials have been securely stored in Vault"** ✅
  *(This message is different from the DB backend — key demo differentiator)*

### B8. Verify Token is in Vault (Not in Database)

```bash
# Check Vault directly — token should be there
curl -s \
  -H "X-Vault-Token: test-root-token" \
  "http://localhost:8200/v1/secret/data/contextforge/oauth/default" \
  | python -m json.tool
# Expected: KV structure with nested token data

# Confirm it is NOT in the database
sqlite3 mcp.db "SELECT count(*) FROM oauth_tokens WHERE gateway_id = '$GATEWAY_ID_VAULT';"
# Expected: 0  ← nothing in DB, everything is in Vault
```

### B9. Verify Token Used for Tool Invocation (Vault path)

```bash
# Tool invocation should transparently fetch from Vault
curl -s http://localhost:8000/servers/$SERVER_ID_VAULT/tools \
  -H "Authorization: Bearer $TOKEN" | python -m json.tool

# In ContextForge server logs you should see:
#   DEBUG  Cache miss ... fetching from Vault
#   INFO   Vault GET secret/data/contextforge/oauth/...  → 200
```

### B10. Verify Token Revocation Removes from Vault

```bash
# Revoke token
curl -s -X DELETE "http://localhost:8000/oauth/status/$GATEWAY_ID_VAULT" \
  -H "Authorization: Bearer $TOKEN"

# Confirm gone from Vault
curl -s \
  -H "X-Vault-Token: test-root-token" \
  "http://localhost:8200/v1/secret/data/contextforge/oauth/default" \
  | python -m json.tool
# Expected: 404 or empty data
```

### B11. Demonstrate Backend Switch (Key Demo Moment)

This is the headline feature: **switch from database to Vault with a single config change**.

```bash
# 1. Show token count in database (should be > 0 from Scenario A)
sqlite3 mcp.db "SELECT count(*) FROM oauth_tokens;"

# 2. Show tokens currently in Vault (should be > 0 from Scenario B)
curl -s -H "X-Vault-Token: test-root-token" \
  "http://localhost:8200/v1/secret/metadata/contextforge/oauth?list=true" \
  | python -m json.tool

# 3. Change ONE line in .env:
#    OAUTH_TOKEN_BACKEND=database   ← switch back to database
# 4. Restart ContextForge — everything works from DB again, zero code change
make dev
```

**✅ Scenario B complete — Vault backend working end to end.**

---

## Scenario C — Backend Switch with No Downtime (Bonus Demo)

```bash
# Show the audience that switching between backends is purely config-driven
# No code changes, no migration scripts, no data loss on either side

# Step 1: Vault backend active → new tokens go to Vault
OAUTH_TOKEN_BACKEND=vault && make dev
# Authorize a user → token in Vault

# Step 2: Switch to database → new tokens go to DB
OAUTH_TOKEN_BACKEND=database && make dev
# Authorize a user → token in DB

# Step 3: Switch back to Vault → new tokens go to Vault again
# The Vault token from Step 1 is still there — no data loss
```

---

## Integration Test Run (Final Validation Before Demo)

```bash
# Run all automated integration tests against real Vault
# (Vault container must be running from B2 above)
VAULT_ADDR=http://localhost:8200 \
VAULT_TOKEN=test-root-token \
pytest tests/integration/test_vault_integration.py -v

# Expected: 20 passed
# If any fail, DO NOT proceed with demo — investigate first
```

---

## Cleanup After Testing

```bash
# Stop Vault container
docker-compose -f docker-compose.vault-test.yml down

# Reset .env back to database backend
# OAUTH_TOKEN_BACKEND=database

# Clear test data from SQLite
sqlite3 mcp.db "DELETE FROM oauth_tokens; DELETE FROM gateways WHERE name LIKE 'demo%' OR name LIKE 'vault%';"
```

---

## Quick Pre-Demo Checklist

Run through this the morning of the demo:

```
[ ] source .venv/bin/activate
[ ] colima start  (macOS)
[ ] docker-compose -f docker-compose.vault-test.yml up -d
[ ] curl http://localhost:8200/v1/sys/health  → sealed:false
[ ] export TOKEN=$(python -m mcpgateway.utils.create_jwt_token --username admin@example.com --exp 0 --secret my-test-salt)
[ ] OAUTH_TOKEN_BACKEND=database make dev  → startup log: "Token storage backend: Database"
[ ] Run Scenario A steps A3–A5 → confirm DB token stored
[ ] OAUTH_TOKEN_BACKEND=vault make dev    → startup log: "Token storage backend: Vault"
[ ] Run Scenario B steps B5–B8 → confirm Vault token stored, DB count = 0
[ ] pytest tests/integration/test_vault_integration.py -q → 20 passed
[ ] Reset all test data (Cleanup section above)
[ ] Ready for demo ✅
```

---

## Troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| `ValueError: Unknown OAUTH_TOKEN_BACKEND` | Typo in .env | Must be exactly `database` or `vault` |
| `VaultAuthError: VAULT_TOKEN invalid` | Wrong token in .env | Use `test-root-token` for dev |
| `VaultConnectionError: Credential storage unavailable` | Vault container not running | `docker-compose -f docker-compose.vault-test.yml up -d` |
| Vault callback shows wrong team path | user_context not resolved | Fixed in this branch — verify latest code is running |
| Token found in DB when vault backend set | Old instance still running | `pkill -f uvicorn` then restart |
| `colima is not running` (macOS) | Colima stopped | `colima start` |
| OAuth callback 400 Invalid state | State expired (>10 min) | Restart the OAuth flow |
