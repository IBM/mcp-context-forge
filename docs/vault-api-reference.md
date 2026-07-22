# Vault HTTP API Reference for OAuth Token Storage

## Quick Reference

### Environment Variables
```bash
export VAULT_ADDR="http://127.0.0.1:8200"
export VAULT_TOKEN="hvs.CAESI..."
```

### Basic Query Pattern
```bash
curl -s \
  -H "X-Vault-Token: $VAULT_TOKEN" \
  "${VAULT_ADDR}/v1/secret/data/<path>" \
  | jq '.data.data'
```

---

## OAuth Token Path Structure

**ContextForge stores tokens at:**
```
secret/contextforge/oauth/{team_id}/{provider_hash}/{user_email}
```

**Example:**
```
secret/contextforge/oauth/d855a360a0f24f56ac2b5a1ab54cbb70/ca602dd4/user2@example.com
```

---

## Common Operations

### 1. List All Teams with OAuth Tokens

```bash
curl -s \
  -H "X-Vault-Token: $VAULT_TOKEN" \
  "${VAULT_ADDR}/v1/secret/metadata/contextforge/oauth?list=true" \
  | jq -r '.data.keys[]'
```

**Output:**
```
d855a360a0f24f56ac2b5a1ab54cbb70/
```

### 2. List Provider Hashes for a Team

```bash
TEAM_ID="d855a360a0f24f56ac2b5a1ab54cbb70"

curl -s \
  -H "X-Vault-Token: $VAULT_TOKEN" \
  "${VAULT_ADDR}/v1/secret/metadata/contextforge/oauth/${TEAM_ID}?list=true" \
  | jq -r '.data.keys[]'
```

**Output:**
```
ca602dd4/
```

### 3. List Users with Tokens

```bash
TEAM_ID="d855a360a0f24f56ac2b5a1ab54cbb70"
PROVIDER_HASH="ca602dd4"

curl -s \
  -H "X-Vault-Token: $VAULT_TOKEN" \
  "${VAULT_ADDR}/v1/secret/metadata/contextforge/oauth/${TEAM_ID}/${PROVIDER_HASH}?list=true" \
  | jq -r '.data.keys[]'
```

**Output:**
```
user2@example.com
```

### 4. Get Full Token Data

```bash
curl -s \
  -H "X-Vault-Token: $VAULT_TOKEN" \
  "${VAULT_ADDR}/v1/secret/data/contextforge/oauth/d855a360a0f24f56ac2b5a1ab54cbb70/ca602dd4/user2@example.com" \
  | jq '.data.data'
```

**Output:**
```json
{
  "created_at": "2026-07-10T04:47:07.960110+00:00",
  "email": "user2@example.com",
  "expires_at": null,
  "mcp_url": "https://api.githubcopilot.com/mcp/",
  "team_id": "d855a360a0f24f56ac2b5a1ab54cbb70",
  "token": {
    "access_token": "gho_REDACTED_EXAMPLE_TOKEN_FOR_DOCUMENTATION",
    "refresh_token": null,
    "scopes": []
  },
  "token_type": "Bearer",
  "updated_at": "2026-07-10T04:47:07.960110+00:00",
  "user_id": "Ov23li373LN81kl4mDI4"
}
```

### 5. Extract Specific Fields

#### Get Access Token Only
```bash
curl -s \
  -H "X-Vault-Token: $VAULT_TOKEN" \
  "${VAULT_ADDR}/v1/secret/data/contextforge/oauth/${TEAM_ID}/${PROVIDER_HASH}/${EMAIL}" \
  | jq -r '.data.data.token.access_token'
```

#### Get User ID Only
```bash
curl -s \
  -H "X-Vault-Token: $VAULT_TOKEN" \
  "${VAULT_ADDR}/v1/secret/data/contextforge/oauth/${TEAM_ID}/${PROVIDER_HASH}/${EMAIL}" \
  | jq -r '.data.data.user_id'
```

---

## Response Structure

### Full HTTP Response
```json
{
  "request_id": "365e41fd-fe58-3ae1-c0c5-42338b104e9d",
  "lease_id": "",
  "renewable": false,
  "lease_duration": 0,
  "data": {
    "data": {
      // ← Your actual secret data here
      "created_at": "2026-07-10T04:47:07.960110+00:00",
      "email": "user2@example.com",
      "token": {
        "access_token": "gho_..."
      }
    },
    "metadata": {
      "created_time": "2026-07-10T04:47:07.966463Z",
      "version": 2
    }
  }
}
```

**JQ Path Breakdown:**
- `.data.data` - The secret payload
- `.data.metadata` - Vault metadata (version, timestamps)
- `.data.data.token.access_token` - Just the token

---

## PostgreSQL Backend (Raw Storage)

### View Encrypted Data in PostgreSQL

```sql
-- Show all encrypted OAuth entries
SELECT
    parent_path,
    LEFT(key, 40) as key_prefix,
    LENGTH(value) as encrypted_bytes,
    encode(substring(value from 1 for 32), 'hex') as encryption_header
FROM vault_kv_store
WHERE parent_path LIKE '/logical/%'
  AND LENGTH(value) > 400
ORDER BY LENGTH(value) DESC;
```

