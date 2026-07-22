# ContextForge — Vault Local Development: Complete Guide

This guide covers the full local Vault setup with PostgreSQL storage **and** the exact
secret payload shape ContextForge writes, including path derivation from the client's
virtual server URL.

> **Architecture reference:** See
> `file:///Users/rakhidutta/mcp-context-forge/contextforge-pluggable-token-storage-architect-design-document.html`
> — in particular §3 (Client Access Model), §7 (Vault Secret Schema), and §8 (Authorization Endpoints).

## Prerequisites

- PostgreSQL running locally (e.g., via Homebrew or Docker)
- Vault CLI installed
- ContextForge repository with PostgreSQL configured

---

## Part A — Vault Setup

### Step 1 — Install Vault CLI

```bash
# macOS (Homebrew)
brew tap hashicorp/tap
brew install hashicorp/tap/vault

# Verify installation
vault version
# Expected: Vault v1.17.x or later
```

---

### Step 2 — Set up PostgreSQL database for Vault

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

### Step 3 — Create Vault server configuration

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

### Step 4 — Create PostgreSQL storage table

Before starting Vault, create the storage table manually to avoid initialization loops:

```bash
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

### Step 5 — Start Vault server

```bash
# Start Vault with the PostgreSQL config
vault server -config=$HOME/.vault-config/config.hcl

# Server starts on http://127.0.0.1:8200
# Keep this terminal open — server runs in foreground
```

---

### Step 6 — Initialize Vault (first time only)

Open a **new terminal** and initialize Vault:

```bash
export VAULT_ADDR="http://127.0.0.1:8200"

vault operator init -key-shares=1 -key-threshold=1

# Output:
# Unseal Key 1: <UNSEAL_KEY>
# Initial Root Token: <ROOT_TOKEN>
```

Save the output:

```bash
cat > ~/.vault-config/keys.txt <<EOF
VAULT_UNSEAL_KEY=<paste-unseal-key-here>
VAULT_ROOT_TOKEN=<paste-root-token-here>
EOF

chmod 600 ~/.vault-config/keys.txt
```

---

### Step 7 — Unseal Vault

```bash
source ~/.vault-config/keys.txt
vault operator unseal "$VAULT_UNSEAL_KEY"

# Expected: Sealed: false
```

**Note**: Unseal after **every restart**. In production, use auto-unseal with a cloud KMS.

---

### Step 8 — Authenticate with root token

```bash
source ~/.vault-config/keys.txt
export VAULT_TOKEN="$VAULT_ROOT_TOKEN"

vault token lookup
# Should show token info without errors
```

---

### Step 9 — Enable KV v2 secrets engine

```bash
vault secrets enable -version=2 -path=secret kv

vault secrets list
# Should show:  secret/   kv   kv_2   ...
```

---

### Step 10 — Create ContextForge Vault policy

```bash
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

vault policy write contextforge ~/.vault-config/contextforge-policy.hcl

vault policy read contextforge
```

---

### Step 11 — Create scoped token for ContextForge

```bash
vault token create \
  -policy="contextforge" \
  -display-name="contextforge-dev" \
  -ttl="720h" \
  -format=json | jq -r '.auth.client_token'

# Copy the printed token — this is your VAULT_TOKEN for ContextForge
# Example: hvs.CAESIJx...  (starts with hvs.)
```

Save it:

```bash
echo "VAULT_CF_TOKEN=<paste-token-here>" >> ~/.vault-config/keys.txt
```

---

### Step 12 — Smoke test Vault setup (Optional but Recommended)

```bash
source ~/.vault-config/keys.txt
export VAULT_TOKEN="$VAULT_CF_TOKEN"

vault token lookup
# Should show: policies [contextforge default]  (not [root])
```

```bash
vault kv put secret/contextforge/oauth/test-server/testuser@example.com \
  mcp_url="http://localhost:9000" \
  access_token="test_access_abc123" \
  refresh_token="test_refresh_xyz789" \
  token_type="bearer" \
  expires_in="3600"

vault kv get secret/contextforge/oauth/test-server/testuser@example.com

vault kv list secret/contextforge/oauth/test-server

vault kv delete secret/contextforge/oauth/test-server/testuser@example.com
```

**✅ If all commands above work, Vault is ready for ContextForge integration.**

### Verify PostgreSQL Storage (Optional)

```bash
psql vault_dev -U vault_user -c "SELECT COUNT(*) FROM vault_kv_store;"

vault kv put secret/contextforge/oauth/verify-test/newuser@example.com \
  mcp_url="http://localhost:9002" \
  access_token="verify_token_abc"

psql vault_dev -U vault_user -c "SELECT COUNT(*) FROM vault_kv_store;"
# Count should increase by 2-3 rows

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

