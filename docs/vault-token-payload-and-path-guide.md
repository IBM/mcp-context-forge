# ContextForge Vault Token — Payload Shape & Path Structure

This guide covers the **exact secret payload** ContextForge writes to Vault and explains
how the Vault path is derived from the client's virtual server URL.

> **Prerequisites:** Vault is already running and the `contextforge` policy token is available.
> See `docs/vault-local-dev-postgresql.md` for the full Vault setup walkthrough.

---

## 1. Two kinds of server — what the client sees vs what Vault stores

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
  → gateways.url              ← this is the Vault key (e.g. http://localhost:9000)
  → SHA-256[:8] hash          ← used as path segment (e.g. a1b4e82c)
```

---

## 2. Vault path structure

```
secret/data/contextforge/oauth/<team_id>/<server_id_hash>/<url-encoded-email>
```

| Segment | Source | Example |
|---|---|---|
| `team_id` | Extracted from JWT/session by ContextForge | `engineering` |
| `server_id_hash` | SHA-256 first 8 hex chars of `gateways.url` | `a1b4e82c` |
| `email` | URL-encoded `app_user_email` | `alice%40acme.com` |

### Derive `server_id_hash` for any gateway URL

```python
import hashlib
url = "http://localhost:9000"
server_id_hash = hashlib.sha256(url.encode()).hexdigest()[:8]
print(server_id_hash)  # a1b4e82c
```

### Path examples

| User | Team | Gateway URL (`gateways.url`) | `server_id_hash` | Full Vault path |
|---|---|---|---|---|
| `alice@acme.com` | `engineering` | `http://localhost:9000` | `a1b4e82c` | `secret/data/contextforge/oauth/engineering/a1b4e82c/alice%40acme.com` |
| `bob@acme.com` | `sales` | `https://mcp.jira.acme.com` | `8f2c91e5` | `secret/data/contextforge/oauth/sales/8f2c91e5/bob%40acme.com` |

---

## 3. Final secret payload

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

### Field reference

| Field | Type | Maps to `oauth_tokens` column | Note |
|---|---|---|---|
| `email` | string | `app_user_email` | Also in Vault path (URL-encoded) |
| `team_id` | string | — (no DB column in Phase 1) | Also in Vault path |
| `mcp_url` | string | **replaces** `gateway_id` FK | `gateways.url` — System identifier |
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
> **System** column (e.g. `http://localhost:9000` or `https://mcp.github.acme.com`).

---

## 4. Manual test — write & read with the exact payload

> `vault kv put` only handles flat key=value pairs and **cannot write nested objects**.
> Use the KV v2 HTTP API directly for manual testing with the exact payload shape.

### Setup

```bash
source ~/.vault-config/keys.txt
export VAULT_ADDR="http://127.0.0.1:8200"
export VAULT_TOKEN="$VAULT_CF_TOKEN"

# Derive server_id_hash for your local gateway
# Python: import hashlib; hashlib.sha256("http://localhost:9000".encode()).hexdigest()[:8]
SERVER_ID_HASH="a1b4e82c"
```

### WRITE

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
  "data": {
    "created_time": "2025-07-07T10:00:00Z",
    "version": 1
  }
}
```

### READ — nested `token` object must be intact

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

### LIST

```bash
# All credentials under this team + gateway server
vault kv list secret/contextforge/oauth/engineering/${SERVER_ID_HASH}
```

**Expected output:**
```
Keys
----
alice%40acme.com
```

### DELETE

```bash
vault kv delete secret/contextforge/oauth/engineering/${SERVER_ID_HASH}/alice%40acme.com
```

**Expected output:**
```
Success! Data deleted (if it existed) at: secret/data/contextforge/oauth/engineering/a1b4e82c/alice%40acme.com
```

### Verify deletion

```bash
curl -s \
  -H "X-Vault-Token: $VAULT_TOKEN" \
  "${VAULT_ADDR}/v1/secret/data/contextforge/oauth/engineering/${SERVER_ID_HASH}/alice%40acme.com" \
  | jq .data
```

**Expected output:**
```json
null
```

---

## 5. Test the authorize endpoint (virtual server UUID → Vault)

The `/vault/authorize/{server_id}` endpoint accepts the **virtual server UUID** from the
client MCP config URL — not the gateway ID:

```bash
export MCPGATEWAY_BEARER_TOKEN=$(python -m mcpgateway.utils.create_jwt_token \
  --username admin@example.com --exp 0 --secret <your-jwt-secret>)

# Pass the virtual server UUID from your MCP config URL:
# e.g. http://localhost:4444/servers/647ad7b348044bce8fa27a2157b00a0d/mcp
#                                     ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
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

**Expected responses:**

| HTTP | Meaning |
|---|---|
| `302` | Redirect to IdP — OAuth gateway found, flow started |
| `400` | No OAuth-configured gateway linked to this virtual server |
| `404` | Virtual server UUID does not exist |

---

## 6. Related documents

- `docs/vault-local-dev-postgresql.md` — Full Vault + PostgreSQL local dev setup (install, init, unseal, policy)
- `contextforge-pluggable-token-storage-architect-design-document.html` — Architecture design document (§7 Vault Secret Schema)