**Output:**
```
                 parent_path                  |             key_prefix              | encrypted_bytes |       encryption_header
----------------------------------------------+-------------------------------------+-----------------+---------------------------------
 /logical/.../versions/                       | 36dd2870309163e4622bc190176add...   |             440 | 0000000102b6ddd354f1bc3f5579...
```

### ⚠️ Important: PostgreSQL Data is Encrypted

The `value` column in `vault_kv_store` contains **AES-GCM encrypted blobs**. You CANNOT decrypt this data using SQL queries. You must use Vault's HTTP API or CLI.

```
PostgreSQL Storage:
┌────────────────────────────────────────┐
│ vault_kv_store.value (bytea)          │
├────────────────────────────────────────┤
│ 0000000102b6ddd354... (encrypted)     │
│  ^^^^^^                                │
│  Vault encryption header               │
└────────────────────────────────────────┘
          ↓ Decryption via Vault API
┌────────────────────────────────────────┐
│ Plaintext JSON                         │
├────────────────────────────────────────┤
│ {                                      │
│   "email": "user2@example.com",        │
│   "token": {                           │
│     "access_token": "gho_..."          │
│   }                                    │
│ }                                      │
└────────────────────────────────────────┘
```

---

## Vault CLI vs HTTP API Comparison

| Operation | Vault CLI | HTTP API |
|-----------|-----------|----------|
| **Get Secret** | `vault kv get secret/my-path` | `GET /v1/secret/data/my-path` |
| **List Keys** | `vault kv list secret/my-path` | `GET /v1/secret/metadata/my-path?list=true` |
| **Put Secret** | `vault kv put secret/my-path key=value` | `POST /v1/secret/data/my-path` |
| **Delete Secret** | `vault kv delete secret/my-path` | `DELETE /v1/secret/data/my-path` |

**Key Difference:** HTTP API requires `/data/` or `/metadata/` in the path, CLI auto-adds it.

---

## Error Handling

### 403 Permission Denied
```json
{
  "errors": ["permission denied"]
}
```

**Solution:** Check `VAULT_TOKEN` is valid:
```bash
curl -s -H "X-Vault-Token: $VAULT_TOKEN" "${VAULT_ADDR}/v1/auth/token/lookup-self"
```

### 404 Not Found
```json
{
  "errors": []
}
```

**Solution:** Verify the path exists:
```bash
curl -s \
  -H "X-Vault-Token: $VAULT_TOKEN" \
  "${VAULT_ADDR}/v1/secret/metadata/contextforge/oauth?list=true"
```

---

## Complete Example Script

```bash
#!/bin/bash
# Query OAuth token for a user

VAULT_ADDR="http://127.0.0.1:8200"
VAULT_TOKEN="hvs.CAESI..."
TEAM_ID="d855a360a0f24f56ac2b5a1ab54cbb70"
EMAIL="user2@example.com"

# Step 1: List all provider hashes for this team
echo "=== Providers for team ${TEAM_ID} ==="
PROVIDERS=$(curl -s \
  -H "X-Vault-Token: $VAULT_TOKEN" \
  "${VAULT_ADDR}/v1/secret/metadata/contextforge/oauth/${TEAM_ID}?list=true" \
  | jq -r '.data.keys[]')

echo "$PROVIDERS"

# Step 2: For each provider, try to find the user's token
for provider in $PROVIDERS; do
  # Remove trailing slash
  provider=${provider%/}
  
  TOKEN_PATH="contextforge/oauth/${TEAM_ID}/${provider}/${EMAIL}"
  
  echo "=== Checking ${TOKEN_PATH} ==="
  
  RESULT=$(curl -s \
    -H "X-Vault-Token: $VAULT_TOKEN" \
    "${VAULT_ADDR}/v1/secret/data/${TOKEN_PATH}")
  
  if echo "$RESULT" | jq -e '.data.data' > /dev/null 2>&1; then
    echo "✅ Found token!"
    echo "$RESULT" | jq '.data.data'
    exit 0
  fi
done

echo "❌ Token not found for ${EMAIL} in team ${TEAM_ID}"
```

---

## Security Best Practices

1. **Never log tokens** - Always use `jq -r` for raw output, avoid echoing full responses
2. **Use environment variables** - Don't hardcode `VAULT_TOKEN` in scripts
3. **Check token expiry** - Vault tokens have TTLs, rotate regularly
4. **Restrict paths** - Use Vault policies to limit token access by path
5. **Audit access** - Enable Vault audit logging for compliance

---

## See Also

- [ContextForge OAuth Design](oauth-design.md)
- [Vault PostgreSQL Backend](https://developer.hashicorp.com/vault/docs/configuration/storage/postgresql)
- [KV Secrets Engine API](https://developer.hashicorp.com/vault/api-docs/secret/kv/kv-v2)