vault kv delete secret/contextforge/oauth/verify-test/newuser@example.com
```

**✅ PostgreSQL verification complete!**

---

### Step 13 — Configure ContextForge `.env`

```bash
OAUTH_TOKEN_BACKEND=vault

VAULT_ADDR=http://127.0.0.1:8200
VAULT_TOKEN=<token-from-step-11>     # pragma: allowlist secret
VAULT_KV_MOUNT=secret
VAULT_KV_PATH_PREFIX=contextforge/oauth

VAULT_TLS_VERIFY=false
```

---

### Step 14 — Install ContextForge with Vault support

```bash
pip install -e ".[vault]"

# Or if already installed:
pip install hvac
```

---

### Step 15 — Start ContextForge and verify

```bash
make dev

# Look for:
#   INFO  oauth_token_backend=vault  vault_addr=http://127.0.0.1:8200  ✓ reachable
```

---

## Part B — Vault Path Structure & Secret Payload

### B.1 — Two kinds of server: what the client sees vs what Vault stores

| | Client MCP config | Vault storage |
|---|---|---|
| **Identifier** | Virtual server UUID (`servers.id`) | MCP URL (`gateways.url`) |
| **Example** | `647ad7b348044bce8fa27a2157b00a0d` | `http://localhost:9000` |
| **Who knows it** | Client (in MCP config URL) | ContextForge only |

The client configures a **virtual server** URL:

```json
{
  "servers": {
    "git-server": {
      "type": "streamable-http",
      "url": "http://localhost:4444/servers/647ad7b348044bce8fa27a2157b00a0d/mcp",
      "headers": { "Authorization": "Bearer your-token-here" }
    }
  }
}
```

The UUID `647ad7b348044bce8fa27a2157b00a0d` is the **virtual server ID** — the façade
the client connects to. It is **never** used as a Vault path key.

ContextForge resolves the real credential anchor internally:

```
virtual server ID (647ad7b3...)
  → server_tool_association   (join table: server_id ↔ tool_id)
  → tools.gateway_id
  → gateways.url              ← the Vault key (e.g. http://localhost:9000)
  → SHA-256[:8] hash          ← path segment   (e.g. a1b4e82c)
```

---

### B.2 — Vault path structure

```
secret/data/contextforge/oauth/<team_id>/<server_id_hash>/<url-encoded-email>
```

| Segment | Source | Example |
|---|---|---|
| `team_id` | Extracted from JWT/session by ContextForge | `engineering` |
| `server_id_hash` | SHA-256 first 8 hex chars of `gateways.url` | `a1b4e82c` |
| `email` | URL-encoded `app_user_email` | `alice%40acme.com` |

**Derive `server_id_hash` for any gateway URL:**

```python
import hashlib
url = "http://localhost:9000"
server_id_hash = hashlib.sha256(url.encode()).hexdigest()[:8]
print(server_id_hash)  # a1b4e82c
```

**Path examples:**

| User | Team | Gateway URL | `server_id_hash` | Full Vault path |
|---|---|---|---|---|
| `alice@acme.com` | `engineering` | `http://localhost:9000` | `a1b4e82c` | `secret/data/contextforge/oauth/engineering/a1b4e82c/alice%40acme.com` |
| `bob@acme.com` | `sales` | `https://mcp.jira.acme.com` | `8f2c91e5` | `secret/data/contextforge/oauth/sales/8f2c91e5/bob%40acme.com` |

---

### B.3 — Final secret payload

Every secret ContextForge writes has this exact JSON structure.
`token` is a **nested object** — not flat fields.

```json
{
  "email":      "alice@acme.com",
  "team_id":    "engineering",
  "mcp_url":    "http://localhost:9000",
  "token": {
    "access_token":  "gho_Aa1Bb2...",
    "refresh_token": "ghr_Rr9Ss8...",
    "scopes":        ["repo", "read:user"]
  },
  "user_id":    "github_uid_44712",
  "token_type": "Bearer",
  "expires_at": "2026-07-07T18:00:00Z",
  "created_at": "2025-07-07T10:00:00Z",
  "updated_at": "2025-07-07T10:00:00Z"
}
```

**Field reference:**

| Field | Type | Maps to `oauth_tokens` column | Note |
|---|---|---|---|
| `email` | string | `app_user_email` | Also in Vault path (URL-encoded) |
| `team_id` | string | — (no DB column in Phase 1) | Also in Vault path |
| `mcp_url` | string | **replaces** `gateway_id` FK | `gateways.url` — System identifier in Vault UI |
| `token.access_token` | string | `access_token` | Plain-text; Vault encrypts at rest |
| `token.refresh_token` | string \| null | `refresh_token` | Nullable |
| `token.scopes` | array | `scopes` | JSON array, not JSON-encoded string |
| `user_id` | string | `user_id` | OAuth provider user ID |
| `token_type` | string | `token_type` | Always `"Bearer"` |
| `expires_at` | ISO-8601 string | `expires_at` | UTC |
| `created_at` | ISO-8601 string | `created_at` | UTC |
| `updated_at` | ISO-8601 string | `updated_at` | UTC |

> **Why `mcp_url` instead of `gateway_id`?**  
> `gateway_id` is an internal UUID FK with no meaning outside the database.
> `mcp_url` is the upstream MCP endpoint URL — it names the system that issued the token,
> is portable across DB migrations, and is what operators see in the Vault UI as the
> **System** column (e.g. `http://localhost:9000`).

---

### B.4 — Manual test with the exact payload

> `vault kv put` only handles flat key=value pairs and **cannot write nested objects**.
> Use the KV v2 HTTP API (`curl`) for the full nested payload.

**Setup:**

```bash
source ~/.vault-config/keys.txt
export VAULT_ADDR="http://127.0.0.1:8200"
export VAULT_TOKEN="$VAULT_CF_TOKEN"

# Python: import hashlib; hashlib.sha256("http://localhost:9000".encode()).hexdigest()[:8]
SERVER_ID_HASH="a1b4e82c"
```

**WRITE:**

```bash
curl -s -X POST \
  -H "X-Vault-Token: $VAULT_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "data": {
      "email":      "alice@acme.com",
      "team_id":    "engineering",
      "mcp_url":    "http://localhost:9000",
      "token": {
        "access_token":  "test_access_abc123",
        "refresh_token": "test_refresh_xyz789",
        "scopes":        ["repo", "read:user"]
      },
      "user_id":    "github_uid_44712",
      "token_type": "Bearer",
      "expires_at": "2026-07-07T18:00:00Z",
      "created_at": "2025-07-07T10:00:00Z",
      "updated_at": "2025-07-07T10:00:00Z"
    }
  }' \
  "${VAULT_ADDR}/v1/secret/data/contextforge/oauth/engineering/${SERVER_ID_HASH}/alice%40acme.com" \
  | jq .
```

**Expected output:**
```json
{
  "request_id": "...",
  "data": { "created_time": "2025-07-07T10:00:00Z", "version": 1 }
}
```

**READ — nested `token` object must be intact:**

```bash
curl -s \
  -H "X-Vault-Token: $VAULT_TOKEN" \
  "${VAULT_ADDR}/v1/secret/data/contextforge/oauth/engineering/${SERVER_ID_HASH}/alice%40acme.com" \
  | jq .data.data
```

**Expected output:**
```json
{
  "created_at": "2025-07-07T10:00:00Z",
  "email": "alice@acme.com",
  "expires_at": "2026-07-07T18:00:00Z",
  "mcp_url": "http://localhost:9000",
  "team_id": "engineering",
  "token": {
    "access_token": "test_access_abc123",
    "refresh_token": "test_refresh_xyz789",
    "scopes": ["repo", "read:user"]
  },
  "token_type": "Bearer",
  "updated_at": "2025-07-07T10:00:00Z",
  "user_id": "github_uid_44712"
}
```

**LIST:**

```bash
vault kv list secret/contextforge/oauth/engineering/${SERVER_ID_HASH}
# Keys
# ----
# alice%40acme.com
```

**DELETE:**

```bash
vault kv delete secret/contextforge/oauth/engineering/${SERVER_ID_HASH}/alice%40acme.com
```

**Verify deletion:**

```bash
curl -s \
  -H "X-Vault-Token: $VAULT_TOKEN" \
  "${VAULT_ADDR}/v1/secret/data/contextforge/oauth/engineering/${SERVER_ID_HASH}/alice%40acme.com" \
  | jq .data
# null
```

---

### B.5 — Test the authorize endpoint (virtual server UUID → Vault)

The `/vault/authorize/{server_id}` endpoint accepts the **virtual server UUID** from the
client MCP config URL:

```bash
export MCPGATEWAY_BEARER_TOKEN=$(python -m mcpgateway.utils.create_jwt_token \
  --username admin@example.com --exp 0 --secret <your-jwt-secret>)

# Use the virtual server UUID from your MCP config URL:
# http://localhost:4444/servers/647ad7b348044bce8fa27a2157b00a0d/mcp
#                               ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
curl -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN" \
  "http://localhost:4444/vault/authorize/647ad7b348044bce8fa27a2157b00a0d"
```

ContextForge resolves the Vault path internally:

```
647ad7b348044bce8fa27a2157b00a0d  (virtual server UUID — from client)
  → server_tool_association        (server_id ↔ tool_id)
  → tools.gateway_id
  → gateways.url = "http://localhost:9000"
  → SHA-256[:8]  = "a1b4e82c"
  → Vault path: secret/data/contextforge/oauth/engineering/a1b4e82c/alice%40acme.com
```

| HTTP | Meaning |
|---|---|
| `302` | Redirect to IdP — OAuth gateway found, flow started |
| `400` | No OAuth-configured gateway linked to this virtual server |
| `404` | Virtual server UUID does not exist |

---

## Daily Workflow

```bash
# Terminal 1: Start Vault server
vault server -config=$HOME/.vault-config/config.hcl

# Terminal 2: Unseal (required after every restart)
source ~/.vault-config/keys.txt
export VAULT_ADDR="http://127.0.0.1:8200"
vault operator unseal "$VAULT_UNSEAL_KEY"
```

**No re-initialization needed** — policies, tokens, and secrets persist in PostgreSQL.

---

## Troubleshooting

| Error | Fix |
|---|---|
| `connection refused` | Check Vault is running: `ps aux \| grep vault` |
| `Vault is sealed` | Unseal: `vault operator unseal "$VAULT_UNSEAL_KEY"` |
| `permission denied` | Verify token: `vault token lookup` — should show `contextforge` policy |
| PostgreSQL connection error | Check `~/.vault-config/config.hcl` connection URL and `sslmode=disable` |
| Tokens not persisting | Confirm no `-dev` flag; check `psql vault_dev -c "\dt"` shows `vault_kv_store` |
| `barrier reports initialized but no seal configuration found` | Vault storage corrupted — see "Storage Corruption Recovery" below |

---

## Storage Corruption Recovery

### Why It Happens

Vault's PostgreSQL backend can corrupt if Vault is **killed abruptly** (Ctrl+C, `pkill -9`, crash, power loss). This happens because:

1. **Barrier metadata is in-memory** — Vault keeps critical seal configuration in memory for performance
2. **PostgreSQL writes are buffered** — The OS may buffer writes for 30-60 seconds before flushing to disk
3. **No WAL for barrier state** — Vault's barrier initialization writes aren't in PostgreSQL's WAL

Result: Vault marks itself "initialized" → crash → PostgreSQL never receives seal config → restart sees "initialized=true" but no seal keys → **ERROR 500**

### Recovery Script

**Run the automated recovery:**

```bash
# 1. Run the recovery script
cd /Users/rakhidutta/mcp-context-forge
./scripts/restart-vault.sh
```

The script will:
- Stop any running Vault processes
- Backup existing storage to `~/.vault-config/vault_kv_store_backup_<timestamp>.sql`
- Drop and recreate the `vault_kv_store` table (fixes corruption)
- Restart Vault
- Re-initialize if needed (saves new keys to `~/.vault-config/keys.txt`)
- Unseal Vault
- Re-create the ContextForge policy and token

### After Recovery

```bash
# 2. In a new terminal, set environment
source ~/.vault-config/keys.txt
export VAULT_ADDR=http://127.0.0.1:8200
export VAULT_TOKEN=$VAULT_CF_TOKEN

# 3. Verify it works
vault status
# Should show: Sealed: false
```

**⚠️ Note:** Previous OAuth tokens are lost and must be re-authorized. The backup is saved but cannot be restored without the original seal keys.

---

## Preventing Corruption

### Always Stop Vault Gracefully

```bash
# ❌ DON'T: Force kill (CORRUPTS STATE)
pkill -9 vault

# ✅ DO: Graceful stop
./scripts/stop-vault-gracefully.sh

# Or manually send SIGTERM (not SIGKILL):
kill -TERM $(pgrep -f "vault server")
```

### Graceful Shutdown Script

The `scripts/stop-vault-gracefully.sh` script:
- Sends `SIGTERM` (graceful shutdown signal)
- Waits up to 10 seconds for Vault to flush writes
- Only force-kills if Vault doesn't respond

**Use this instead of Ctrl+C or `pkill -9` to avoid corruption.**

---

## Security Notes (Local Dev)

- **Unseal key**: Stored in `~/.vault-config/keys.txt` (600 permissions). Do not commit.
- **Root token**: Only use for initial setup. Use the scoped `VAULT_CF_TOKEN` for ContextForge.
- **TLS disabled**: `tls_disable = 1` is acceptable for local dev. Enable in production.
- **Passwords**: Default password shown here (`password`) is for local dev only.

---

## Next Steps

- For production deployment, see `docs/vault-production-deployment.md`
- Enable TLS with proper certificates
- Use auto-unseal with cloud KMS (AWS, Azure, GCP)
- Configure high-availability PostgreSQL backend
- Architecture reference: `file:///Users/rakhidutta/mcp-context-forge/contextforge-pluggable-token-storage-architect-design-document.html`
